
"""
cogs/mmorpg_equipment.py — 装备系统 / Equipment System
Supports: Weapon(ATK) / Helmet(DEF) / Armor(DEF) / Leggings(HP) / Boots(HP) / Accessory(CRIT+HP)
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
    "common":    {"label": "⚪ 普通 Common",    "mult": 1.0, "color": 0x95A5A6},
    "rare":      {"label": "🔵 稀有 Rare",      "mult": 1.3, "color": 0x3498DB},
    "epic":      {"label": "🟣 史诗 Epic",      "mult": 1.6, "color": 0x9B59B6},
    "legendary": {"label": "🟡 传说 Legendary",  "mult": 2.0, "color": 0xF1C40F},
}

QUALITY_WEIGHTS = [0.55, 0.30, 0.12, 0.03]  # common, rare, epic, legendary

SLOT_STATS = {
    "weapon":     ["atk"],
    "helmet":     ["def"],
    "armor":      ["def"],
    "leggings":   ["hp"],
    "boots":      ["hp"],
    "accessory":  ["crit", "hp"],
}

# ══════════════════════════════════════════════════════════════
# BASE_NAMES — LOL Equipment Pool (used by _roll_equipment)
# ══════════════════════════════════════════════════════════════
BASE_NAMES = {
    "weapon": [
        ("多兰之刃 Doran's Blade", "atk"),
        ("长剑 Long Sword", "atk"),
        ("暴风之剑 B.F. Sword", "atk"),
        ("无尽之刃 Infinity Edge", "atk"),
        ("饮血剑 Bloodthirster", "atk"),
        ("三相之力 Trinity Force", "atk"),
        ("神圣分离者 Divine Sunderer", "atk"),
        ("暮刃 Duskblade", "atk"),
        ("幽梦之灵 Youmuu's Ghostblade", "atk"),
        ("破败王者之刃 Blade of the Ruined King", "atk"),
    ],
    "helmet": [
        ("抗魔斗篷 Null-Magic Mantle", "def"),
        ("布甲 Cloth Armor", "def"),
        ("负极斗篷 Negatron Cloak", "def"),
        ("振奋盔甲 Spirit Visage", "def"),
        ("灭世者的死亡之帽 Rabadon's Deathcap", "def"),
        ("适应性头盔 Adaptive Helm", "def"),
        ("兰顿之兆 Randuin's Omen", "def"),
        ("深渊面具 Abyssal Mask", "def"),
        ("女妖面纱 Banshee's Veil", "def"),
    ],
    "armor": [
        ("锁子甲 Chain Vest", "def"),
        ("守望者铠甲 Warden's Mail", "def"),
        ("日炎斗篷 Sunfire Cape", "def"),
        ("荆棘之甲 Thornmail", "def"),
        ("亡者的板甲 Dead Man's Plate", "def"),
        ("冰霜之心 Frozen Heart", "def"),
        ("狂徒铠甲 Warmog's Armor", "def"),
        ("石像鬼石板甲 Gargoyle Stoneplate", "def"),
        ("守护天使 Guardian Angel", "def"),
    ],
    "leggings": [
        ("草鞋 Boots of Speed", "hp"),
        ("水银之靴 Mercury's Treads", "hp"),
        ("忍者足具 Ninja Tabi", "hp"),
        ("狂战士胫甲 Berserker's Greaves", "hp"),
        ("明朗之靴 Ionian Boots", "hp"),
        ("轻灵之靴 Boots of Swiftness", "hp"),
        ("铁板靴 Plated Steelcaps", "hp"),
        ("法穿鞋 Sorcerer's Shoes", "hp"),
    ],
    "boots": [
        ("速度之靴 Boots", "hp"),
        ("疾行之靴 Boots of Mobility", "hp"),
        ("明朗之靴 Cosmic Drive", "hp"),
        ("幽梦之靴 Youmuu's Greaves", "hp"),
        ("无尽之靴 Infinity Treads", "hp"),
        ("暗行者之靴 Prowler's Greaves", "hp"),
        ("风暴之靴 Stormrazor Boots", "hp"),
        ("神谕之靴 Oracle's Greaves", "hp"),
    ],
    "accessory": [
        ("暴击手套 Brawler's Gloves", "crit"),
        ("灵巧披风 Cloak of Agility", "crit"),
        ("狂热 Zeal", "crit"),
        ("幻影之舞 Phantom Dancer", "crit"),
        ("斯塔缇克电刃 Statikk Shiv", "crit"),
        ("卢安娜的飓风 Runaan's Hurricane", "crit"),
        ("水银饰带 Quicksilver Sash", "crit"),
        ("中娅沙漏 Zhonya's Hourglass", "crit"),
        ("破败王者之刃 Blade of the Ruined King", "crit"),
        ("界弓 The Collector", "crit"),
    ],
}

# ── Legendary-only equipment (only rolls as legendary quality) ──
LEGENDARY_ONLY = {
    "weapon": [
        ("诸神黄昏 Ragnarok", "atk"),
    ],
    "helmet": [
        ("全知者之冠 Crown of Omniscience", "def"),
    ],
    "armor": [
        ("创世神之铠 Aegis of Creation", "def"),
    ],
    "leggings": [
        ("终末护腿 Leggings of Finality", "hp"),
    ],
    "boots": [
        ("光速行者 Lightspeed Strider", "hp"),
    ],
    "accessory": [
        ("创世之心 Heart of Genesis", "crit"),
    ],
}


def _strip_stat_suffix(item_name: str) -> str:
    """Strip |||stat:value|||quality suffix from item_name for display."""
    if "|||" in item_name:
        return item_name.split("|||")[0]
    if "|" in item_name:
        return item_name.split("|")[0]
    return item_name


def _parse_item_name(item_name: str):
    """Parse item_name in format 'Name|||stat1:val1,stat2:val2|||quality'.
    Returns (clean_name, stat_str, stat_value_str, quality).
    For legacy items without |||, returns (item_name, 'atk', '5', 'common').
    """
    if "|||" not in item_name:
        logger.warning(f"_parse_item_name: legacy item_name (no pipe): {item_name}")
        return item_name, "atk", "5", "common"

    parts = item_name.split("|||")
    if len(parts) < 3:
        logger.warning(f"_parse_item_name: malformed item_name: {item_name}")
        return parts[0], "atk", "5", "common"

    clean_name = parts[0]
    stat_part = parts[1]   # "atk:10" or "crit:20,hp:20"
    quality = parts[2]

    # Parse stat:value pairs
    stat_keys = []
    stat_vals = []
    for pair in stat_part.split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            stat_keys.append(k.strip())
            stat_vals.append(v.strip())

    if not stat_keys:
        return clean_name, "atk", "5", quality

    return clean_name, ",".join(stat_keys), ",".join(stat_vals), quality


def _resolve_slot(item_id: str, item_name: str) -> str:
    """Resolve equipment slot from item_id prefix or fallback to item_name matching."""
    slot = None
    if item_id.startswith("eq_"):
        parts = item_id.split("_", 2)
        if len(parts) >= 2 and parts[1] in EQUIP_SLOTS:
            slot = parts[1]
    if not slot:
        name_lower = item_name.lower()
        for s in EQUIP_SLOTS:
            if s in name_lower:
                slot = s
                break
    return slot


def _roll_equipment(slot: str, min_level: int = 1) -> dict:
    """Generate a random equipment piece for the given slot."""
    quality_key = random.choices(list(QUALITIES.keys()), weights=QUALITY_WEIGHTS, k=1)[0]

    # Legendary quality: 60% chance to pick from LEGENDARY_ONLY pool
    if quality_key == "legendary" and slot in LEGENDARY_ONLY and random.random() < 0.6:
        base_name, stat_key = random.choice(LEGENDARY_ONLY[slot])
    else:
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
        super().__init__(timeout=600)
        if isinstance(user_id, str):
            self.uid = user_id
            self.uname = user_name
            self.main_view = main_view
            self.guild = uid_or_guild
        else:
            self.uid = str(uid_or_guild)
            self.uname = None
            self.guild = None
            self.main_view = user_id if user_id is not None else main_view
        self._build()

    def build_main_embed(self):
        equipped = _get_equipped(self.uid)
        total_stats = _get_equip_stats(self.uid)

        embed = discord.Embed(
            title="⚔️ 装备面板 / Equipment Panel",
            description=(
                f"ATK: **{total_stats['atk']}** | "
                f"DEF: **{total_stats['def']}** | "
                f"HP: **{total_stats['hp']}** | "
                f"Crit: **{total_stats['crit']}%** | "
                f"SPD: **{total_stats['spd']}**"
            ),
            color=0xF39C12,
        )

        SLOT_EMOJIS = {
            "weapon": "⚔️", "helmet": "🪖", "armor": "🛡️",
            "leggings": "👖", "boots": "👢", "accessory": "💍",
        }
        QUALITY_COLORS = {
            "common": "⚪", "rare": "🔵", "epic": "🟣", "legendary": "🟡",
        }

        for slot in EQUIP_SLOTS:
            eq = equipped.get(slot)
            emoji = SLOT_EMOJIS.get(slot, "⬜")
            if eq:
                quality_mark = QUALITY_COLORS.get(eq.get("quality", "common"), "⚪")
                stat_display = _format_stat_display(eq["stat"], eq["stat_value"])
                display_name = _strip_stat_suffix(eq["name"])
                value = f"{quality_mark} **{display_name}**\n{stat_display}"
            else:
                value = "⬜ 空 / Empty"
            embed.add_field(
                name=f"{emoji} {EQUIP_SLOT_LABELS_CN[slot]}",
                value=value,
                inline=True,
            )

        return embed

    def _build(self):
        self.clear_items()
        equipped = _get_equipped(self.uid)

        # ── Row 0: Operations ──
        equip_btn = discord.ui.Button(
            label="⚔️ Equip 装备", style=discord.ButtonStyle.success, row=0,
            custom_id="eq_equip",
        )
        equip_btn.callback = self._equip_callback
        self.add_item(equip_btn)

        has_any_equipped = any(equipped.get(s) for s in EQUIP_SLOTS)
        unequip_btn = discord.ui.Button(
            label="🔴 Unequip 卸下", style=discord.ButtonStyle.primary, row=0,
            custom_id="eq_unequip", disabled=not has_any_equipped,
        )
        unequip_btn.callback = self._unequip_callback
        self.add_item(unequip_btn)

        best_btn = discord.ui.Button(
            label="⚡ Best Equip 一键最强", style=discord.ButtonStyle.primary, row=0,
            custom_id="eq_best",
        )
        best_btn.callback = self._best_equip_callback
        self.add_item(best_btn)

        # ── Row 1-2: 6 Slot buttons ──
        SLOT_EMOJIS = {
            "weapon": "⚔️", "helmet": "🪖", "armor": "🛡️",
            "leggings": "👖", "boots": "👢", "accessory": "💍",
        }
        QUALITY_MARKS = {
            "common": "⚪", "rare": "🔵", "epic": "🟣", "legendary": "🟡",
        }
        rows_for_slots = [1, 1, 1, 2, 2, 2]  # 3 per row
        for i, slot in enumerate(EQUIP_SLOTS):
            emoji = SLOT_EMOJIS.get(slot, "⬜")
            eq = equipped.get(slot)
            if eq:
                lvl = eq.get("enhance_level", 0)
                mark = QUALITY_MARKS.get(eq.get("quality", "common"), "⚪")
                short_name = _strip_stat_suffix(eq["name"])[:20]
                label = f"{emoji} {mark} {short_name} +{lvl}"[:80]
            else:
                label = f"{emoji} 空 / Empty"
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                row=rows_for_slots[i],
                custom_id=f"eq_slot_{slot}",
            )
            btn.callback = self._make_slot_callback(slot)
            self.add_item(btn)

        # ── Row 3: Bag / Sell / Sell Weak ──
        bag_btn = discord.ui.Button(
            label="🎒 Bag 背包", style=discord.ButtonStyle.secondary, row=3,
            custom_id="eq_bag",
        )
        bag_btn.callback = self._bag_callback
        self.add_item(bag_btn)

        sell_equip_btn = discord.ui.Button(
            label="💲 Sell 卖装备", style=discord.ButtonStyle.secondary, row=3,
            custom_id="eq_sell",
        )
        sell_equip_btn.callback = self._sell_callback
        self.add_item(sell_equip_btn)

        sell_btn = discord.ui.Button(
            label="💰 Sell Weak 卖弱装", style=discord.ButtonStyle.secondary, row=3,
            custom_id="eq_sell_weak",
        )
        sell_btn.callback = self._sell_weak_callback
        self.add_item(sell_btn)

        # ── Row 4: Enhance / Back ──
        enhance_btn = discord.ui.Button(
            label="🔨 Enhance 强化", style=discord.ButtonStyle.secondary, row=4,
            custom_id="eq_enhance",
        )
        enhance_btn.callback = self._enhance_callback
        self.add_item(enhance_btn)

        if self.main_view:
            back_btn = discord.ui.Button(
                label="🏠 Back 返回", style=discord.ButtonStyle.secondary, row=4,
                custom_id="eq_back",
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    # ── Best Equip / 一键最强 ──
    async def _best_equip_callback(self, interaction: discord.Interaction):
        try:
            results = _auto_equip_best(self.uid)
            if not results:
                await interaction.response.defer(ephemeral=True)
                return await interaction.edit_original_response(
                    content="背包中没有可装备的装备！/ No equippable items in inventory!")

            # Build summary embed
            embed = discord.Embed(
                title="⚡ Best Equip / 一键最强装备",
                description="已自动为每个槽位装备最强装备：",
                color=0xF1C40F,
            )
            for slot, info in results.items():
                if info.get("error"):
                    embed.add_field(
                        name=f"{EQUIP_SLOT_LABELS_CN[slot]}",
                        value=f"⚠️ {info['error']}",
                        inline=True,
                    )
                else:
                    q = QUALITIES.get(info["quality"], QUALITIES["common"])
                    stat_disp = _format_stat_display(info["stat"], info["stat_value"])
                    embed.add_field(
                        name=f"{info['emoji']} {EQUIP_SLOT_LABELS_CN[slot]}",
                        value=f"**{info['name']}**\n{q['label']}\n{stat_disp}",
                        inline=True,
                    )

            # defer → refresh panel → send summary as ephemeral followup
            await interaction.response.defer()
            self._build()
            await interaction.edit_original_response(embed=self.build_main_embed(), view=self)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Best equip error (uid={self.uid}): {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "一键装备出错 / Best equip error", ephemeral=True)
            except Exception:
                logger.error("Best equip send_message error", exc_info=True)

    async def _unequip_callback(self, interaction: discord.Interaction):
        """Unequip from a selected slot."""
        try:
            equipped = _get_equipped(self.uid)
            if not equipped:
                return await interaction.response.send_message(
                    "No equipment to unequip / 没有装备可卸下", ephemeral=True)

            options = []
            for slot in EQUIP_SLOTS:
                eq = equipped.get(slot)
                if eq:
                    options.append(discord.SelectOption(
                        label=f"{EQUIP_SLOT_LABELS_CN[slot]}: {eq['name'][:50]}",
                        value=slot,
                    ))
            if not options:
                return await interaction.response.send_message(
                    "No equipment to unequip / 没有装备可卸下", ephemeral=True)

            class UnequipSelect(discord.ui.Select):
                def __init__(sel):
                    super().__init__(placeholder="Select slot to unequip / 选择要卸下的槽位", options=options)

                async def callback(sel, inter: discord.Interaction):
                    slot = sel.values[0]
                    success = _unequip_item(self.uid, slot)
                    if success:
                        self._build()
                        await inter.response.edit_message(
                            embed=self.build_main_embed(), view=self)
                    else:
                        await inter.response.send_message(
                            "Unequip failed / 卸下失败", ephemeral=True)

            view = discord.ui.View(timeout=60)
            view.add_item(UnequipSelect())
            await interaction.response.send_message(
                "Select a slot to unequip / 选择要卸下的槽位:", view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Unequip callback error (uid={self.uid}): {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "卸下过程出错 / Error during unequip", ephemeral=True)
            except Exception:
                logger.error("Unequip send_message error", exc_info=True)

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
                display_name = _strip_stat_suffix(row["item_name"])[:100]
                qty = row["quantity"]
                name_lower = row["item_name"].lower()
                emoji = "⚪"
                if "legendary" in name_lower:
                    emoji = "🟡"
                elif "epic" in name_lower:
                    emoji = "🟣"
                elif "rare" in name_lower:
                    emoji = "🔵"
                options.append(discord.SelectOption(
                    label=display_name,
                    value=row["item_id"],
                    description=f"x{qty} | {emoji}",
                    emoji=emoji,
                ))

            view = EquipSelectView(self.uid, self, interaction.message)
            # Populate item_map so _select_callback can resolve item_id → item_name
            for row in rows:
                view.item_map[row["item_id"]] = row["item_name"]
            select = discord.ui.Select(
                placeholder="选择要装备的装备 / Select equipment to equip",
                options=options[:25],
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

            view = EnhanceSelectView(self.uid, equipped, self, interaction.message)
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
                logger.error("Enhance callback error", exc_info=True)

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

        q = QUALITIES.get(eq["quality"], QUALITIES["common"])
        lvl = eq.get("enhance_level", 0)
        base_stat = int(eq["stat_value"] / (1 + lvl * 0.1)) if lvl > 0 and isinstance(eq["stat_value"], (int, float)) else eq["stat_value"]
        enhance_bonus = eq["stat_value"] - base_stat if isinstance(eq["stat_value"], (int, float)) else 0

        stat_display = _format_stat_display(eq["stat"], eq["stat_value"])

        desc = (
            f"**属性 Stats**: {stat_display}\n"
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

        # ── Add Unequip button ──
        view = discord.ui.View(timeout=60)
        unequip_btn = discord.ui.Button(
            label="Unequip 卸下", emoji="🔴",
            style=discord.ButtonStyle.danger, row=0,
        )
        unequip_btn.callback = self._make_unequip_callback(slot, eq, interaction.message)
        view.add_item(unequip_btn)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def _make_unequip_callback(self, slot: str, eq: dict, panel_msg=None):
        async def cb(interaction: discord.Interaction):
            try:
                success = _unequip_item(self.uid, slot)
                if success:
                    self._build()
                    await interaction.response.edit_message(
                        content=f"✅ 已卸下 / Unequipped: **{eq['name']}**", embed=None, view=None)
                    # Refresh the main panel
                    if panel_msg:
                        try:
                            embed = self.build_main_embed()
                            await panel_msg.edit(embed=embed, view=self)
                        except (discord.NotFound, discord.HTTPException) as e:
                            logger.debug(f"Failed to refresh EquipmentView after unequip: {e}")
                else:
                    await interaction.response.send_message(
                        "卸下失败 / Unequip failed", ephemeral=True)
            except Exception as e:
                logger.error(f"Unequip error (uid={self.uid}, slot={slot}): {e}", exc_info=True)
                try:
                    await interaction.response.send_message(
                        "卸下过程出错 / Error during unequip", ephemeral=True)
                except Exception:
                    pass
        return cb

    # ── Bag / 背包 ──
    async def _bag_callback(self, interaction: discord.Interaction):
        """Show inventory equipment grouped by slot."""
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
                    "背包中没有装备！/ No equipment in backpack!", ephemeral=True)

            # Group by slot
            grouped = {s: [] for s in EQUIP_SLOTS}
            for row in rows:
                slot = _resolve_slot(row["item_id"], row["item_name"])
                if slot and slot in grouped:
                    grouped[slot].append(row)
                else:
                    if "other" not in grouped:
                        grouped["other"] = []
                    grouped["other"].append(row)

            embed = discord.Embed(
                title=f"🎒 {self.uname} 的背包 / Backpack",
                color=discord.Color.blue(),
            )

            quality_emoji = {"common": "⚪", "rare": "🔵", "epic": "🟣", "legendary": "🟡"}
            for slot, items in grouped.items():
                if not items:
                    continue
                label = EQUIP_SLOT_LABELS_CN.get(slot, "其他 / Other")
                lines = []
                for item in items:
                    display_name = _strip_stat_suffix(item["item_name"])[:60]
                    _, _, _, quality = _parse_item_name(item["item_name"])
                    emoji = quality_emoji.get(quality, "⚪")
                    qty_str = f" x{item['quantity']}" if item["quantity"] > 1 else ""
                    lines.append(f"{emoji} {display_name}{qty_str}")
                embed.add_field(
                    name=f"{label} ({len(items)})",
                    value="\n".join(lines) if lines else "（空 / Empty）",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Bag callback error (uid={self.uid}): {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "背包查看出错 / Error viewing backpack", ephemeral=True)
            except Exception:
                pass

    # ── Sell / 手动卖装备 ──
    async def _sell_callback(self, interaction: discord.Interaction):
        """Show Select dropdown to manually sell a piece of equipment."""
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
                    "背包中没有装备！/ No equipment to sell!", ephemeral=True)

            QUALITY_PRICES = {"common": 50, "rare": 150, "epic": 300, "legendary": 800}

            options = []
            for row in rows:
                display_name = _strip_stat_suffix(row["item_name"])[:60]
                _, _, _, quality = _parse_item_name(row["item_name"])
                price = QUALITY_PRICES.get(quality, 25)
                qty_str = f" x{row['quantity']}" if row["quantity"] > 1 else ""
                options.append(discord.SelectOption(
                    label=f"{display_name}{qty_str}",
                    value=row["item_id"],
                    description=f"品质: {quality} | 售价/Price: {price}G",
                ))

            class SellSelect(discord.ui.Select):
                def __init__(sel):
                    super().__init__(
                        placeholder="Select equipment to sell / 选择要卖的装备",
                        options=options[:25],  # Discord limit
                    )

                async def callback(sel, inter: discord.Interaction):
                    item_id = sel.values[0]
                    row2 = next((r for r in rows if r["item_id"] == item_id), None)
                    if not row2:
                        return await inter.response.send_message("Item not found / 未找到物品", ephemeral=True)

                    _, _, _, quality = _parse_item_name(row2["item_name"])
                    price = QUALITY_PRICES.get(quality, 25)
                    display_name = _strip_stat_suffix(row2["item_name"])[:60]

                    with get_db_ctx() as conn2:
                        cur2 = conn2.cursor()
                        if row2["quantity"] <= 1:
                            cur2.execute("DELETE FROM user_inventory WHERE user_id=? AND item_id=?",
                                         (self.uid, item_id))
                        else:
                            cur2.execute("UPDATE user_inventory SET quantity=quantity-1"
                                         " WHERE user_id=? AND item_id=?",
                                         (self.uid, item_id))
                        cur2.execute(
                            "INSERT INTO user_balance (user_id, coins) VALUES (?, ?)"
                            " ON CONFLICT(user_id) DO UPDATE SET coins=coins+excluded.coins",
                            (self.uid, price),
                        )
                        conn2.commit()

                    await inter.response.send_message(
                        f"💰 卖出 / Sold: **{display_name}** — +{price}G",
                        ephemeral=True,
                    )

            view = discord.ui.View(timeout=120)
            view.add_item(SellSelect())
            await interaction.response.send_message(
                "选择要卖的装备 / Select equipment to sell:", view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Sell callback error (uid={self.uid}): {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "卖装备出错 / Error selling equipment", ephemeral=True)
            except Exception:
                pass

    async def _sell_weak_callback(self, interaction: discord.Interaction):
        """Sell inventory equipment weaker than currently equipped items."""
        try:
            equipped = _get_equipped(self.uid)
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT item_id, item_name, quantity FROM user_inventory"
                    " WHERE user_id = ? AND item_type = 'equipment' AND quantity > 0",
                    (self.uid,),
                )
                rows = cur.fetchall()

            if not rows:
                return await interaction.response.send_message(
                    "No equipment in inventory / 背包中没有装备", ephemeral=True)

            QUALITY_PRICES = {"common": 50, "rare": 150, "epic": 300, "legendary": 800}
            sold_count = 0
            sold_details = []
            total_gold = 0

            for row in rows:
                # Determine slot using shared helper
                slot = _resolve_slot(row["item_id"], row["item_name"])
                if not slot:
                    continue

                # Skip if no equipped item in this slot — inventory item may be useful later
                if slot not in equipped:
                    continue

                # Compare stat_value: inventory vs equipped
                _, stat_str, stat_val_str, quality = _parse_item_name(row["item_name"])
                try:
                    inv_val = sum(int(v.strip()) for v in stat_val_str.split(","))
                except (ValueError, AttributeError):
                    inv_val = 0

                current_val_str = str(equipped[slot].get("stat_value", "0"))
                try:
                    cur_val = sum(int(v.strip()) for v in current_val_str.split(","))
                except (ValueError, AttributeError):
                    cur_val = 0

                # Only sell if strictly weaker
                if inv_val >= cur_val:
                    continue

                price = QUALITY_PRICES.get(quality, 25)
                total_gold += price * row["quantity"]
                sold_count += row["quantity"]
                display_name = _strip_stat_suffix(row["item_name"])

                # Delete from inventory
                with get_db_ctx() as conn_write:
                    conn_write.execute("DELETE FROM user_inventory WHERE item_id = ?", (row["item_id"],))
                    conn_write.commit()

                sold_details.append(f"{display_name} x{row['quantity']} ({quality}, {price}G each)")

            if sold_count == 0:
                return await interaction.response.send_message(
                    "No weak equipment to sell / 没有比当前装备弱的可卖装备！", ephemeral=True)

            # Add coins
            from cogs.mmorpg_shop import _add_coins
            _add_coins(self.uid, total_gold, f"Sell {sold_count} weak equipment")

            # Build result embed
            detail_lines = "\n".join(sold_details[:20])
            if len(sold_details) > 20:
                detail_lines += f"\n... and {len(sold_details) - 20} more"

            embed = discord.Embed(
                title="💰 Sold Weak Equipment / 弱装出售",
                description=f"Sold **{sold_count}** items for **{total_gold:,}G**",
                color=0xF1C40F,
            )
            embed.add_field(name="Details / 明细", value=detail_lines or "(none)", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Sell weak error (uid={self.uid}): {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "处理出错 / Error", ephemeral=True)
            except Exception:
                pass


class EnhanceSelectView(discord.ui.View):
    """Select dropdown for enhancement target."""

    def __init__(self, uid: str, equipped: dict, eq_view, panel_msg=None):
        super().__init__(timeout=60)
        self.uid = uid
        self.equipped = equipped
        self.eq_view = eq_view
        self.panel_msg = panel_msg

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

            reason = f"Enhance {eq['name']} +{lvl}→+{lvl+1}"
            _add_coins(self.uid, -cost, reason)
            deducted = True

            import random, asyncio

            success = random.random() < rate
            if success:
                new_lvl = lvl + 1
                new_stat = int(eq["stat_value"] * (1 + 0.1) / (1 + lvl * 0.1) * (1 + new_lvl * 0.1)) if isinstance(eq["stat_value"], (int, float)) else eq["stat_value"]
            else:
                if lvl <= 5:
                    new_lvl = lvl
                elif lvl <= 10:
                    new_lvl = max(0, lvl - 1)
                else:
                    new_lvl = max(0, lvl - 3)
                if new_lvl == lvl:
                    new_stat = eq["stat_value"]
                else:
                    new_stat = int(eq["stat_value"] * (1 + new_lvl * 0.1) / (1 + lvl * 0.1)) if isinstance(eq["stat_value"], (int, float)) else eq["stat_value"]

            await enhance_animation(interaction, lvl, new_lvl, success)

            with get_db_ctx() as conn:
                conn.execute(
                    "UPDATE user_equipment SET enhance_level = ?, stat_value = ? WHERE user_id = ? AND slot = ?",
                    (new_lvl, new_stat, self.uid, slot),
                )
                conn.commit()

            new_bal = _bal(self.uid)
            if success:
                msg = (
                    f"## ✨ Enhancement Success / 强化成功！\n"
                    f"**{eq['name']}**: +{lvl} → **+{new_lvl}**\n"
                    f"STAT: {eq['stat_value']} → **{new_stat}**\n"
                    f"Cost / 花费: {cost:,}G  |  Balance / 余额: **{new_bal:,}**"
                )
            else:
                if new_lvl < lvl:
                    msg = (
                        f"## 💥 Enhancement Failed / 强化失败！\n"
                        f"**{eq['name']}**: +{lvl} → **+{new_lvl}** (Dropped / 降级)\n"
                        f"Cost / 花费: {cost:,}G  |  Balance / 余额: **{new_bal:,}**"
                    )
                else:
                    msg = (
                        f"## 💥 Enhancement Failed / 强化失败！\n"
                        f"**{eq['name']}**: +{lvl} (No change / 不变)\n"
                        f"Cost / 花费: {cost:,}G  |  Balance / 余额: **{new_bal:,}**"
                    )

            await interaction.followup.send(msg, ephemeral=True)

            self.eq_view._build()
            if self.panel_msg:
                try:
                    embed = self.eq_view.build_main_embed()
                    await self.panel_msg.edit(embed=embed, view=self.eq_view)
                except (discord.NotFound, discord.HTTPException) as e:
                    logger.debug(f"Failed to refresh EquipmentView after enhance: {e}")
            try:
                await interaction.edit_original_response(content="强化完成 / Enhancement complete", embed=None, view=None)
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
                logger.error("Enhance failed send_message error", exc_info=True)


def _format_stat_display(stat: str, stat_value) -> str:
    """Format stat display: 'ATK:+10' or 'CRIT:+20 HP:+15'."""
    if isinstance(stat_value, str) and "," in stat_value:
        stats = stat.split(",")
        vals = stat_value.split(",")
        parts = [f"{s.upper()}:+{v}" for s, v in zip(stats, vals)]
        return " ".join(parts)
    return f"+{stat_value} {stat.upper()}"


# ══════════════════════════════════════════════════════════════
# Core equipment functions
# ══════════════════════════════════════════════════════════════

def _get_equipped(user_id: str) -> dict:
    """Return {slot: {name, quality, stat, stat_value, enhance_level, emoji}, ...}."""
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
        stat_str = str(eq["stat"])
        val_str = str(eq["stat_value"])
        stat_names = stat_str.split(",")
        stat_vals = val_str.split(",")
        for s, v in zip(stat_names, stat_vals):
            s = s.strip()
            try:
                iv = int(v.strip())
            except (ValueError, AttributeError):
                iv = 0
            if s in stats:
                stats[s] += iv
    return stats


# ── Stat-to-users column mapping ──
_STAT_COL_MAP = {"atk": "attack", "def": "defense", "hp": "max_hp"}


def _apply_stat_delta(cur, user_id: str, stat_str: str, delta_str: str):
    """Apply stat delta(s) to users table. Handles comma-separated multi-stats.
    stat_str: "atk" or "crit,hp"
    delta_str: "10" or "20,15"
    crit/spd are not tracked in users table and are silently ignored."""
    stat_names = str(stat_str).split(",")
    delta_vals = str(delta_str).split(",")

    for s, d in zip(stat_names, delta_vals):
        s = s.strip()
        try:
            d_int = int(d.strip())
        except (ValueError, AttributeError):
            continue
        col = _STAT_COL_MAP.get(s)
        if not col:
            continue
        cur.execute(f"UPDATE users SET {col} = MAX(0, {col} + ?) WHERE discord_id = ?", (d_int, user_id))
        if s == "hp":
            cur.execute("UPDATE users SET hp = MIN(hp + ?, max_hp) WHERE discord_id = ?", (d_int, user_id))


def _equip_item(user_id: str, item_name: str, item_id: str = None) -> bool:
    """Equip an item from inventory. Parses stat info from item_name.
    item_name format: 'Name|||stat_type:stat_value|||quality' or legacy plain name.
    If item_id is provided, uses exact item_id match; otherwise falls back to LIKE.
    Returns True if successful."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        # Find the item in inventory
        if item_id:
            cur.execute(
                "SELECT item_id, item_name, item_type, quantity FROM user_inventory WHERE user_id=? AND item_id=?",
                (user_id, item_id),
            )
        else:
            search_name = item_name.split("|||")[0] if "|||" in item_name else item_name
            cur.execute(
                "SELECT item_id, item_name, item_type, quantity FROM user_inventory WHERE user_id=? AND item_name LIKE ?",
                (user_id, f"%{search_name}%"),
            )
        rows = cur.fetchall()
        if not rows:
            return False
        row = rows[0]

        # Parse slot from item_id (format: eq_{slot}_{name} or eq_{slot}_gacha_{name})
        slot = None
        item_id = row["item_id"]
        if item_id.startswith("eq_"):
            parts = item_id.split("_", 2)
            if len(parts) >= 2:
                candidate = parts[1]
                if candidate in EQUIP_SLOTS:
                    slot = candidate
        if not slot:
            for s in EQUIP_SLOTS:
                if s in row["item_name"].lower():
                    slot = s
                    break
        if not slot:
            logger.error(f"_equip_item: cannot determine slot for item_id={item_id} item_name={row['item_name']}")
            return False

        # ── Parse stat info from item_name ──
        clean_name, stat_str, stat_val_str, quality = _parse_item_name(row["item_name"])

        # ── Unequip old: save info & subtract its stats from users table ──
        cur.execute(
            "SELECT item_id, name, stat, stat_value, quality FROM user_equipment WHERE user_id=? AND slot=?",
            (user_id, slot),
        )
        old_eq = cur.fetchone()
        if old_eq:
            old_stat_str = str(old_eq["stat"])
            old_val_str = str(old_eq["stat_value"])
            old_stats = old_stat_str.split(",")
            old_vals = old_val_str.split(",")
            neg_vals = []
            for v in old_vals:
                try:
                    neg_vals.append(str(-int(v.strip())))
                except ValueError:
                    neg_vals.append("0")
            _apply_stat_delta(cur, user_id, old_stat_str, ",".join(neg_vals))
        cur.execute("DELETE FROM user_equipment WHERE user_id=? AND slot=?", (user_id, slot))

        # ── Equip new: write to user_equipment and users table ──
        cur.execute(
            "INSERT INTO user_equipment (user_id, slot, name, quality, stat, stat_value, emoji, item_id) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, slot, clean_name, quality, stat_str, stat_val_str, "", item_id),
        )
        _apply_stat_delta(cur, user_id, stat_str, stat_val_str)

        # ── Consume from inventory (after successful equip, within same transaction) ──
        if row["quantity"] <= 1:
            cur.execute("DELETE FROM user_inventory WHERE item_id=?", (row["item_id"],))
        else:
            cur.execute("UPDATE user_inventory SET quantity=quantity-1 WHERE item_id=?", (row["item_id"],))

        # ── Return old equipment to inventory ──
        if old_eq:
            # Reconstruct encoded item_name: "Name|||stat1:val1,stat2:val2|||quality"
            old_stat_keys = str(old_eq["stat"]).split(",")
            old_stat_vals = str(old_eq["stat_value"]).split(",")
            stat_pairs = ",".join(
                f"{k.strip()}:{v.strip()}"
                for k, v in zip(old_stat_keys, old_stat_vals)
            )
            old_full_name = f"{old_eq['name']}|||{stat_pairs}|||{old_eq['quality']}"
            old_item_id = old_eq["item_id"]
            cur.execute(
                "SELECT quantity FROM user_inventory WHERE user_id=? AND item_id=?",
                (user_id, old_item_id),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    "UPDATE user_inventory SET quantity=quantity+1 WHERE user_id=? AND item_id=?",
                    (user_id, old_item_id),
                )
            else:
                cur.execute(
                    "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) "
                    "VALUES (?,?,?,1,'equipment')",
                    (user_id, old_item_id, old_full_name),
                )

        conn.commit()
        logger.info(f"_equip_item: uid={user_id} slot={slot} name={clean_name} stat={stat_str} val={stat_val_str} quality={quality}")
    return True


