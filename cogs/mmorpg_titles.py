"""
GMPT Bot — MMORPG Titles / 称号系统
/gmpt-titles — View and equip titles / 查看和装备称号
unlock_title() — Called by other cogs to unlock titles / 其他cog调用解锁称号
"""
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Title Definitions
# ══════════════════════════════════════════════════════════════
TITLE_DEFS = {
    "novice": {
        "name_cn": "新手冒险者",
        "name_en": "Novice Adventurer",
        "emoji": "\U0001f331",
        "condition_cn": "默认称号",
        "condition_en": "Default title",
        "unlock_type": "default",
        "unlock_value": 0,
    },
    "work_king": {
        "name_cn": "打工皇帝",
        "name_en": "Work King",
        "emoji": "\u2692\ufe0f",
        "condition_cn": "打工累计收入 10,000",
        "condition_en": "Earn 10,000 from work",
        "unlock_type": "work_income",
        "unlock_value": 10000,
    },
    "boss_killer": {
        "name_cn": "Boss杀手",
        "name_en": "Boss Killer",
        "emoji": "\U0001f409",
        "condition_cn": "Boss击杀 10 次",
        "condition_en": "Kill 10 bosses",
        "unlock_type": "boss_kills",
        "unlock_value": 10,
    },
    "pvp_champion": {
        "name_cn": "PVP冠军",
        "name_en": "PVP Champion",
        "emoji": "\u2694\ufe0f",
        "condition_cn": "PVP胜场 20",
        "condition_en": "Win 20 PVP matches",
        "unlock_type": "pvp_wins",
        "unlock_value": 20,
    },
    "millionaire": {
        "name_cn": "亿万富翁",
        "name_en": "Millionaire",
        "emoji": "\U0001f4b0",
        "condition_cn": "持有金币 100,000",
        "condition_en": "Hold 100,000 coins",
        "unlock_type": "balance",
        "unlock_value": 100000,
    },
    "dungeon_king": {
        "name_cn": "副本之王",
        "name_en": "Dungeon King",
        "emoji": "\U0001f3f0",
        "condition_cn": "通关地下城 5 次",
        "condition_en": "Clear 5 dungeons",
        "unlock_type": "dungeon_clears",
        "unlock_value": 5,
    },
    "gambler": {
        "name_cn": "赌神",
        "name_en": "Gambling God",
        "emoji": "\U0001f3b2",
        "condition_cn": "赌博累计赢 50,000",
        "condition_en": "Win 50,000 from gambling",
        "unlock_type": "gamble_wins",
        "unlock_value": 50000,
    },
    "collector": {
        "name_cn": "收藏家",
        "name_en": "Collector",
        "emoji": "\U0001f392",
        "condition_cn": "拥有 20 件不同物品",
        "condition_en": "Own 20 different items",
        "unlock_type": "unique_items",
        "unlock_value": 20,
    },
    "max_level": {
        "name_cn": "满级勇士",
        "name_en": "Max Level Hero",
        "emoji": "\u2b50",
        "condition_cn": "达到 Lv.50",
        "condition_en": "Reach Lv.50",
        "unlock_type": "level",
        "unlock_value": 50,
    },
    # ── Battle Titles / 战斗称号 (10) ──
    "warrior": {
        "name_cn": "战士",
        "name_en": "Warrior",
        "emoji": "\u2694\ufe0f",
        "condition_cn": "Boss击杀 20 次",
        "condition_en": "Kill 20 bosses",
        "unlock_type": "boss_kills",
        "unlock_value": 20,
        "grade": "white",
    },
    "slayer": {
        "name_cn": "屠龙者",
        "name_en": "Dragon Slayer",
        "emoji": "\U0001f409",
        "condition_cn": "Boss击杀 50 次",
        "condition_en": "Kill 50 bosses",
        "unlock_type": "boss_kills",
        "unlock_value": 50,
        "grade": "blue",
    },
    "gladiator": {
        "name_cn": "角斗士",
        "name_en": "Gladiator",
        "emoji": "\U0001f5e1\ufe0f",
        "condition_cn": "PVP胜场 50",
        "condition_en": "Win 50 PVP matches",
        "unlock_type": "pvp_wins",
        "unlock_value": 50,
        "grade": "blue",
    },
    "warlord": {
        "name_cn": "战争领主",
        "name_en": "Warlord",
        "emoji": "\U0001f3f0",
        "condition_cn": "PVP胜场 100",
        "condition_en": "Win 100 PVP matches",
        "unlock_type": "pvp_wins",
        "unlock_value": 100,
        "grade": "purple",
    },
    "dungeon_master": {
        "name_cn": "地下城主",
        "name_en": "Dungeon Master",
        "emoji": "\U0001f3f0",
        "condition_cn": "通关地下城 20 次",
        "condition_en": "Clear 20 dungeons",
        "unlock_type": "dungeon_clears",
        "unlock_value": 20,
        "grade": "blue",
    },
    "legendary_hero": {
        "name_cn": "传说英雄",
        "name_en": "Legendary Hero",
        "emoji": "\U0001f31f",
        "condition_cn": "达到 Lv.100",
        "condition_en": "Reach Lv.100",
        "unlock_type": "level",
        "unlock_value": 100,
        "grade": "gold",
    },
    "arena_champion": {
        "name_cn": "竞技场冠军",
        "name_en": "Arena Champion",
        "emoji": "\U0001f3c6",
        "condition_cn": "PVP胜场 200",
        "condition_en": "Win 200 PVP matches",
        "unlock_type": "pvp_wins",
        "unlock_value": 200,
        "grade": "gold",
    },
    "dungeon_conqueror": {
        "name_cn": "副本征服者",
        "name_en": "Dungeon Conqueror",
        "emoji": "\U0001f4af",
        "condition_cn": "通关地下城 50 次",
        "condition_en": "Clear 50 dungeons",
        "unlock_type": "dungeon_clears",
        "unlock_value": 50,
        "grade": "purple",
    },
    "boss_slayer": {
        "name_cn": "魔王猎手",
        "name_en": "Demon Slayer",
        "emoji": "\u2620\ufe0f",
        "condition_cn": "Boss击杀 100 次",
        "condition_en": "Kill 100 bosses",
        "unlock_type": "boss_kills",
        "unlock_value": 100,
        "grade": "purple",
    },
    "god_of_war": {
        "name_cn": "战神",
        "name_en": "God of War",
        "emoji": "\U0001f451",
        "condition_cn": "Boss击杀 200 次",
        "condition_en": "Kill 200 bosses",
        "unlock_type": "boss_kills",
        "unlock_value": 200,
        "grade": "gold",
    },
    # ── Collection Titles / 收集称号 (5) ──
    "treasure_hunter": {
        "name_cn": "寻宝猎人",
        "name_en": "Treasure Hunter",
        "emoji": "\U0001f50d",
        "condition_cn": "收集 10 件不同物品",
        "condition_en": "Own 10 different items",
        "unlock_type": "unique_items",
        "unlock_value": 10,
        "grade": "white",
    },
    "artifact_collector": {
        "name_cn": "神器收集者",
        "name_en": "Artifact Collector",
        "emoji": "\U0001f48e",
        "condition_cn": "收集 50 件不同物品",
        "condition_en": "Own 50 different items",
        "unlock_type": "unique_items",
        "unlock_value": 50,
        "grade": "blue",
    },
    "hoarder": {
        "name_cn": "囤积狂",
        "name_en": "Hoarder",
        "emoji": "\U0001f4e6",
        "condition_cn": "收集 100 件不同物品",
        "condition_en": "Own 100 different items",
        "unlock_type": "unique_items",
        "unlock_value": 100,
        "grade": "purple",
    },
    "museum_curator": {
        "name_cn": "博物馆长",
        "name_en": "Museum Curator",
        "emoji": "\U0001f3db\ufe0f",
        "condition_cn": "收集 200 件不同物品",
        "condition_en": "Own 200 different items",
        "unlock_type": "unique_items",
        "unlock_value": 200,
        "grade": "purple",
    },
    "omni_collector": {
        "name_cn": "全知收藏家",
        "name_en": "Omni-Collector",
        "emoji": "\U0001f31f",
        "condition_cn": "收集 500 件不同物品",
        "condition_en": "Own 500 different items",
        "unlock_type": "unique_items",
        "unlock_value": 500,
        "grade": "gold",
    },
    # ── Event Titles / 活动称号 (5) ──
    "festival_goer": {
        "name_cn": "节日狂欢者",
        "name_en": "Festival Goer",
        "emoji": "\U0001f389",
        "condition_cn": "参与 3 次特殊活动",
        "condition_en": "Join 3 special events",
        "unlock_type": "event_participation",
        "unlock_value": 3,
        "grade": "white",
    },
    "event_veteran": {
        "name_cn": "活动老手",
        "name_en": "Event Veteran",
        "emoji": "\U0001f38a",
        "condition_cn": "参与 10 次特殊活动",
        "condition_en": "Join 10 special events",
        "unlock_type": "event_participation",
        "unlock_value": 10,
        "grade": "blue",
    },
    "lucky_star": {
        "name_cn": "幸运星",
        "name_en": "Lucky Star",
        "emoji": "\U0001f31f",
        "condition_cn": "活动抽奖中奖 1 次",
        "condition_en": "Win 1 event lottery",
        "unlock_type": "event_win",
        "unlock_value": 1,
        "grade": "purple",
    },
    "festival_king": {
        "name_cn": "活动之王",
        "name_en": "Festival King",
        "emoji": "\U0001f451",
        "condition_cn": "参与 30 次特殊活动",
        "condition_en": "Join 30 special events",
        "unlock_type": "event_participation",
        "unlock_value": 30,
        "grade": "purple",
    },
    "legend_of_festival": {
        "name_cn": "节庆传说",
        "name_en": "Legend of Festival",
        "emoji": "\u2728",
        "condition_cn": "参与 50 次特殊活动",
        "condition_en": "Join 50 special events",
        "unlock_type": "event_participation",
        "unlock_value": 50,
        "grade": "gold",
    },
}


