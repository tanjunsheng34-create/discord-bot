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

    lines = []
    for key, td in TITLE_DEFS.items():
        is_unlocked = key in unlocked
        is_active = key == active_key
        status = "\u2705" if is_active else ("\U0001f513" if is_unlocked else "\U0001f512")
        line = f"{status} {td['emoji']} **{td['name_cn']}**"
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


class MMORPGTitles(CogBase):
    """称号系统 / Titles System"""

    def __init__(self, bot):
        super().__init__(bot)
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
