"""
cogs/mmorpg_equipment.py — 装备系统 / Equipment System
Supports: Weapon(ATK) / Armor(DEF) / Helmet(HP) / Ring(Crit) / Accessory(SPD)
Qualities: ⚪ Normal / 🔵 Rare / 🟣 Epic / 🟡 Legendary
"""

import random
import discord
from discord import app_commands

from database import get_db_ctx
from utils.helpers import CogBase, ensure_user

EQUIP_SLOTS = ["weapon", "armor", "helmet", "ring", "accessory"]
EQUIP_SLOT_LABELS_CN = {
    "weapon": "武器 Weapon",
    "armor": "护甲 Armor",
    "helmet": "头盔 Helmet",
    "ring": "戒指 Ring",
    "accessory": "饰品 Accessory",
}

QUALITIES = {
    "normal":    {"label": "⚪ 普通 Normal",    "mult": 1.0, "color": 0x95A5A6},
    "rare":      {"label": "🔵 稀有 Rare",      "mult": 1.3, "color": 0x3498DB},
    "epic":      {"label": "🟣 史诗 Epic",      "mult": 1.6, "color": 0x9B59B6},
    "legendary": {"label": "🟡 传说 Legendary",  "mult": 2.0, "color": 0xF1C40F},
}

QUALITY_WEIGHTS = [0.55, 0.30, 0.12, 0.03]  # normal, rare, epic, legendary

SLOT_STATS = {
    "weapon":     ["atk"],
    "armor":      ["def"],
    "helmet":     ["hp"],
    "ring":       ["crit"],
    "accessory":  ["spd"],
}

BASE_NAMES = {
    "weapon": [
        ("生锈的铁剑 Rusty Sword", "atk"),
        ("短剑 Short Sword", "atk"),
        ("长剑 Longsword", "atk"),
        ("战斧 Battle Axe", "atk"),
        ("暗影之刃 Shadow Blade", "atk"),
    ],
    "armor": [
        ("皮甲 Leather Armor", "def"),
        ("锁子甲 Chainmail", "def"),
        ("板甲 Plate Armor", "def"),
        ("龙鳞甲 Dragonscale Armor", "def"),
        ("守护者铠甲 Guardian Plate", "def"),
    ],
    "helmet": [
        ("布帽 Cloth Cap", "hp"),
        ("铁盔 Iron Helmet", "hp"),
        ("秘银盔 Mithril Helm", "hp"),
        ("龙牙盔 Dragonfang Helm", "hp"),
        ("王冠 Crown", "hp"),
    ],
    "ring": [
        ("铜戒 Copper Ring", "crit"),
        ("银戒 Silver Ring", "crit"),
        ("红宝石戒 Ruby Ring", "crit"),
        ("钻石戒 Diamond Ring", "crit"),
        ("命运之戒 Ring of Fate", "crit"),
    ],
    "accessory": [
        ("布腰带 Cloth Belt", "spd"),
        ("皮革披风 Leather Cloak", "spd"),
        ("鹰翼披风 Eaglewing Cloak", "spd"),
        ("疾风之靴 Wind Boots", "spd"),
        ("凤凰羽毛 Phoenix Feather", "spd"),
    ],
}


def _roll_equipment(slot: str, min_level: int = 1) -> dict:
    """Generate a random equipment piece for the given slot."""
    quality_key = random.choices(list(QUALITIES.keys()), weights=QUALITY_WEIGHTS, k=1)[0]
    base_name, stat_key = random.choice(BASE_NAMES[slot])
    quality = QUALITIES[quality_key]
    base_stat = random.randint(5 + min_level * 2, 15 + min_level * 5)
    stat_value = int(base_stat * quality["mult"])

    return {
        "slot": slot,
        "name": base_name,
        "quality": quality_key,
        "quality_label": quality["label"],
        "stat": stat_key,
        "stat_value": stat_value,
        "color": quality["color"],
    }


