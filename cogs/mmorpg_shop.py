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
            "SELECT hp, max_hp, mp, max_mp, attack, defense, level FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    if row:
        return dict(row)
    return {"hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50, "attack": 10, "defense": 5, "level": 1}


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
        view = MMORPGMainView(uid)
        await interaction.response.send_message(embed=embed, view=view)

    # ══════════════════════════════════════════════════════════
    # /gmpt-potionshop group
    # ══════════════════════════════════════════════════════════
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
        desc = (
            "**NPC Potion Shop / NPC 药水商店**\n\n"
            "🛒 `/gmpt-potionshop browse` — Browse all potions / 浏览所有药水\n"
            "💰 `/gmpt-potionshop buy <potion> [qty]` — Buy potion / 购买药水\n"
            "🎒 `/gmpt-potionshop inventory` — View your bag / 查看背包\n"
            "🧪 `/gmpt-potionshop use <potion>` — Drink a potion / 使用药水\n\n"
            "Categories / 类别: Recovery / Combat Buffs / Special"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("Potion Shop / 药水商店", 0x3498DB, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("Potion Shop / 药水商店", 0x3498DB, desc), view=self
            )

    @discord.ui.button(label="Skills / 技能", style=discord.ButtonStyle.primary, row=0, emoji="⚔️")
    async def skills_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**Skill System / 技能系统**\n\n"
            "📚 `/gmpt-skill learn` — Learn a skill / 学习技能\n"
            "📋 `/gmpt-skill list` — List learned skills / 查看已学技能\n"
            "✅ `/gmpt-skill equip` — Equip skill / 装备技能\n"
            "❌ `/gmpt-skill unequip` — Unequip skill / 卸下技能\n\n"
            "Skills can be used in PVP and Boss battles!"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("Skill System / 技能系统", 0xE67E22, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("Skill System / 技能系统", 0xE67E22, desc), view=self
            )

    @discord.ui.button(label="PVP Arena / PVP 对战", style=discord.ButtonStyle.primary, row=0, emoji="🏆")
    async def pvp_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**PVP Arena / PVP 对战系统**\n\n"
            "⚔️ `/gmpt-pvp challenge` — Challenge a player / 发起挑战\n"
            "✅ `/gmpt-pvp accept` — Accept challenge / 接受挑战\n"
            "🚫 `/gmpt-pvp decline` — Decline challenge / 拒绝挑战\n\n"
            "Use skills and potions to win!"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("PVP Arena / PVP 对战", 0xE74C3C, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("PVP Arena / PVP 对战", 0xE74C3C, desc), view=self
            )

    @discord.ui.button(label="Boss Raid / Boss 战", style=discord.ButtonStyle.danger, row=0, emoji="🐉")
    async def boss_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**Boss Raid / Boss 团战**\n\n"
            "🏰 `/gmpt-boss dungeon` — View all bosses / 查看所有副本\n"
            "⚔️ `/gmpt-boss create` — Create a raid room / 创建Boss房间\n"
            "👥 `/gmpt-boss join` — Join a raid / 加入房间\n"
            "💥 `/gmpt-boss attack` — Attack the boss / 攻击Boss\n\n"
            "Team up to defeat powerful bosses!"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("Boss Raid / Boss 团战", 0xC0392B, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("Boss Raid / Boss 团战", 0xC0392B, desc), view=self
            )

    # Row 1: Dungeon, Equipment, Daily Quest, Class, Back
    @discord.ui.button(label="Dungeon / 地下城", style=discord.ButtonStyle.secondary, row=1, emoji="🏰")
    async def dungeon_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**Dungeon / 地下城**\n\n"
            "🏰 `/gmpt-dungeon explore` — Start dungeon run / 开始探索\n"
            "📊 5 层随机怪物，每日免费 1 次\n"
            "📊 5 floors, 1 free daily run\n"
            "💵 Extra runs / 额外: 200G\n\n"
            "Each floor yields increasing rewards!"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("Dungeon / 地下城", 0x8E44AD, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("Dungeon / 地下城", 0x8E44AD, desc), view=self
            )

    @discord.ui.button(label="Equipment / 装备", style=discord.ButtonStyle.secondary, row=1, emoji="🗡️")
    async def equipment_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**Equipment System / 装备系统**\n\n"
            "⚔️ Weapon 武器 (ATK) | 🛡️ Armor 护甲 (DEF)\n"
            "⛑️ Helmet 头盔 (HP) | 💍 Ring 戒指 (Crit)\n"
            "📿 Accessory 饰品 (SPD)\n\n"
            "💎 品质 / Quality: ⚪普通 🔵稀有 🟣史诗 🟡传说\n"
            "Boss 掉落 / Shop / `/gmpt-equipment` to manage"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("Equipment System / 装备系统", 0xE67E22, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("Equipment System / 装备系统", 0xE67E22, desc), view=self
            )

    @discord.ui.button(label="Daily Quest / 每日任务", style=discord.ButtonStyle.secondary, row=1, emoji="📋")
    async def daily_quest_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**Daily Quests / 每日任务**\n\n"
            "📋 每日 3 个随机任务 / 3 random quests daily\n"
            "🕛 UTC+8 午夜重置 / Resets at midnight UTC+8\n\n"
            "Tasks: 杀怪 / 打工 / PVP / 购物 / 用药水\n"
            "Use `/gmpt-daily` to view your quests"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("Daily Quests / 每日任务", 0x3498DB, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("Daily Quests / 每日任务", 0x3498DB, desc), view=self
            )

    @discord.ui.button(label="Class / 职业", style=discord.ButtonStyle.secondary, row=1, emoji="🎭")
    async def class_btn(self, interaction: discord.Interaction, button):
        from cogs.mmorpg_class import CLASS_DEFS, _get_class
        uid = str(interaction.user.id)
        current_key = _get_class(uid)
        lines = []
        if current_key:
            cd = CLASS_DEFS.get(current_key)
            if cd:
                lines.append(
                    f"**当前职业 / Current:** {cd['emoji']} **{cd['name_cn']} / {cd['name_en']}**\n"
                    f"　{cd['passive_cn']}\n"
                )
        else:
            lines.append("**未选择 / None selected**\n")
        lines.append("")
        lines.append(
            "⚔️ 战士 Warrior | 🔮 法师 Mage | 🗡️ 刺客 Assassin\n"
            "✝️ 牧师 Priest | 🛡️ 圣骑士 Paladin | 🏹 弓箭手 Archer\n\n"
            "**Choose:** `/gmpt-class choose <class>`\n"
            "**View:** `/gmpt-class info`\n"
            "首次免费 / First free | 更换 500G / Change 500G"
        )
        desc = "\n".join(lines)
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("Class System / 职业系统", 0x9B59B6, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("Class System / 职业系统", 0x9B59B6, desc), view=self
            )

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
    def __init__(self, potions: dict, user_level: int, user_id: str):
        super().__init__(timeout=180)
        self.potions = potions
        self.user_level = user_level
        self.user_id = user_id
        self.active_category = "recovery"
        self._update_category_buttons()

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

    async def _switch_category(self, interaction: discord.Interaction, category: str):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("Not your page / 不是你的页面", ephemeral=True)
        self.active_category = category
        self._update_category_buttons()
        try:
            await interaction.response.edit_message(embed=self.build_embed(category), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(category), view=self)

    @discord.ui.button(label="Recovery / 恢复类", custom_id="cat_recovery", style=discord.ButtonStyle.primary, row=0, emoji="❤️")
    async def cat_recovery(self, interaction: discord.Interaction, button):
        await self._switch_category(interaction, "recovery")

    @discord.ui.button(label="Combat Buffs / 战斗增益", custom_id="cat_combat", style=discord.ButtonStyle.secondary, row=0, emoji="⚔️")
    async def cat_combat(self, interaction: discord.Interaction, button):
        await self._switch_category(interaction, "combat")

    @discord.ui.button(label="Special / 特殊", custom_id="cat_special", style=discord.ButtonStyle.secondary, row=0, emoji="✨")
    async def cat_special(self, interaction: discord.Interaction, button):
        await self._switch_category(interaction, "special")

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


async def setup(bot):
    await bot.add_cog(PotionShop(bot))
