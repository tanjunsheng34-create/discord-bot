"""
cogs/mmorpg_gems.py — Gem Socket / 宝石镶嵌系统
Gem types: Ruby(+ATK), Sapphire(+DEF), Emerald(+HP), Diamond(+CRIT), Amethyst(+Element%)
5 levels: Lv1(+2%) → Lv5(+10%)
3-same-color resonance: stat doubled
Synthesis: 3 low → 1 high
"""

import logging
import datetime
import discord
from discord import app_commands
from discord.ext import commands

from database import get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Gem definitions
# ══════════════════════════════════════════════════════════════
GEM_TYPES = {
    "Ruby":   {"stat": "ATK",  "emoji": "🔴", "name_cn": "红宝石", "name_en": "Ruby"},
    "Sapphire": {"stat": "DEF",  "emoji": "🔵", "name_cn": "蓝宝石", "name_en": "Sapphire"},
    "Emerald":  {"stat": "HP",   "emoji": "🟢", "name_cn": "绿宝石", "name_en": "Emerald"},
    "Diamond":  {"stat": "CRIT", "emoji": "💎", "name_cn": "钻石",   "name_en": "Diamond"},
    "Amethyst": {"stat": "ELEM", "emoji": "🟣", "name_cn": "紫水晶", "name_en": "Amethyst"},
}

# Level → bonus percentage (applied to base stat)
GEM_LEVEL_BONUS = {1: 0.02, 2: 0.04, 3: 0.06, 4: 0.08, 5: 0.10}

GEM_SHOP_PRICE = {"Ruby": 500, "Sapphire": 500, "Emerald": 500, "Diamond": 800, "Amethyst": 800}

EQUIP_SLOTS_GEM = ["weapon", "helmet", "armor", "leggings", "boots", "accessory"]
EQUIP_SLOT_LABELS = {
    "weapon": "武器 Weapon", "helmet": "头盔 Helmet", "armor": "护甲 Armor",
    "leggings": "护腿 Leggings", "boots": "靴子 Boots", "accessory": "饰品 Accessory",
}
MAX_SLOTS_PER_EQUIP = 3


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════

def _init_gem_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()

        # Gem inventory: user_id, gem_type, level, quantity
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_gems (
                user_id TEXT NOT NULL,
                gem_type TEXT NOT NULL,
                level INTEGER DEFAULT 1,
                quantity INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, gem_type, level)
            )
        """)

        # Gem sockets: which gems are socketed into which equipment
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gem_sockets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                slot_index INTEGER NOT NULL,
                gem_type TEXT,
                gem_level INTEGER DEFAULT 1,
                UNIQUE(equipment_id, user_id, slot_index)
            )
        """)

        # Ensure columns exist
        cur.execute("PRAGMA table_info(user_equipment)")
        eq_cols = {r["name"] for r in cur.fetchall()}
        if "gem_socket_count" not in eq_cols:
            cur.execute("ALTER TABLE user_equipment ADD COLUMN gem_socket_count INTEGER DEFAULT 0")
        conn.commit()

_init_gem_tables()


# ══════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════

def _get_balance(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["score"] or 0) if row else 0


def _add_coins(uid: str, amount: int, reason: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING", (uid,))
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)", (uid, amount, reason))
        conn.commit()


def _get_equipped(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT slot, name, quality, stat, stat_value, enhance_level, emoji, item_id, set_name FROM user_equipment WHERE user_id=?",
            (uid,),
        )
        rows = cur.fetchall()
    result = {}
    for r in rows:
        result[r["slot"]] = {
            "name": r["name"], "quality": r["quality"], "stat": r["stat"],
            "stat_value": r["stat_value"], "enhance_level": r["enhance_level"] or 0,
            "emoji": r["emoji"], "item_id": r["item_id"], "set_name": r["set_name"],
        }
    return result