def _init_titles_db():
    """Initialize titles table."""
    with get_db_ctx() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_titles (
                user_id TEXT NOT NULL,
                title_key TEXT NOT NULL,
                unlocked_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, title_key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_active_title (
                user_id TEXT PRIMARY KEY,
                title_key TEXT NOT NULL DEFAULT 'novice'
            )
        """)
        conn.commit()


_init_titles_db()


def _get_user_titles(uid: str) -> set:
    """Get set of unlocked title keys."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT title_key FROM user_titles WHERE user_id = ?", (uid,))
        return {r["title_key"] for r in cur.fetchall()}


def _get_active_title(uid: str) -> str:
    """Get the currently equipped title key."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT title_key FROM user_active_title WHERE user_id = ?", (uid,))
        row = cur.fetchone()
    return row["title_key"] if row else "novice"


def _get_title_display(uid: str) -> str:
    """Get display string for user's title, e.g. [Boss杀手]."""
    active_key = _get_active_title(uid)
    td = TITLE_DEFS.get(active_key, TITLE_DEFS["novice"])
    return f"[{td['emoji']} {td['name_cn']}]"


def unlock_title(uid: str, title_key: str) -> bool:
    """Attempt to unlock a title. Returns True if newly unlocked."""
    if title_key not in TITLE_DEFS:
        return False
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO user_titles (user_id, title_key) VALUES (?, ?)",
            (uid, title_key),
        )
        conn.commit()
        if cur.rowcount > 0:
            logger.info(f"Title unlocked: {uid} -> {title_key}")
            return True
    return False


