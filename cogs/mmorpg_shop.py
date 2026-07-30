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

        # Deduct coins and add to inventory in a single transaction
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING",
                (uid,),
            )
            cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (-total_cost, uid))
            cur.execute(
                "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
                (uid, -total_cost, f"Bought {p['name_en']} x{quantity} / 购买 {p['name_cn']} x{quantity}"),
            )
            cur.execute(
                "SELECT quantity FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
                (uid, potion_key),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    "UPDATE user_inventory SET quantity = quantity + ? WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
                    (quantity, uid, potion_key),
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
                "SELECT quantity FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
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
                cur.execute("UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_name = ? AND item_type = 'potion'", (uid, potion_key))
                conn.commit()
        else:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'", (uid, potion_key))
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
        class_emoji = "\U0001f9d1"
        class_name = "未选择 / None"

    hp = stats["hp"]
    max_hp = max(stats["max_hp"], 1)
    mp = stats["mp"]
    max_mp = max(stats["max_mp"], 1)
    atk = stats["attack"]
    defense = stats["defense"]
    level = stats["level"]

    hp_pct = hp / max_hp
    mp_pct = mp / max_mp
    hp_bar = "\u2588" * max(1, int(hp_pct * 10)) + "\u2591" * max(0, 10 - int(hp_pct * 10))
    mp_bar = "\u2588" * max(1, int(mp_pct * 10)) + "\u2591" * max(0, 10 - int(mp_pct * 10))

    xp_for_level = 1000
    xp_progress = xp % xp_for_level
    xp_pct = xp_progress / xp_for_level
    xp_bar = "\u2588" * max(1, int(xp_pct * 10)) + "\u2591" * max(0, 10 - int(xp_pct * 10))

    # ANSI art header
    header = (
        "```ansi\n"
        "\u001b[1;33m      \u2694\uFE0F  \U0001f451  \u2694\uFE0F      \u001b[0m\n"
        f"\u001b[1;37m  {display_name or 'Adventurer'}  \u001b[0m\n"
        f"\u001b[1;36m  {class_emoji} {class_name} Lv.{level}  \u001b[0m\n"
        "```"
    )

    embed = discord.Embed(
        title="\u2694\uFE0F  GMPT MMORPG  \u2694\uFE0F",
        description=header,
        color=0x9B59B6,
    )

    # Two-column layout using fields
    embed.add_field(
        name=f"\u2764\uFE0F HP  `{hp_bar}`",
        value=f"**{hp}/{max_hp}**",
        inline=True,
    )
    embed.add_field(
        name=f"\U0001f4a1 MP  `{mp_bar}`",
        value=f"**{mp}/{max_mp}**",
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

    embed.add_field(name="\u2694\uFE0F ATK", value=f"**{atk}**", inline=True)
    embed.add_field(name="\U0001f6e1\uFE0F DEF", value=f"**{defense}**", inline=True)
    embed.add_field(name="\U0001f4b0 Coins", value=f"**{bal:,}**", inline=True)

    embed.add_field(
        name=f"\u2b50 EXP  `{xp_bar}`",
        value=f"**{xp_progress:,}** / {xp_for_level:,}  (Total: **{xp:,}**)",
        inline=False,
    )

    if display_name:
        embed.set_footer(text=f"{display_name}  |  /gmpt-mmorpg")
    return embed


# ══════════════════════════════════════════════════════════════
# MMORPGMainView — Unified Control Panel (14 subsystems, 5 rows)
# Row 0: Work | Shop | Class
# Row 1: Boss | Dungeon | PVP
# Row 2: Quest | Equip | Skills
# Row 3: Bag | Stats | TitlesHub
# Row 4: Guild | Bounty
# ══════════════════════════════════════════════════════════════
class MMORPGMainView(discord.ui.View):
    def __init__(self, uid: str):
        super().__init__(timeout=None)
        self.uid = uid

    # ── Row 0: Work + Shop + Class ──
    @discord.ui.button(label="Work 打工", emoji="\u2692\uFE0F", style=discord.ButtonStyle.primary, row=0, custom_id="mmorpg_main:work")
    async def work_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.economy_jobs import EconomyJobsView
        view = EconomyJobsView(interaction.guild, main_view=self)
        embed = discord.Embed(
            title="\u2692\uFE0F Work / 打工",
            description="Choose a job to earn coins and EXP!\n选择工作来赚取金币和经验！",
            color=0xF39C12,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Shop 商店", emoji="\U0001f3ea", style=discord.ButtonStyle.primary, row=0, custom_id="mmorpg_main:shop")
    async def shop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_level = _get_user_level(self.uid)
        view = ShopHubView(self.uid, user_level, main_view=self)
        embed = discord.Embed(
            title="\U0001f3ea Shop / 商店",
            description="Choose a shop category!\n选择商店类型！",
            color=0xE67E22,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Class 职业", emoji="\U0001f464", style=discord.ButtonStyle.primary, row=0, custom_id="mmorpg_main:class")
    async def class_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_class import ClassSelectView, _get_class
        current_class = _get_class(self.uid)
        view = ClassSelectView(self.uid, current_class, main_view=self)
        embed = discord.Embed(
            title="\U0001f464 Class / 职业",
            description="Choose your class!\n选择你的职业！",
            color=0x8E44AD,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 1: Boss + Dungeon + PVP ──
    @discord.ui.button(label="Boss", emoji="\u2694\uFE0F", style=discord.ButtonStyle.danger, row=1, custom_id="mmorpg_main:boss")
    async def boss_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.boss import BossLobbyView
        view = BossLobbyView(self.uid, main_view=self)
        embed = discord.Embed(
            title="\u2694\uFE0F Boss Hunt / Boss 狩猎",
            description="Fight epic bosses for rare loot!\n挑战史诗Boss获取稀有装备！",
            color=0xE74C3C,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Dungeon 副本", emoji="\U0001f3f0", style=discord.ButtonStyle.danger, row=1, custom_id="mmorpg_main:dungeon")
    async def dungeon_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.dungeon import DungeonLobbyView
        view = DungeonLobbyView(self.uid, main_view=self)
        embed = discord.Embed(
            title="\U0001f3f0 Dungeon / 副本",
            description="Explore dungeons for treasures!\n探索副本寻找宝藏！",
            color=0x3498DB,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="PVP", emoji="\u2694\uFE0F", style=discord.ButtonStyle.success, row=1, custom_id="mmorpg_main:pvp")
    async def pvp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            from cogs.mmorpg_pvp import PVPView
            view = PVPView(self.uid, main_view=self)
        except (ImportError, AttributeError):
            embed = discord.Embed(
                title="\u2694\uFE0F PVP Arena / PVP竞技场",
                description="PVP coming soon!\nPVP功能即将开放！",
                color=0xE67E22,
            )
            view = MMORPGMainView(self.uid)
            await interaction.response.edit_message(embed=embed, view=view)
            return
        embed = discord.Embed(
            title="\u2694\uFE0F PVP Arena / PVP竞技场",
            description="Challenge other players!\n挑战其他玩家！",
            color=0xE67E22,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Pets 宠物", emoji="🐾", style=discord.ButtonStyle.success, row=1, custom_id="mmorpg_main:pets")
    async def pets_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.pets import PetPanelView
        view = PetPanelView(self.uid, main_view=self)
        embed = discord.Embed(
            title="🐾 Pets / 宠物",
            description="Adopt, feed and play with your pets!\n领养、喂养和与宠物玩耍！",
            color=0x2ECC71,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 2: Quest + Equip + Skills ──
    @discord.ui.button(label="Quest 任务", emoji="\U0001f4cb", style=discord.ButtonStyle.success, row=2, custom_id="mmorpg_main:quest")
    async def quest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.daily_quest import DailyQuestView
        view = DailyQuestView(self.uid, main_view=self)
        embed = view.build_main_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Equip 装备", emoji="\U0001f6e1\uFE0F", style=discord.ButtonStyle.secondary, row=2, custom_id="mmorpg_main:equip")
    async def equip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_equipment import EquipmentView
        view = EquipmentView(self.uid, main_view=self)
        embed = discord.Embed(
            title="\U0001f6e1\uFE0F Equipment / 装备",
            description="Manage your gear!\n管理你的装备！",
            color=0x7F8C8D,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Skills 技能", emoji="\U0001f5e1\uFE0F", style=discord.ButtonStyle.secondary, row=2, custom_id="mmorpg_main:skills")
    async def skills_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_skills import SkillShopView
        view = SkillShopView(self.uid, main_view=self)
        embed = discord.Embed(
            title="\U0001f5e1\uFE0F Skills / 技能",
            description="Learn powerful skills!\n学习强力技能！",
            color=0x9B59B6,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Achieve 成就", emoji="🏆", style=discord.ButtonStyle.secondary, row=2, custom_id="mmorpg_main:achievements")
    async def achievements_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.achievements import AchievementsView
        view = AchievementsView(self.uid, main_view=self)
        embed = await view._get_achievements_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 3: Bag + Stats + TitlesHub ──
    @discord.ui.button(label="Bag 背包", emoji="🎒", style=discord.ButtonStyle.secondary, row=3, custom_id="mmorpg_main:inv")
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
            view = _BackOnlyView(self.uid, main_view=self)
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
            view = PotionBagView(self.uid, rows, main_view=self)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Stats 属性", emoji="📊", style=discord.ButtonStyle.secondary, row=3, custom_id="mmorpg_main:stats")
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_stats import StatsView
        view = StatsView(self.uid, main_view=self)
        embed = view.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Titles 称号", emoji="🏅", style=discord.ButtonStyle.secondary, row=3, custom_id="mmorpg_main:titles")
    async def titles_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_titles import TitlesHubView
        view = TitlesHubView(self.uid, main_view=self)
        embed = discord.Embed(
            title="🏅 Titles & Achievements / 称号与成就",
            description="View your titles and achievements!\n查看你的称号和成就！",
            color=0xF1C40F,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Market 市场", emoji="🏪", style=discord.ButtonStyle.secondary, row=3, custom_id="mmorpg_main:market")
    async def market_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.market import MarketListView
        view = MarketListView(self.uid, main_view=self)
        embed = view.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    # ── Row 4: Guild + Bounty ──
    @discord.ui.button(label="Guild 公会", emoji="🏰", style=discord.ButtonStyle.success, row=4, custom_id="mmorpg_main:guild")
    async def guild_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.clans import ClanPanelView
        view = ClanPanelView()
        embed = discord.Embed(
            title="🏰 Clan / 公会",
            description="Create or join a clan! Work together for glory!\n创建或加入公会，一起征战四方！",
            color=0x8E44AD,
        )
        embed.set_footer(text="Clan actions use slash commands: /gmpt-clan create | join | leave | info | donate")
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Bounty 悬赏", emoji="📜", style=discord.ButtonStyle.success, row=4, custom_id="mmorpg_main:bounty")
    async def bounty_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_bounty import BountyPanelView, _assign_bounties
        bounties = _assign_bounties(self.uid)
        view = BountyPanelView(self.uid, main_view=self)
        embed = discord.Embed(
            title="📜 Bounty Board / 悬赏任务板",
            description="Daily bounties — kill enemies or gather items for rewards!\n每日悬赏 — 击杀敌人或收集物品获取奖励！",
            color=0xE67E22,
        )
        from cogs.mmorpg_bounty import BOUNTY_TEMPLATES
        for b in bounties:
            template = BOUNTY_TEMPLATES[b["bounty_id"]]
            emoji, cn, en = template[6], template[0], template[1]
            pct = int(b["progress"] / max(1, b["target_count"]) * 100)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            status = "✅ COMPLETE" if b["progress"] >= b["target_count"] else f"{bar} {b['progress']}/{b['target_count']}"
            embed.add_field(
                name=f"{emoji} {cn} / {en}",
                value=(
                    f"Type / 类型: {'Kill 击杀' if b['target_type'] == 'kill' else 'Gather 采集'} × {b['target_count']}\n"
                    f"Progress / 进度: {status}\n"
                    f"Reward / 奖励: 🪙 {b['coins']} | ⚡ {b['exp']} EXP"
                ),
                inline=False,
            )
        embed.set_footer(text="Click a complete bounty to claim your reward!")
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Cosmetics 外观", emoji="🎨", style=discord.ButtonStyle.success, row=4, custom_id="mmorpg_main:cosmetics")
    async def cosmetics_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🎨 Cosmetics Shop / 外观商店",
            description=(
                "Buy cosmetic titles to show off!\n"
                "购买外观称号来展示个性！\n\n"
                "Available items / 可购买物品:\n"
                "👑 王者皇冠 (King's Crown) — 🪙 5000\n"
                "🎭 忍者面具 (Ninja Mask) — 🪙 3000\n"
                "👼 天使翅膀 (Angel Wings) — 🪙 4000\n"
                "😈 恶魔之角 (Demon Horns) — 🪙 4000\n"
                "🌈 彩虹披风 (Rainbow Cape) — 🪙 3500\n"
                "🛡️ 黄金铠甲 (Golden Armor) — 🪙 6000\n"
                "🌑 暗影斗篷 (Shadow Cloak) — 🪙 4500\n"
                "🔥 火焰光环 (Fire Aura) — 🪙 5500"
            ),
            color=0xFF69B4,
        )
        embed.set_footer(text="/gmpt-shop buy <item> to purchase | 使用 /gmpt-shop buy <物品> 购买")
        view = _BackOnlyView(self.uid, main_view=self)
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


# ══════════════════════════════════════════════════════════════
# PotionBagView — Backpack with Use buttons per potion
# ══════════════════════════════════════════════════════════════
class PotionBagView(discord.ui.View):
    """Backpack view with Use buttons for each potion."""
    def __init__(self, uid: str, potion_rows: list, main_view: MMORPGMainView):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view
        self._potions = {row["item_name"]: row for row in potion_rows}
        self._build()

    def _build(self):
        self.clear_items()
        for idx, (potion_key, row) in enumerate(self._potions.items()):
            p = POTION_CATALOG.get(potion_key, {})
            emoji = p.get("emoji", "🧪")
            cn = p.get("name_cn", potion_key)
            btn = discord.ui.Button(
                label=f"Use {cn}",
                emoji=emoji,
                style=discord.ButtonStyle.primary,
                row=idx // 3,
                custom_id=f"potbag_use:{potion_key}",
            )
            btn.callback = self._make_use_callback(potion_key)
            self.add_item(btn)

        if self.main_view:
            back_btn = discord.ui.Button(
                label="Back 返回", emoji="🔙",
                style=discord.ButtonStyle.secondary,
                row=4, custom_id="potbag_back",
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    def _make_use_callback(self, potion_key: str):
        async def cb(interaction: discord.Interaction):
            await self._use_potion(interaction, potion_key)
        return cb

    async def _use_potion(self, interaction: discord.Interaction, potion_key: str):
        """Consume 1 potion from inventory."""
        uid = self.uid

        if potion_key not in POTION_CATALOG:
            await interaction.response.send_message("Potion not found / 药水不存在", ephemeral=True)
            return

        p = POTION_CATALOG[potion_key]

        # Re-check inventory
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT quantity FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
                (uid, potion_key),
            )
            inv_row = cur.fetchone()

        if not inv_row or inv_row["quantity"] <= 0:
            await interaction.response.send_message(
                f"You don't have **{p['name_cn']}** in your bag / 背包中没有此药水！",
                ephemeral=True,
            )
            return

        user_level = _get_user_level(uid)
        if user_level < p["min_level"]:
            await interaction.response.send_message(
                f"Level too low / 等级不足！Requires Lv.{p['min_level']}, you are Lv.{user_level}",
                ephemeral=True,
            )
            return

        # Defer for animation
        await interaction.response.defer()

        # Consume 1
        if inv_row["quantity"] > 1:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE user_inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
                    (uid, potion_key),
                )
                conn.commit()
        else:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "DELETE FROM user_inventory WHERE user_id = ? AND item_name = ? AND item_type = 'potion'",
                    (uid, potion_key),
                )
                conn.commit()

        # Apply effect
        effect_type = p["effect_type"]
        effect_value = p["effect_value"]

        if effect_type == "heal_hp":
            stats = _get_user_stats(uid)
            cur_hp = stats["hp"]
            max_hp = stats["max_hp"]
            new_hp = min(cur_hp + effect_value, max_hp)
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE users SET hp = ? WHERE discord_id = ?", (new_hp, uid))
                conn.commit()
            embed = discord.Embed(
                title=f"{p['emoji']} {p['name_cn']} / {p['name_en']}",
                description=f"Restored **{new_hp - cur_hp}** HP / 恢复了 **{new_hp - cur_hp}** HP！\n{cur_hp} → {new_hp} / {max_hp}",
                color=0xE74C3C,
            )

        elif effect_type == "heal_mp":
            stats = _get_user_stats(uid)
            cur_mp = stats["mp"]
            max_mp = stats["max_mp"]
            new_mp = min(cur_mp + effect_value, max_mp)
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE users SET mp = ? WHERE discord_id = ?", (new_mp, uid))
                conn.commit()
            embed = discord.Embed(
                title=f"{p['emoji']} {p['name_cn']} / {p['name_en']}",
                description=f"Restored **{new_mp - cur_mp}** MP / 恢复了 **{new_mp - cur_mp}** MP！\n{cur_mp} → {new_mp} / {max_mp}",
                color=0x3498DB,
            )

        elif effect_type in ("buff_atk", "buff_def", "buff_spd", "buff_crit", "buff_exp"):
            expires = datetime.datetime.now() + datetime.timedelta(minutes=p["duration"])
            buff_type_map = {
                "buff_atk": "atk_up", "buff_def": "def_up",
                "buff_spd": "spd_up", "buff_crit": "crit_up", "buff_exp": "exp_up",
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
                description=f"{p['effect_cn']}\n{p['effect_en']}\n\nDuration / 持续: **{p['duration']}** turns/minutes",
                color=0xE67E22,
            )

        elif effect_type == "revive":
            stats = _get_user_stats(uid)
            if stats["hp"] > 0:
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) VALUES (?, ?, ?, 1, 'potion')",
                        (uid, p["id"], potion_key),
                    )
                    conn.commit()
                await interaction.followup.send(
                    "You're still alive! Revival potion only usable when HP=0.\n你还活着！复活药水只能在 HP=0 时使用。",
                    ephemeral=True,
                )
                return
            max_hp = stats["max_hp"]
            max_mp = stats["max_mp"]
            restore_hp = max(1, int(max_hp * effect_value / 100))
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE users SET hp = ?, mp = ? WHERE discord_id = ?", (restore_hp, max_mp, uid))
                conn.commit()
            embed = discord.Embed(
                title=f"{p['emoji']} {p['name_cn']} / {p['name_en']}",
                description=f"Revived! HP restored to **{restore_hp}**/{max_hp}, MP fully restored!\n复活成功！HP 恢复到 **{restore_hp}**/{max_hp}，MP 全满！",
                color=0x2ECC71,
            )

        else:
            embed = discord.Embed(
                title=f"{p['emoji']} {p['name_cn']} / {p['name_en']}",
                description=f"Used successfully / 使用成功！",
                color=0x95A5A6,
            )

        # Refresh the bag view with remaining potions
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT item_name, quantity FROM user_inventory WHERE user_id = ? AND item_type = 'potion' AND quantity > 0 ORDER BY item_name",
                (uid,),
            )
            rows = cur.fetchall()

        if not rows:
            lines = ["Your backpack is empty!\n背包空空如也！"]
        else:
            lines = []
            for row_data in rows:
                pp = POTION_CATALOG.get(row_data["item_name"], {})
                lines.append(f"{pp.get('emoji', '🧪')} **{pp.get('name_cn', row_data['item_name'])} / {pp.get('name_en', row_data['item_name'])}** x{row_data['quantity']}")

        bag_embed = discord.Embed(
            title="🎒 Backpack / 背包",
            description="\n".join(lines),
            color=0x95A5A6,
        )

        new_view = PotionBagView(uid, rows, main_view=self.main_view)
        await interaction.followup.edit_message(interaction.message.id, embed=bag_embed, view=new_view)
        await interaction.followup.send(embed=embed)

    async def _back_callback(self, interaction: discord.Interaction):
        embed = build_main_embed(self.uid, interaction.user.display_name)
        try:
            await interaction.response.edit_message(embed=embed, view=self.main_view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=self.main_view)

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
            # Deduct coins and add to inventory in a single transaction
            with get_db_ctx() as conn:
                conn.execute(
                    "INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING",
                    (uid,),
                )
                conn.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (-p["price"], uid))
                conn.execute(
                    "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
                    (uid, -p["price"], f"Buy potion / 购买药水: {p['name_en']}"),
                )
                cur = conn.cursor()
                cur.execute(
                    "SELECT quantity FROM user_inventory WHERE user_id = ? AND item_id = ?",
                    (uid, p["id"]),
                )
                existing = cur.fetchone()
                if existing:
                    conn.execute(
                        "UPDATE user_inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?",
                        (uid, p["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) "
                        "VALUES (?, ?, ?, 1, 'potion')",
                        (uid, p["id"], potion_key),
                    )
                conn.commit()
            new_bal = _get_balance(uid)
            import asyncio as _asyncio
            from utils.animations import shop_purchase_animation
            await interaction.response.defer(ephemeral=True)
            await shop_purchase_animation(interaction, p["name_cn"], p["emoji"], p["price"], new_bal)
            # Rebuild the category panel after purchase
            try:
                await interaction.message.edit(embed=self.build_embed(self.active_category), view=self)
            except (discord.NotFound, discord.HTTPException):
                pass
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


# ══════════════════════════════════════════════════════════════
# ShopHubView — Shop hub with potion / equipment sub-menus
# ══════════════════════════════════════════════════════════════
class ShopHubView(discord.ui.View):
    """Hub view linking to Potion Shop and Equipment Shop."""
    def __init__(self, uid: str, user_level: int, main_view: MMORPGMainView):
        super().__init__(timeout=300)
        self.uid = uid
        self.user_level = user_level
        self.main_view = main_view

    @discord.ui.button(label="🧪 Potion Shop 药水", style=discord.ButtonStyle.primary, row=0)
    async def potion_shop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.mmorpg_shop import PotionBrowseView
        view = PotionBrowseView(POTION_CATALOG, self.user_level, self.uid, main_view=self.main_view)
        embed = view.build_embed("recovery")
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="⚔️ Equipment Shop 装备", style=discord.ButtonStyle.success, row=0)
    async def equip_shop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EquipmentShopView(self.uid, main_view=self.main_view)
        embed = view.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.followup.edit_message(embed=embed, view=view)

    @discord.ui.button(label="🎰 Equipment Gacha 装备抽奖", style=discord.ButtonStyle.danger, row=0)
    async def gacha_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EquipmentGachaView(self.uid, main_view=self.main_view)
        embed = view.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="↩ Back 返回", emoji="↩", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        embed = build_main_embed(uid, interaction.user.display_name)
        try:
            await interaction.response.edit_message(embed=embed, view=self.main_view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self.main_view)


# ══════════════════════════════════════════════════════════════
# EquipmentShopView — Equipment purchase shop
# ══════════════════════════════════════════════════════════════
EQUIPMENT_SHOP = {
    "weapon": [
        {"name": "铁剑 Iron Sword", "quality": "normal", "stat": "atk", "stat_value": 10, "price": 500, "emoji": "⚔️"},
        {"name": "秘银剑 Mithril Sword", "quality": "rare", "stat": "atk", "stat_value": 18, "price": 1200, "emoji": "⚔️"},
        {"name": "烈焰之刃 Flame Blade", "quality": "epic", "stat": "atk", "stat_value": 28, "price": 3000, "emoji": "🔥"},
    ],
    "helmet": [
        {"name": "铁盔 Iron Helm", "quality": "normal", "stat": "hp", "stat_value": 15, "price": 400, "emoji": "🪖"},
        {"name": "秘银盔 Mithril Helm", "quality": "rare", "stat": "hp", "stat_value": 25, "price": 1000, "emoji": "🪖"},
        {"name": "龙鳞盔 Dragonscale Helm", "quality": "epic", "stat": "hp", "stat_value": 38, "price": 2500, "emoji": "🐉"},
    ],
    "armor": [
        {"name": "皮甲 Leather Armor", "quality": "normal", "stat": "def", "stat_value": 10, "price": 500, "emoji": "🛡️"},
        {"name": "锁子甲 Chainmail", "quality": "rare", "stat": "def", "stat_value": 18, "price": 1200, "emoji": "🛡️"},
        {"name": "龙鳞甲 Dragonscale Plate", "quality": "epic", "stat": "def", "stat_value": 28, "price": 3000, "emoji": "🐉"},
    ],
    "leggings": [
        {"name": "布裤 Cloth Pants", "quality": "normal", "stat": "def", "stat_value": 8, "price": 350, "emoji": "👖"},
        {"name": "锁子裤 Chain Leggings", "quality": "rare", "stat": "def", "stat_value": 14, "price": 900, "emoji": "👖"},
        {"name": "龙鳞护腿 Dragonscale Greaves", "quality": "epic", "stat": "def", "stat_value": 22, "price": 2200, "emoji": "🐉"},
    ],
    "boots": [
        {"name": "皮靴 Leather Boots", "quality": "normal", "stat": "spd", "stat_value": 8, "price": 350, "emoji": "👢"},
        {"name": "铁靴 Iron Boots", "quality": "rare", "stat": "spd", "stat_value": 14, "price": 900, "emoji": "👢"},
        {"name": "疾风之靴 Wind Walkers", "quality": "epic", "stat": "spd", "stat_value": 22, "price": 2200, "emoji": "💨"},
    ],
    "accessory": [
        {"name": "铜戒 Copper Ring", "quality": "normal", "stat": "crit", "stat_value": 6, "price": 300, "emoji": "💍"},
        {"name": "银戒 Silver Ring", "quality": "rare", "stat": "crit", "stat_value": 10, "price": 800, "emoji": "💍"},
        {"name": "翡翠项链 Jade Amulet", "quality": "epic", "stat": "hp", "stat_value": 20, "price": 2000, "emoji": "📿"},
    ],
}

EQUIPMENT_SHOP_SLOT_LABELS = {
    "weapon": "⚔️ Weapon 武器",
    "helmet": "🪖 Helmet 头盔",
    "armor": "🛡️ Armor 护甲",
    "leggings": "👖 Leggings 护腿",
    "boots": "👢 Boots 鞋子",
    "accessory": "📿 Accessory 饰品",
}

QUALITY_EMOJI = {
    "normal": "⚪",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟡",
}


class EquipmentShopView(discord.ui.View):
    def __init__(self, uid: str, main_view: MMORPGMainView):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view
        self.slots = list(EQUIPMENT_SHOP.keys())
        self.active_slot_idx = 0
        self._rebuild_buttons()

    def build_embed(self) -> discord.Embed:
        slot = self.slots[self.active_slot_idx]
        label = EQUIPMENT_SHOP_SLOT_LABELS[slot]
        items = EQUIPMENT_SHOP[slot]

        embed = discord.Embed(
            title="⚔️ Equipment Shop / 装备商店",
            description=f"**{label}** — Purchase to add to your inventory!\n购买后自动加入背包，可在装备面板中穿戴。",
            color=0x27AE60,
        )
        bal = _get_balance(self.uid) or 0
        embed.set_footer(text=f"Your balance: 🪙 {bal:,}  |  Click Buy to purchase an item")

        for idx, item in enumerate(items):
            qe = QUALITY_EMOJI.get(item["quality"], "⚪")
            stat_label = {"atk": "ATK", "def": "DEF", "hp": "HP", "spd": "SPD", "crit": "CRIT"}.get(item["stat"], item["stat"].upper())
            embed.add_field(
                name=f"{idx + 1}. {item['emoji']} {qe} {item['name']}",
                value=f"{stat_label} **+{item['stat_value']}**  |  🪙 **{item['price']:,}**",
                inline=False,
            )

        nav = " / ".join(
            f"**{EQUIPMENT_SHOP_SLOT_LABELS[s]}**" if i == self.active_slot_idx
            else EQUIPMENT_SHOP_SLOT_LABELS[s]
            for i, s in enumerate(self.slots)
        )
        embed.description += f"\n\n📂 {nav}"
        return embed

    def _rebuild_buttons(self):
        self.clear_items()
        slot = self.slots[self.active_slot_idx]
        items = EQUIPMENT_SHOP[slot]

        # Buy buttons for each item in current slot
        for idx, item in enumerate(items):
            btn = discord.ui.Button(
                label=f"{item['emoji']} {item['name']} ({item['price']:,}🪙)",
                style=discord.ButtonStyle.success if item["quality"] != "normal" else discord.ButtonStyle.primary,
                row=0,
                custom_id=None,
            )
            btn.callback = self._make_buy_callback(idx, item, slot)
            self.add_item(btn)

        # Navigation buttons for slots
        prev_btn = discord.ui.Button(label="◀ Prev Slot", style=discord.ButtonStyle.secondary, row=1)
        prev_btn.callback = self._prev_slot
        self.add_item(prev_btn)

        next_btn = discord.ui.Button(label="Next Slot ▶", style=discord.ButtonStyle.secondary, row=1)
        next_btn.callback = self._next_slot
        self.add_item(next_btn)

        back_btn = discord.ui.Button(label="↩ Back to Shop Hub", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back_to_hub
        self.add_item(back_btn)

    def _make_buy_callback(self, idx: int, item: dict, slot: str):
        async def callback(interaction: discord.Interaction):
            uid = str(interaction.user.id)
            if uid != self.uid:
                return await interaction.response.send_message("Not your shop / 不是你的商店", ephemeral=True)

            bal = _get_balance(uid) or 0
            if bal < item["price"]:
                return await interaction.response.send_message(
                    f"Insufficient coins! Need 🪙 {item['price']:,}, you have 🪙 {bal:,}\n金币不足！",
                    ephemeral=True,
                )

            try:
                item_id = f"eq_{slot}_{item['name'].split(' ')[0]}"
                with get_db_ctx() as conn:
                    conn.execute(
                        "INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING",
                        (uid,),
                    )
                    conn.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (-item["price"], uid))
                    conn.execute(
                        "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
                        (uid, -item["price"], f"Buy equipment / 购买装备: {item['name']}"),
                    )
                    # Check if user already owns this equipment
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT quantity FROM user_inventory WHERE user_id = ? AND item_id = ?",
                        (uid, item_id),
                    )
                    existing = cur.fetchone()
                    if existing:
                        conn.execute(
                            "UPDATE user_inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?",
                            (uid, item_id),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) "
                            "VALUES (?, ?, ?, 1, 'equipment')",
                            (uid, item_id, item['name']),
                        )
                    conn.commit()
                new_bal = _get_balance(uid) or 0
                # Quest progress
                from cogs.daily_quest import _update_progress
                _update_progress(uid, "buy")
                await interaction.response.send_message(
                    f"✅ Purchased / 已购买: {item['emoji']} **{item['name']}** for 🪙 {item['price']:,}\n"
                    f"Remaining / 余额: 🪙 {new_bal:,}",
                    ephemeral=True,
                )
            except Exception as e:
                logger.error(f"EquipmentShop buy error: {e}", exc_info=True)
                await interaction.response.send_message(f"❌ Purchase failed / 购买失败: {e}", ephemeral=True)

        return callback

    async def _prev_slot(self, interaction: discord.Interaction):
        self.active_slot_idx = (self.active_slot_idx - 1) % len(self.slots)
        self._rebuild_buttons()
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)

    async def _next_slot(self, interaction: discord.Interaction):
        self.active_slot_idx = (self.active_slot_idx + 1) % len(self.slots)
        self._rebuild_buttons()
        try:
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(), view=self)

    async def _back_to_hub(self, interaction: discord.Interaction):
        user_level = _get_user_level(self.uid)
        view = ShopHubView(self.uid, user_level, main_view=self.main_view)
        embed = discord.Embed(
            title="🏪 Shop / 商店",
            description="Choose a shop category!\n选择商店类型！",
            color=0xE67E22,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(PotionShop(bot))


# ══════════════════════════════════════════════════════════════
# EquipmentGachaView — Equipment Gacha / Lottery
# ══════════════════════════════════════════════════════════════
GACHA_POOL = {
    "weapon": [
        {"name": "新手木剑 Wooden Sword", "quality": "normal", "stat": "atk", "stat_value": 5, "emoji": "🗡️"},
        {"name": "猎人之弓 Hunter Bow", "quality": "normal", "stat": "atk", "stat_value": 7, "emoji": "🏹"},
        {"name": "魔法短杖 Magic Wand", "quality": "rare", "stat": "atk", "stat_value": 15, "emoji": "🪄"},
        {"name": "龙牙匕首 Dragon Fang Dagger", "quality": "epic", "stat": "atk", "stat_value": 25, "emoji": "🗡️"},
        {"name": "雷霆战斧 Thunder Axe", "quality": "legendary", "stat": "atk", "stat_value": 40, "emoji": "⚡"},
    ],
    "helmet": [
        {"name": "布帽 Cloth Cap", "quality": "normal", "stat": "hp", "stat_value": 8, "emoji": "🎩"},
        {"name": "鹿角盔 Antler Helm", "quality": "rare", "stat": "hp", "stat_value": 18, "emoji": "🦌"},
        {"name": "王冠 Crown of Kings", "quality": "epic", "stat": "hp", "stat_value": 30, "emoji": "👑"},
        {"name": "不死鸟之盔 Phoenix Crown", "quality": "legendary", "stat": "hp", "stat_value": 50, "emoji": "🔥"},
    ],
    "armor": [
        {"name": "布衣 Cloth Robe", "quality": "normal", "stat": "def", "stat_value": 5, "emoji": "👘"},
        {"name": "佣兵甲 Mercenary Plate", "quality": "rare", "stat": "def", "stat_value": 12, "emoji": "🛡️"},
        {"name": "龙鳞甲 Dragonscale Mail", "quality": "epic", "stat": "def", "stat_value": 22, "emoji": "🐉"},
        {"name": "暗影之铠 Shadow Plate", "quality": "legendary", "stat": "def", "stat_value": 35, "emoji": "🌑"},
    ],
    "leggings": [
        {"name": "粗麻裤 Hemp Pants", "quality": "normal", "stat": "def", "stat_value": 4, "emoji": "👖"},
        {"name": "暗影护腿 Shadow Greaves", "quality": "rare", "stat": "def", "stat_value": 10, "emoji": "👖"},
        {"name": "雷神护腿 Thunder Greaves", "quality": "epic", "stat": "def", "stat_value": 18, "emoji": "⚡"},
    ],
    "boots": [
        {"name": "草鞋 Straw Sandals", "quality": "normal", "stat": "spd", "stat_value": 4, "emoji": "👟"},
        {"name": "风行者之靴 Windstride Boots", "quality": "rare", "stat": "spd", "stat_value": 10, "emoji": "👢"},
        {"name": "影步之靴 Shadowstep Boots", "quality": "epic", "stat": "spd", "stat_value": 18, "emoji": "💨"},
        {"name": "光速靴 Lightspeed Boots", "quality": "legendary", "stat": "spd", "stat_value": 30, "emoji": "⚡"},
    ],
    "accessory": [
        {"name": "铜手镯 Copper Bangle", "quality": "normal", "stat": "crit", "stat_value": 3, "emoji": "💫"},
        {"name": "月光石 Moonstone", "quality": "rare", "stat": "crit", "stat_value": 8, "emoji": "🌙"},
        {"name": "贤者之石 Philosopher's Stone", "quality": "epic", "stat": "hp", "stat_value": 20, "emoji": "💎"},
        {"name": "命运之轮 Wheel of Fate", "quality": "legendary", "stat": "crit", "stat_value": 25, "emoji": "☸️"},
    ],
}

GACHA_QUALITY_WEIGHTS = {
    "normal": 60,
    "rare": 30,
    "epic": 9,
    "legendary": 1,
}

GACHA_SINGLE_COST = 100
GACHA_TEN_COST = 900
GACHA_TEN_GUARANTEED_RARE = True  # 10-pull guarantees at least 1 rare+


class EquipmentGachaView(discord.ui.View):
    """Equipment Gacha / Lottery View with single and 10-pull."""

    def __init__(self, uid: str, main_view: MMORPGMainView):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        bal = _get_balance(self.uid) or 0
        embed = discord.Embed(
            title="🎰 Equipment Gacha / 装备抽奖",
            description=(
                "试试手气，抽取随机装备！\nTest your luck for random equipment!\n\n"
                f"🎲 **Single Pull / 单抽**: 🪙 **{GACHA_SINGLE_COST:,}**\n"
                f"🎰 **10-Pull / 十连抽**: 🪙 **{GACHA_TEN_COST:,}** (guaranteed Rare+ / 保底稀有)\n\n"
                "Probability / 概率:\n"
                "⚪ Normal 普通 60%  |  🔵 Rare 稀有 30%\n"
                "🟣 Epic 史诗 9%  |  🟡 Legendary 传说 1%"
            ),
            color=0x9B59B6,
        )
        embed.set_footer(text=f"Your balance: 🪙 {bal:,}")
        return embed

    @discord.ui.button(label="🎲 Single Pull / 单抽", style=discord.ButtonStyle.primary, row=0)
    async def single_pull_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_pull(interaction, 1)

    @discord.ui.button(label="🎰 10-Pull / 十连抽", style=discord.ButtonStyle.danger, row=0)
    async def ten_pull_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_pull(interaction, 10)

    @discord.ui.button(label="↩ Back / 返回", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        embed = build_main_embed(uid, interaction.user.display_name)
        view = MMORPGMainView(uid, uname=interaction.user.display_name, interaction=interaction)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    async def _do_pull(self, interaction: discord.Interaction, count: int):
        uid = str(interaction.user.id)
        if uid != self.uid:
            return await interaction.response.send_message("Not your gacha / 不是你的抽奖", ephemeral=True)

        # Check balance
        cost = GACHA_TEN_COST if count == 10 else GACHA_SINGLE_COST
        bal = _get_balance(uid) or 0
        if bal < cost:
            return await interaction.response.send_message(
                f"Insufficient coins! Need 🪙 {cost:,}, you have 🪙 {bal:,}\n金币不足！",
                ephemeral=True,
            )

        # Deduct coins
        from cogs.economy import add_coins as _add_coins
        _add_coins(uid, -cost, f"装备抽奖{'十连' if count == 10 else '单抽'} / Equipment Gacha")

        # Roll items
        results = []
        guaranteed_hit = False
        for i in range(count):
            slot = random.choice(list(GACHA_POOL.keys()))
            quality = self._roll_quality()
            # 10-pull guarantee: if no rare+ after 9, force rare+ on 10th
            if count == 10 and i == 9 and not guaranteed_hit:
                quality = random.choice(["rare", "epic", "legendary"])
                quality = random.choices(["rare", "epic", "legendary"], weights=[80, 18, 2])[0]
            if quality in ("rare", "epic", "legendary"):
                guaranteed_hit = True

            pool_items = GACHA_POOL[slot]
            same_quality = [it for it in pool_items if it["quality"] == quality]
            if not same_quality:
                same_quality = [it for it in pool_items if it["quality"] == "normal"]
            item = random.choice(same_quality)
            results.append((slot, item))

        # Write to inventory
        with get_db_ctx() as conn:
            conn.execute(
                "INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING",
                (uid,),
            )
            for slot, item in results:
                conn.execute(
                    "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) "
                    "VALUES (?, ?, ?, 1, 'equipment')",
                    (uid, f"eq_gacha_{slot}_{item['name'].replace(' ', '_')}", item['name']),
                )
            conn.commit()

        # Animated frames
        uname = interaction.user.display_name
        total_frames = 4  # will be extended dynamically
        emoji_str = ""
        for slot, item in results:
            qe = QUALITY_EMOJI.get(item["quality"], "⚪")
            emoji_str += f"\n{item['emoji']} {qe} **{item['name']}** [{EQUIPMENT_SHOP_SLOT_LABELS.get(slot, slot)}]"

        new_bal = _get_balance(uid) or 0
        result_embed = discord.Embed(
            title=f"🎰 {'10-Pull' if count == 10 else 'Single Pull'} Results / 抽奖结果",
            description=(
                f"{uname} {'十连抽' if count == 10 else '单抽'}！\n"
                f"Cost / 花费: 🪙 **{cost:,}**\n"
                f"Remaining / 余额: 🪙 **{new_bal:,}**\n\n"
                f"**Results / 结果:**{emoji_str}"
            ),
            color=0x9B59B6,
        )

        frames = [
            f"🎰 {uname} 转动抽奖机...",
            f"💫 光芒闪耀！",
            f"✨ {'十连抽' if count == 10 else '单抽'} 结果揭晓！",
            f"🎁 {uname} 获得了新装备！",
        ]

        try:
            from utils.animations import play_animation
            await play_animation(interaction, frames, result_embed)
        except (ImportError, AttributeError):
            try:
                await interaction.response.edit_message(embed=result_embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=result_embed, view=self)

    @staticmethod
    def _roll_quality() -> str:
        roll = random.randint(1, 100)
        cumulative = 0
        for quality, weight in GACHA_QUALITY_WEIGHTS.items():
            cumulative += weight
            if roll <= cumulative:
                return quality
        return "normal"