def _get_user_gems(uid: str) -> dict:
    """Returns {(gem_type, level): quantity}."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT gem_type, level, quantity FROM user_gems WHERE user_id = ? AND quantity > 0", (uid,))
        rows = cur.fetchall()
    result = {}
    for r in rows:
        result[(r["gem_type"], r["level"])] = r["quantity"]
    return result


def _add_gem_to_user(uid: str, gem_type: str, level: int, quantity: int = 1):
    with get_db_ctx() as conn:
        conn.execute(
            "INSERT INTO user_gems (user_id, gem_type, level, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, gem_type, level) DO UPDATE SET quantity = quantity + ?",
            (uid, gem_type, level, quantity, quantity),
        )
        conn.commit()


def _remove_gem_from_user(uid: str, gem_type: str, level: int, quantity: int = 1) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT quantity FROM user_gems WHERE user_id = ? AND gem_type = ? AND level = ?", (uid, gem_type, level))
        row = cur.fetchone()
        if not row or row["quantity"] < quantity:
            return False
        new_qty = row["quantity"] - quantity
        if new_qty <= 0:
            cur.execute("DELETE FROM user_gems WHERE user_id = ? AND gem_type = ? AND level = ?", (uid, gem_type, level))
        else:
            cur.execute("UPDATE user_gems SET quantity = ? WHERE user_id = ? AND gem_type = ? AND level = ?", (new_qty, uid, gem_type, level))
        conn.commit()
    return True


def _get_socketed_gems(uid: str, eq_id: str) -> list:
    """Return list of {slot_index, gem_type, gem_level} for an equipment."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT slot_index, gem_type, gem_level FROM gem_sockets WHERE equipment_id = ? AND user_id = ? AND gem_type IS NOT NULL ORDER BY slot_index",
            (eq_id, uid),
        )
        return [dict(r) for r in cur.fetchall()]


