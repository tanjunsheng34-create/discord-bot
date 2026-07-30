"""
cogs/mmorpg_equipment.py — 装备系统 / Equipment System
Supports: Weapon(ATK) / Armor(DEF) / Helmet(HP) / Ring(Crit) / Accessory(SPD)
Qualities: ⚪ Normal / 🔵 Rare / 🟣 Epic / 🟡 Legendary
"""

import random
import logging
import discord
from discord import app_commands

from database import get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

EQUIP_SLOTS = ["weapon", "helmet", "armor", "leggings", "boots", "accessory"]
EQUIP_SLOT_LABELS_CN = {
    "weapon": "武器 Weapon",
    "helmet": "头盔 Helmet",
    "armor": "护甲 Armor",
    "leggings": "护腿 Leggings",
    "boots": "靴子 Boots",
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
    "helmet":     ["hp"],
    "armor":      ["def"],
    "leggings":   ["def"],
    "boots":      ["spd"],
    "accessory":  ["crit", "hp"],
}

BASE_NAMES = {
    "weapon": [
        ("生锈的铁剑 Rusty Sword", "atk"),
        ("短剑 Short Sword", "atk"),
        ("长剑 Longsword", "atk"),
        ("战斧 Battle Axe", "atk"),
        ("暗影之刃 Shadow Blade", "atk"),
        ("龙牙剑 Dragonfang Blade", "atk"),
        ("冰霜之剑 Frostbrand", "atk"),
    ],
    "helmet": [
        ("布帽 Cloth Cap", "hp"),
        ("铁盔 Iron Helmet", "hp"),
        ("秘银盔 Mithril Helm", "hp"),
        ("龙牙盔 Dragonfang Helm", "hp"),
        ("王冠 Crown", "hp"),
        ("暗影兜帽 Shadow Hood", "hp"),
        ("圣光头冠 Holy Circlet", "hp"),
    ],
    "armor": [
        ("皮甲 Leather Armor", "def"),
        ("锁子甲 Chainmail", "def"),
        ("板甲 Plate Armor", "def"),
        ("龙鳞甲 Dragonscale Armor", "def"),
        ("守护者铠甲 Guardian Plate", "def"),
        ("暗影斗篷 Shadow Mantle", "def"),
        ("圣骑士胸甲 Paladin Chestplate", "def"),
    ],
    "leggings": [
        ("布裤 Cloth Pants", "def"),
        ("皮裤 Leather Pants", "def"),
        ("锁子护腿 Chain Leggings", "def"),
        ("板甲护腿 Plate Greaves", "def"),
        ("龙鳞护腿 Dragonscale Greaves", "def"),
    ],
    "boots": [
        ("布靴 Cloth Boots", "spd"),
        ("皮靴 Leather Boots", "spd"),
        ("铁靴 Iron Boots", "spd"),
        ("暗影之靴 Shadow Boots", "spd"),
        ("疾风之靴 Wind Walkers", "spd"),
    ],
    "accessory": [
        ("铜戒 Copper Ring", "crit"),
        ("银戒 Silver Ring", "crit"),
        ("红宝石戒 Ruby Ring", "crit"),
        ("钻石戒 Diamond Ring", "crit"),
        ("命运之戒 Ring of Fate", "crit"),
        ("翡翠项链 Jade Amulet", "hp"),
        ("凤凰羽毛 Phoenix Feather", "spd"),
        ("力量护符 Amulet of Power", "atk"),
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

    def __init__(self, uid_or_guild, user_id: str = None, user_name: str = None, main_view=None):
        super().__init__(timeout=180)
        # Support two calling conventions:
        # 1. New: EquipmentView(uid, main_view=mv)
        # 2. Old: EquipmentView(guild, uid, uname)
        if isinstance(user_id, str):
            # Old style: (guild, uid_str, uname_str)
            self.uid = user_id
            self.uname = user_name
            self.main_view = main_view
            self.guild = uid_or_guild
        else:
            # New style: (uid_str, main_view=view_obj)
            self.uid = str(uid_or_guild)
            self.uname = None
            self.guild = None
            # When called as EquipmentView(uid, main_view=mv), user_id receives the main_view
            self.main_view = user_id if user_id is not None else main_view
        self._build()

    def build_main_embed(self):
        equipped = _get_equipped(self.uid)
        total_stats = _get_equip_stats(self.uid)
        embed = discord.Embed(
            title="⚔️ 装备面板 / Equipment Panel",
            description="点击下方槽位按钮查看装备详情 / Click a slot button to view equipment",
            color=0xE67E22,
        )
        for slot in EQUIP_SLOTS:
            eq = equipped.get(slot)
            if eq:
                q = QUALITIES.get(eq["quality"], QUALITIES["normal"])
                embed.add_field(
                    name=f"{eq['emoji'] if eq.get('emoji') else q['label'].split()[0]} {EQUIP_SLOT_LABELS_CN[slot]}",
                    value=f"{eq['name']}\n+{eq['stat_value']} {eq['stat'].upper()}",
                    inline=True,
                )
            else:
                embed.add_field(
                    name=f"⬜ {EQUIP_SLOT_LABELS_CN[slot]}",
                    value="未装备 / Empty",
                    inline=True,
                )
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        stats_text = f"ATK:{total_stats['atk']} DEF:{total_stats['def']} HP:{total_stats['hp']} Crit:{total_stats['crit']} SPD:{total_stats['spd']}"
        embed.set_footer(text=f"Total Stats: {stats_text}")
        return embed

    def _build(self):
        self.clear_items()
        equipped = _get_equipped(self.uid)

        for i, slot in enumerate(EQUIP_SLOTS):
            eq = equipped.get(slot)
            if eq:
                lvl = eq.get('enhance_level', 0)
                label = f"{eq['emoji']} {EQUIP_SLOT_LABELS_CN[slot]} +{lvl}"[:80]
            else:
                label = f"⬜ {EQUIP_SLOT_LABELS_CN[slot]}"
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary if eq else discord.ButtonStyle.primary,
                row=i // 3,  # 3 per row: row 0 = weapon/helmet/armor, row 1 = leggings/boots/accessory
                custom_id=f"eq_slot_{slot}",
            )
            btn.callback = self._make_slot_callback(slot)
            self.add_item(btn)

        # Equip + Enhance + Back on row 2 (3 buttons)
        equip_btn = discord.ui.Button(
            label="Equip 装备", emoji="⚔️",
            style=discord.ButtonStyle.primary, row=2,
            custom_id="eq_equip",
        )
        equip_btn.callback = self._equip_callback
        self.add_item(equip_btn)

        enhance_btn = discord.ui.Button(
            label="Enhance 强化", emoji="🔨",
            style=discord.ButtonStyle.success, row=2,
            custom_id="eq_enhance",
        )
        enhance_btn.callback = self._enhance_callback
        self.add_item(enhance_btn)

        if self.main_view:
            back_btn = discord.ui.Button(
                label="Back to MMORPG / 返回", style=discord.ButtonStyle.danger,
                row=2, emoji="🏠", custom_id="eq_back",
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    async def _equip_callback(self, interaction: discord.Interaction):
        """Show inventory equipment list to equip."""
        try:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT item_id, item_name, quantity FROM user_inventory"
                    " WHERE user_id = ? AND item_type = 'equipment' AND quantity > 0"
                    " ORDER BY item_name",
                    (self.uid,),
                )
                rows = cur.fetchall()

            if not rows:
                return await interaction.response.send_message(
                    "背包中没有可装备的装备！/ No equippable items in inventory!", ephemeral=True)

            # Build select options
            options = []
            for row in rows:
                name = row["item_name"][:100]
                qty = row["quantity"]
                # Parse quality prefix for emoji
                emoji = "⚪"
                if "legendary" in name.lower():
                    emoji = "🟡"
                elif "epic" in name.lower():
                    emoji = "🟣"
                elif "rare" in name.lower():
                    emoji = "🔵"
                options.append(discord.SelectOption(
                    label=name,
                    value=row["item_name"],
                    description=f"x{qty} | {emoji}",
                    emoji=emoji,
                ))

            view = EquipSelectView(self.uid, self)
            select = discord.ui.Select(
                placeholder="选择要装备的装备 / Select equipment to equip",
                options=options[:25],  # Discord limit
                row=0,
            )
            select.callback = view._select_callback
            view.add_item(select)
            await interaction.response.send_message(
                "选择要装备的装备 / Select equipment to equip：",
                view=view,
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Equip callback error (uid={self.uid}): {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "加载装备列表出错 / Error loading equipment list", ephemeral=True)
            except Exception:
                pass

    async def _enhance_callback(self, interaction: discord.Interaction):
        """Handle equipment enhancement."""
        try:
            equipped = _get_equipped(self.uid)
            if not equipped:
                return await interaction.response.send_message(
                    "No equipment to enhance / 没有可强化的装备！", ephemeral=True)

            # Show slot selection
            options = []
            for slot in EQUIP_SLOTS:
                eq = equipped.get(slot)
                if eq:
                    lvl = eq.get('enhance_level', 0)
                    if lvl >= 15:
                        options.append(discord.SelectOption(
                            label=f"{EQUIP_SLOT_LABELS_CN[slot]} +{lvl} (MAX)",
                            value=slot,
                            description="Already max level / 已达最大等级",
                            emoji="✅",
                        ))
                    else:
                        cost = _get_enhance_cost(lvl)
                        rate = _get_enhance_rate(lvl)
                        options.append(discord.SelectOption(
                            label=f"{EQUIP_SLOT_LABELS_CN[slot]} +{lvl} → +{lvl+1}",
                            value=slot,
                            description=f"Cost: {cost}G | Rate: {int(rate*100)}%",
                            emoji="🔨",
                        ))

            if not options:
                return await interaction.response.send_message(
                    "No equipment to enhance / 没有可强化的装备！", ephemeral=True)

            view = EnhanceSelectView(self.uid, equipped, self)
            select = discord.ui.Select(
                placeholder="Select equipment to enhance / 选择要强化的装备",
                options=options,
                row=0,
            )
            select.callback = view._select_callback
            view.add_item(select)
            await interaction.response.send_message(
                "Choose equipment to enhance / 选择要强化的装备：",
                view=view,
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Enhance callback error (uid={self.uid}): {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "Error loading enhancement panel / 加载强化面板出错", ephemeral=True)
            except Exception:
                pass

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import _get_user_stats, _get_balance
            uid = str(self.uid)
            stats = _get_user_stats(uid)
            bal = _get_balance(uid)
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
        lvl = eq.get("enhance_level", 0)
        base_stat = int(eq["stat_value"] / (1 + lvl * 0.1)) if lvl > 0 else eq["stat_value"]
        enhance_bonus = eq["stat_value"] - base_stat

        desc = (
            f"**{eq['stat'].upper()}**: +{eq['stat_value']}\n"
            f"**槽位 Slot**: {EQUIP_SLOT_LABELS_CN[slot]}\n"
            f"**强化 Enhance**: +{lvl}"
        )
        if enhance_bonus > 0:
            desc += f" (Base: +{base_stat} + Bonus: +{enhance_bonus})"

        embed = discord.Embed(
            title=f"{q['label']} | {eq['name']} +{lvl}",
            description=desc,
            color=q["color"],
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class EnhanceSelectView(discord.ui.View):
    """Select dropdown for enhancement target."""

    def __init__(self, uid: str, equipped: dict, eq_view):
        super().__init__(timeout=60)
        self.uid = uid
        self.equipped = equipped
        self.eq_view = eq_view

    async def _select_callback(self, interaction: discord.Interaction):
        deducted = False
        cost = 0
        reason = ""
        try:
            slot = interaction.data["values"][0]
            eq = self.equipped.get(slot)
            if not eq:
                return await interaction.response.send_message("Not equipped / 未装备", ephemeral=True)

            lvl = eq.get("enhance_level", 0)
            if lvl >= 15:
                return await interaction.response.send_message(
                    "Already max level +15 / 已达最大强化等级！", ephemeral=True)

            cost = _get_enhance_cost(lvl)
            rate = _get_enhance_rate(lvl)

            from cogs.mmorpg_shop import _get_balance as _bal, _add_coins
            bal = _bal(self.uid)
            if bal < cost:
                return await interaction.response.send_message(
                    f"Insufficient coins / 金币不足！Need {cost:,}, you have {bal:,}", ephemeral=True)

            # Deduct coins
            reason = f"Enhance {eq['name']} +{lvl}→+{lvl+1}"
            _add_coins(self.uid, -cost, reason)
            deducted = True

            import random, asyncio

            # Try enhancement with animation
            success = random.random() < rate
            if success:
                new_lvl = lvl + 1
                new_stat = int(eq["stat_value"] * (1 + 0.1) / (1 + lvl * 0.1) * (1 + new_lvl * 0.1))
            else:
                if lvl <= 5:
                    new_lvl = lvl  # No drop
                elif lvl <= 10:
                    new_lvl = max(0, lvl - 1)
                else:
                    new_lvl = max(0, lvl - 3)
                if new_lvl == lvl:
                    new_stat = eq["stat_value"]
                else:
                    new_stat = int(eq["stat_value"] * (1 + new_lvl * 0.1) / (1 + lvl * 0.1))

            # Animation
            await enhance_animation(interaction, lvl, new_lvl, success)

            # Update DB
            with get_db_ctx() as conn:
                conn.execute(
                    "UPDATE user_equipment SET enhance_level = ?, stat_value = ? WHERE user_id = ? AND slot = ?",
                    (new_lvl, new_stat, self.uid, slot),
                )
                conn.commit()

            new_bal = _bal(self.uid)
            if success:
                msg = (
                    f"## \u2728 Enhancement Success / \u5f3a\u5316\u6210\u529f\uff01\n"
                    f"**{eq['name']}**: +{lvl} \u2192 **+{new_lvl}**\n"
                    f"STAT: {eq['stat_value']} \u2192 **{new_stat}**\n"
                    f"Cost / \u82b1\u8d39: {cost:,}G  |  Balance / \u4f59\u989d: **{new_bal:,}**"
                )
            else:
                if new_lvl < lvl:
                    msg = (
                        f"## \U0001f4a5 Enhancement Failed / \u5f3a\u5316\u5931\u8d25\uff01\n"
                        f"**{eq['name']}**: +{lvl} \u2192 **+{new_lvl}** (Dropped / \u964d\u7ea7)\n"
                        f"Cost / \u82b1\u8d39: {cost:,}G  |  Balance / \u4f59\u989d: **{new_bal:,}**"
                    )
                else:
                    msg = (
                        f"## \U0001f4a5 Enhancement Failed / \u5f3a\u5316\u5931\u8d25\uff01\n"
                        f"**{eq['name']}**: +{lvl} (No change / \u4e0d\u53d8)\n"
                        f"Cost / \u82b1\u8d39: {cost:,}G  |  Balance / \u4f59\u989d: **{new_bal:,}**"
                    )

            await interaction.followup.send(msg, ephemeral=True)

            # Refresh the equipment view
            self.eq_view._build()
            try:
                await interaction.edit_original_response(embed=self.eq_view.build_main_embed(), view=self.eq_view)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Enhance _select_callback error (uid={self.uid}): {e}", exc_info=True)
            if deducted:
                try:
                    _add_coins(self.uid, cost, f"Refund: {reason}")
                    logger.info(f"Refunded {cost} to {self.uid} after enhance failure")
                except Exception as re:
                    logger.error(f"Refund failed for {self.uid}: {re}")
            try:
                await interaction.response.send_message(
                    "Enhancement failed due to an error. Any deducted coins have been refunded. / 强化出错，已退还金币。",
                    ephemeral=True,
                )
            except Exception:
                pass


def _get_equipped(user_id: str) -> dict:
    """Return {slot: {emoji, name, quality, stat, stat_value, enhance_level}, ...}."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT slot, name, quality, stat, stat_value, enhance_level, emoji FROM user_equipment WHERE user_id=?",
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
            "enhance_level": r["enhance_level"] or 0,
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
        # Parse slot from item_id (format: eq_{slot}_{name})
        slot = None
        item_id = row["item_id"]
        if item_id.startswith("eq_"):
            parts = item_id.split("_", 2)
            if len(parts) >= 2:
                candidate = parts[1]
                if candidate in EQUIP_SLOTS:
                    slot = candidate
        if not slot:
            # Fallback: parse from item_name for backward compat
            for s in EQUIP_SLOTS:
                if s in row["item_name"].lower():
                    slot = s
                    break
        if not slot:
            logger.error(f"_equip_item: cannot determine slot for item_id={item_id} item_name={row['item_name']}")
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
                enhance_level INTEGER DEFAULT 0,
                emoji TEXT DEFAULT '',
                PRIMARY KEY (user_id, slot)
            )
        """)
        # Add enhance_level column if upgrading from old schema
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(user_equipment)")
        cols = {r["name"] for r in cur.fetchall()}
        if "enhance_level" not in cols:
            cur.execute("ALTER TABLE user_equipment ADD COLUMN enhance_level INTEGER DEFAULT 0")
        conn.commit()

ENHANCE_RATES = {
    (0, 1): 1.00, (1, 2): 1.00, (2, 3): 0.95, (3, 4): 0.90, (4, 5): 0.85,
    (5, 6): 0.70, (6, 7): 0.60, (7, 8): 0.50, (8, 9): 0.45, (9, 10): 0.40,
    (10, 11): 0.40, (11, 12): 0.30, (12, 13): 0.25, (13, 14): 0.20, (14, 15): 0.15,
}

ENHANCE_COSTS = {
    1: 200, 2: 400, 3: 600, 4: 800, 5: 1000,
    6: 1500, 7: 2000, 8: 3000, 9: 4000, 10: 5000,
    11: 8000, 12: 12000, 13: 18000, 14: 25000, 15: 40000,
}


def _get_enhance_rate(from_level: int) -> float:
    """Get success rate for enhancing from a given level to the next."""
    to_level = from_level + 1
    return ENHANCE_RATES.get((from_level, to_level), 0.15)


def _get_enhance_cost(from_level: int) -> int:
    """Get cost to enhance from a given level."""
    to_level = from_level + 1
    return ENHANCE_COSTS.get(to_level, 50000)


async def enhance_animation(interaction, level_before: int, level_after: int, success: bool):
    """Animate the enhancement process. Returns the interaction with the original response edited to the final result."""
    import asyncio
    try:
        await interaction.response.send_message(
            f"🔨 Enhancing... **+{level_before}** → 🔨...",
            ephemeral=True,
        )
        await asyncio.sleep(0.6)
        await interaction.edit_original_response(content=f"🔨 Enhancing... **+{level_before}** → ✨...")
        await asyncio.sleep(0.6)
        if success:
            await interaction.edit_original_response(content=f"✨ Enhancement success! **+{level_before}** → **+{level_after}** ✨")
        else:
            if level_after < level_before:
                await interaction.edit_original_response(content=f"💥 Enhancement failed! **+{level_before}** → **+{level_after}** (dropped)")
            else:
                await interaction.edit_original_response(content=f"💥 Enhancement failed! Stayed at **+{level_before}**")
        await asyncio.sleep(1.0)
    except Exception:
        pass


class MMORPGEquipment(CogBase):
    """装备系统 / Equipment System"""

    def __init__(self, bot):
        super().__init__()
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


class EquipSelectView(discord.ui.View):
    """Select view for equipping items from inventory."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=60)
        self.uid = uid
        self.main_view = main_view

    async def _select_callback(self, interaction: discord.Interaction):
        item_name = interaction.data["values"][0]
        try:
            success = _equip_item(self.uid, item_name)
            if success:
                await interaction.response.edit_message(
                    content=f"装备成功！/ Equipped: **{item_name}**",
                    view=None,
                )
            else:
                await interaction.response.send_message(
                    "装备失败 / Equip failed", ephemeral=True
                )
        except Exception as e:
            logger.error(
                f"EquipSelectView error (uid={self.uid}): {e}", exc_info=True
            )
            try:
                await interaction.response.send_message(
                    "装备过程出错 / Error during equip", ephemeral=True
                )
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(MMORPGEquipment(bot))