def _unequip_item(user_id: str, slot: str) -> bool:
    """Unequip an item from a slot and return it to inventory.
    1. Read user_equipment record for the slot
    2. DELETE it
    3. INSERT back to user_inventory with encoded item_name
    4. Subtract stats from users table
    Returns True if successful, False if slot was empty."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, quality, stat, stat_value, emoji, item_id FROM user_equipment WHERE user_id=? AND slot=?",
            (user_id, slot),
        )
        eq = cur.fetchone()
        if not eq:
            return False

        # Reconstruct encoded item_name: "Name|||stat:val|||quality"
        encoded_name = f"{eq['name']}|||{eq['stat']}:{eq['stat_value']}|||{eq['quality']}"

        # Use the original item_id from user_equipment if available, else fallback
        item_id = eq["item_id"] if eq["item_id"] else f"eq_{slot}_{eq['name'].split(' ')[0]}"

        # Delete from user_equipment
        cur.execute("DELETE FROM user_equipment WHERE user_id=? AND slot=?", (user_id, slot))

        # Subtract stats
        stat_str = str(eq["stat"])
        val_str = str(eq["stat_value"])
        stats = stat_str.split(",")
        vals = val_str.split(",")
        neg_vals = []
        for v in vals:
            try:
                neg_vals.append(str(-int(v.strip())))
            except ValueError:
                neg_vals.append("0")
        _apply_stat_delta(cur, user_id, stat_str, ",".join(neg_vals))

        # Return to inventory
        cur.execute(
            "SELECT quantity FROM user_inventory WHERE user_id = ? AND item_id = ?",
            (user_id, item_id),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                "UPDATE user_inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?",
                (user_id, item_id),
            )
        else:
            cur.execute(
                "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) "
                "VALUES (?, ?, ?, 1, 'equipment')",
                (user_id, item_id, encoded_name),
            )

        conn.commit()
    return True


def _auto_equip_best(user_id: str) -> dict:
    """Scan inventory for all equipment, group by slot, pick highest stat_value per slot,
    and equip each. Returns {slot: {name, quality, stat, stat_value, emoji, error?}}."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT item_id, item_name, quantity FROM user_inventory"
            " WHERE user_id = ? AND item_type = 'equipment' AND quantity > 0",
            (user_id,),
        )
        rows = cur.fetchall()

    if not rows:
        return {}

    # Group by slot, pick best
    best_by_slot = {}
    for row in rows:
        # Determine slot from item_id
        slot = None
        item_id = row["item_id"]
        if item_id.startswith("eq_"):
            parts = item_id.split("_", 2)
            if len(parts) >= 2 and parts[1] in EQUIP_SLOTS:
                slot = parts[1]
        if not slot:
            for s in EQUIP_SLOTS:
                if s in row["item_name"].lower():
                    slot = s
                    break
        if not slot:
            continue

        # Parse stat_value from item_name
        _, stat_str, stat_val_str, quality = _parse_item_name(row["item_name"])
        # For comparison, sum all stat values (e.g. crit+hp for accessories)
        try:
            primary_val = sum(int(v.strip()) for v in stat_val_str.split(","))
        except (ValueError, AttributeError):
            primary_val = 0

        if slot not in best_by_slot or primary_val > best_by_slot[slot]["score"]:
            best_by_slot[slot] = {
                "item_name": row["item_name"],
                "score": primary_val,
                "item_id": row["item_id"],
            }

    # Equip each best — only if strictly better than currently equipped
    equipped = _get_equipped(user_id)
    results = {}
    for slot in EQUIP_SLOTS:
        if slot not in best_by_slot:
            results[slot] = {"error": "无可用装备 / No available equipment"}
            continue

        info = best_by_slot[slot]

        # Compare against currently equipped item; keep if already better or equal
        current = equipped.get(slot)
        if current:
            current_val_str = str(current.get("stat_value", "0"))
            try:
                current_val = sum(int(v.strip()) for v in current_val_str.split(","))
            except (ValueError, AttributeError):
                current_val = 0
            if info["score"] <= current_val:
                results[slot] = {
                    "name": current.get("name", slot),
                    "quality": current.get("quality", "common"),
                    "stat": current.get("stat", "atk"),
                    "stat_value": current_val_str,
                    "emoji": current.get("emoji", "⚪"),
                }
                continue

        # Inventory item is strictly better — equip it with exact item_id
        success = _equip_item(user_id, info["item_name"], item_id=info["item_id"])
        if success:
            # Read back what was equipped
            equipped_refresh = _get_equipped(user_id)
            eq = equipped_refresh.get(slot, {})
            results[slot] = {
                "name": eq.get("name", info["item_name"]),
                "quality": eq.get("quality", "common"),
                "stat": eq.get("stat", "atk"),
                "stat_value": eq.get("stat_value", "0"),
                "emoji": eq.get("emoji", "⚪"),
            }
        else:
            results[slot] = {"error": "装备失败 / Equip failed"}

    return results