def _get_socket_count(uid: str, eq_id: str) -> int:
    """How many sockets are available for this equipment (0-3)."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM gem_sockets WHERE equipment_id = ? AND user_id = ?", (eq_id, uid))
        row = cur.fetchone()
        return row["cnt"] if row else 0


def _ensure_sockets(uid: str, eq_id: str, count: int):
    """Ensure at least `count` socket slots exist for this equipment."""
    existing = _get_socket_count(uid, eq_id)
    if existing >= count:
        return
    with get_db_ctx() as conn:
        for i in range(existing, count):
            conn.execute(
                "INSERT INTO gem_sockets (equipment_id, user_id, slot_index) VALUES (?, ?, ?) "
                "ON CONFLICT(equipment_id, user_id, slot_index) DO NOTHING",
                (eq_id, uid, i),
            )
        conn.commit()


def _open_socket(uid: str, eq_id: str):
    """Open one new socket slot. Cost increases per socket."""
    existing = _get_socket_count(uid, eq_id)
    if existing >= MAX_SLOTS_PER_EQUIP:
        return (False, "Already 3 sockets / 已满3孔")
    cost = [2000, 8000, 15000][existing]  # cost for unlocking slot 1/2/3
    bal = _get_balance(uid)
    if bal < cost:
        return (False, f"Insufficient coins / 金币不足! Need {cost:,}G, you have {bal:,}")
    _add_coins(uid, -cost, f"Open gem socket #{existing + 1} for {eq_id}")
    _ensure_sockets(uid, eq_id, existing + 1)
    return (True, f"Opened socket #{existing + 1} / 成功开第{existing + 1}孔！Cost: {cost:,}G")


def _socket_gem(uid: str, eq_id: str, slot_idx: int, gem_type: str, gem_level: int):
    """Insert a gem into a socket. Returns (success, message, old_gem_info_or_none)."""
    # Check gem exists in user inventory
    gems = _get_user_gems(uid)
    if gems.get((gem_type, gem_level), 0) <= 0:
        return (False, "You don't have this gem / 你没有这个宝石", None)

    # Check socket exists and read old gem
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT gem_type, gem_level FROM gem_sockets WHERE equipment_id = ? AND user_id = ? AND slot_index = ?",
            (eq_id, uid, slot_idx),
        )
        old = cur.fetchone()

    old_gem = None
    if old and old["gem_type"]:
        old_gem = {"gem_type": old["gem_type"], "gem_level": old["gem_level"]}
        # Return old gem to inventory
        _add_gem_to_user(uid, old["gem_type"], old["gem_level"], 1)

    # Remove gem from user inventory
    if not _remove_gem_from_user(uid, gem_type, gem_level, 1):
        return (False, "Failed to remove gem / 移除宝石失败", None)

    # Insert into socket
    with get_db_ctx() as conn:
        conn.execute(
            "UPDATE gem_sockets SET gem_type = ?, gem_level = ? WHERE equipment_id = ? AND user_id = ? AND slot_index = ?",
            (gem_type, gem_level, eq_id, uid, slot_idx),
        )
        conn.commit()

    if old_gem:
        return (True, f"Socked {gem_type} Lv{gem_level} (replaced {old_gem['gem_type']} Lv{old_gem['gem_level']})", old_gem)
    return (True, f"Socked {gem_type} Lv{gem_level} / 镶嵌成功！", None)


def _unsocket_gem(uid: str, eq_id: str, slot_idx: int):
    """Remove a gem from socket, return to inventory."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT gem_type, gem_level FROM gem_sockets WHERE equipment_id = ? AND user_id = ? AND slot_index = ?",
            (eq_id, uid, slot_idx),
        )
        row = cur.fetchone()
    if not row or not row["gem_type"]:
        return (False, "No gem in this slot / 孔中没有宝石")

    gem_type, gem_level = row["gem_type"], row["gem_level"]
    _add_gem_to_user(uid, gem_type, gem_level, 1)
    with get_db_ctx() as conn:
        conn.execute(
            "UPDATE gem_sockets SET gem_type = NULL, gem_level = NULL WHERE equipment_id = ? AND user_id = ? AND slot_index = ?",
            (eq_id, uid, slot_idx),
        )
        conn.commit()
    return (True, f"Unsocketed {gem_type} Lv{gem_level} / 已取下{gem_type} Lv{gem_level}")


def _synthesize_gems(uid: str, gem_type: str, source_level: int) -> tuple:
    """Synthesize 3 gems of source_level into 1 of source_level+1. Returns (success, message)."""
    if source_level >= 5:
        return (False, "Already max level / 已是最高等级")
    gems = _get_user_gems(uid)
    qty = gems.get((gem_type, source_level), 0)
    if qty < 3:
        return (False, f"Need 3x {gem_type} Lv{source_level}, you have {qty} / 需要3个Lv{source_level}，你只有{qty}个")
    _remove_gem_from_user(uid, gem_type, source_level, 3)
    _add_gem_to_user(uid, gem_type, source_level + 1, 1)
    info = GEM_TYPES.get(gem_type, {})
    return (True, f"Synthesized {gem_type} Lv{source_level+1} / 合成{info.get('name_cn', gem_type)}Lv{source_level+1}！")


def _calc_resonance(gems: list) -> tuple:
    """Check for 3-same-color resonance. Returns (activated, gem_type_or_None, bonus_text)."""
    if len(gems) < 3:
        return (False, None, "")
    counts = {}
    for g in gems:
        t = g.get("gem_type")
        if t:
            counts[t] = counts.get(t, 0) + 1
    for t, c in counts.items():
        if c >= 3:
            info = GEM_TYPES.get(t, {})
            return (True, t, f"3x {info.get('name_cn', t)} resonance: {info.get('stat', t)} bonus DOUBLED / 属性翻倍！")
    return (False, None, "")


# ══════════════════════════════════════════════════════════════
# Views / UI
# ══════════════════════════════════════════════════════════════

