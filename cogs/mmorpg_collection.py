"""
GMPT Bot — MMORPG Collection / 图鉴收集系统
/gmpt-collection — View collection progress / 查看图鉴收集进度
register_collect() — Called by other cogs to register collection items
"""
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Collection Definitions
# ══════════════════════════════════════════════════════════════

# Equipment sets: 6 themed sets, each with 6 items across all slots
EQUIPMENT_SETS = {
    "dorans_might": {
        "name_cn": "多兰之力",
        "name_en": "Doran's Might",
        "emoji": "\U0001f5e1\ufe0f",
        "grade": "white",
        "items": [
            ("weapon", "多兰之刃"),
            ("helmet", "抗魔斗篷"),
            ("armor", "锁子甲"),
            ("leggings", "草鞋"),
            ("boots", "速度之靴"),
            ("accessory", "暴击手套"),
        ],
        "bonus_desc_cn": "+5% 全属性",
        "bonus_desc_en": "+5% All Stats",
    },
    "infinity_rage": {
        "name_cn": "无尽之怒",
        "name_en": "Infinity Rage",
        "emoji": "\u2694\ufe0f",
        "grade": "blue",
        "items": [
            ("weapon", "无尽之刃"),
            ("helmet", "灭世者的死亡之帽"),
            ("armor", "日炎斗篷"),
            ("leggings", "狂战士胫甲"),
            ("boots", "无尽之靴"),
            ("accessory", "幻影之舞"),
        ],
        "bonus_desc_cn": "+5% 全属性",
        "bonus_desc_en": "+5% All Stats",
    },
    "trinity_balance": {
        "name_cn": "三相平衡",
        "name_en": "Trinity Balance",
        "emoji": "\u2696\ufe0f",
        "grade": "blue",
        "items": [
            ("weapon", "三相之力"),
            ("helmet", "振奋盔甲"),
            ("armor", "荆棘之甲"),
            ("leggings", "水银之靴"),
            ("boots", "疾行之靴"),
            ("accessory", "斯塔缇克电刃"),
        ],
        "bonus_desc_cn": "+5% 全属性",
        "bonus_desc_en": "+5% All Stats",
    },
    "shadow_hunter": {
        "name_cn": "暗影猎手",
        "name_en": "Shadow Hunter",
        "emoji": "\U0001f3f9",
        "grade": "purple",
        "items": [
            ("weapon", "暮刃"),
            ("helmet", "适应性头盔"),
            ("armor", "亡者的板甲"),
            ("leggings", "忍者足具"),
            ("boots", "暗行者之靴"),
            ("accessory", "卢安娜的飓风"),
        ],
        "bonus_desc_cn": "+5% 全属性",
        "bonus_desc_en": "+5% All Stats",
    },
    "frozen_queen": {
        "name_cn": "冰雪女王",
        "name_en": "Frozen Queen",
        "emoji": "\u2744\ufe0f",
        "grade": "purple",
        "items": [
            ("weapon", "破败王者之刃"),
            ("helmet", "深渊面具"),
            ("armor", "冰霜之心"),
            ("leggings", "明朗之靴"),
            ("boots", "风暴之靴"),
            ("accessory", "中娅沙漏"),
        ],
        "bonus_desc_cn": "+5% 全属性",
        "bonus_desc_en": "+5% All Stats",
    },
    "guardian_light": {
        "name_cn": "守护之光",
        "name_en": "Guardian Light",
        "emoji": "\U0001f6e1\ufe0f",
        "grade": "gold",
        "items": [
            ("weapon", "神圣分离者"),
            ("helmet", "兰顿之兆"),
            ("armor", "守护天使"),
            ("leggings", "轻灵之靴"),
            ("boots", "神谕之靴"),
            ("accessory", "水银饰带"),
        ],
        "bonus_desc_cn": "+5% 全属性",
        "bonus_desc_en": "+5% All Stats",
    },
}