class EquipmentView(discord.ui.View):
    """装备面板 / Equipment panel with slot buttons."""

    def __init__(self, guild, user_id: str, user_name: str):
        super().__init__(timeout=180)
        self.guild = guild
        self.uid = user_id
        self.uname = user_name
        self._build()

    def _build(self):
        self.clear_items()
        equipped = _get_equipped(self.uid)

        for slot in EQUIP_SLOTS:
            eq = equipped.get(slot)
            if eq:
                label = f"{eq['emoji']} {EQUIP_SLOT_LABELS_CN[slot]}"
            else:
                label = f"⬜ {EQUIP_SLOT_LABELS_CN[slot]}"
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary if eq else discord.ButtonStyle.primary,
                row=0,
                custom_id=f"eq_slot_{slot}",
            )
            btn.callback = self._make_slot_callback(slot)
            self.add_item(btn)

    def _make_slot_callback(self, slot: str):
        async def cb(interaction: discord.Interaction):
            await self._show_slot(interaction, slot)
        return cb

    async def _show_slot(self, interaction: discord.Interaction, slot: str):
        equipped = _get_equipped(self.uid)
        eq = equipped.get(slot)
        if not eq:
            await interaction.response.send_message(
                f"⬜ **{EQUIP_SLOT_LABELS_CN[slot]}** — 未装备 / Not equipped",
                ephemeral=True,
            )
            return

        q = QUALITIES.get(eq["quality"], QUALITIES["normal"])
        embed = discord.Embed(
            title=f"{q['label']} | {eq['name']}",
            description=(
                f"**{eq['stat'].upper()}**: +{eq['stat_value']}\n"
                f"**槽位 Slot**: {EQUIP_SLOT_LABELS_CN[slot]}"
            ),
            color=q["color"],
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def _get_equipped(user_id: str) -> dict:
    """Return {slot: {emoji, name, quality, stat, stat_value}, ...}."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT slot, name, quality, stat, stat_value, emoji FROM user_equipment WHERE user_id=?",
            (user_id,),
        )
        rows = cur.fetchall()
    result = {}
    for r in rows:
        result[r["slot"]] = {
            "name": r["name"],
            "quality": r["quality"],
            "stat": r["stat"],
            "stat_value": r["stat_value"],
            "emoji": r["emoji"],
        }
    return result


def _get_equip_stats(user_id: str) -> dict:
    """Get total stats from equipment: {atk, def, hp, crit, spd}."""
    stats = {"atk": 0, "def": 0, "hp": 0, "crit": 0, "spd": 0}
    equipped = _get_equipped(user_id)
    for eq in equipped.values():
        stat_name = eq["stat"]
        if stat_name in stats:
            stats[stat_name] += eq["stat_value"]
    return stats


def _equip_item(user_id: str, item_name: str) -> bool:
    """Equip an item from inventory. Returns True if successful."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        # Find the item in inventory
        cur.execute(
            "SELECT item_id, item_name, item_type, quantity FROM user_inventory WHERE user_id=? AND item_name LIKE ?",
            (user_id, f"%{item_name}%"),
        )
        rows = cur.fetchall()
        if not rows:
            return False
        row = rows[0]
        # Parse slot from item_name
        name_parts = row["item_name"].split()
        slot = None
        for s in EQUIP_SLOTS:
            if s in row["item_name"].lower():
                slot = s
                break
        if not slot:
            return False

        # Consume 1 from inventory
        if row["quantity"] <= 1:
            cur.execute("DELETE FROM user_inventory WHERE item_id=?", (row["item_id"],))
        else:
            cur.execute("UPDATE user_inventory SET quantity=quantity-1 WHERE item_id=?", (row["item_id"],))

        # Unequip old and equip new
        cur.execute("DELETE FROM user_equipment WHERE user_id=? AND slot=?", (user_id, slot))
        quality, stat_val = _parse_equip_quality(row["item_name"])
        stat_type = SLOT_STATS.get(slot, ["atk"])[0]
        cur.execute(
            "INSERT INTO user_equipment (user_id, slot, name, quality, stat, stat_value, emoji) VALUES (?,?,?,?,?,?,?)",
            (user_id, slot, row["item_name"], quality, stat_type, stat_val, ""),
        )
        conn.commit()
    return True


def _parse_equip_quality(name: str):
    """Parse quality and stat value from equipment name."""
    for qk in ["legendary", "epic", "rare"]:
        if qk in name.lower():
            return qk, random.randint(10, 30) * QUALITIES[qk]["mult"]
    return "normal", random.randint(5, 15)


# ── Init DB table ──
def _init_equipment_db():
    with get_db_ctx() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_equipment (
                user_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                name TEXT,
                quality TEXT DEFAULT 'normal',
                stat TEXT,
                stat_value INTEGER DEFAULT 0,
                emoji TEXT DEFAULT '',
                PRIMARY KEY (user_id, slot)
            )
        """)
        conn.commit()


class MMORPGEquipment(CogBase):
    """装备系统 / Equipment System"""

    def __init__(self, bot):
        super().__init__(bot)
        _init_equipment_db()

    @app_commands.command(name="gmpt-equipment", description="⚔️ 装备面板 / Equipment panel")
    async def equipment_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        uname = interaction.user.display_name
        equipped = _get_equipped(uid)
        total_stats = _get_equip_stats(uid)

        embed = discord.Embed(
            title=f"⚔️ {uname} 的装备 / Equipment",
            description="点击下方按钮查看各槽位装备详情 / Click buttons to view each slot",
            color=0xE67E22,
        )
        for slot in EQUIP_SLOTS:
            eq = equipped.get(slot)
            if eq:
                q = QUALITIES.get(eq["quality"], QUALITIES["normal"])
                val = f"{q['label'].split()[0]} **{eq['name']}** (+{eq['stat_value']} {eq['stat'].upper()})"
            else:
                val = "⬜ 空 / Empty"
            embed.add_field(
                name=EQUIP_SLOT_LABELS_CN[slot],
                value=val,
                inline=True,
            )

        # Total stats
        stats_text = (
            f"⚔️ ATK: +{total_stats['atk']}  |  🛡️ DEF: +{total_stats['def']}  |  ❤️ HP: +{total_stats['hp']}\n"
            f"💥 Crit: +{total_stats['crit']}%  |  💨 SPD: +{total_stats['spd']}"
        )
        embed.add_field(name="📊 总属性加成 / Total Stats", value=stats_text, inline=False)

        view = EquipmentView(interaction.guild, uid, uname)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(MMORPGEquipment(bot))
