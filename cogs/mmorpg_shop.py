"""
GMPT Bot — MMORPG NPC Potion Shop / NPC 药水商店
/gmpt-mmorpg — MMORPG Main Panel / MMORPG 主面板
/gmpt-potionshop browse  — Browse potions by category / 按类别浏览药水
/gmpt-potionshop buy     — Buy potion / 购买药水
/gmpt-potionshop inventory — View potion bag / 查看药水背包
/gmpt-potionshop use     — Use a potion / 使用药水
"""
import asyncio
import logging
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Potion Catalog — 10 potions, bilingual, grouped by category
# ══════════════════════════════════════════════════════════════
POTION_CATALOG = {
    # ── Recovery / 恢复类 ──
    "health_potion": {
        "id": 1,
        "name_cn": "生命药水",
        "name_en": "Health Potion",
        "emoji": "❤️",
        "price": 100,
        "min_level": 1,
        "category": "recovery",
        "category_cn": "恢复类",
        "category_en": "Recovery",
        "effect_cn": "恢复 50 HP",
        "effect_en": "Restore 50 HP",
        "effect_type": "heal_hp",
        "effect_value": 50,
        "duration": 0,
    },
    "greater_health_potion": {
        "id": 2,
        "name_cn": "大生命药水",
        "name_en": "Greater Health Potion",
        "emoji": "💖",
        "price": 250,
        "min_level": 3,
        "category": "recovery",
        "category_cn": "恢复类",
        "category_en": "Recovery",
        "effect_cn": "恢复 150 HP",
        "effect_en": "Restore 150 HP",
        "effect_type": "heal_hp",
        "effect_value": 150,
        "duration": 0,
    },
    "mana_potion": {
        "id": 3,
        "name_cn": "法力药水",
        "name_en": "Mana Potion",
        "emoji": "🔮",
        "price": 80,
        "min_level": 1,
        "category": "recovery",
        "category_cn": "恢复类",
        "category_en": "Recovery",
        "effect_cn": "恢复 30 MP",
        "effect_en": "Restore 30 MP",
        "effect_type": "heal_mp",
        "effect_value": 30,
        "duration": 0,
    },
    # ── Combat Buffs / 战斗增益 ──
    "strength_potion": {
        "id": 4,
        "name_cn": "大力药水",
        "name_en": "Strength Potion",
        "emoji": "💪",
        "price": 200,
        "min_level": 2,
        "category": "combat",
        "category_cn": "战斗增益",
        "category_en": "Combat Buffs",
        "effect_cn": "攻击力 +30%，持续 3 回合",
        "effect_en": "+30% ATK for 3 turns",
        "effect_type": "buff_atk",
        "effect_value": 30,
        "duration": 3,
    },
    "defense_potion": {
        "id": 5,
        "name_cn": "铁壁药水",
        "name_en": "Defense Potion",
        "emoji": "🛡️",
        "price": 180,
        "min_level": 2,
        "category": "combat",
        "category_cn": "战斗增益",
        "category_en": "Combat Buffs",
        "effect_cn": "防御力 +30%，持续 3 回合",
        "effect_en": "+30% DEF for 3 turns",
        "effect_type": "buff_def",
        "effect_value": 30,
        "duration": 3,
    },
    "swiftness_potion": {
        "id": 6,
        "name_cn": "迅捷药水",
        "name_en": "Swiftness Potion",
        "emoji": "💨",
        "price": 150,
        "min_level": 3,
        "category": "combat",
        "category_cn": "战斗增益",
        "category_en": "Combat Buffs",
        "effect_cn": "速度 +50%，持续 2 回合",
        "effect_en": "+50% SPD for 2 turns",
        "effect_type": "buff_spd",
        "effect_value": 50,
        "duration": 2,
    },
    "critical_potion": {
        "id": 7,
        "name_cn": "暴击药水",
        "name_en": "Critical Potion",
        "emoji": "💥",
        "price": 220,
        "min_level": 4,
        "category": "combat",
        "category_cn": "战斗增益",
        "category_en": "Combat Buffs",
        "effect_cn": "暴击率 +25%，持续 2 回合",
        "effect_en": "+25% Crit Rate for 2 turns",
        "effect_type": "buff_crit",
        "effect_value": 25,
        "duration": 2,
    },
    # ── Special / 特殊 ──
    "revival_potion": {
        "id": 8,
        "name_cn": "复活药水",
        "name_en": "Revival Potion",
        "emoji": "✨",
        "price": 500,
        "min_level": 5,
        "category": "special",
        "category_cn": "特殊",
        "category_en": "Special",
        "effect_cn": "战斗中被击倒时自动复活并恢复 30% HP",
        "effect_en": "Auto-revive with 30% HP when KO'd",
        "effect_type": "revive",
        "effect_value": 30,
        "duration": 0,
    },
    "purification_potion": {
        "id": 9,
        "name_cn": "净化药水",
        "name_en": "Purification Potion",
        "emoji": "💧",
        "price": 120,
        "min_level": 2,
        "category": "special",
        "category_cn": "特殊",
        "category_en": "Special",
        "effect_cn": "移除所有负面状态",
        "effect_en": "Remove all debuffs",
        "effect_type": "purify",
        "effect_value": 0,
        "duration": 0,
    },
    "exp_potion": {
        "id": 10,
        "name_cn": "经验药水",
        "name_en": "EXP Potion",
        "emoji": "⭐",
        "price": 300,
        "min_level": 3,
        "category": "special",
        "category_cn": "特殊",
        "category_en": "Special",
        "effect_cn": "战斗经验 +50%，持续 5 分钟",
        "effect_en": "+50% EXP for 5 minutes",
        "effect_type": "buff_exp",
        "effect_value": 50,
        "duration": 5,
    },
}

