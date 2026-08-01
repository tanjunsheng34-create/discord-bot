"""
GMPT Bot — MMORPG World Boss / 世界Boss
/gmpt-wb — 查看当前世界Boss状态
/gmpt-wb attack — 攻击世界Boss

全服共享一只 Boss，HP 池巨大，定时刷新。
玩家攻击消耗攻击次数，Boss 死亡后按伤害排名发奖励。
"""
import asyncio
import datetime
import logging
import random
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database import get_db_ctx

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════
BOSS_NAMES = [
    ("远古巨龙", "Ancient Dragon", "🐉"),
    ("暗影领主", "Shadow Lord", "👹"),
    ("冰霜巨人", "Frost Giant", "🧊"),
    ("炎魔之王", "Fire Demon King", "🔥"),
    ("雷霆之翼", "Thunder Wing", "⚡"),
]

BOSS_MAX_HP = 50000
BOSS_RESPAWN_SECONDS = 30
ATTACK_COOLDOWN_SECONDS = 1800  # 30 minutes
MAX_ATTACKS_STORED = 3
REFRESH_INTERVAL_HOURS = 6

# Rank rewards: (rank_range, coins, equipment_quality)
RANK_REWARDS = [
    ((1, 1), 800, "legendary"),
    ((2, 3), 500, "epic"),
    ((4, 10), 300, "rare"),
]


def _add_coins(uid: str, amount: int, reason: str):
    """Add coins and record transaction."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING",
            (uid,),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
        cur.execute(
            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
            (uid, amount, reason),
        )
        conn.commit()


def _add_xp(uid: str, xp: int):
    """Add XP and handle level-up."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT xp, level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
        if not row:
            return
        new_xp = (row["xp"] or 0) + xp
        level = row["level"] or 1
        while new_xp >= level * 1000:
            new_xp -= level * 1000
            level += 1
        cur.execute("UPDATE users SET xp = ?, level = ? WHERE discord_id = ?", (new_xp, level, uid))
        conn.commit()


def _get_user_stats(uid: str):
    """Read user ATK/DEF from users table."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT attack, defense, level, score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    if not row:
        return {"attack": 10, "defense": 5, "level": 1, "score": 0}
    return {
        "attack": row["attack"] or 10,
        "defense": row["defense"] or 5,
        "level": row["level"] or 1,
        "score": row["score"] or 0,
    }


def _get_balance(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return row["score"] if row else 0


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_worldboss_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS world_boss (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                hp INTEGER NOT NULL,
                max_hp INTEGER NOT NULL,
                atk INTEGER NOT NULL DEFAULT 80,
                def INTEGER NOT NULL DEFAULT 20,
                spawned_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'alive'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS world_boss_damage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                boss_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                damage INTEGER NOT NULL DEFAULT 0,
                attacked_at TEXT NOT NULL
            )
        """)
        # Attack cooldown tracker
        cur.execute("""
            CREATE TABLE IF NOT EXISTS world_boss_attacks (
                user_id TEXT PRIMARY KEY,
                attacks_remaining INTEGER NOT NULL DEFAULT 3,
                last_attack_ts TEXT
            )
        """)
        conn.commit()

_init_worldboss_tables()


def _get_current_boss():
    """Get or create the current world boss."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM world_boss WHERE status = 'alive' ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    if row:
        boss = dict(row)
        # Check if refresh needed
        spawned = datetime.datetime.fromisoformat(boss["spawned_at"])
        now = datetime.datetime.now()
        if (now - spawned).total_seconds() >= REFRESH_INTERVAL_HOURS * 3600:
            return _spawn_new_boss()
        return boss
    return _spawn_new_boss()


def _spawn_new_boss():
    """Kill old bosses (mark dead) and spawn a new one."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE world_boss SET status = 'expired' WHERE status = 'alive'")
        name_cn, name_en, emoji = random.choice(BOSS_NAMES)
        now = datetime.datetime.now().isoformat()
        cur.execute(
            "INSERT INTO world_boss (name, hp, max_hp, atk, def, spawned_at, status) VALUES (?, ?, ?, ?, ?, ?, 'alive')",
            (f"{emoji} {name_cn} / {name_en}", BOSS_MAX_HP, BOSS_MAX_HP, 80, 20, now),
        )
        conn.commit()
        boss_id = cur.lastrowid
    return {"id": boss_id, "name": f"{emoji} {name_cn} / {name_en}", "hp": BOSS_MAX_HP, "max_hp": BOSS_MAX_HP, "atk": 80, "def": 20, "spawned_at": now, "status": "alive"}


