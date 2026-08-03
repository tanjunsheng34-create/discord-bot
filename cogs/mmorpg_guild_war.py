"""
GMPT Bot — MMORPG Guild War System / 公会战系统
自动每周六 20:00 触发，公会成员对公会 Boss 累计伤害排名。
/gmpt-guild-war — 公会战面板
"""
import asyncio
import datetime
import logging
import random
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database import get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════
GUILD_WAR_DAY = 5  # Saturday (0=Monday in Python weekday)
GUILD_WAR_HOUR = 20
GUILD_WAR_DURATION = 3600  # 1 hour in seconds
BOSS_BASE_HP = 100000
BOSS_HP_PER_MEMBER = 5000
WAR_ACTIONS = ["slash", "charge", "power_strike", "defend"]


def _get_user_guild(uid: str) -> dict | None:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT g.*, gm.contribution FROM mmorpg_guilds g "
            "JOIN mmorpg_guild_members gm ON g.id = gm.guild_id WHERE gm.user_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _get_user_stats(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT hp, max_hp, mp, max_mp, attack, defense, level FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    if row:
        return dict(row)
    return {"hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50, "attack": 10, "defense": 5, "level": 1}


def _get_player_element(uid: str) -> str:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT element FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["element"] or "none") if row else "none"


def _calc_element_multiplier(atk_elem: str, def_elem: str) -> float:
    chart = {
        ("fire", "wind"): 1.5, ("wind", "water"): 1.5, ("water", "fire"): 1.5,
        ("light", "dark"): 1.5, ("dark", "light"): 1.5,
        ("wind", "fire"): 0.75, ("water", "wind"): 0.75, ("fire", "water"): 0.75,
    }
    return chart.get((atk_elem, def_elem), 1.0)


def _add_coins(uid: str, amount: int, reason: str):
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


def _get_coins(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["score"] or 0) if row else 0