def check_and_unlock_titles(uid: str, stat_type: str, current_value: int) -> list:
    """Check all titles of a given stat type and unlock any that qualify.
    Returns list of newly unlocked title keys."""
    newly_unlocked = []
    for key, td in TITLE_DEFS.items():
        if td["unlock_type"] == stat_type and current_value >= td["unlock_value"]:
            if unlock_title(uid, key):
                newly_unlocked.append(key)
    return newly_unlocked


class TitlesView(discord.ui.View):
    """View all titles with unlock status and equip button."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=None)
        self.uid = uid
        self.main_view = main_view

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Refresh", emoji="\U0001f504", style=discord.ButtonStyle.primary, row=0)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_titles_embed(self.uid)
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="\U0001f519", style=discord.ButtonStyle.secondary, row=0)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.followup.edit_message(embed=embed, view=self.main_view)
        else:
            await interaction.response.edit_message(content="Main panel not available.", view=None)


def build_titles_embed(uid: str) -> discord.Embed:
    """Build the titles display embed."""
    unlocked = _get_user_titles(uid)
    active_key = _get_active_title(uid)

    # Ensure "novice" is always unlocked
    if "novice" not in unlocked:
        unlock_title(uid, "novice")
        unlocked.add("novice")

    embed = discord.Embed(
        title="\U0001f3c5 Titles / 称号系统",
        description="Your unlocked titles / 你已解锁的称号：",
        color=0xF1C40F,
    )

    grade_emojis = {"white": "\u26aa", "blue": "\U0001f535", "purple": "\U0001f7e3", "gold": "\U0001f7e1"}

    lines = []
    for key, td in TITLE_DEFS.items():
        is_unlocked = key in unlocked
        is_active = key == active_key
        status = "\u2705" if is_active else ("\U0001f513" if is_unlocked else "\U0001f512")
        grade = td.get("grade")
        grade_str = f" {grade_emojis.get(grade, '')}" if grade else ""
        line = f"{status}{grade_str} {td['emoji']} **{td['name_cn']}**"
        if is_active:
            line += " *(Equipped / 已装备)*"
        line += f"\n\u3000{td['condition_cn']}"
        lines.append(line)

    embed.add_field(
        name="All Titles / 全部称号",
        value="\n".join(lines),
        inline=False,
    )

    active_td = TITLE_DEFS.get(active_key, TITLE_DEFS["novice"])
    embed.set_footer(text=f"Current: {active_td['emoji']} {active_td['name_cn']}  |  /gmpt-titles equip <key>")
    return embed


class TitlesHubView(discord.ui.View):
    """Hub panel: pick Titles or Achievements, then Back."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=None)
        self.uid = uid
        self.main_view = main_view

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Titles 称号", emoji="🏷️", style=discord.ButtonStyle.primary, row=0)
    async def titles_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_titles_embed(self.uid)
        view = TitlesView(self.uid, main_view=self.main_view)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Achievements 成就", emoji="🏆", style=discord.ButtonStyle.primary, row=0)
    async def achievements_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.achievements import AchievementsView
        view = AchievementsView(uid=self.uid, main_view=self.main_view)
        embed = await view._get_achievements_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.followup.edit_message(embed=embed, view=self.main_view)