# Boss collection: 10 boss types
BOSS_COLLECTION = {
    "dragon":        {"name_cn": "巨龙",        "name_en": "Dragon",        "emoji": "\U0001f409", "grade": "white"},
    "baron":         {"name_cn": "纳什男爵",    "name_en": "Baron Nashor",  "emoji": "\U0001f9cc", "grade": "white"},
    "elder_dragon":  {"name_cn": "远古巨龙",    "name_en": "Elder Dragon",  "emoji": "\U0001f432", "grade": "blue"},
    "rift_herald":   {"name_cn": "峡谷先锋",    "name_en": "Rift Herald",   "emoji": "\U0001f9ca", "grade": "blue"},
    "shadow_spirit": {"name_cn": "暗影之灵",    "name_en": "Shadow Spirit", "emoji": "\U0001f47b", "grade": "blue"},
    "frost_giant":   {"name_cn": "冰霜巨人",    "name_en": "Frost Giant",   "emoji": "\U0001f9ca", "grade": "purple"},
    "magma_beast":   {"name_cn": "熔岩巨兽",    "name_en": "Magma Beast",   "emoji": "\U0001f30b", "grade": "purple"},
    "storm_lord":    {"name_cn": "风暴之主",    "name_en": "Storm Lord",    "emoji": "\u26c8\ufe0f", "grade": "purple"},
    "void_lord":     {"name_cn": "虚空领主",    "name_en": "Void Lord",     "emoji": "\U0001f47e", "grade": "gold"},
    "fallen_angel":  {"name_cn": "堕落天使",    "name_en": "Fallen Angel",  "emoji": "\U0001f47f", "grade": "gold"},
}

GRADE_COLORS = {
    "white":  0xFFFFFF,
    "blue":   0x3498DB,
    "purple": 0x9B59B6,
    "gold":   0xF1C40F,
}

GRADE_LABELS = {
    "white":  "\u26aa 白 White",
    "blue":   "\U0001f535 蓝 Blue",
    "purple": "\U0001f7e3 紫 Purple",
    "gold":   "\U0001f7e1 金 Gold",
}

# ══════════════════════════════════════════════════════════════
# Database
# ══════════════════════════════════════════════════════════════

def _init_collection_db():
    """Initialize collection table."""
    with get_db_ctx() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collection (
                user_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                collected_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, item_name)
            )
        """)
        conn.commit()


_init_collection_db()


def _get_user_collection(uid: str) -> set:
    """Get set of collected item names for a user."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT item_name FROM collection WHERE user_id = ?", (uid,))
        return {r["item_name"] for r in cur.fetchall()}


