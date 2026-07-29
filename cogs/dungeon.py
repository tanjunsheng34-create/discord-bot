"""
cogs/dungeon.py — 地下城 / Dungeon
5 floors, random monsters per floor, daily 1 free run (+200G per extra).
Floor rewards increase with depth.
"""

import random
import time
import asyncio
import discord
from discord import app_commands

from database import get_db_ctx
from utils.cog_base import CogBase
from utils.animations import battle_animation, progress_bar
from cogs.economy import add_coins, get_balance

# ── Dungeon Monsters ──
DUNGEON_MONSTERS = {
    1: [  # Floor 1
        {"name": "史莱姆 Slime", "hp": 50, "atk": 8, "def": 2, "exp": 20, "coins": 50, "emoji": "🟢"},
        {"name": "哥布林 Goblin", "hp": 65, "atk": 12, "def": 3, "exp": 30, "coins": 70, "emoji": "👺"},
        {"name": "巨型老鼠 Giant Rat", "hp": 45, "atk": 10, "def": 1, "exp": 25, "coins": 60, "emoji": "🐀"},
    ],
    2: [  # Floor 2
        {"name": "骷髅战士 Skeleton Warrior", "hp": 90, "atk": 18, "def": 5, "exp": 50, "coins": 120, "emoji": "💀"},
        {"name": "暗影法师 Shadow Mage", "hp": 70, "atk": 22, "def": 3, "exp": 55, "coins": 130, "emoji": "🧙‍♂️"},
        {"name": "石像鬼 Gargoyle", "hp": 100, "atk": 15, "def": 8, "exp": 45, "coins": 110, "emoji": "🗿"},
    ],
    3: [  # Floor 3
        {"name": "牛头人 Minotaur", "hp": 140, "atk": 30, "def": 12, "exp": 100, "coins": 250, "emoji": "🐂"},
        {"name": "亡灵骑士 Death Knight", "hp": 160, "atk": 28, "def": 15, "exp": 110, "coins": 280, "emoji": "⚰️"},
        {"name": "地狱犬 Hellhound", "hp": 120, "atk": 35, "def": 10, "exp": 95, "coins": 230, "emoji": "🐺"},
    ],
    4: [  # Floor 4
        {"name": "狮鹫 Griffin", "hp": 200, "atk": 40, "def": 20, "exp": 180, "coins": 450, "emoji": "🦅"},
        {"name": "九头蛇 Hydra", "hp": 250, "atk": 35, "def": 22, "exp": 200, "coins": 500, "emoji": "🐍"},
        {"name": "岩石巨人 Stone Golem", "hp": 300, "atk": 30, "def": 30, "exp": 170, "coins": 420, "emoji": "🗻"},
    ],
    5: [  # Floor 5 — Boss
        {"name": "暗影巨龙 Shadow Dragon", "hp": 400, "atk": 55, "def": 25, "exp": 500, "coins": 1200, "emoji": "🐉"},
        {"name": "魔王 Demon Lord", "hp": 450, "atk": 50, "def": 20, "exp": 550, "coins": 1300, "emoji": "👹"},
        {"name": "远古巫妖 Ancient Lich", "hp": 350, "atk": 60, "def": 18, "exp": 600, "coins": 1400, "emoji": "💀"},
    ],
}

FLOOR_NAMES = {
    1: "阴暗洞穴 Dark Cave",
    2: "亡灵墓穴 Undead Tomb",
    3: "烈焰深渊 Fire Abyss",
    4: "风暴之巅 Storm Peak",
    5: "魔王宫殿 Demon Lord's Palace",
}

EXTRA_RUN_COST = 200