# Category display order
CATEGORY_ORDER = ["recovery", "combat", "special"]
CATEGORY_EMOJI = {
    "recovery": "❤️",
    "combat": "⚔️",
    "special": "✨",
}


def _get_balance(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return row["score"] if row else 0


def _get_xp(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT xp FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return row["xp"] if row else 0


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


def _get_user_level(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return row["level"] if row else 1


def _get_user_stats(uid: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT hp, max_hp, mp, max_mp, attack, defense, level, xp FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    if row:
        return dict(row)
    return {"hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50, "attack": 10, "defense": 5, "level": 1, "xp": 0}


# ══════════════════════════════════════════════════════════════
# PotionShop Cog
# ══════════════════════════════════════════════════════════════
class PotionShop(CogBase):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    # ── Autocomplete for potion keys ──
    async def _potion_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        choices = []
        for key, p in POTION_CATALOG.items():
            display = f"{p['emoji']} {p['name_cn']} / {p['name_en']}"
            if not current or current.lower() in display.lower():
                choices.append(app_commands.Choice(name=display, value=key))
        return choices[:25]

    # ══════════════════════════════════════════════════════════
    # /gmpt-mmorpg — MMORPG Main Panel / MMORPG 主面板
    # ══════════════════════════════════════════════════════════
    @app_commands.command(name="gmpt-mmorpg", description="MMORPG Main Panel / MMORPG 主面板")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def mmorpg_panel(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        embed = build_main_embed(uid, interaction.user.display_name)
        view = MMORPGMainView(uid)
        await interaction.response.send_message(embed=embed, view=view)


# ══════════════════════════════════════════════════════════════
# build_main_embed — reusable embed builder for sub-panel Back buttons
# ══════════════════════════════════════════════════════════════
def build_main_embed(uid: str, display_name: str = None) -> discord.Embed:
    """Build the MMORPG main panel embed. Compatible with sub-panel Back callbacks."""
    stats = _get_user_stats(uid)
    bal = _get_balance(uid)
    xp = _get_xp(uid)

    from cogs.mmorpg_class import _get_class, CLASS_DEFS
    current_key = _get_class(uid)
    if current_key and current_key in CLASS_DEFS:
        cd = CLASS_DEFS[current_key]
        class_emoji = cd["emoji"]
        class_name = f"{cd['name_cn']} / {cd['name_en']}"
    else:
        class_emoji = "🧑"
        class_name = "未选择 / None"

    hp_pct = stats["hp"] / max(stats["max_hp"], 1)
    mp_pct = stats["mp"] / max(stats["max_mp"], 1)
    hp_bar = "█" * max(1, int(hp_pct * 8)) + "░" * max(0, 8 - int(hp_pct * 8))
    mp_bar = "█" * max(1, int(mp_pct * 8)) + "░" * max(0, 8 - int(mp_pct * 8))

    panel_lines = [
        "```ansi",
        "        \u001b[1;33m\uD83D\uDEE1\uFE0F\u001b[0m",
        "      \u001b[1;33m\u2694\uFE0F\u001b[0m  \u001b[1;35m\uD83D\uDC51\u001b[0m  \u001b[1;33m\u2694\uFE0F\u001b[0m",
        "    \u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        f"    {class_emoji}  {class_name}  Lv.{stats['level']}",
        "    \u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        "```",
    ]

    embed = discord.Embed(
        title="\u250C\u2500\u2500\u2500\u2500\u2500 GMPT MMORPG \u2500\u2500\u2500\u2500\u2500\u2510",
        description="\n".join(panel_lines),
        color=0x9B59B6,
    )
    embed.add_field(
        name=f"\u2764\uFE0F HP [{hp_bar}]",
        value=f"**{stats['hp']}/{stats['max_hp']}**",
        inline=True,
    )
    embed.add_field(
        name=f"\uD83D\uDD2E MP [{mp_bar}]",
        value=f"**{stats['mp']}/{stats['max_mp']}**",
        inline=True,
    )
    embed.add_field(
        name="\uD83D\uDCB0 Coins",
        value=f"\uD83E\uDE99 **{bal:,}**",
        inline=True,
    )
    embed.add_field(
        name="\u2694\uFE0F ATK",
        value=f"**{stats['attack']}**",
        inline=True,
    )
    embed.add_field(
        name="\uD83D\uDEE1\uFE0F DEF",
        value=f"**{stats['defense']}**",
        inline=True,
    )
    embed.add_field(
        name="\u2B50 EXP",
        value=f"\u2B50 **{xp:,}**",
        inline=True,
    )
    if display_name:
        embed.set_footer(text=f"{display_name}  |  /gmpt-mmorpg")
    return embed


# ══════════════════════════════════════════════════════════════
# MMORPGMainView — Unified Control Panel (14 subsystems)
# ══════════════════════════════════════════════════════════════
class MMORPGMainView(discord.ui.View):
    def __init__(self, uid: str):
        super().__init__(timeout=None)
        self.uid = uid

    # ── Row 0: Work + Shop ──
    @discord.ui.button(label="Work 打工", emoji="⚒️", style=discord.ButtonStyle.primary, row=0, custom_id="mmorpg_main:work")
    async def work_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.economy_jobs import EconomyJobsView
        view = EconomyJobsView(self.uid, main_view=self)
        embed = discord.Embed(
            title="⚒️ Work / 打工",
            description="Choose a job to earn coins and EXP!\n选择工作来赚取金币和经验！",
            color=0xF39C12,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Shop 商店", emoji="🏪", style=discord.ButtonStyle.primary, row=0, custom_id="mmorpg_main:shop")
    async def shop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_shop import PotionBrowseView
        user_level = _get_user_level(self.uid)
        view = PotionBrowseView(POTION_CATALOG, user_level, self.uid, main_view=self)
        embed = view.build_embed("recovery")
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 1: Boss + Dungeon ──
    @discord.ui.button(label="Boss", emoji="⚔️", style=discord.ButtonStyle.danger, row=1, custom_id="mmorpg_main:boss")
    async def boss_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.boss import BossLobbyView
        view = BossLobbyView(self.uid, main_view=self)
        embed = discord.Embed(
            title="⚔️ Boss Hunt / Boss 狩猎",
            description="Fight epic bosses for rare loot!\n挑战史诗Boss获取稀有装备！",
            color=0xE74C3C,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Dungeon 副本", emoji="🏰", style=discord.ButtonStyle.danger, row=1, custom_id="mmorpg_main:dungeon")
    async def dungeon_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.dungeon import DungeonLobbyView
        view = DungeonLobbyView(self.uid, main_view=self)
        embed = discord.Embed(
            title="🏰 Dungeon / 副本",
            description="Explore dungeons for treasures!\n探索副本寻找宝藏！",
            color=0x3498DB,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 2: PVP + Quest ──
    @discord.ui.button(label="PVP", emoji="⚔️", style=discord.ButtonStyle.success, row=2, custom_id="mmorpg_main:pvp")
    async def pvp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            from cogs.mmorpg_pvp import PVPView
            view = PVPView(self.uid, main_view=self)
        except (ImportError, AttributeError):
            embed = discord.Embed(
                title="⚔️ PVP Arena / PVP竞技场",
                description="PVP coming soon!\nPVP功能即将开放！",
                color=0xE67E22,
            )
            view = MMORPGMainView(self.uid)
            await interaction.response.edit_message(embed=embed, view=view)
            return
        embed = discord.Embed(
            title="⚔️ PVP Arena / PVP竞技场",
            description="Challenge other players!\n挑战其他玩家！",
            color=0xE67E22,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Quest 任务", emoji="📋", style=discord.ButtonStyle.success, row=2, custom_id="mmorpg_main:quest")
    async def quest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.daily_quest import DailyQuestView
        view = DailyQuestView(self.uid, main_view=self)
        embed = discord.Embed(
            title="📋 Daily Quests / 每日任务",
            description="Complete quests for rewards!\n完成任务获取奖励！",
            color=0x2ECC71,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 3: Equipment + Skills ──
    @discord.ui.button(label="Equip 装备", emoji="🛡️", style=discord.ButtonStyle.secondary, row=3, custom_id="mmorpg_main:equip")
    async def equip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_equipment import EquipmentView
        view = EquipmentView(self.uid, main_view=self)
        embed = discord.Embed(
            title="🛡️ Equipment / 装备",
            description="Manage your gear!\n管理你的装备！",
            color=0x7F8C8D,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Skills 技能", emoji="🗡️", style=discord.ButtonStyle.secondary, row=3, custom_id="mmorpg_main:skills")
    async def skills_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_skills import SkillShopView
        view = SkillShopView(self.uid, main_view=self)
        embed = discord.Embed(
            title="🗡️ Skills / 技能",
            description="Learn powerful skills!\n学习强力技能！",
            color=0x9B59B6,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 4: Inventory + Class ──
    @discord.ui.button(label="Bag 背包", emoji="🎒", style=discord.ButtonStyle.secondary, row=4, custom_id="mmorpg_main:inv")
    async def inv_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT item_name, quantity FROM user_inventory WHERE user_id = ? AND item_type = 'potion' AND quantity > 0 ORDER BY item_name",
                (self.uid,),
            )
            rows = cur.fetchall()
        if not rows:
            embed = discord.Embed(
                title="🎒 Backpack / 背包",
                description="Your backpack is empty!\n背包空空如也！Visit the Shop to buy items.",
                color=0x95A5A6,
            )
        else:
            lines = []
            for row in rows:
                p = POTION_CATALOG.get(row["item_name"], {})
                emoji = p.get("emoji", "🧪")
                cn = p.get("name_cn", row["item_name"])
                en = p.get("name_en", row["item_name"])
                lines.append(f"{emoji} **{cn} / {en}** x{row['quantity']}")
            embed = discord.Embed(
                title="🎒 Backpack / 背包",
                description="\n".join(lines),
                color=0x95A5A6,
            )
        view = _BackOnlyView(self.uid, main_view=self)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Class 职业", emoji="👤", style=discord.ButtonStyle.secondary, row=4, custom_id="mmorpg_main:class")
    async def class_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_class import ClassSelectView
        view = ClassSelectView(self.uid, main_view=self)
        embed = discord.Embed(
            title="👤 Class / 职业",
            description="Choose your class!\n选择你的职业！",
            color=0x8E44AD,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 5: Economy + Gambling ──
    @discord.ui.button(label="Econ 经济", emoji="💎", style=discord.ButtonStyle.primary, row=5, custom_id="mmorpg_main:econ")
    async def econ_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.economy import MainMenuView
        view = MainMenuView(self.uid, self.uid)
        embed = discord.Embed(
            title="💎 Economy / 经济系统",
            description="Bank, transfer, invest!\n银行、转账、投资！",
            color=0x1ABC9C,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Gamble 赌博", emoji="🎰", style=discord.ButtonStyle.primary, row=5, custom_id="mmorpg_main:gamble")
    async def gamble_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.gambling import GamblingLobbyView
        view = GamblingLobbyView(self.uid, main_view=self)
        embed = discord.Embed(
            title="🎰 Gambling / 赌博",
            description="Try your luck!\n试试你的运气！",
            color=0xFF5722,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 6: Cosmetics + Leaderboard ──
    @discord.ui.button(label="Pet 外观", emoji="🎨", style=discord.ButtonStyle.success, row=6, custom_id="mmorpg_main:pet")
    async def pet_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            from cogs.pets import PetPanelView
            view = PetPanelView(self.uid, main_view=self)
        except (ImportError, AttributeError):
            embed = discord.Embed(
                title="🎨 Pets / 宠物外观",
                description="Pet system coming soon!\n宠物系统即将开放！",
                color=0xE91E63,
            )
            view = _BackOnlyView(self.uid, main_view=self)
            await interaction.response.edit_message(embed=embed, view=view)
            return
        embed = discord.Embed(
            title="🎨 Pets / 宠物外观",
            description="Hatch and raise pets!\n孵化培养宠物！",
            color=0xE91E63,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Rank 排行", emoji="📊", style=discord.ButtonStyle.success, row=6, custom_id="mmorpg_main:rank")
    async def rank_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.leaderboard import LeaderboardView
        view = LeaderboardView(main_view=self)
        embed = discord.Embed(
            title="📊 Leaderboard / 排行榜",
            description="Top players ranking!\n玩家排行榜！",
            color=0xF1C40F,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Achieve 成就", emoji="🏅", style=discord.ButtonStyle.success, row=6, custom_id="mmorpg_main:achievements")
    async def achievements_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.achievements import AchievementsView
        view = AchievementsView(uid=self.uid, main_view=self)
        embed = await view._get_achievements_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)


class _BackOnlyView(discord.ui.View):
    """Simple view with just a Back button for panels that only display info."""
    def __init__(self, uid: str, main_view: MMORPGMainView):
        super().__init__(timeout=None)
        self.uid = uid
        self.main_view = main_view

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=4, custom_id="back_only:back")
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_main_embed(self.uid, interaction.user.display_name)
        try:
            await interaction.response.edit_message(embed=embed, view=self.main_view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=self.main_view)
    potionshop_group = app_commands.Group(
        name="gmpt-potionshop",
        description="NPC Potion Shop / NPC 药水商店",
    )

    @potionshop_group.command(name="browse", description="Browse potions by category / 按类别浏览药水")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def browse_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        user_level = _get_user_level(uid)
        view = PotionBrowseView(POTION_CATALOG, user_level, uid)
        embed = view.build_embed("recovery")
        await interaction.response.send_message(embed=embed, view=view)

    @potionshop_group.command(name="buy", description="Buy a potion / 购买药水")
    @app_commands.describe(
        potion_key="Potion name / 药水名称",
        quantity="Quantity / 数量 (default 1)"
    )
    @app_commands.autocomplete(potion_key=_potion_autocomplete)
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: (i.guild_id, i.user.id))
    async def buy_cmd(self, interaction: discord.Interaction, potion_key: str, quantity: int = 1):
        uid = str(interaction.user.id)

        if potion_key not in POTION_CATALOG:
            return await interaction.response.send_message(
                "Potion not found / 药水不存在", ephemeral=True
            )
        if quantity < 1:
            return await interaction.response.send_message(
                "Quantity must be > 0 / 数量必须大于0", ephemeral=True
            )

        p = POTION_CATALOG[potion_key]
        user_level = _get_user_level(uid)

        if user_level < p["min_level"]:
            return await interaction.response.send_message(
                f"Level too low / 等级不足！Requires Lv.{p['min_level']}, you are Lv.{user_level}",
                ephemeral=True,
            )

        total_cost = p["price"] * quantity
        bal = _get_balance(uid)

        if bal < total_cost:
            return await interaction.response.send_message(
                f"Insufficient balance / 余额不足！Need 🪙 {total_cost:,}, you have 🪙 {bal:,}",
                ephemeral=True,
            )

        _add_coins(uid, -total_cost, f"Bought {p['name_en']} x{quantity} / 购买 {p['name_cn']} x{quantity}")

        # Add to inventory
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, quantity FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
                (uid, potion_key),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    "UPDATE user_inventory SET quantity = quantity + ? WHERE id = ?",
                    (quantity, existing["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) VALUES (?, ?, ?, ?, 'potion')",
                    (uid, p["id"], potion_key, quantity),
                )
            conn.commit()

        new_bal = _get_balance(uid)
        embed = discord.Embed(
            title=f"Purchase Complete / 购买成功",
            description=(
                f"{p['emoji']} **{p['name_cn']} / {p['name_en']}** x{quantity}\n"
                f"Cost / 花费: 🪙 **{total_cost:,}**"
            ),
            color=0x2ECC71,
        )
        embed.add_field(name="Balance / 余额", value=f"🪙 {new_bal:,}", inline=True)
        embed.add_field(name="Effect / 效果", value=f"{p['effect_cn']}\n{p['effect_en']}", inline=False)
        await interaction.response.send_message(embed=embed)

    @potionshop_group.command(name="inventory", description="View potion bag / 查看药水背包")
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: (i.guild_id, i.user.id))
    async def inventory_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT item_name, quantity FROM user_inventory WHERE user_id = ? AND item_type = 'potion' AND quantity > 0 ORDER BY item_name",
                (uid,),
            )
            rows = cur.fetchall()

        if not rows:
            return await interaction.response.send_message(
                "Your potion bag is empty / 药水背包是空的！Use `/gmpt-potionshop browse` to buy some.",
                ephemeral=True,
            )

        lines = []
        for row in rows:
            p = POTION_CATALOG.get(row["item_name"], {})
            emoji = p.get("emoji", "🧪")
            cn = p.get("name_cn", row["item_name"])
            en = p.get("name_en", row["item_name"])
            eff = p.get("effect_cn", "")
            lines.append(f"{emoji} **{cn} / {en}** x{row['quantity']} — {eff}")

        embed = discord.Embed(
            title=f"Potion Bag / 药水背包 — {interaction.user.display_name}",
            description="\n".join(lines) if lines else "Empty / 空空如也",
            color=0x9B59B6,
        )
        embed.set_footer(text="Use /gmpt-potionshop use <potion> to drink / 使用 /gmpt-potionshop use <药水名> 来喝")
        await interaction.response.send_message(embed=embed)

    @potionshop_group.command(name="use", description="Use a potion from your bag / 使用背包中药水")
    @app_commands.describe(potion_key="Potion name / 药水名称")
    @app_commands.autocomplete(potion_key=_potion_autocomplete)
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def use_cmd(self, interaction: discord.Interaction, potion_key: str):
        uid = str(interaction.user.id)

        if potion_key not in POTION_CATALOG:
            return await interaction.response.send_message(
                "Potion not found / 药水不存在", ephemeral=True
            )

        p = POTION_CATALOG[potion_key]

        # Check inventory
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, quantity FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
                (uid, potion_key),
            )
            inv_row = cur.fetchone()

        if not inv_row or inv_row["quantity"] <= 0:
            return await interaction.response.send_message(
                f"You don't have **{p['name_cn']}** in your bag / 背包中没有此药水！",
                ephemeral=True,
            )

        user_level = _get_user_level(uid)
        if user_level < p["min_level"]:
            return await interaction.response.send_message(
                f"Level too low / 等级不足！Requires Lv.{p['min_level']}, you are Lv.{user_level}",
                ephemeral=True,
            )

        # Consume 1
        if inv_row["quantity"] > 1:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE user_inventory SET quantity = quantity - 1 WHERE id = ?", (inv_row["id"],))
                conn.commit()
        else:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM user_inventory WHERE id = ?", (inv_row["id"],))
                conn.commit()

        # Apply effect
        effect_type = p["effect_type"]
        effect_value = p["effect_value"]

        if effect_type == "heal_hp":
            stats = _get_user_stats(uid)
            cur_hp = stats["hp"]
            max_hp = stats["max_hp"]
            new_hp = min(cur_hp + effect_value, max_hp)
            healed = new_hp - cur_hp
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE users SET hp = ? WHERE discord_id = ?", (new_hp, uid))
                conn.commit()
            embed = discord.Embed(
                title=f"{p['emoji']} {p['name_cn']} / {p['name_en']}",
                description=(
                    f"Restored **{healed}** HP / 恢复了 **{healed}** HP！\n"
                    f"{cur_hp} → {new_hp} / {max_hp}"
                ),
                color=0xE74C3C,
            )

        elif effect_type == "heal_mp":
            stats = _get_user_stats(uid)
            cur_mp = stats["mp"]
            max_mp = stats["max_mp"]
            new_mp = min(cur_mp + effect_value, max_mp)
            healed = new_mp - cur_mp
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE users SET mp = ? WHERE discord_id = ?", (new_mp, uid))
                conn.commit()
            embed = discord.Embed(
                title=f"{p['emoji']} {p['name_cn']} / {p['name_en']}",
                description=(
                    f"Restored **{healed}** MP / 恢复了 **{healed}** MP！\n"
                    f"{cur_mp} → {new_mp} / {max_mp}"
                ),
                color=0x3498DB,
            )

        elif effect_type in ("buff_atk", "buff_def", "buff_spd", "buff_crit", "buff_exp"):
            expires = datetime.datetime.now() + datetime.timedelta(minutes=p["duration"])
            buff_type_map = {
                "buff_atk": "atk_up",
                "buff_def": "def_up",
                "buff_spd": "spd_up",
                "buff_crit": "crit_up",
                "buff_exp": "exp_up",
            }
            buff_type = buff_type_map.get(effect_type, effect_type)
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO active_buffs (user_id, buff_type, value, expires_at) VALUES (?, ?, ?, ?)",
                    (uid, buff_type, effect_value, expires.isoformat()),
                )
                conn.commit()
            embed = discord.Embed(
                title=f"{p['emoji']} {p['name_cn']} / {p['name_en']}",
                description=(
                    f"{p['effect_cn']}\n{p['effect_en']}\n\n"
                    f"Duration / 持续: **{p['duration']}** turns/minutes"
                ),
                color=0xE67E22,
            )

        elif effect_type == "revive":
            stats = _get_user_stats(uid)
            if stats["hp"] > 0:
                # Refund — can't use while alive
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) VALUES (?, ?, ?, 1, 'potion')",
                        (uid, p["id"], potion_key),
                    )
                    conn.commit()
                return await interaction.response.send_message(
                    "You're still alive! Revival potion only usable when HP=0.\n"
                    "你还活着！复活药水只能在 HP=0 时使用。",
                    ephemeral=True,
                )

            max_hp = stats["max_hp"]
            max_mp = stats["max_mp"]
            restore_hp = max(1, int(max_hp * effect_value / 100))
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE users SET hp = ?, mp = ? WHERE discord_id = ?",
                    (restore_hp, max_mp, uid),
                )
                conn.commit()
            embed = discord.Embed(
                title=f"{p['emoji']} {p['name_cn']} / {p['name_en']}",
                description=(
                    f"Revived! HP restored to **{restore_hp}**/{max_hp}, MP fully restored!\n"
                    f"复活成功！HP 恢复到 **{restore_hp}**/{max_hp}，MP 全满！"
                ),
                color=0xF1C40F,
            )

        elif effect_type == "purify":
            # Clear all active debuffs
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM active_buffs WHERE user_id = ? AND buff_type LIKE '%down%'", (uid,))
                debuffs_cleared = cur.rowcount
                conn.commit()
            embed = discord.Embed(
                title=f"{p['emoji']} {p['name_cn']} / {p['name_en']}",
                description=(
                    f"All debuffs removed / 所有负面状态已移除！\n"
                    f"Cleared {debuffs_cleared} debuff(s)"
                ),
                color=0x1ABC9C,
            )

        else:
            return await interaction.response.send_message(
                f"Unknown potion type / 未知药水类型: {effect_type}", ephemeral=True
            )

        embed.set_footer(text="Check bag with /gmpt-potionshop inventory / 查看背包: /gmpt-potionshop inventory")
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # PVP potion autocomplete helper (used by mmorpg_pvp.py)
    # ══════════════════════════════════════════════════════════
    async def pvp_potion_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        uid = str(interaction.user.id)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT item_name FROM user_inventory WHERE user_id = ? AND item_type = 'potion' AND quantity > 0",
                (uid,),
            )
            rows = cur.fetchall()
        choices = []
        for r in rows:
            p = POTION_CATALOG.get(r["item_name"], {})
            display = f"{p.get('emoji', '🧪')} {p.get('name_cn', r['item_name'])} / {p.get('name_en', r['item_name'])}"
            if not current or current.lower() in display.lower():
                choices.append(app_commands.Choice(name=display, value=r["item_name"]))
        return choices[:25]


# ══════════════════════════════════════════════════════════════
# MMORPG Main Panel View / MMORPG 主面板
# ══════════════════════════════════════════════════════════════
class MMORPGMainView(discord.ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=180)
        self.user_id = user_id

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "Not your panel / 这不是你的面板", ephemeral=True
            )
            return False
        return True

    def _build_sub_embed(self, title: str, color: int, desc: str) -> discord.Embed:
        embed = discord.Embed(title=title, color=color)
        embed.description = desc
        embed.set_footer(text="Use /gmpt-mmorpg to return to main panel / 使用 /gmpt-mmorpg 回到主面板")
        return embed

    # Row 0: Potion Shop, Skills, PVP, Boss
    @discord.ui.button(label="Potion Shop / 药水商店", style=discord.ButtonStyle.primary, row=0, emoji="🧪")
    async def shop_btn(self, interaction: discord.Interaction, button):
        uid = str(interaction.user.id)
        level = _get_user_level(uid)
        import cogs.mmorpg_shop as ms
        view = PotionBrowseView(ms.POTION_CATALOG, level, uid, main_view=self)
        try:
            await interaction.response.edit_message(embed=view.build_embed("recovery"), view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=view.build_embed("recovery"), view=view)

    @discord.ui.button(label="Skills / 技能", style=discord.ButtonStyle.primary, row=0, emoji="⚔️")
    async def skills_btn(self, interaction: discord.Interaction, button):
        from cogs.mmorpg_skills import SkillShopView
        uid = str(interaction.user.id)
        view = SkillShopView(uid, main_view=self)
        embed = view.build_main_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="PVP Arena / PVP 对战", style=discord.ButtonStyle.primary, row=0, emoji="🏆")
    async def pvp_btn(self, interaction: discord.Interaction, button):
        from cogs.mmorpg_pvp import PVPLobbyView
        uid = str(interaction.user.id)
        view = PVPLobbyView(uid, main_view=self)
        embed = view.build_main_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Boss Raid / Boss 战", style=discord.ButtonStyle.danger, row=0, emoji="🐉")
    async def boss_btn(self, interaction: discord.Interaction, button):
        from cogs.boss import BossLobbyView
        uid = str(interaction.user.id)
        view = BossLobbyView(uid, main_view=self)
        embed = view.build_main_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    # Row 1: Dungeon, Equipment, Daily Quest, Class, Back
    @discord.ui.button(label="Dungeon / 地下城", style=discord.ButtonStyle.secondary, row=1, emoji="🏰")
    async def dungeon_btn(self, interaction: discord.Interaction, button):
        from cogs.dungeon import DungeonLobbyView
        uid = str(interaction.user.id)
        view = DungeonLobbyView(uid, main_view=self)
        embed = view.build_main_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Equipment / 装备", style=discord.ButtonStyle.secondary, row=1, emoji="🗡️")
    async def equipment_btn(self, interaction: discord.Interaction, button):
        from cogs.mmorpg_equipment import EquipmentView
        uid = str(interaction.user.id)
        view = EquipmentView(uid, main_view=self)
        embed = view.build_main_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Daily Quest / 每日任务", style=discord.ButtonStyle.secondary, row=1, emoji="📋")
    async def daily_quest_btn(self, interaction: discord.Interaction, button):
        from cogs.daily_quest import DailyQuestView
        uid = str(interaction.user.id)
        view = DailyQuestView(uid, main_view=self)
        embed = view.build_main_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Class / 职业", style=discord.ButtonStyle.secondary, row=1, emoji="🎭")
    async def class_btn(self, interaction: discord.Interaction, button):
        from cogs.mmorpg_class import ClassSelectView, _get_class
        uid = str(interaction.user.id)
        current_key = _get_class(uid)
        bal = _get_balance(uid)
        view = ClassSelectView(uid, current_key, bal, main_view=self)
        embed = view.build_main_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Main Panel / 主面板", style=discord.ButtonStyle.success, row=1, emoji="🏠")
    async def back_btn(self, interaction: discord.Interaction, button):
        uid = str(interaction.user.id)
        stats = _get_user_stats(uid)
        bal = _get_balance(uid)
        embed = discord.Embed(
            title="MMORPG Main Panel / MMORPG 主面板",
            description=(
                f"Welcome to GMPT MMORPG World / 欢迎来到 GMPT MMORPG 世界！\n\n"
                f"❤️ HP: **{stats['hp']}/{stats['max_hp']}**  "
                f"🔮 MP: **{stats['mp']}/{stats['max_mp']}**\n"
                f"⚔️ ATK: **{stats['attack']}**  🛡️ DEF: **{stats['defense']}**  "
                f"⭐ Lv.**{stats['level']}**  🪙 **{bal:,}**\n\n"
                f"Click a button below / 点击下方按钮："
            ),
            color=0x9B59B6,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)


# ══════════════════════════════════════════════════════════════
# Potion Browse View — Categories with tabs
# ══════════════════════════════════════════════════════════════
class PotionBrowseView(discord.ui.View):
    def __init__(self, potions: dict, user_level: int, user_id: str, main_view=None):
        super().__init__(timeout=180)
        self.potions = potions
        self.user_level = user_level
        self.user_id = user_id
        self.main_view = main_view
        self.active_category = "recovery"
        self._update_category_buttons()
        self._add_buy_buttons()

    def _update_category_buttons(self):
        for child in self.children:
            if hasattr(child, "custom_id") and child.custom_id:
                if child.custom_id == f"cat_{self.active_category}":
                    child.style = discord.ButtonStyle.primary
                    child.disabled = True
                else:
                    child.style = discord.ButtonStyle.secondary
                    child.disabled = False

    def build_embed(self, category: str) -> discord.Embed:
        cat_potions = [
            (k, p) for k, p in self.potions.items() if p["category"] == category
        ]

        embed = discord.Embed(
            title="NPC Potion Shop / NPC 药水商店",
            description=f"Your Level / 你的等级: **Lv.{self.user_level}**",
            color=0x9B59B6,
        )

        category_headers = {
            "recovery": "Recovery / 恢复类",
            "combat": "Combat Buffs / 战斗增益",
            "special": "Special / 特殊",
        }

        lines = []
        for key, p in cat_potions:
            locked = "🔒" if self.user_level < p["min_level"] else ""
            cn = p["name_cn"]
            en = p["name_en"]
            lines.append(
                f"{p['emoji']} **{cn} / {en}** {locked}\n"
                f"　{p['effect_cn']}\n"
                f"　{p['effect_en']} | 🪙 {p['price']:,} | Lv.{p['min_level']}+"
            )

        embed.add_field(
            name=category_headers.get(category, category),
            value="\n\n".join(lines) if lines else "No potions / 暂无药水",
            inline=False,
        )
        embed.set_footer(text="Buy: /gmpt-potionshop buy <potion> <qty> / 购买: /gmpt-potionshop buy <药水名> <数量>")
        return embed

    @discord.ui.button(label="Recovery / 恢复类", custom_id="cat_recovery", style=discord.ButtonStyle.primary, row=0, emoji="❤️")
    async def cat_recovery(self, interaction: discord.Interaction, button):
        await self._switch_category(interaction, "recovery")

    @discord.ui.button(label="Combat Buffs / 战斗增益", custom_id="cat_combat", style=discord.ButtonStyle.secondary, row=0, emoji="⚔️")
    async def cat_combat(self, interaction: discord.Interaction, button):
        await self._switch_category(interaction, "combat")

    @discord.ui.button(label="Special / 特殊", custom_id="cat_special", style=discord.ButtonStyle.secondary, row=0, emoji="✨")
    async def cat_special(self, interaction: discord.Interaction, button):
        await self._switch_category(interaction, "special")

    def _add_buy_buttons(self):
        """Add Buy buttons for potions in the active category (row 1-3, 5 per row)."""
        # Clear old buy/back buttons
        self._remove_buy_buttons()
        cat_potions = [
            (k, p) for k, p in self.potions.items() if p["category"] == self.active_category
        ]
        for i, (key, p) in enumerate(cat_potions):
            row = 1 + i // 2
            locked = self.user_level < p["min_level"]
            style = discord.ButtonStyle.secondary if locked else discord.ButtonStyle.success
            label = f"Buy {p['name_cn']} 🪙{p['price']:,}"[:80]
            if locked:
                label = f"🔒 {p['name_cn']} Lv.{p['min_level']}"[:80]
            btn = discord.ui.Button(
                label=label,
                style=style,
                row=row,
                custom_id=f"buy_{key}",
                emoji=p["emoji"],
                disabled=locked,
            )
            btn.callback = self._make_buy_callback(key)
            self.add_item(btn)

        # Back button on last row
        back_btn = discord.ui.Button(
            label="Back to MMORPG / 返回", style=discord.ButtonStyle.danger,
            row=4, emoji="🏠", custom_id="shop_back",
        )
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    def _remove_buy_buttons(self):
        to_remove = []
        for child in self.children:
            if hasattr(child, "custom_id") and child.custom_id:
                if child.custom_id.startswith("buy_") or child.custom_id == "shop_back":
                    to_remove.append(child)
        for child in to_remove:
            self.remove_item(child)

    def _make_buy_callback(self, potion_key: str):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.user_id:
                return await interaction.response.send_message("Not your page / 不是你的页面", ephemeral=True)
            p = self.potions.get(potion_key)
            if not p:
                return await interaction.response.send_message("Potion not found / 药水不存在", ephemeral=True)
            uid = str(interaction.user.id)
            bal = _get_balance(uid)
            if bal < p["price"]:
                return await interaction.response.send_message(
                    f"金币不足 / Insufficient coins. Need 🪙 {p['price']:,}, you have 🪙 {bal:,}", ephemeral=True
                )
            if self.user_level < p["min_level"]:
                return await interaction.response.send_message(
                    f"等级不足 Need Lv.{p['min_level']} / You are Lv.{self.user_level}", ephemeral=True
                )
            _add_coins(uid, -p["price"], f"Buy potion / 购买药水: {p['name_en']}")
            with get_db_ctx() as conn:
                conn.execute(
                    "INSERT INTO mmorpg_potions (user_id, potion_key, qty) VALUES (?, ?, 1) "
                    "ON CONFLICT(user_id, potion_key) DO UPDATE SET qty = qty + 1",
                    (uid, potion_key),
                )
            new_bal = _get_balance(uid)
            await interaction.response.send_message(
                f"✅ 购买了 {p['emoji']} **{p['name_cn']}**! 余额 / Balance: 🪙 {new_bal:,}",
                ephemeral=True,
            )
        return callback

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            uid = str(interaction.user.id)
            embed = build_main_embed(uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
        else:
            await interaction.response.edit_message(content="Main panel not available.", view=None)

    async def _switch_category(self, interaction: discord.Interaction, category: str):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("Not your page / 不是你的页面", ephemeral=True)
        self.active_category = category
        self._update_category_buttons()
        self._add_buy_buttons()
        try:
            await interaction.response.edit_message(embed=self.build_embed(category), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(category), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


async def setup(bot):
    await bot.add_cog(PotionShop(bot))
