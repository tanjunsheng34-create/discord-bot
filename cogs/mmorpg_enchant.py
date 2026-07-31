"""
GMPT Bot — MMORPG Enchantment System / 附魔系统
/gmpt-enchant — 装备附魔

消耗附魔石+金币给装备附加额外属性。安全附魔（失败不掉级）。
"""
import logging
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Enchant Stones
# ══════════════════════════════════════════════════════════════
ENCHANT_TYPES = {
    "atk": {
        "name_cn": "攻击符文", "name_en": "ATK Rune",
        "emoji": "🔴", "stat_key": "enchant_atk",
        "min_val": 3, "max_val": 15, "stone_cost": 1,
    },
    "def": {
        "name_cn": "防御符文", "name_en": "DEF Rune",
        "emoji": "🔵", "stat_key": "enchant_def",
        "min_val": 2, "max_val": 10, "stone_cost": 1,
    },
    "hp": {
        "name_cn": "生命符文", "name_en": "HP Rune",
        "emoji": "🟢", "stat_key": "enchant_hp",
        "min_val": 10, "max_val": 50, "stone_cost": 1,
    },
    "crit": {
        "name_cn": "暴击符文", "name_en": "Crit Rune",
        "emoji": "🟡", "stat_key": "enchant_crit",
        "min_val": 1, "max_val": 5, "stone_cost": 1,
    },
}

# Success rate by enchant level
ENCHANT_SUCCESS_RATES = {1: 0.90, 2: 0.80, 3: 0.65, 4: 0.45, 5: 0.25}

# Gold cost per attempt
ENCHANT_GOLD_COST = {1: 200, 2: 500, 3: 1000, 4: 2500, 5: 5000}


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


def _get_user_equipment(uid: str) -> list:
    """Get equipment from inventory."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT item_id, item_name, quantity FROM user_inventory WHERE user_id = ? AND item_type = 'equipment' AND quantity > 0 ORDER BY item_name",
            (uid,),
        )
        return cur.fetchall()


def _get_enchantment(uid: str, item_name: str) -> dict | None:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM mmorpg_enchantments WHERE user_id = ? AND item_name = ?",
            (uid, item_name),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _get_or_create_enchantment(uid: str, item_name: str) -> dict:
    """Get existing enchant or create default."""
    ench = _get_enchantment(uid, item_name)
    if not ench:
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO mmorpg_enchantments (user_id, item_name, enchant_atk, enchant_def, enchant_hp, enchant_crit) "
                "VALUES (?, ?, 0, 0, 0, 0)",
                (uid, item_name),
            )
            conn.commit()
        ench = {
            "user_id": uid, "item_name": item_name,
            "enchant_atk": 0, "enchant_def": 0, "enchant_hp": 0, "enchant_crit": 0,
        }
    return ench


def _get_stone_count(uid: str, stone_type: str) -> int:
    """Get number of enchant stones of given type from inventory."""
    stone_name_map = {
        "atk": "附魔石:攻击符文",
        "def": "附魔石:防御符文",
        "hp": "附魔石:生命符文",
        "crit": "附魔石:暴击符文",
    }
    stone_name = stone_name_map.get(stone_type, "")
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT SUM(quantity) as cnt FROM user_inventory WHERE user_id = ? AND item_type = 'enchant_stone' AND item_name = ?",
            (uid, stone_name),
        )
        row = cur.fetchone()
    return (row["cnt"] or 0) if row else 0


def _consume_stone(uid: str, stone_type: str, count: int):
    stone_name_map = {
        "atk": "附魔石:攻击符文",
        "def": "附魔石:防御符文",
        "hp": "附魔石:生命符文",
        "crit": "附魔石:暴击符文",
    }
    stone_name = stone_name_map.get(stone_type, "")
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE user_inventory SET quantity = quantity - ? WHERE user_id = ? AND item_type = 'enchant_stone' AND item_name = ? AND quantity >= ?",
            (count, uid, stone_name, count),
        )
        conn.commit()


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_enchant_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_enchantments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                enchant_atk INTEGER NOT NULL DEFAULT 0,
                enchant_def INTEGER NOT NULL DEFAULT 0,
                enchant_hp INTEGER NOT NULL DEFAULT 0,
                enchant_crit INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, item_name)
            )
        """)
        conn.commit()

_init_enchant_tables()