class GemMainView(discord.ui.View):
    """Main gem panel — select equipment, manage gems."""

    def __init__(self, uid: str, user_name: str = None, main_view=None):
        super().__init__(timeout=600)
        self.uid = uid
        self.user_name = user_name
        self.main_view = main_view
        self._build()

    def _build(self):
        self.clear_items()
        equipped = _get_equipped(self.uid)

        equip_options = []
        for slot in EQUIP_SLOTS_GEM:
            eq = equipped.get(slot)
            if eq:
                eq_id = eq.get("item_id", "") or slot
                socket_count = _get_socket_count(self.uid, eq_id)
                adorned_gems = _get_socketed_gems(self.uid, eq_id)
                filled = sum(1 for g in adorned_gems if g.get("gem_type"))
                equip_options.append(discord.SelectOption(
                    label=f"{EQUIP_SLOT_LABELS[slot]}: {eq['name'][:20]}",
                    value=slot,
                    description=f"Sockets: {filled}/{socket_count} (max 3)",
                    emoji="💎",
                ))

        if equip_options:
            select = discord.ui.Select(
                placeholder="Select equipment / 选择装备",
                options=equip_options,
                row=0,
            )
            select.callback = self._select_equip_callback
            self.add_item(select)

        # Buttons
        shop_btn = discord.ui.Button(label="🛒 Buy Gems 购买宝石", style=discord.ButtonStyle.primary, row=1)
        shop_btn.callback = self._shop_callback
        self.add_item(shop_btn)

        synth_btn = discord.ui.Button(label="⚗️ Synthesize 合成", style=discord.ButtonStyle.success, row=1)
        synth_btn.callback = self._synth_callback
        self.add_item(synth_btn)

        inv_btn = discord.ui.Button(label="🎒 My Gems 宝石背包", style=discord.ButtonStyle.secondary, row=1)
        inv_btn.callback = self._inventory_callback
        self.add_item(inv_btn)

        # Back button
        if self.main_view:
            back_btn = discord.ui.Button(label="🏠 Back 返回", style=discord.ButtonStyle.danger, row=4)
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    def build_embed(self) -> discord.Embed:
        equipped = _get_equipped(self.uid)
        bal = _get_balance(self.uid)

        embed = discord.Embed(
            title="💎 宝石镶嵌 / Gem Socket System",
            description=(
                f"🪙 **Balance**: {bal:,}G\n\n"
                f"**Gem Types / 宝石类型**:\n"
                f"🔴 Ruby (+ATK%) | 🔵 Sapphire (+DEF%) | 🟢 Emerald (+HP%)\n"
                f"💎 Diamond (+CRIT%) | 🟣 Amethyst (+Element%)\n\n"
                f"**Levels / 等级**: Lv1(+2%) → Lv5(+10%)\n"
                f"**Resonance / 共鸣**: 3 same-color gems on one equip = stat doubled!\n"
                f"**Synthesis / 合成**: 3x LvN → 1x Lv(N+1)"
            ),
            color=0x1ABC9C,
        )

        for slot in EQUIP_SLOTS_GEM:
            eq = equipped.get(slot)
            if eq:
                eq_id = eq.get("item_id", "") or slot
                socket_count = _get_socket_count(self.uid, eq_id)
                adorned = _get_socketed_gems(self.uid, eq_id)
                if socket_count == 0:
                    slot_info = "0 slots / 未开孔"
                else:
                    parts = []
                    for i in range(socket_count):
                        gem = next((g for g in adorned if g["slot_index"] == i), None)
                        if gem and gem.get("gem_type"):
                            info = GEM_TYPES.get(gem["gem_type"], {})
                            parts.append(f"{info.get('emoji','?')} {gem['gem_type']} Lv{gem['gem_level']}")
                        else:
                            parts.append("⬛ Empty")
                    slot_info = " | ".join(parts)
                    res_ok, res_type, res_text = _calc_resonance(adorned)
                    if res_ok:
                        slot_info += f"\n✨ *{res_text}*"
                val = f"**{eq['name']}**\n{slot_info}"
            else:
                val = "⬜ 空 / Empty"
            embed.add_field(name=EQUIP_SLOT_LABELS[slot], value=val, inline=True)

        return embed

    async def _select_equip_callback(self, interaction: discord.Interaction):
        try:
            slot = interaction.data["values"][0]
            equipped = _get_equipped(self.uid)
            eq = equipped.get(slot)
            if not eq:
                return await interaction.response.send_message("Not equipped / 未装备", ephemeral=True)

            eq_id = eq.get("item_id", "") or slot
            view = GemEquipView(self.uid, slot, eq, eq_id, self)
            embed = view.build_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            logger.error(f"GemMainView _select_equip_callback error: {e}", exc_info=True)

    async def _shop_callback(self, interaction: discord.Interaction):
        view = GemShopView(self.uid, self)
        embed = view.build_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def _synth_callback(self, interaction: discord.Interaction):
        view = GemSynthView(self.uid, self)
        embed = view.build_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def _inventory_callback(self, interaction: discord.Interaction):
        view = GemInventoryView(self.uid, self)
        embed = view.build_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            try:
                self.main_view.build_page_buttons()
                embed = discord.Embed(
                    title=self.main_view.CATEGORY_TITLES.get(self.main_view.category, "GMPT Dashboard"),
                    color=self.main_view.CATEGORY_COLORS.get(self.main_view.category, 0x9B59B6),
                )
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except Exception:
                await interaction.response.edit_message(content="Back / 返回 — use `/dashboard` to reopen.", view=None)
        else:
            await interaction.response.edit_message(content="Use `/dashboard` to reopen / 使用 `/dashboard` 重新打开", view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class GemEquipView(discord.ui.View):
    """Manage gems for a specific equipment."""

    def __init__(self, uid: str, slot: str, eq: dict, eq_id: str, main_view: GemMainView = None):
        super().__init__(timeout=300)
        self.uid = uid
        self.slot = slot
        self.eq = eq
        self.eq_id = eq_id
        self.main_view = main_view
        self._build()

    def _build(self):
        self.clear_items()
        socket_count = _get_socket_count(self.uid, self.eq_id)
        adorned = _get_socketed_gems(self.uid, self.eq_id)

        # Open socket button
        if socket_count < MAX_SLOTS_PER_EQUIP:
            cost = [2000, 8000, 15000][socket_count]
            open_btn = discord.ui.Button(
                label=f"🔓 Open Socket #{socket_count + 1} ({cost:,}G)",
                style=discord.ButtonStyle.primary, row=0,
            )
            open_btn.callback = self._open_socket_callback
            self.add_item(open_btn)

        # Socket slots
        for i in range(socket_count):
            gem = next((g for g in adorned if g["slot_index"] == i), None)
            if gem and gem.get("gem_type"):
                info = GEM_TYPES.get(gem["gem_type"], {})
                row_idx = 1 + i
                label = f"{info.get('emoji','')} Slot {i+1}: {gem['gem_type']} Lv{gem['gem_level']}"
                btn = discord.ui.Button(label=label, style=discord.ButtonStyle.success, row=row_idx)
                btn.callback = self._make_slot_callback(i)
                self.add_item(btn)

                remove_btn = discord.ui.Button(
                    label=f"❌ Remove 取下", style=discord.ButtonStyle.danger, row=row_idx,
                )
                remove_btn.callback = self._make_remove_callback(i)
                self.add_item(remove_btn)
            else:
                row_idx = 1 + i
                btn = discord.ui.Button(
                    label=f"⬛ Slot {i+1}: Empty 空",
                    style=discord.ButtonStyle.secondary, row=row_idx,
                )
                btn.callback = self._make_slot_callback(i)
                self.add_item(btn)

        # Back
        back_btn = discord.ui.Button(label="↩ Back 返回", style=discord.ButtonStyle.danger, row=4)
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    def build_embed(self):
        socket_count = _get_socket_count(self.uid, self.eq_id)
        adorned = _get_socketed_gems(self.uid, self.eq_id)
        bal = _get_balance(self.uid)

        gem_details = []
        for i in range(socket_count):
            gem = next((g for g in adorned if g["slot_index"] == i), None)
            if gem and gem.get("gem_type"):
                info = GEM_TYPES.get(gem["gem_type"], {})
                bonus = GEM_LEVEL_BONUS.get(gem["gem_level"], 0)
                gem_details.append(f"Slot {i+1}: {info.get('emoji','')} {gem['gem_type']} Lv{gem['gem_level']} (+{int(bonus*100)}% {info.get('stat','')})")
            else:
                gem_details.append(f"Slot {i+1}: ⬛ Empty")

        res_ok, res_type, res_text = _calc_resonance(adorned)
        if res_ok:
            gem_details.append(f"\n✨ **Resonance Active / 共鸣激活**: {res_text}")

        embed = discord.Embed(
            title=f"💎 {self.eq['name']} - Gem Sockets",
            description=(
                f"**Slot / 槽位**: {EQUIP_SLOT_LABELS.get(self.slot, self.slot)}\n"
                f"**Sockets / 孔数**: {socket_count}/{MAX_SLOTS_PER_EQUIP}\n"
                f"**Balance / 余额**: {bal:,}G\n\n"
                + "\n".join(gem_details)
            ),
            color=0x1ABC9C,
        )
        return embed

    def _make_slot_callback(self, slot_idx: int):
        async def cb(interaction: discord.Interaction):
            gems = _get_user_gems(self.uid)
            if not gems:
                return await interaction.response.send_message("You have no gems / 你没有任何宝石", ephemeral=True)
            view = GemSelectForSocketView(self.uid, self.eq_id, slot_idx, self)
            embed = view.build_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        return cb

    def _make_remove_callback(self, slot_idx: int):
        async def cb(interaction: discord.Interaction):
            await interaction.response.defer()
            success, msg = _unsocket_gem(self.uid, self.eq_id, slot_idx)
            if self.main_view:
                self.main_view._build()
            self._build()
            embed = self.build_embed()
            await interaction.edit_original_response(embed=embed, view=self, content=msg if not success else f"✅ {msg}")
        return cb

    async def _open_socket_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        success, msg = _open_socket(self.uid, self.eq_id)
        self._build()
        embed = self.build_embed()
        await interaction.edit_original_response(embed=embed, view=self, content=f"{'✅' if success else '❌'} {msg}")

    async def _back_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if self.main_view:
            self.main_view._build()
            embed = self.main_view.build_embed()
            await interaction.edit_original_response(embed=embed, view=self.main_view, content="")

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class GemSelectForSocketView(discord.ui.View):
    """Select a gem from inventory to socket."""

    def __init__(self, uid: str, eq_id: str, slot_idx: int, equip_view: GemEquipView):
        super().__init__(timeout=180)
        self.uid = uid
        self.eq_id = eq_id
        self.slot_idx = slot_idx
        self.equip_view = equip_view
        self._build()

    def _build(self):
        self.clear_items()
        gems = _get_user_gems(self.uid)
        if not gems:
            return

        # Show gems as buttons (group by type+level)
        sorted_gems = sorted(gems.items(), key=lambda x: (x[0][0], -x[0][1]))
        for i, ((gem_type, level), qty) in enumerate(sorted_gems[:25]):
            info = GEM_TYPES.get(gem_type, {})
            row_idx = i // 3
            if row_idx > 3:
                break
            btn = discord.ui.Button(
                label=f"{info.get('emoji','')} {gem_type} Lv{level} x{qty}",
                style=discord.ButtonStyle.primary,
                row=row_idx,
            )
            btn.callback = self._make_select_callback(gem_type, level)
            self.add_item(btn)

        back_btn = discord.ui.Button(label="↩ Cancel 取消", style=discord.ButtonStyle.danger, row=4)
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    def build_embed(self):
        return discord.Embed(
            title="Select Gem / 选择宝石",
            description=f"Socket #{self.slot_idx + 1} — Choose a gem below / 选择一个宝石镶嵌到孔{self.slot_idx + 1}：",
            color=0x1ABC9C,
        )

    def _make_select_callback(self, gem_type: str, gem_level: int):
        async def cb(interaction: discord.Interaction):
            await interaction.response.defer()
            success, msg, _ = _socket_gem(self.uid, self.eq_id, self.slot_idx, gem_type, gem_level)
            if self.equip_view.main_view:
                self.equip_view.main_view._build()
            self.equip_view._build()
            embed = self.equip_view.build_embed()
            await interaction.edit_original_response(embed=embed, view=self.equip_view, content=f"{'✅' if success else '❌'} {msg}")
        return cb

    async def _back_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.equip_view._build()
        embed = self.equip_view.build_embed()
        await interaction.edit_original_response(embed=embed, view=self.equip_view, content="")


class GemShopView(discord.ui.View):
    """Buy gems from shop."""

    def __init__(self, uid: str, main_view: GemMainView = None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view
        self._build()

    def _build(self):
        self.clear_items()
        for i, (gem_type, price) in enumerate(GEM_SHOP_PRICE.items()):
            info = GEM_TYPES.get(gem_type, {})
            btn = discord.ui.Button(
                label=f"{info.get('emoji','')} {info.get('name_cn', gem_type)} Lv1 ({price}G)",
                style=discord.ButtonStyle.primary,
                row=i // 2,
            )
            btn.callback = self._make_buy_callback(gem_type)
            self.add_item(btn)
        back_btn = discord.ui.Button(label="↩ Back 返回", style=discord.ButtonStyle.danger, row=4)
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    def build_embed(self):
        bal = _get_balance(self.uid)
        desc = f"🪙 Balance: **{bal:,}**G\n\n"
        for gem_type, price in GEM_SHOP_PRICE.items():
            info = GEM_TYPES.get(gem_type, {})
            desc += f"{info.get('emoji','')} **{info.get('name_cn', gem_type)}** ({info.get('name_en', gem_type)}) — +{info.get('stat','')}%  |  **{price}**G\n"
        return discord.Embed(
            title="🛒 Gem Shop / 宝石商店",
            description=desc + "\nOnly Lv1 gems available / 只售卖Lv1宝石",
            color=0xF1C40F,
        )

    def _make_buy_callback(self, gem_type: str):
        async def cb(interaction: discord.Interaction):
            await interaction.response.defer()
            price = GEM_SHOP_PRICE[gem_type]
            bal = _get_balance(self.uid)
            if bal < price:
                await interaction.followup.send(f"Insufficient coins / 金币不足！Need {price:,}G, you have {bal:,}G", ephemeral=True)
                return
            _add_coins(self.uid, -price, f"Buy {gem_type} Lv1 gem")
            _add_gem_to_user(self.uid, gem_type, 1, 1)
            info = GEM_TYPES.get(gem_type, {})
            new_bal = _get_balance(self.uid)
            embed = self.build_embed()
            await interaction.edit_original_response(
                embed=embed, view=self,
                content=f"✅ Bought {info.get('emoji','')} {gem_type} Lv1! Balance: {new_bal:,}G"
            )
        return cb

    async def _back_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if self.main_view:
            self.main_view._build()
            embed = self.main_view.build_embed()
            await interaction.edit_original_response(embed=embed, view=self.main_view, content="")


class GemSynthView(discord.ui.View):
    """Synthesize gems: 3 low → 1 high."""

    def __init__(self, uid: str, main_view: GemMainView = None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view
        self._build()

    def _build(self):
        self.clear_items()
        gems = _get_user_gems(self.uid)

        for gem_type in GEM_TYPES:
            for lv in range(1, 5):
                key = (gem_type, lv)
                qty = gems.get(key, 0)
                if qty >= 3:
                    info = GEM_TYPES.get(gem_type, {})
                    btn = discord.ui.Button(
                        label=f"⚗️ 3x {info.get('name_cn', gem_type)} Lv{lv} → 1x Lv{lv+1} (have {qty})",
                        style=discord.ButtonStyle.success,
                    )
                    btn.callback = self._make_synth_callback(gem_type, lv)
                    self.add_item(btn)

        back_btn = discord.ui.Button(label="↩ Back 返回", style=discord.ButtonStyle.danger, row=4)
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    def build_embed(self):
        gems = _get_user_gems(self.uid)
        desc = "**Synthesis / 合成**: 3x LvN → 1x Lv(N+1)\n\n"
        has_any = False
        for gem_type in GEM_TYPES:
            info = GEM_TYPES.get(gem_type, {})
            parts = []
            for lv in range(1, 6):
                qty = gems.get((gem_type, lv), 0)
                if qty > 0:
                    parts.append(f"Lv{lv}:{qty}")
            if parts:
                desc += f"{info.get('emoji','')} {info.get('name_cn', gem_type)}: {' | '.join(parts)}\n"
                has_any = True
        if not has_any:
            desc += "You have no gems / 你没有任何宝石"

        return discord.Embed(
            title="⚗️ Gem Synthesis / 宝石合成",
            description=desc,
            color=0x9B59B6,
        )

    def _make_synth_callback(self, gem_type: str, source_level: int):
        async def cb(interaction: discord.Interaction):
            await interaction.response.defer()
            success, msg = _synthesize_gems(self.uid, gem_type, source_level)
            self._build()
            embed = self.build_embed()
            await interaction.edit_original_response(embed=embed, view=self, content=f"{'✅' if success else '❌'} {msg}")
        return cb

    async def _back_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if self.main_view:
            self.main_view._build()
            embed = self.main_view.build_embed()
            await interaction.edit_original_response(embed=embed, view=self.main_view, content="")


class GemInventoryView(discord.ui.View):
    """View user's gem inventory."""

    def __init__(self, uid: str, main_view: GemMainView = None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view
        self._build()

    def _build(self):
        self.clear_items()
        back_btn = discord.ui.Button(label="↩ Back 返回", style=discord.ButtonStyle.danger, row=4)
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    def build_embed(self):
        gems = _get_user_gems(self.uid)
        desc = ""
        for gem_type in GEM_TYPES:
            info = GEM_TYPES.get(gem_type, {})
            parts = []
            for lv in range(1, 6):
                qty = gems.get((gem_type, lv), 0)
                if qty > 0:
                    bonus = int(GEM_LEVEL_BONUS.get(lv, 0) * 100)
                    parts.append(f"Lv{lv} (+{bonus}% {info.get('stat','')}) x{qty}")
            if parts:
                desc += f"{info.get('emoji','')} **{info.get('name_cn', gem_type)}**: {' | '.join(parts)}\n"
        if not desc:
            desc = "You have no gems / 你没有任何宝石"

        return discord.Embed(
            title="🎒 My Gems / 宝石背包",
            description=desc,
            color=0x2ECC71,
        )

    async def _back_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if self.main_view:
            self.main_view._build()
            embed = self.main_view.build_embed()
            await interaction.edit_original_response(embed=embed, view=self.main_view, content="")


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════

class MMORPGGems(CogBase):
    """宝石镶嵌系统 / Gem Socket System"""

    def __init__(self, bot):
        super().__init__()
        _init_gem_tables()

    @app_commands.command(name="gmpt-gems", description="💎 宝石镶嵌 / Gem Socket System")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def gems_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        uname = interaction.user.display_name
        view = GemMainView(uid, uname)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(MMORPGGems(bot))
    logger.info("MMORPG Gems cog loaded")