def _get_guild_members(guild_id: int) -> list:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, contribution FROM mmorpg_guild_members WHERE guild_id = ?",
            (guild_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_war_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS guild_war (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                war_date TEXT NOT NULL,
                total_damage INTEGER NOT NULL DEFAULT 0,
                boss_hp INTEGER NOT NULL DEFAULT 0,
                boss_max_hp INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                started_at TEXT,
                ended_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS guild_war_damage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                war_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                damage INTEGER NOT NULL DEFAULT 0,
                actions INTEGER NOT NULL DEFAULT 0,
                last_action_at TEXT,
                UNIQUE(war_id, user_id)
            )
        """)
        conn.commit()

_init_war_tables()


# ══════════════════════════════════════════════════════════════
# In-memory war state (active wars)
# ══════════════════════════════════════════════════════════════
_active_wars: dict = {}  # guild_id -> war state
_user_cooldowns: dict = {}  # (guild_id, user_id) -> cooldown_until timestamp


# ══════════════════════════════════════════════════════════════
# GuildWarView
# ══════════════════════════════════════════════════════════════
class GuildWarView(discord.ui.View):
    """公会战面板 / Guild War panel."""

    def __init__(self, uid: str, guild: dict, war_state: dict | None, main_view=None):
        super().__init__(timeout=120)
        self.uid = uid
        self.guild = guild
        self.war_state = war_state
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        if not self.war_state or self.war_state.get("status") == "ended":
            embed = discord.Embed(
                title="🏰 Guild War / 公会战",
                description=(
                    "公会战在 **每周六 20:00** 自动开启！\n"
                    "Guild War auto-starts every **Saturday 20:00**!\n\n"
                    "全体公会成员共同攻击公会 Boss，按伤害排名获得奖励。\n"
                    "All guild members attack the Guild Boss together.\n"
                    "Rewards based on damage ranking."
                ),
                color=0xE74C3C,
            )
            next_saturday = datetime.datetime.now()
            days_until = (GUILD_WAR_DAY - next_saturday.weekday()) % 7
            if days_until == 0 and next_saturday.hour >= GUILD_WAR_HOUR:
                days_until = 7
            next_war = next_saturday + datetime.timedelta(days=days_until)
            next_war = next_war.replace(hour=GUILD_WAR_HOUR, minute=0, second=0, microsecond=0)
            embed.add_field(
                name="Next War / 下次公会战",
                value=f"{next_war.strftime('%Y-%m-%d %H:%M')} ({days_until}天后 / days)",
                inline=False,
            )
            return embed

        boss_hp = self.war_state.get("boss_hp", 0)
        boss_max = self.war_state.get("boss_max_hp", 1)
        total_dmg = self.war_state.get("total_damage", 0)
        hp_bar = "█" * max(0, int(boss_hp / max(1, boss_max) * 10))
        hp_bar += "░" * (10 - len(hp_bar))

        embed = discord.Embed(
            title=f"⚔️ Guild War IN PROGRESS! / 公会战进行中！— {self.guild['name']}",
            description=f"Boss HP / Boss血量: [{hp_bar}] {boss_hp:,}/{boss_max:,}",
            color=0xE74C3C,
        )
        embed.add_field(name="Total Damage / 总伤害", value=f"{total_dmg:,}", inline=True)

        # Top damage dealers
        damages = self.war_state.get("damages", {})
        sorted_dmg = sorted(damages.items(), key=lambda x: x[1], reverse=True)[:10]
        if sorted_dmg:
            lines = []
            for i, (uid, dmg) in enumerate(sorted_dmg, 1):
                prefix = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"#{i}")
                lines.append(f"{prefix} <@{uid}> — {dmg:,} DMG")
            embed.add_field(name="Damage Ranking / 伤害排名", value="\n".join(lines), inline=False)

        return embed


    @discord.ui.button(label="⚔️ Attack / 攻击", style=discord.ButtonStyle.danger, row=0)
    async def attack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return

        war = _active_wars.get(self.guild["id"])
        if not war or war.get("status") != "active":
            await interaction.response.send_message("No active guild war! / 当前没有进行中的公会战！", ephemeral=True)
            return

        # Cooldown check (10 seconds)
        now = datetime.datetime.now().timestamp()
        last = _user_cooldowns.get((self.guild["id"], uid), 0)
        if now - last < 10:
            remaining = int(10 - (now - last))
            await interaction.response.send_message(f"⏰ Cooldown: {remaining}s / 冷却中：{remaining}秒", ephemeral=True)
            return
        _user_cooldowns[(self.guild["id"], uid)] = now

        # Calculate damage
        stats = _get_user_stats(uid)
        base_atk = stats["attack"]
        action = random.choice(WAR_ACTIONS)

        dmg_mult = {"slash": 1.0, "charge": 2.0, "power_strike": 1.5, "defend": 0.5}
        action_names = {
            "slash": "斩击 / Slash", "charge": "蓄力攻击 / Charge",
            "power_strike": "强力打击 / Power Strike", "defend": "防御反击 / Counter",
        }
        dmg = int(base_atk * dmg_mult[action] * random.uniform(0.8, 1.5))
        crit = random.random() < 0.1
        if crit:
            dmg = int(dmg * 2)

        war["boss_hp"] = max(0, war["boss_hp"] - dmg)
        war["total_damage"] += dmg
        war["damages"][uid] = war["damages"].get(uid, 0) + dmg

        # Persist to DB
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE guild_war SET total_damage = total_damage + ?, boss_hp = ? WHERE id = ?",
                (dmg, war["boss_hp"], war["war_id"]),
            )
            cur.execute(
                """INSERT INTO guild_war_damage (war_id, user_id, damage, actions, last_action_at)
                   VALUES (?, ?, ?, 1, datetime('now'))
                   ON CONFLICT(war_id, user_id) DO UPDATE SET
                   damage = damage + ?, actions = actions + 1, last_action_at = datetime('now')""",
                (war["war_id"], uid, dmg, dmg),
            )
            conn.commit()

        msg = f"⚔️ <@{uid}> 使用了 **{action_names[action]}** — {'💥 CRIT! ' if crit else ''}**{dmg}** DMG！"

        # Check if boss defeated
        if war["boss_hp"] <= 0:
            war["status"] = "ended"
            war["ended_at"] = datetime.datetime.now().isoformat()
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE guild_war SET status='ended', ended_at=datetime('now'), boss_hp=0 WHERE id=?",
                    (war["war_id"],),
                )
                conn.commit()
            await interaction.response.send_message(
                f"{msg}\n\n🎉 **Boss Defeated! / Boss 被击败！**\n"
                f"Total Damage / 总伤害: {war['total_damage']:,}\n"
                f"Rewards are being distributed... / 奖励正在发放..."
            )
            await _distribute_war_rewards(interaction.guild, war)
            return

        # Rebuild embed
        embed = self.build_embed()
        await interaction.response.send_message(f"{msg}", ephemeral=False)
        # Also update panel if possible
        try:
            if hasattr(self, 'message') and self.message:
                new_view = GuildWarView(self.uid, self.guild, war, self.main_view)
                new_embed = new_view.build_embed()
                await self.message.edit(embed=new_embed, view=new_view)
        except (discord.NotFound, discord.HTTPException):
            pass

    @discord.ui.button(label="🏆 Ranking / 排名", style=discord.ButtonStyle.primary, row=0)
    async def ranking_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        guild_id = self.guild["id"]

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM guild_war WHERE guild_id = ? ORDER BY id DESC LIMIT 1",
                (guild_id,),
            )
            last_war = cur.fetchone()
        if not last_war:
            await interaction.response.send_message("No guild war history! / 暂无公会战记录！", ephemeral=True)
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT user_id, damage, actions FROM guild_war_damage WHERE war_id = ? ORDER BY damage DESC LIMIT 20",
                (last_war["id"],),
            )
            rows = cur.fetchall()

        if not rows:
            await interaction.response.send_message("No participants. / 无参战记录。", ephemeral=True)
            return

        lines = []
        for i, r in enumerate(rows, 1):
            prefix = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"#{i}")
            lines.append(f"{prefix} <@{r['user_id']}> — {r['damage']:,} DMG ({r['actions']} actions)")

        embed = discord.Embed(
            title=f"🏆 Guild War Ranking — {self.guild['name']}",
            description="\n".join(lines),
            color=0xF1C40F,
        )
        embed.set_footer(text=f"War ID: {last_war['id']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            try:
                await interaction.response.edit_message(view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(view=self.main_view)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass


# ══════════════════════════════════════════════════════════════
# War reward distribution
# ══════════════════════════════════════════════════════════════
async def _distribute_war_rewards(guild, war: dict):
    damages = sorted(war["damages"].items(), key=lambda x: x[1], reverse=True)
    total_dmg = max(1, war["total_damage"])
    total_pool = min(50000, total_dmg)  # gold pool

    for rank, (uid, dmg) in enumerate(damages, 1):
        pct = dmg / total_dmg
        gold = int(total_pool * pct * 0.8) + int(total_pool * 0.2 / max(1, len(damages)))
        contribution = int(dmg / 10)

        _add_coins(uid, gold, f"公会战奖励 / Guild War reward (Rank #{rank})")

        # Add contribution
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE mmorpg_guild_members SET contribution = contribution + ? WHERE user_id = ?",
                (contribution, uid),
            )
            cur.execute(
                "UPDATE mmorpg_guilds SET total_contribution = total_contribution + ? WHERE id = ?",
                (contribution, war["guild_id"]),
            )
            conn.commit()

    logger.info(f"[GuildWar] Rewards distributed for guild {war['guild_id']}, "
                f"{len(damages)} participants, {total_pool}G pool")


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════
class GuildWarCog(commands.Cog):
    """公会战系统 / Guild War System."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ══════════════════════════════════════════════════════════
    # Weekly guild war check
    # ══════════════════════════════════════════════════════════
    @tasks.loop(minutes=1)
    async def war_scheduler(self):
        now = datetime.datetime.now()
        if now.weekday() != GUILD_WAR_DAY or now.hour != GUILD_WAR_HOUR or now.minute != 0:
            return

        logger.info("[GuildWar] Saturday 20:00 — Starting guild wars...")
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name FROM mmorpg_guilds")
            guilds = [dict(r) for r in cur.fetchall()]

        for guild in guilds:
            if guild["id"] in _active_wars:
                continue

            members = _get_guild_members(guild["id"])
            if len(members) < 1:
                continue

            boss_hp = BOSS_BASE_HP + BOSS_HP_PER_MEMBER * len(members)
            war_date = now.strftime("%Y-%m-%d")

            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO guild_war (guild_id, war_date, boss_hp, boss_max_hp, status, started_at) "
                    "VALUES (?, ?, ?, ?, 'active', datetime('now'))",
                    (guild["id"], war_date, boss_hp, boss_hp),
                )
                war_id = cur.lastrowid
                conn.commit()

            _active_wars[guild["id"]] = {
                "war_id": war_id,
                "guild_id": guild["id"],
                "guild_name": guild["name"],
                "boss_hp": boss_hp,
                "boss_max_hp": boss_hp,
                "total_damage": 0,
                "damages": {},
                "status": "active",
                "started_at": now.isoformat(),
            }

            # Announce to guild channel if possible
            for g in self.bot.guilds:
                for ch in g.text_channels:
                    if ch.name in ("mmorpg", "guild", "general"):
                        embed = discord.Embed(
                            title="⚔️ Guild War Has Started! / 公会战开始！",
                            description=(
                                f"**{guild['name']}** Guild War is now live!\n"
                                f"公会战已经开始！\n\n"
                                f"Boss HP / Boss血量: **{boss_hp:,}**\n"
                                f"Use `/gmpt-guild-war` to join the fight! / 用 `/gmpt-guild-war` 参战！"
                            ),
                            color=0xE74C3C,
                        )
                        try:
                            await ch.send(embed=embed)
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                        break

            logger.info(f"[GuildWar] Started war for guild {guild['name']} (ID: {guild['id']}), Boss HP: {boss_hp}")

        # Cleanup ended wars older than 1 hour
        now_ts = now.timestamp()
        to_remove = []
        for gid, war in _active_wars.items():
            if war.get("status") != "active":
                started = war.get("started_at", "")
                try:
                    start_ts = datetime.datetime.fromisoformat(started).timestamp()
                    if now_ts - start_ts > 7200:
                        to_remove.append(gid)
                except (ValueError, TypeError):
                    to_remove.append(gid)
        for gid in to_remove:
            _active_wars.pop(gid, None)

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.war_scheduler.is_running():
            self.war_scheduler.start()
            logger.info("[GuildWar] War scheduler started")

    # ══════════════════════════════════════════════════════════
    # /gmpt-guild-war
    # ══════════════════════════════════════════════════════════
    @app_commands.command(
        name="gmpt-guild-war",
        description="公会战面板 / Guild War panel"
    )
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def guild_war_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        guild = _get_user_guild(uid)
        if not guild:
            await interaction.response.send_message(
                "You are not in a guild! / 你不在任何公会中！",
                ephemeral=True,
            )
            return

        war = _active_wars.get(guild["id"])
        view = GuildWarView(uid, guild, war)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildWarCog(bot))
    logger.info("MMORPG Guild War cog loaded")