def register_collect(uid: str, item_name: str) -> bool:
    """Register an item as collected. Returns True if newly collected."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO collection (user_id, item_name) VALUES (?, ?)",
            (uid, item_name),
        )
        conn.commit()
        if cur.rowcount > 0:
            logger.info(f"Collection registered: {uid} -> {item_name}")
            return True
    return False


def _get_collection_bonuses(uid: str) -> dict:
    """Calculate collection bonuses for a user.
    Returns: {all_stats_pct, xp_pct, gold_pct}
    Each equipment set fully collected = +5% all_stats; 1.5% stacking max.
    All bosses collected = +10% XP.
    All titles collected = +10% gold.
    """
    collected = _get_user_collection(uid)

    # Equipment set bonuses
    equipment_bonus = 0
    for set_key, set_def in EQUIPMENT_SETS.items():
        set_item_names = {item_name for _, item_name in set_def["items"]}
        if set_item_names.issubset(collected):
            equipment_bonus += 5

    # Boss bonus
    boss_complete = all(b["name_cn"] in collected for b in BOSS_COLLECTION.values())
    boss_xp_bonus = 10 if boss_complete else 0

    # All titles bonus — check via titles cog
    title_complete = False
    try:
        from cogs.mmorpg_titles import TITLE_DEFS, _get_user_titles
        user_titles = _get_user_titles(uid)
        all_title_keys = set(TITLE_DEFS.keys())
        title_complete = all_title_keys.issubset(user_titles)
    except Exception:
        pass
    title_gold_bonus = 10 if title_complete else 0

    return {
        "all_stats_pct": equipment_bonus,
        "xp_pct": boss_xp_bonus,
        "gold_pct": title_gold_bonus,
    }


# ══════════════════════════════════════════════════════════════
# Discord UI
# ══════════════════════════════════════════════════════════════

def _check_set_complete(uid: str, set_def: dict) -> tuple:
    """Check if an equipment set is complete. Returns (collected_count, total, is_complete)."""
    collected = _get_user_collection(uid)
    count = 0
    for _, item_name in set_def["items"]:
        if item_name in collected:
            count += 1
    total = len(set_def["items"])
    return count, total, count == total


def build_collection_embed(uid: str) -> discord.Embed:
    """Build the collection status embed."""
    bonuses = _get_collection_bonuses(uid)

    embed = discord.Embed(
        title="\U0001f4d6 Collection / 图鉴收集",
        description="Your collection progress and bonuses / 你的收集进度和加成：",
        color=0x9B59B6,
    )

    # ── Equipment Sets ──
    eq_lines = []
    for set_key, set_def in EQUIPMENT_SETS.items():
        collected_cnt, total, complete = _check_set_complete(uid, set_def)
        status = "\u2705" if complete else f"({collected_cnt}/{total})"
        grade_emoji = {"white": "\u26aa", "blue": "\U0001f535", "purple": "\U0001f7e3", "gold": "\U0001f7e1"}.get(set_def["grade"], "")
        line = f"{status} {grade_emoji} {set_def['emoji']} **{set_def['name_cn']}** ({set_def['name_en']})"
        if complete:
            line += " \u2728 Complete!"
        eq_lines.append(line)

    embed.add_field(
        name="\u2694\ufe0f Equipment Sets / 装备图鉴 (6)",
        value="\n".join(eq_lines),
        inline=False,
    )

    # ── Boss Collection ──
    collected = _get_user_collection(uid)
    boss_lines = []
    boss_collected = 0
    for boss_key, boss_def in BOSS_COLLECTION.items():
        is_collected = boss_def["name_cn"] in collected
        status = "\u2705" if is_collected else "\u274c"
        grade_emoji = {"white": "\u26aa", "blue": "\U0001f535", "purple": "\U0001f7e3", "gold": "\U0001f7e1"}.get(boss_def["grade"], "")
        boss_lines.append(f"{status} {grade_emoji} {boss_def['emoji']} **{boss_def['name_cn']}** ({boss_def['name_en']})")
        if is_collected:
            boss_collected += 1

    embed.add_field(
        name=f"\U0001f409 Boss Collection / 怪物图鉴 ({boss_collected}/10)",
        value="\n".join(boss_lines),
        inline=False,
    )

    # ── Active Bonuses ──
    bonus_lines = []
    if bonuses["all_stats_pct"] > 0:
        bonus_lines.append(f"\u2694\ufe0f 全属性 +{bonuses['all_stats_pct']}% (装备图鉴)")
    else:
        bonus_lines.append(f"\u2694\ufe0f 全属性 +0% (集齐6套装备图鉴各+5%)")
    if bonuses["xp_pct"] > 0:
        bonus_lines.append(f"\u2b50 XP +{bonuses['xp_pct']}% (怪物图鉴)")
    else:
        bonus_lines.append(f"\u2b50 XP +0% (集齐10种Boss +10%)")
    if bonuses["gold_pct"] > 0:
        bonus_lines.append(f"\U0001f4b0 金币 +{bonuses['gold_pct']}% (全部称号)")
    else:
        bonus_lines.append(f"\U0001f4b0 金币 +0% (集齐全部称号 +10%)")

    embed.add_field(
        name="\U0001f4ca Active Bonuses / 生效加成",
        value="\n".join(bonus_lines),
        inline=False,
    )

    embed.set_footer(text="/gmpt-collection  |  Collected items grant permanent bonuses")
    return embed


class CollectionView(discord.ui.View):
    """Collection panel view."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=None)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        return build_collection_embed(self.uid)

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Refresh", emoji="\U0001f504", style=discord.ButtonStyle.primary, row=0)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_collection_embed(self.uid)
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
            return
        await interaction.response.send_message("Use /gmpt-mmorpg to return.", ephemeral=True)


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════

class MMORPGCollection(CogBase):
    """图鉴收集系统 / Collection System"""

    def __init__(self, bot):
        super().__init__()
        _init_collection_db()

    @app_commands.command(name="gmpt-collection", description="\U0001f4d6 View your collection / 查看图鉴收集")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def collection_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        embed = build_collection_embed(uid)
        view = CollectionView(uid)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(MMORPGCollection(bot))