def _get_attack_count(uid: str) -> int:
    """Get remaining attack count. Auto-regen if cooldown elapsed."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT attacks_remaining, last_attack_ts FROM world_boss_attacks WHERE user_id = ?", (uid,))
        row = cur.fetchone()
    if not row:
        # First time — give max attacks
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO world_boss_attacks (user_id, attacks_remaining, last_attack_ts) VALUES (?, ?, ?)",
                (uid, MAX_ATTACKS_STORED, datetime.datetime.now().isoformat()),
            )
            conn.commit()
        return MAX_ATTACKS_STORED

    remaining = row["attacks_remaining"]
    last_ts = row["last_attack_ts"]
    if not last_ts:
        return remaining

    last_atk = datetime.datetime.fromisoformat(last_ts)
    now = datetime.datetime.now()
    elapsed = (now - last_atk).total_seconds()
    regen_count = int(elapsed / ATTACK_COOLDOWN_SECONDS)
    if regen_count > 0:
        new_remaining = min(remaining + regen_count, MAX_ATTACKS_STORED)
        new_last = last_atk + datetime.timedelta(seconds=regen_count * ATTACK_COOLDOWN_SECONDS)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE world_boss_attacks SET attacks_remaining = ?, last_attack_ts = ? WHERE user_id = ?",
                (new_remaining, new_last.isoformat(), uid),
            )
            conn.commit()
        return new_remaining
    return remaining


def _get_rankings(boss_id: int) -> list:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, SUM(damage) as total_damage FROM world_boss_damage WHERE boss_id = ? GROUP BY user_id ORDER BY total_damage DESC LIMIT 10",
            (boss_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _get_user_total_damage(boss_id: int, uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(damage), 0) as total FROM world_boss_damage WHERE boss_id = ? AND user_id = ?",
            (boss_id, uid),
        )
        row = cur.fetchone()
    return row["total"] if row else 0


def _distribute_rewards(boss_id: int, boss_name: str):
    """After boss death, distribute rewards based on damage ranking."""
    rankings = _get_rankings(boss_id)
    if not rankings:
        return

    all_participant_ids = set()
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT user_id FROM world_boss_damage WHERE boss_id = ?", (boss_id,))
        for r in cur.fetchall():
            all_participant_ids.add(r["user_id"])

    # Give participation reward to all
    for uid in all_participant_ids:
        _add_coins(uid, 100, f"World Boss 参与奖励: {boss_name}")
        _add_xp(uid, 50)

    # Rank rewards
    for rank_idx, rank_data in enumerate(rankings):
        rank = rank_idx + 1
        uid = rank_data["user_id"]
        for (lo, hi), coins, quality in RANK_REWARDS:
            if lo <= rank <= hi:
                _add_coins(uid, coins, f"World Boss 排名 #{rank} 奖励: {boss_name}")
                # Give equipment via inventory
                eq_name = f"WB_{quality}_装备_{rank}"
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) VALUES (?, ?, ?, 1, 'equipment') "
                        "ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = quantity + 1",
                        (uid, f"wb_boss_{eq_name}", f"World Boss {quality.title()} Gear|||atk:{5 + rank * 3}|||{quality}"),
                    )
                    conn.commit()
                break


# ══════════════════════════════════════════════════════════════
# Views
# ══════════════════════════════════════════════════════════════

def _hp_bar(current: int, maximum: int, length: int = 20) -> str:
    ratio = max(0, min(1, current / maximum))
    filled = int(ratio * length)
    empty = length - filled
    pct = int(ratio * 100)
    bar = "█" * filled + "░" * empty
    return f"`{bar}` {pct}% ({current:,} / {maximum:,})"


class WorldBossView(discord.ui.View):
    """世界Boss主面板 / World Boss main panel."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        boss = _get_current_boss()
        stats = _get_user_stats(self.uid)
        attacks = _get_attack_count(self.uid)
        total_dmg = _get_user_total_damage(boss["id"], self.uid)

        hp_pct = max(0, int(boss["hp"] / boss["max_hp"] * 100))
        color = 0x2ECC71 if hp_pct > 50 else (0xF39C12 if hp_pct > 25 else 0xE74C3C)

        embed = discord.Embed(
            title=f"🐉 World Boss / 世界Boss",
            description=f"**{boss['name']}**\n\n{_hp_bar(boss['hp'], boss['max_hp'])}\n",
            color=color,
        )
        embed.add_field(name="ATK / 攻击力", value=str(boss["atk"]), inline=True)
        embed.add_field(name="DEF / 防御力", value=str(boss["def"]), inline=True)
        embed.add_field(name="Your ATK / 你的攻击", value=str(stats["attack"]), inline=True)
        embed.add_field(
            name="Attack Chances / 攻击次数",
            value=f"⚔️ **{attacks}** / {MAX_ATTACKS_STORED} (regen every 30min / 每30分钟恢复1次)",
            inline=False,
        )
        embed.add_field(name="Your Total Damage / 你的伤害", value=f"🔥 **{total_dmg:,}**", inline=True)

        spawned = datetime.datetime.fromisoformat(boss["spawned_at"])
        elapsed = datetime.datetime.now() - spawned
        remaining = max(0, REFRESH_INTERVAL_HOURS * 3600 - elapsed.total_seconds())
        h, m = divmod(int(remaining), 3600)
        m //= 60
        embed.add_field(name="Auto Refresh / 自动刷新", value=f"in {h}h {m}m", inline=True)

        embed.set_footer(text="⚔️ Attack to deal ATK×random(0.8~1.2) damage | 暴击率 15% ×1.8")
        return embed

    @discord.ui.button(label="Attack 攻击", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def attack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return

        attacks = _get_attack_count(uid)
        if attacks <= 0:
            await interaction.response.send_message(
                "No attack chances left! Wait for regeneration.\n没有攻击次数了！等待恢复。",
                ephemeral=True,
            )
            return

        boss = _get_current_boss()
        if boss["status"] != "alive":
            await interaction.response.send_message("The boss is already dead!\nBoss已经死了！", ephemeral=True)
            return

        stats = _get_user_stats(uid)
        base_dmg = stats["attack"]
        multiplier = random.uniform(0.8, 1.2)
        damage = int(base_dmg * multiplier)
        crit = random.random() < 0.15
        if crit:
            damage = int(damage * 1.8)

        # Update boss HP
        new_hp = max(0, boss["hp"] - damage)
        now = datetime.datetime.now().isoformat()
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE world_boss SET hp = ? WHERE id = ?", (new_hp, boss["id"]))
            cur.execute(
                "INSERT INTO world_boss_damage (boss_id, user_id, damage, attacked_at) VALUES (?, ?, ?, ?)",
                (boss["id"], uid, damage, now),
            )
            cur.execute(
                "UPDATE world_boss_attacks SET attacks_remaining = attacks_remaining - 1, last_attack_ts = ? WHERE user_id = ?",
                (now, uid),
            )
            conn.commit()

        # Build result message
        crit_text = "💥 **CRITICAL HIT! / 暴击！**\n" if crit else ""
        remaining = _get_attack_count(uid)

        if new_hp <= 0:
            # Boss died!
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE world_boss SET status = 'dead', hp = 0 WHERE id = ?", (boss["id"],))
                conn.commit()

            _distribute_rewards(boss["id"], boss["name"])

            embed = discord.Embed(
                title=f"🏆 {boss['name']} DEFEATED! / 已被击败！",
                description=f"{crit_text}You dealt **{damage:,}** damage! Final blow!\n造成了 **{damage:,}** 伤害！最后一击！\n\n"
                            f"Rewards distributed by ranking!\n按伤害排名发放奖励！\n"
                            f"Top 1: 🪙800 + Legendary 传说装备\n"
                            f"Top 2-3: 🪙500 + Epic 史诗装备\n"
                            f"Top 4-10: 🪙300 + Rare 稀有装备\n"
                            f"All participants: 🪙100 + EXP\n\n"
                            f"New boss spawning in {BOSS_RESPAWN_SECONDS}s...",
                color=0xF1C40F,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)

            # Schedule respawn
            await asyncio.sleep(BOSS_RESPAWN_SECONDS)
            _spawn_new_boss()
            return

        result_embed = discord.Embed(
            title=f"⚔️ Attack Result / 攻击结果",
            description=f"{crit_text}You dealt **{damage:,}** damage to **{boss['name']}**!\n"
                        f"对 **{boss['name']}** 造成了 **{damage:,}** 伤害！\n\n"
                        f"Boss HP: {_hp_bar(new_hp, boss['max_hp'])}\n"
                        f"Remaining attacks / 剩余攻击: **{remaining}**",
            color=0xE74C3C if crit else 0x3498DB,
        )
        try:
            await interaction.response.edit_message(embed=result_embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=result_embed, view=self)

    @discord.ui.button(label="Ranking 排行", emoji="📊", style=discord.ButtonStyle.primary, row=0)
    async def ranking_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        boss = _get_current_boss()
        rankings = _get_rankings(boss["id"])

        if not rankings:
            embed = discord.Embed(
                title=f"📊 Damage Ranking / 伤害排行 — {boss['name']}",
                description="No attacks yet! Be the first!\n还没有人攻击！来当第一吧！",
                color=0x95A5A6,
            )
        else:
            lines = []
            for idx, r in enumerate(rankings):
                rank = idx + 1
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
                lines.append(f"{medal} <@{r['user_id']}> — 🔥 **{r['total_damage']:,}** dmg")
            embed = discord.Embed(
                title=f"📊 Damage Ranking / 伤害排行 — {boss['name']}",
                description="\n".join(lines),
                color=0xF39C12,
            )
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
        else:
            embed = discord.Embed(
                title="World Boss / 世界Boss",
                description="Use `/gmpt-mmorpg` to return.\n使用 `/gmpt-mmorpg` 返回。",
                color=0x95A5A6,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════

class WorldBossCog(commands.Cog):
    """世界Boss系统 / World Boss system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Ensure a boss exists at startup
        _get_current_boss()
        self._respawn_loop.start()

    def cog_unload(self):
        self._respawn_loop.cancel()

    @tasks.loop(hours=REFRESH_INTERVAL_HOURS)
    async def _respawn_loop(self):
        """Periodically refresh the world boss."""
        _spawn_new_boss()
        logger.info("World Boss auto-refreshed")

    @_respawn_loop.before_loop
    async def _before_respawn(self):
        await self.bot.wait_until_ready()

    wb_group = app_commands.Group(
        name="gmpt-wb",
        description="World Boss System / 世界Boss系统",
    )

    @wb_group.command(name="status", description="查看当前世界Boss状态 / View current World Boss status")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def wb_status(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        view = WorldBossView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @wb_group.command(name="attack", description="攻击世界Boss / Attack the World Boss")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def wb_attack(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        attacks = _get_attack_count(uid)
        if attacks <= 0:
            await interaction.response.send_message(
                "No attack chances! Wait for regeneration (30min per charge).\n没有攻击次数了！每30分钟恢复1次。",
                ephemeral=True,
            )
            return

        boss = _get_current_boss()
        if boss["status"] != "alive":
            await interaction.response.send_message(
                "The boss is already dead! A new one will spawn soon.\nBoss已死亡！新Boss即将刷新。",
                ephemeral=True,
            )
            return

        stats = _get_user_stats(uid)
        base_dmg = stats["attack"]
        multiplier = random.uniform(0.8, 1.2)
        damage = int(base_dmg * multiplier)
        crit = random.random() < 0.15
        if crit:
            damage = int(damage * 1.8)

        new_hp = max(0, boss["hp"] - damage)
        now = datetime.datetime.now().isoformat()

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE world_boss SET hp = ? WHERE id = ?", (new_hp, boss["id"]))
            cur.execute(
                "INSERT INTO world_boss_damage (boss_id, user_id, damage, attacked_at) VALUES (?, ?, ?, ?)",
                (boss["id"], uid, damage, now),
            )
            cur.execute(
                "UPDATE world_boss_attacks SET attacks_remaining = attacks_remaining - 1, last_attack_ts = ? WHERE user_id = ?",
                (now, uid),
            )
            conn.commit()

        remaining = _get_attack_count(uid)
        crit_text = "💥 **CRITICAL HIT! / 暴击！**\n" if crit else ""

        if new_hp <= 0:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE world_boss SET status = 'dead', hp = 0 WHERE id = ?", (boss["id"],))
                conn.commit()

            _distribute_rewards(boss["id"], boss["name"])

            embed = discord.Embed(
                title=f"🏆 {boss['name']} DEFEATED! / 已被击败！",
                description=f"{crit_text}You dealt **{damage:,}** damage! Final blow!\n"
                            f"造成了 **{damage:,}** 伤害！最后一击！\n\n"
                            f"Rewards distributed! 新Boss {BOSS_RESPAWN_SECONDS}s 后刷新...",
                color=0xF1C40F,
            )
            await interaction.response.send_message(embed=embed)

            await asyncio.sleep(BOSS_RESPAWN_SECONDS)
            _spawn_new_boss()
            return

        embed = discord.Embed(
            title=f"⚔️ Attack Result / 攻击结果 — {boss['name']}",
            description=f"{crit_text}Dealt **{damage:,}** damage!\n"
                        f"造成了 **{damage:,}** 伤害！\n\n"
                        f"Boss HP: {_hp_bar(new_hp, boss['max_hp'])}\n"
                        f"Remaining attacks / 剩余: **{remaining}**",
            color=0xE74C3C if crit else 0x3498DB,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(WorldBossCog(bot))
    logger.info("WorldBoss cog loaded")