class MMORPGTitles(CogBase):
    """称号系统 / Titles System"""

    def __init__(self, bot):
        super().__init__()
        _init_titles_db()

    @app_commands.command(name="gmpt-titles", description="\U0001f3c5 View your titles / 查看你的称号")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def titles_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        embed = build_titles_embed(uid)
        view = TitlesView(uid)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="gmpt-title-equip", description="\U0001f3c5 Equip a title / 装备称号")
    @app_commands.describe(title_key="Title key / 称号key (e.g. novice, boss_killer)")
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: (i.guild_id, i.user.id))
    async def equip_cmd(self, interaction: discord.Interaction, title_key: str):
        uid = str(interaction.user.id)

        if title_key not in TITLE_DEFS:
            return await interaction.response.send_message(
                f"Unknown title / 未知称号: `{title_key}`\nAvailable: {', '.join(TITLE_DEFS.keys())}",
                ephemeral=True,
            )

        unlocked = _get_user_titles(uid)
        if title_key not in unlocked:
            td = TITLE_DEFS[title_key]
            return await interaction.response.send_message(
                f"\U0001f512 Title locked / 称号未解锁！\n"
                f"Condition / 条件: {td['condition_cn']}",
                ephemeral=True,
            )

        with get_db_ctx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_active_title (user_id, title_key) VALUES (?, ?)",
                (uid, title_key),
            )
            conn.commit()

        td = TITLE_DEFS[title_key]
        await interaction.response.send_message(
            f"\u2705 Title equipped / 称号已装备: {td['emoji']} **{td['name_cn']}**",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(MMORPGTitles(bot))