# ══════════════════════════════════════════════════════════════
# EnchantView — Main UI
# ══════════════════════════════════════════════════════════════
class EnchantView(discord.ui.View):
    """附魔主面板 / Enchant main panel."""

    def __init__(self, uid: str, item_name: str | None = None, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.item_name = item_name
        self.main_view = main_view

        if not item_name:
            equipment = _get_user_equipment(uid)
            if equipment:
                options = []
                for i, eq in enumerate(equipment[:25]):
                    label = eq["item_name"][:100]
                    options.append(discord.SelectOption(label=label, value=str(i)))

                select = discord.ui.Select(
                    placeholder="Select equipment to enchant... / 选择要附魔的装备...",
                    options=options,
                    row=0,
                )
                select.callback = self._select_callback
                self._equipment = equipment
                self.add_item(select)

            # Add enchant buttons (disabled until equipment selected)
            self._add_enchant_buttons(disabled=True)
        else:
            self._add_enchant_buttons(disabled=False)

    def _add_enchant_buttons(self, disabled: bool = False):
        for etype, info in ENCHANT_TYPES.items():
            btn = discord.ui.Button(
                label=f"{info['name_cn']}",
                emoji=info["emoji"],
                style=discord.ButtonStyle.primary,
                row=1,
                disabled=disabled,
            )
            btn.callback = self._make_enchant_callback(etype)
            self.add_item(btn)

    def _make_enchant_callback(self, etype: str):
        async def callback(interaction: discord.Interaction):
            await self._do_enchant(interaction, etype)
        return callback

    def build_embed(self) -> discord.Embed:
        if not self.item_name:
            embed = discord.Embed(
                title="✨ Enchantment / 附魔系统",
                description=(
                    "Select equipment from your inventory to enchant!\n"
                    "从背包中选择装备进行附魔！\n\n"
                    "**Enchant Stones / 附魔石:**\n"
                    "🔴 ATK Rune / 攻击符文: +3~15 ATK\n"
                    "🔵 DEF Rune / 防御符文: +2~10 DEF\n"
                    "🟢 HP Rune / 生命符文: +10~50 HP\n"
                    "🟡 Crit Rune / 暴击符文: +1~5% Crit\n\n"
                    "**Safe Enchant / 安全附魔:** Failure won't downgrade!\n"
                    "失败不掉级！仅消耗材料。"
                ),
                color=0xE67E22,
            )
            embed.set_footer(text="Select equipment first | 请先选择装备")
            return embed

        ench = _get_or_create_enchantment(self.uid, self.item_name)
        stats = {
            "atk": ench["enchant_atk"],
            "def": ench["enchant_def"],
            "hp": ench["enchant_hp"],
            "crit": ench["enchant_crit"],
        }

        # Find current enchant level
        max_level = 0
        for v in stats.values():
            if v > 0:
                max_level = max(max_level, 1)
        # Rough level estimation
        total_enchant = sum(stats.values())
        if total_enchant == 0:
            current_level = 0
        elif total_enchant <= 15:
            current_level = 1
        elif total_enchant <= 30:
            current_level = 2
        elif total_enchant <= 50:
            current_level = 3
        elif total_enchant <= 80:
            current_level = 4
        else:
            current_level = 5

        if current_level < 5:
            success_rate = ENCHANT_SUCCESS_RATES.get(current_level + 1, 0.25)
            gold_cost = ENCHANT_GOLD_COST.get(current_level + 1, 5000)
        else:
            success_rate = 0.0
            gold_cost = 0

        desc = (
            f"**Equipment / 装备:** {self.item_name}\n\n"
            f"**Current Enchants / 当前附魔:**\n"
            f"🔴 ATK: +{stats['atk']}\n"
            f"🔵 DEF: +{stats['def']}\n"
            f"🟢 HP: +{stats['hp']}\n"
            f"🟡 Crit: +{stats['crit']}%\n\n"
        )

        if current_level < 5:
            desc += (
                f"Estimated Level / 预估等级: +{current_level}\n"
                f"Next success rate / 下次成功率: **{int(success_rate * 100)}%**\n"
                f"Cost per attempt / 每次消耗: 🪙 {gold_cost} + 1x Stone"
            )
        else:
            desc += "**MAX Enchant! / 已满附魔！**"

        # Show stone counts
        stone_lines = []
        for etype, info in ENCHANT_TYPES.items():
            count = _get_stone_count(self.uid, etype)
            stone_lines.append(f"{info['emoji']} {info['name_cn']}: {count}")
        desc += "\n\n**Your Stones / 你的附魔石:**\n" + "\n".join(stone_lines)

        embed = discord.Embed(
            title="✨ Enchantment / 附魔系统",
            description=desc,
            color=0xE67E22,
        )
        embed.set_footer(text="Safe enchant: failure won't downgrade | 安全附魔：失败不掉级")
        return embed

    async def _select_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return

        idx = int(interaction.data["values"][0])
        item_name = self._equipment[idx]["item_name"]

        view = EnchantView(self.uid, item_name=item_name, main_view=self.main_view)
        embed = view.build_embed()

        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    async def _do_enchant(self, interaction: discord.Interaction, etype: str):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return

        if not self.item_name:
            await interaction.response.send_message("Select equipment first!", ephemeral=True)
            return

        ench = _get_or_create_enchantment(self.uid, self.item_name)
        current_val = ench.get(ENCHANT_TYPES[etype]["stat_key"], 0)

        # Determine current enchant level based on total
        total_enchant = ench["enchant_atk"] + ench["enchant_def"] + ench["enchant_hp"] + ench["enchant_crit"]
        if total_enchant == 0:
            current_level = 0
        elif total_enchant <= 15:
            current_level = 1
        elif total_enchant <= 30:
            current_level = 2
        elif total_enchant <= 50:
            current_level = 3
        elif total_enchant <= 80:
            current_level = 4
        else:
            current_level = 5

        if current_level >= 5:
            embed = discord.Embed(
                title="✨ Enchant / 附魔",
                description="Already at MAX enchant level!\n已是最高附魔等级！",
                color=0xF39C12,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        next_level = current_level + 1
        gold_cost = ENCHANT_GOLD_COST.get(next_level, 5000)
        success_rate = ENCHANT_SUCCESS_RATES.get(next_level, 0.25)

        coins = _get_coins(uid)
        stones = _get_stone_count(uid, etype)

        if coins < gold_cost or stones < 1:
            info = ENCHANT_TYPES[etype]
            embed = discord.Embed(
                title="✨ Enchant Failed / 附魔失败",
                description=(
                    f"Need / 需要:\n"
                    f"🪙 Gold: {coins:,}/{gold_cost:,}\n"
                    f"{info['emoji']} {info['name_cn']}: {stones}/1"
                ),
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        # Pay cost
        _add_coins(uid, -gold_cost, f"附魔消耗 — Enchant cost: {self.item_name} +{etype}")
        _consume_stone(uid, etype, 1)

        # Roll
        success = random.random() < success_rate

        if success:
            info = ENCHANT_TYPES[etype]
            bonus = random.randint(info["min_val"], info["max_val"])
            new_val = current_val + bonus

            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    f"UPDATE mmorpg_enchantments SET {info['stat_key']} = ? WHERE user_id = ? AND item_name = ?",
                    (new_val, uid, self.item_name),
                )
                conn.commit()

            embed = discord.Embed(
                title="✨ Enchant Success! / 附魔成功！",
                description=(
                    f"**{self.item_name}**\n"
                    f"{info['emoji']} {info['name_cn']}: **+{bonus}** (Total: {new_val})\n"
                    f"Rate: {int(success_rate * 100)}% → SUCCESS!"
                ),
                color=0x2ECC71,
            )
        else:
            info = ENCHANT_TYPES[etype]
            embed = discord.Embed(
                title="✨ Enchant Failed / 附魔失败",
                description=(
                    f"**{self.item_name}**\n"
                    f"{info['emoji']} {info['name_cn']}: No change (Safe Enchant)\n"
                    f"Rate: {int(success_rate * 100)}% → FAILED\n"
                    f"Safe enchant: no downgrade! / 安全附魔，未降级！"
                ),
                color=0xE74C3C,
            )

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=2)
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
                title="✨ Enchant / 附魔",
                description="Use `/gmpt-mmorpg` to return.",
                color=0x95A5A6,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════

class EnchantCog(commands.Cog):
    """附魔系统 / Enchantment System."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gmpt-enchant", description="Enchantment / 附魔 — add extra stats to equipment!")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def enchant_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        view = EnchantView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(EnchantCog(bot))
    logger.info("MMORPG Enchant cog loaded")