def _init_dungeon_db():
    with get_db_ctx() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dungeon_runs (
                user_id TEXT PRIMARY KEY,
                free_runs_used INTEGER DEFAULT 0,
                last_reset_ts INTEGER DEFAULT 0
            )
        """)
        conn.commit()


def _get_dungeon_runs(user_id: str) -> tuple:
    """Return (free_remaining, extra_cost)."""
    import datetime
    now = int(time.time())
    utc8_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    midnight_ts = int(utc8_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    tomorrow_ts = midnight_ts + 86400

    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT free_runs_used, last_reset_ts FROM dungeon_runs WHERE user_id=?", (user_id,))
        row = cur.fetchone()

    if not row or row["last_reset_ts"] < midnight_ts:
        # Reset for new day
        free_runs_used = 0
        _save_dungeon_state(user_id, 0, tomorrow_ts)
    else:
        free_runs_used = row["free_runs_used"]

    free_remaining = max(0, 1 - free_runs_used)
    extra_cost = EXTRA_RUN_COST if free_runs_used >= 1 else 0
    return free_remaining, extra_cost


def _save_dungeon_state(user_id: str, free_runs_used: int, reset_ts: int):
    with get_db_ctx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO dungeon_runs (user_id, free_runs_used, last_reset_ts) VALUES (?,?,?)",
            (user_id, free_runs_used, reset_ts),
        )
        conn.commit()


def _get_player_stats(user_id: str) -> dict:
    """Get player combat stats from users table + equipment."""
    from cogs.mmorpg_equipment import _get_equip_stats
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT level, hp, max_hp, attack, defense FROM users WHERE discord_id=?",
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        return {"level": 1, "hp": 100, "max_hp": 100, "atk": 15, "def": 5, "crit": 5, "spd": 10}

    equip_stats = _get_equip_stats(user_id)
    return {
        "level": row["level"],
        "hp": row["hp"],
        "max_hp": row["max_hp"],
        "atk": row["attack"] + equip_stats.get("atk", 0),
        "def": row["defense"] + equip_stats.get("def", 0),
        "crit": 5 + equip_stats.get("crit", 0),
        "spd": 10 + equip_stats.get("spd", 0),
    }


class DungeonView(discord.ui.View):
    """地下城主面板 / Dungeon main panel."""

    def __init__(self, guild, user_id: str, user_name: str):
        super().__init__(timeout=300)
        self.guild = guild
        self.uid = user_id
        self.uname = user_name
        self._build()

    def _build(self):
        self.clear_items()
        free, extra = _get_dungeon_runs(self.uid)

        for floor in range(1, 6):
            btn = discord.ui.Button(
                label=f"第{floor}层 Floor {floor} | {FLOOR_NAMES[floor]}",
                style=discord.ButtonStyle.primary if floor <= 3 else discord.ButtonStyle.danger,
                row=floor - 1,
                custom_id=f"dungeon_f{floor}",
            )
            btn.callback = self._make_floor_callback(floor)
            self.add_item(btn)

    def _make_floor_callback(self, floor: int):
        async def cb(interaction: discord.Interaction):
            await self._start_floor(interaction, floor)
        return cb

    async def _start_floor(self, interaction: discord.Interaction, floor: int):
        free, extra = _get_dungeon_runs(self.uid)
        cost = extra if free == 0 else 0

        if cost > 0:
            bal = get_balance(self.uid)
            if bal < cost:
                await interaction.response.send_message(
                    f"❌ 金币不足！需要 🪙 **{cost}** / Not enough coins! Need 🪙 **{cost}**",
                    ephemeral=True,
                )
                return
            add_coins(self.uid, -cost, "地下城入场费 / Dungeon entry fee")

        # Mark run used
        free_runs_used = 1 if free > 0 else 2
        import datetime
        utc8_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        tomorrow_ts = int(utc8_now.replace(hour=0, minute=0, second=0).timestamp()) + 86400
        _save_dungeon_state(self.uid, free_runs_used, utc8_now.replace(hour=0, minute=0, second=0).timestamp() + 86400)

        await interaction.response.defer()

        # Show entering animation
        msg = await interaction.followup.send(
            f"🚪 {self.uname} 进入了 **{FLOOR_NAMES[floor]}**...\n"
            f"🚪 {self.uname} enters **{FLOOR_NAMES[floor]}**..."
        )
        await asyncio.sleep(1.5)

        # Pick random monster
        monster = random.choice(DUNGEON_MONSTERS[floor])
        player = _get_player_stats(self.uid)

        # Battle simulation
        p_hp = player["hp"]
        m_hp = monster["hp"]
        p_max_hp = player["max_hp"]
        m_max_hp = monster["hp"]
        round_num = 0
        battle_log = []

        while p_hp > 0 and m_hp > 0 and round_num < 20:
            round_num += 1

            # Player attacks (with crit chance)
            crit_hit = random.random() < (player["crit"] / 100)
            p_dmg = max(1, random.randint(player["atk"] // 2, player["atk"]) - monster["def"] // 2)
            if crit_hit:
                p_dmg = int(p_dmg * 1.8)
            m_hp = max(0, m_hp - p_dmg)

            battle_log.append(f"⚔️ {self.uname} 造成 {p_dmg} 伤害{'💥暴击!' if crit_hit else ''} / Dealt {p_dmg} dmg{' CRIT!' if crit_hit else ''}")

            if m_hp <= 0:
                break

            # Monster attacks
            m_dmg = max(1, random.randint(monster["atk"] // 2, monster["atk"]) - player["def"] // 2)
            p_hp = max(0, p_hp - m_dmg)
            battle_log.append(f"👊 {monster['emoji']} {monster['name']} 造成 {m_dmg} 伤害 / {monster['name']} dealt {m_dmg} dmg")

            # Update battle message every 2 rounds
            if round_num % 2 == 0:
                p_bar = progress_bar(p_hp, p_max_hp)
                m_bar = progress_bar(m_hp, m_max_hp)
                embed = discord.Embed(
                    title=f"⚔️ 第{floor}层 / Floor {floor} | 回合 Round {round_num}",
                    color=0xFF6600 if p_hp > 0 else 0xFF0000,
                )
                embed.add_field(name=f"🧑 {self.uname}", value=f"❤️ HP: {p_bar}", inline=True)
                embed.add_field(name=f"{monster['emoji']} {monster['name']}", value=f"❤️ HP: {m_bar}", inline=True)
                embed.description = "\n".join(battle_log[-4:])
                await msg.edit(embed=embed)
                await asyncio.sleep(1.2)

        # Battle result
        if p_hp > 0:
            # Victory!
            coins_earned = monster["coins"] + random.randint(-20, 50)
            exp_earned = monster["exp"]

            add_coins(self.uid, coins_earned, f"地下城第{floor}层奖励 / Dungeon floor {floor} reward")
            # Add exp with level-up check
            from cogs.economy_jobs import _add_user_xp
            _, did_level, old_lv, new_lv, lv_ups = _add_user_xp(self.uid, exp_earned)

            bal = get_balance(self.uid)
            embed = discord.Embed(
                title=f"🏆 胜利！Victory! | {FLOOR_NAMES[floor]}",
                description=(
                    f"🪙 获得金币 Earned coins: **{coins_earned}**\n"
                    f"✨ 获得经验 Earned EXP: **{exp_earned}**\n"
                    f"💰 余额 Balance: 🪙 **{bal:,}**\n"
                    f"❤️ 剩余HP Remaining HP: {p_hp}/{p_max_hp}"
                ),
                color=0x2ECC71,
            )

            # Floor 5 special: chance for equipment drop
            if floor == 5 and random.random() < 0.3:
                embed.add_field(
                    name="🎁 额外掉落 Bonus Drop!",
                    value="⚔️ 获得随机装备一件！/ Random equipment obtained! (type /gmpt-equipment to view)",
                    inline=False,
                )
        else:
            # Defeat
            embed = discord.Embed(
                title=f"💀 战败！Defeat! | {FLOOR_NAMES[floor]}",
                description=(
                    f"你被 {monster['emoji']} **{monster['name']}** 击败了！\n"
                    f"You were defeated by {monster['emoji']} **{monster['name']}**!\n\n"
                    f"💡 提示 Tip: 提升等级和装备再来挑战 / Level up and gear up then try again!"
                ),
                color=0xE74C3C,
            )

        embed.set_footer(text=f"地下城每日免费1次 / Dungeon: 1 free run daily (extra: 🪙 {EXTRA_RUN_COST})")
        await msg.edit(embed=embed)


class Dungeon(CogBase):
    """地下城系统 / Dungeon System"""

    def __init__(self, bot):
        super().__init__(bot)
        _init_dungeon_db()

    @app_commands.command(name="gmpt-dungeon", description="🏰 地下城副本 / Dungeon — explore and fight monsters!")
    async def dungeon_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        uname = interaction.user.display_name
        free, extra = _get_dungeon_runs(uid)
        player = _get_player_stats(uid)

        cost_text = "免费 Free" if free > 0 else f"🪙 {extra}"
        embed = discord.Embed(
            title=f"🏰 地下城 Dungeon | {uname}",
            description=(
                f"❤️ HP: {player['hp']}/{player['max_hp']}  |  ⚔️ ATK: {player['atk']}  |  🛡️ DEF: {player['def']}\n"
                f"Lv.{player['level']}  |  入场费 Entry: **{cost_text}**\n"
                f"每日免费 1 次 / 1 free daily (额外 extra: 🪙 {EXTRA_RUN_COST})"
            ),
            color=0x8E44AD,
        )
        embed.add_field(
            name="📜 楼层信息 / Floors",
            value=(
                "**1F 阴暗洞穴 Dark Cave** — Lv.1-5\n"
                "**2F 亡灵墓穴 Undead Tomb** — Lv.5-10\n"
                "**3F 烈焰深渊 Fire Abyss** — Lv.10-15\n"
                "**4F 风暴之巅 Storm Peak** — Lv.15-20\n"
                "**5F 魔王宫殿 Demon Lord's Palace** — Lv.20+ 👑"
            ),
            inline=False,
        )
        embed.set_footer(text="选择楼层开始探索 / Select a floor to begin exploring!")

        view = DungeonView(interaction.guild, uid, uname)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Dungeon(bot))


# ══════════════════════════════════════════════════════════════
# Dungeon Lobby View — Interactive Dungeon hub
# ══════════════════════════════════════════════════════════════
class DungeonLobbyView(discord.ui.View):
    """地下城大厅面板 / Dungeon lobby panel."""

    def __init__(self, user_id: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = user_id
        self.main_view = main_view
        self._build()

    def build_main_embed(self):
        bal = get_balance(self.uid)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            today = time.strftime("%Y-%m-%d")
            cur.execute(
                "SELECT daily_used FROM dungeon_daily WHERE user_id = ? AND date = ?",
                (self.uid, today),
            )
            row = cur.fetchone()
        used_today = row["daily_used"] if row else 0
        free_left = "1 次免费" if used_today == 0 else "已用完 (used)"

        embed = discord.Embed(
            title="🏰 Dungeon / 地下城",
            description=(
                "5 层随机怪物，奖励随层数递增！\n"
                "5 floors, rewards increase with depth!\n\n"
                f"🆓 今日免费 / Free today: **{free_left}**\n"
                f"💵 额外探索 / Extra: **200G**\n"
                f"🪙 余额 / Balance: **{bal:,}**"
            ),
            color=0x8E44AD,
        )
        embed.add_field(
            name="⚔️ 开始探索 / Start",
            value="点击下方按钮直接进入地下城 / Click below to enter!",
            inline=False,
        )
        embed.set_footer(text="每日免费 1 次，额外每次 200G")
        return embed

    def _build(self):
        self.clear_items()
        explore_btn = discord.ui.Button(
            label="⚔️ Explore / 探索", style=discord.ButtonStyle.success,
            row=0, emoji="🏰", custom_id="dungeon_explore",
        )
        explore_btn.callback = self._explore_info_callback
        self.add_item(explore_btn)

        if self.main_view:
            back_btn = discord.ui.Button(
                label="Back to MMORPG / 返回", style=discord.ButtonStyle.danger,
                row=1, emoji="🏠", custom_id="dungeon_back",
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    async def _explore_info_callback(self, interaction: discord.Interaction):
        """Directly open the full DungeonView for floor selection."""
        uid = str(interaction.user.id)
        uname = interaction.user.display_name
        free, extra = _get_dungeon_runs(uid)
        player = _get_player_stats(uid)
        cost_text = "免费 Free" if free > 0 else f"🪙 {extra}"
        embed = discord.Embed(
            title=f"🏰 地下城 Dungeon | {uname}",
            description=(
                f"❤️ HP: {player['hp']}/{player['max_hp']}  |  ⚔️ ATK: {player['atk']}  |  🛡️ DEF: {player['def']}\n"
                f"Lv.{player['level']}  |  入场费 Entry: **{cost_text}**\n"
                f"每日免费 1 次 / 1 free daily (额外 extra: 🪙 {EXTRA_RUN_COST})"
            ),
            color=0x8E44AD,
        )
        embed.add_field(
            name="📜 楼层信息 / Floors",
            value=(
                "**1F 阴暗洞穴 Dark Cave** — Lv.1-5\n"
                "**2F 亡灵墓穴 Undead Tomb** — Lv.5-10\n"
                "**3F 烈焰深渊 Fire Abyss** — Lv.10-15\n"
                "**4F 风暴之巅 Storm Peak** — Lv.15-20\n"
                "**5F 魔王宫殿 Demon Lord's Palace** — Lv.20+ 👑"
            ),
            inline=False,
        )
        embed.set_footer(text="选择楼层开始探索 / Select a floor to begin exploring!")
        view = DungeonView(interaction.guild, uid, uname)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import _get_user_stats
            uid = str(self.uid)
            stats = _get_user_stats(uid)
            bal = get_balance(uid)
            embed = discord.Embed(
                title="MMORPG Main Panel / MMORPG 主面板",
                description=(
                    f"❤️ HP: **{stats['hp']}/{stats['max_hp']}**  "
                    f"🔮 MP: **{stats['mp']}/{stats['max_mp']}**\n"
                    f"⚔️ ATK: **{stats['attack']}**  🛡️ DEF: **{stats['defense']}**  "
                    f"⭐ Lv.**{stats['level']}**  🪙 **{bal:,}**\n\n"
                    f"Click a button below / 点击下方按钮："
                ),
                color=0x9B59B6,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