# ══════════════════════════════════════════════════════════════
# Enhancement system
# ══════════════════════════════════════════════════════════════

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
    to_level = from_level + 1
    return ENHANCE_RATES.get((from_level, to_level), 0.15)


def _get_enhance_cost(from_level: int) -> int:
    to_level = from_level + 1
    return ENHANCE_COSTS.get(to_level, 50000)


async def enhance_animation(interaction, level_before: int, level_after: int, success: bool):
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
        logger.error("Enhancement progress error", exc_info=True)


# ══════════════════════════════════════════════════════════════
# Init DB table
# ══════════════════════════════════════════════════════════════

def _init_equipment_db():
    with get_db_ctx() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_equipment (
                user_id TEXT NOT NULL,
                slot TEXT NOT NULL,
                name TEXT,
                quality TEXT DEFAULT 'common',
                stat TEXT,
                stat_value TEXT DEFAULT '0',
                enhance_level INTEGER DEFAULT 0,
                emoji TEXT DEFAULT '',
                item_id TEXT DEFAULT '',
                PRIMARY KEY (user_id, slot)
            )
        """)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(user_equipment)")
        cols = {r["name"] for r in cur.fetchall()}
        if "enhance_level" not in cols:
            cur.execute("ALTER TABLE user_equipment ADD COLUMN enhance_level INTEGER DEFAULT 0")
        if "item_id" not in cols:
            cur.execute("ALTER TABLE user_equipment ADD COLUMN item_id TEXT DEFAULT ''")
        conn.commit()


# ══════════════════════════════════════════════════════════════
# Cog & Commands
# ══════════════════════════════════════════════════════════════

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
                q = QUALITIES.get(eq["quality"], QUALITIES["common"])
                stat_display = _format_stat_display(eq["stat"], eq["stat_value"])
                val = f"{q['label'].split()[0]} **{eq['name']}** ({stat_display})"
            else:
                val = "⬜ 空 / Empty"
            embed.add_field(
                name=EQUIP_SLOT_LABELS_CN[slot],
                value=val,
                inline=True,
            )

        stats_text = (
            f"⚔️ ATK: +{total_stats['atk']}  |  🛡️ DEF: +{total_stats['def']}  |  ❤️ HP: +{total_stats['hp']}\n"
            f"💥 Crit: +{total_stats['crit']}%  |  💨 SPD: +{total_stats['spd']}"
        )
        embed.add_field(name="📊 总属性加成 / Total Stats", value=stats_text, inline=False)

        view = EquipmentView(interaction.guild, uid, uname)
        await interaction.response.send_message(embed=embed, view=view)


class EquipSelectView(discord.ui.View):
    """Select view for equipping items from inventory."""

    def __init__(self, uid: str, main_view=None, panel_msg=None):
        super().__init__(timeout=180)
        self.uid = uid
        self.main_view = main_view
        self.panel_msg = panel_msg  # The EquipmentView panel message to refresh after equip
        self.item_map = {}  # item_id → item_name mapping for exact match in _select_callback

    async def _select_callback(self, interaction: discord.Interaction):
        item_id = interaction.data["values"][0]
        item_name = self.item_map.get(item_id)
        try:
            success = _equip_item(self.uid, item_name, item_id=item_id)
            if success:
                display_name = _strip_stat_suffix(item_name)
                logger.info(f"Equip success: uid={self.uid} item={item_name} -> parsed name={display_name}")
                await interaction.response.edit_message(
                    content=f"装备成功！/ Equipped: **{display_name}**",
                    view=None,
                )
                # Refresh the parent EquipmentView panel if available
                if self.main_view and hasattr(self.main_view, '_build') and self.panel_msg:
                    try:
                        self.main_view._build()
                        embed = self.main_view.build_main_embed()
                        await self.panel_msg.edit(embed=embed, view=self.main_view)
                    except (discord.NotFound, discord.HTTPException) as e:
                        logger.debug(f"Failed to refresh EquipmentView after equip: {e}")
            else:
                logger.warning(f"Equip failed: uid={self.uid} item_name={item_name}")
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
                logger.error("Equip select send_message error", exc_info=True)


async def setup(bot):
    await bot.add_cog(MMORPGEquipment(bot))
