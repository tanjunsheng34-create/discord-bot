"""
cogs/mmorpg_enhance.py — Equipment Enhancement +1~+15 System / 装备强化系统
/gmpt-enhance — 装备强化面板
Set bonus system included (套装效果)
"""

import logging
import random
import discord
from discord import app_commands
from discord.ext import commands

from database import get_db_ctx
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Enhancement config
# ══════════════════════════════════════════════════════════════
ENHANCE_RATES = {
    0: 1.00, 1: 1.00, 2: 1.00,   # +1~+3 = 100%
    3: 0.80, 4: 0.80, 5: 0.80,   # +4~+6 = 80%
    6: 0.60, 7: 0.60, 8: 0.60,   # +7~+9 = 60%
    9: 0.40, 10: 0.40, 11: 0.40,  # +10~+12 = 40%
    12: 0.20, 13: 0.20, 14: 0.20,  # +13~+15 = 20%
}

ENHANCE_COSTS = {
    1: 100, 2: 200, 3: 400, 4: 600, 5: 1000,
    6: 2000, 7: 3500, 8: 5500, 9: 8000, 10: 12000,
    11: 18000, 12: 25000, 13: 35000, 14: 45000, 15: 50000,
}

EQUIP_SLOTS = ["weapon", "helmet", "armor", "leggings", "boots", "accessory"]

EQUIP_SLOT_LABELS_CN = {
    "weapon": "武器 Weapon",
    "helmet": "头盔 Helmet",
    "armor": "护甲 Armor",
    "leggings": "护腿 Leggings",
    "boots": "靴子 Boots",
    "accessory": "饰品 Accessory",
}

# ══════════════════════════════════════════════════════════════
# Set Bonus Definitions / 套装效果定义
# ══════════════════════════════════════════════════════════════
SET_DEFINITIONS = {
    "Dragon Set": {
        "name_cn": "龙族套装",
        "name_en": "Dragon Set",
        "emoji": "🐉",
        "slots": ["weapon", "armor", "accessory"],
        "bonus_2": {"hp_pct": 10},
        "bonus_3": {"effect": "burn", "desc_cn": "攻击附带灼烧(每回合3%最大HP)", "desc_en": "Attacks inflict Burn (3% max HP/turn)"},
    },
    "Shadow Set": {
        "name_cn": "暗影套装",
        "name_en": "Shadow Set",
        "emoji": "🌑",
        "slots": ["weapon", "helmet", "boots"],
        "bonus_2": {"hp_pct": 10},
        "bonus_3": {"effect": "double_crit", "desc_cn": "暴击率翻倍", "desc_en": "Crit rate doubled"},
    },
    "Holy Set": {
        "name_cn": "圣光套装",
        "name_en": "Holy Set",
        "emoji": "✨",
        "slots": ["helmet", "armor", "accessory"],
        "bonus_2": {"hp_pct": 10},
        "bonus_3": {"effect": "lifesteal", "desc_cn": "击杀回血(恢复造成伤害的20%)", "desc_en": "Heal 20% damage dealt on kill"},
    },
    "Storm Set": {
        "name_cn": "风暴套装",
        "name_en": "Storm Set",
        "emoji": "⚡",
        "slots": ["weapon", "helmet", "boots"],
        "bonus_2": {"hp_pct": 10},
        "bonus_3": {"effect": "double_attack", "desc_cn": "20%连击", "desc_en": "20% chance for double attack"},
    },
    "Earth Set": {
        "name_cn": "大地套装",
        "name_en": "Earth Set",
        "emoji": "🪨",
        "slots": ["armor", "leggings", "boots"],
        "bonus_2": {"hp_pct": 10},
        "bonus_3": {"effect": "dmg_reduce", "desc_cn": "受伤-15%", "desc_en": "Damage taken -15%"},
    },
    "Frost Set": {
        "name_cn": "冰霜套装",
        "name_en": "Frost Set",
        "emoji": "❄️",
        "slots": ["helmet", "armor", "accessory"],
        "bonus_2": {"hp_pct": 10},
        "bonus_3": {"effect": "freeze", "desc_cn": "攻击10%冻结", "desc_en": "10% chance to freeze on attack"},
    },
}


def get_set_bonus(equipped: dict) -> dict | None:
    """Check equipped items for set bonuses. Returns {set_name, count(2/3), bonus} or None."""
    best = None
    best_count = 0
    for set_name, cfg in SET_DEFINITIONS.items():
        count = 0
        for slot, eq in equipped.items():
            if eq and eq.get("set_name") == set_name and slot in cfg["slots"]:
                count += 1
        if count >= 2 and count > best_count:
            best = {"set_name": set_name, "count": count, "config": cfg}
            best_count = count
    return best


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════

def _init_enhance_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS equipment_enhance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                enhance_level INTEGER DEFAULT 0,
                UNIQUE(equipment_id, user_id)
            )
        """)
        # Add set_name column to user_equipment if not exists
        cur.execute("PRAGMA table_info(user_equipment)")
        cols = {r["name"] for r in cur.fetchall()}
        if "set_name" not in cols:
            cur.execute("ALTER TABLE user_equipment ADD COLUMN set_name VARCHAR DEFAULT NULL")
        conn.commit()

_init_enhance_tables()


# ══════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════

def _get_enhance_rate(from_level: int) -> float:
    return ENHANCE_RATES.get(from_level, 0.20)


def _get_enhance_cost(from_level: int) -> int:
    level = from_level + 1
    return ENHANCE_COSTS.get(level, 50000)


def _get_equipped(user_id: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT slot, name, quality, stat, stat_value, enhance_level, emoji, item_id, set_name FROM user_equipment WHERE user_id=?",
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
            "item_id": r["item_id"],
            "set_name": r["set_name"],
        }
    return result


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


def _get_user_stats(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT level, hp, max_hp, mp, max_mp, attack, defense, element FROM users WHERE discord_id = ?",
            (uid,),
        )
        row = cur.fetchone()
    if not row:
        return {"level": 1, "hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50, "attack": 10, "defense": 5, "element": None}
    return dict(row)


async def _do_single_enhance(uid: str, slot: str, eq: dict, lvl: int) -> tuple:
    """Execute a single enhancement attempt. Returns (success, new_level, message)."""
    if lvl >= 15:
        return (False, lvl, "Already max level +15 / 已达最大强化等级！")

    cost = _get_enhance_cost(lvl)
    rate = _get_enhance_rate(lvl)
    bal = _get_balance(uid)

    if bal < cost:
        return (False, lvl, f"Insufficient coins / 金币不足！Need {cost:,}, you have {bal:,}")

    reason = f"Enhance {eq['name']} +{lvl}→+{lvl+1}"

    try:
        _add_coins(uid, -cost, reason)

        success = random.random() < rate
        if success:
            new_lvl = lvl + 1
            # Apply stat growth: base * (1 + new_lvl * 0.05) / (1 + lvl * 0.05)
            if isinstance(eq["stat_value"], (int, float)) and lvl > 0:
                base_stat = int(eq["stat_value"] / (1 + lvl * 0.05))
                new_stat = int(base_stat * (1 + new_lvl * 0.05))
            else:
                base_stat = int(eq["stat_value"]) if isinstance(eq["stat_value"], (int, float)) else 0
                new_stat = int(base_stat * (1 + new_lvl * 0.05))
        else:
            new_lvl = max(0, lvl - random.randint(1, 3))
            new_stat = int(eq["stat_value"].real if hasattr(eq["stat_value"], 'real') else eq["stat_value"]) if isinstance(eq["stat_value"], (int, float)) else eq["stat_value"]
            if new_lvl > 0 and isinstance(eq["stat_value"], (int, float)):
                old_base = int(eq["stat_value"] / (1 + lvl * 0.05)) if lvl > 0 else int(eq["stat_value"])
                new_stat = int(old_base * (1 + new_lvl * 0.05))

        with get_db_ctx() as conn:
            conn.execute(
                "UPDATE user_equipment SET enhance_level = ?, stat_value = ? WHERE user_id = ? AND slot = ?",
                (new_lvl, str(new_stat), uid, slot),
            )
            # Sync to equipment_enhance table
            item_id = eq.get("item_id", f"{slot}_{eq.get('name','')}")
            conn.execute(
                "INSERT INTO equipment_enhance (equipment_id, user_id, enhance_level) VALUES (?, ?, ?) "
                "ON CONFLICT(equipment_id, user_id) DO UPDATE SET enhance_level = ?",
                (item_id, uid, new_lvl, new_lvl),
            )
            conn.commit()

        new_bal = _get_balance(uid)
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
                    f"**{eq['name']}**: +{lvl} → **+{new_lvl}** (Dropped -{lvl - new_lvl} / 降级)\n"
                    f"Cost / 花费: {cost:,}G  |  Balance / 余额: **{new_bal:,}**"
                )
            else:
                msg = (
                    f"## 💥 Enhancement Failed / 强化失败！\n"
                    f"**{eq['name']}**: +{lvl} (No change / 不变)\n"
                    f"Cost / 花费: {cost:,}G  |  Balance / 余额: **{new_bal:,}**"
                )

        return (success, new_lvl, msg)
    except Exception as e:
        logger.error(f"_do_single_enhance error (uid={uid}, slot={slot}, lvl={lvl}): {e}", exc_info=True)
        try:
            _add_coins(uid, cost, f"Refund: {reason}")
        except Exception:
            pass
        return (False, lvl, f"Enhancement error: {e}")


# ══════════════════════════════════════════════════════════════
# Views / UI
# ══════════════════════════════════════════════════════════════

class EnhanceMainView(discord.ui.View):
    """Main enhancement panel — lists equipped items for enhancement."""

    def __init__(self, uid: str, user_name: str = None, main_view=None):
        super().__init__(timeout=600)
        self.uid = uid
        self.user_name = user_name
        self.main_view = main_view
        self._build()

    def _build(self):
        self.clear_items()
        equipped = _get_equipped(self.uid)

        options = []
        for slot in EQUIP_SLOTS:
            eq = equipped.get(slot)
            if eq:
                lvl = eq.get("enhance_level", 0)
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
                        description=f"Cost: {cost:,}G | Rate: {int(rate*100)}%",
                        emoji="🔨",
                    ))

        if options:
            select = discord.ui.Select(
                placeholder="Select equipment to enhance / 选择要强化的装备",
                options=options,
                row=0,
            )
            select.callback = self._select_callback
            self.add_item(select)

        # Back button
        if self.main_view:
            back_btn = discord.ui.Button(
                label="🏠 Back 返回", style=discord.ButtonStyle.secondary, row=4,
            )
            back_btn.callback = self._back_callback
            self.add_item(back_btn)

    def build_embed(self) -> discord.Embed:
        equipped = _get_equipped(self.uid)
        bal = _get_balance(self.uid)
        set_bonus = get_set_bonus(equipped)

        embed = discord.Embed(
            title="🔨 装备强化 / Equipment Enhancement",
            description=f"🪙 **余额 Balance**: {bal:,}G\n\n**Enhance Rates / 强化成功率:**\n+1~+3=100% | +4~+6=80% | +7~+9=60% | +10~+12=40% | +13~+15=20%\n**Fail / 失败**: 随机降级1-3级 / Drops 1-3 levels randomly",
            color=0xE67E22,
        )

        QUALITY_MARKS = {"common": "⚪", "rare": "🔵", "epic": "🟣", "legendary": "🟡"}
        for slot in EQUIP_SLOTS:
            eq = equipped.get(slot)
            if eq:
                lvl = eq.get("enhance_level", 0)
                mark = QUALITY_MARKS.get(eq.get("quality", "common"), "⚪")
                set_tag = f" [{eq.get('set_name','')}]" if eq.get("set_name") else ""
                val = f"{mark} **{eq['name']}** +{lvl}{set_tag}\nSTAT: {eq.get('stat','')} {eq.get('stat_value','')}"
            else:
                val = "⬜ 空 / Empty"
            embed.add_field(name=EQUIP_SLOT_LABELS_CN[slot], value=val, inline=True)

        if set_bonus:
            cfg = set_bonus["config"]
            embed.add_field(
                name=f"{cfg['emoji']} 套装效果 / Set Bonus: {cfg['name_cn']} ({set_bonus['count']}/3)",
                value=f"2件: +10% HP\n3件: {cfg['bonus_3']['desc_cn']} / {cfg['bonus_3']['desc_en']}",
                inline=False,
            )

        return embed

    async def _select_callback(self, interaction: discord.Interaction):
        try:
            slot = interaction.data["values"][0]
            equipped = _get_equipped(self.uid)
            eq = equipped.get(slot)
            if not eq:
                return await interaction.response.send_message("Not equipped / 未装备", ephemeral=True)

            lvl = eq.get("enhance_level", 0)
            if lvl >= 15:
                return await interaction.response.send_message("Already max +15!", ephemeral=True)

            view = EnhanceTargetView(self.uid, slot, eq, lvl, self)
            embed = view.build_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            logger.error(f"EnhanceMainView _select_callback error: {e}", exc_info=True)
            try:
                await interaction.response.send_message("Error / 出错", ephemeral=True)
            except Exception:
                pass

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            try:
                # Check if main_view is DashboardView (has CATEGORY_TITLES)
                if hasattr(self.main_view, "build_page_buttons"):
                    self.main_view.build_page_buttons()
                    embed = discord.Embed(
                        title=self.main_view.CATEGORY_TITLES.get(self.main_view.category, "GMPT Dashboard"),
                        color=self.main_view.CATEGORY_COLORS.get(self.main_view.category, 0x9B59B6),
                    )
                else:
                    # Standalone mode — return to MMORPG panel
                    stats = _get_user_stats(self.uid)
                    bal = _get_balance(self.uid)
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
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
            except Exception:
                await interaction.response.edit_message(content="Back — use `/dashboard` to reopen.", view=None)
        else:
            await interaction.response.edit_message(content="Use `/dashboard` to reopen / 使用 `/dashboard` 重新打开", view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class EnhanceTargetView(discord.ui.View):
    """Single equipment enhancement view with +1, Max, Target options."""

    def __init__(self, uid: str, slot: str, eq: dict, lvl: int, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.slot = slot
        self.eq = eq
        self.lvl = lvl
        self.main_view = main_view
        self._locked = False

        # Target level select
        target_options = []
        for target in range(lvl + 1, 16):
            cost_est = sum(_get_enhance_cost(l) for l in range(lvl, target))
            target_options.append(discord.SelectOption(
                label=f"🎯 +{target}",
                value=str(target),
                description=f"Est. cost: {cost_est:,}G" if target <= lvl + 3 else f"Target +{target}",
            ))
        if target_options:
            self._target_select = discord.ui.Select(
                placeholder=f"Target level / 目标等级 (current +{lvl})",
                options=target_options[:25],
                row=0,
            )
            self._target_select.callback = self._target_callback
            self.add_item(self._target_select)

        # Buttons row 1
        self._plus_one_btn = discord.ui.Button(
            label="🔨 +1 强化一次", style=discord.ButtonStyle.primary, row=1,
        )
        self._plus_one_btn.callback = self._plus_one_callback
        self.add_item(self._plus_one_btn)

        self._max_btn = discord.ui.Button(
            label="⚡ 强化至最高", style=discord.ButtonStyle.success, row=1,
        )
        self._max_btn.callback = self._max_callback
        self.add_item(self._max_btn)

        # Back button row 2
        self._back_btn = discord.ui.Button(
            label="↩ 返回 Back", style=discord.ButtonStyle.secondary, row=2,
        )
        self._back_btn.callback = self._back_callback
        self.add_item(self._back_btn)

    def build_embed(self):
        cost = _get_enhance_cost(self.lvl)
        rate = _get_enhance_rate(self.lvl)
        bal = _get_balance(self.uid)

        embed = discord.Embed(
            title=f"🔨 Enhance: {self.eq['name']}",
            description=(
                f"**Slot / 槽位**: {EQUIP_SLOT_LABELS_CN.get(self.slot, self.slot)}\n"
                f"**Current Level / 当前等级**: +{self.lvl}\n"
                f"**Next Success Rate / 下一级成功率**: {int(rate * 100)}%\n"
                f"**Next Cost / 下一级花费**: {cost:,}G\n"
                f"**Balance / 余额**: {bal:,}G\n\n"
                f"*Failure drops -1~-3 levels / 失败随机降1~3级*"
            ),
            color=0xE67E22,
        )
        return embed

    async def _refresh(self, interaction, content: str = ""):
        try:
            embed = self.build_embed()
            await interaction.edit_original_response(content=content, embed=embed, view=self)
        except Exception as e:
            logger.error(f"EnhanceTargetView _refresh error: {e}")

    async def _plus_one_callback(self, interaction: discord.Interaction):
        if self._locked:
            return await interaction.response.send_message("Processing... / 处理中...", ephemeral=True)
        self._locked = True
        try:
            await interaction.response.defer()
            success, new_lvl, msg = await _do_single_enhance(self.uid, self.slot, self.eq, self.lvl)
            self.lvl = new_lvl
            equipped = _get_equipped(self.uid)
            self.eq = equipped.get(self.slot, self.eq)

            if self.main_view:
                self.main_view._build()

            if self.lvl >= 15:
                self._plus_one_btn.disabled = True
                self._max_btn.disabled = True
            await self._refresh(interaction, content=f"**+1 Result**: {msg[:400]}")
        except Exception as e:
            logger.error(f"_plus_one_callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"Error: {e}", ephemeral=True)
            except Exception:
                pass
        finally:
            self._locked = False

    async def _max_callback(self, interaction: discord.Interaction):
        if self._locked:
            return await interaction.response.send_message("Processing... / 处理中...", ephemeral=True)
        self._locked = True
        try:
            await interaction.response.defer()
            import asyncio
            messages = []
            attempts = 0

            while self.lvl < 15 and attempts < 30:
                cost = _get_enhance_cost(self.lvl)
                bal = _get_balance(self.uid)
                if bal < cost:
                    messages.append(f"Insufficient coins (need {cost:,}G)")
                    break

                old_lvl = self.lvl
                success, new_lvl, _ = await _do_single_enhance(self.uid, self.slot, self.eq, self.lvl)
                self.lvl = new_lvl
                equipped = _get_equipped(self.uid)
                self.eq = equipped.get(self.slot, self.eq)
                attempts += 1

                if success:
                    messages.append(f"+{old_lvl}→+{new_lvl} ✓")
                    await self._refresh(interaction, content=" | ".join(messages[-5:]))
                    await asyncio.sleep(0.6)
                else:
                    if new_lvl < old_lvl:
                        messages.append(f"Failed (dropped +{old_lvl}→+{new_lvl}) ✗")
                    else:
                        messages.append(f"Failed (no change, stayed +{old_lvl}) ✗")
                    break

            if self.main_view:
                self.main_view._build()
            self._plus_one_btn.disabled = True
            self._max_btn.disabled = True
            summary = f"## ⚡ Max Enhance Complete\n" + "\n".join(messages[-12:])
            await self._refresh(interaction, content=summary)
        except Exception as e:
            logger.error(f"_max_callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"Error: {e}", ephemeral=True)
            except Exception:
                pass
        finally:
            self._locked = False

    async def _target_callback(self, interaction: discord.Interaction):
        if self._locked:
            return await interaction.response.send_message("Processing... / 处理中...", ephemeral=True)
        self._locked = True
        try:
            await interaction.response.defer()
            target = int(interaction.data["values"][0])
            import asyncio
            messages = []
            attempts = 0

            while self.lvl < target and attempts < 30:
                if self.lvl >= 15:
                    messages.append("Already max +15!")
                    break

                cost = _get_enhance_cost(self.lvl)
                bal = _get_balance(self.uid)
                if bal < cost:
                    messages.append(f"Insufficient coins (need {cost:,}G)")
                    break

                old_lvl = self.lvl
                success, new_lvl, _ = await _do_single_enhance(self.uid, self.slot, self.eq, self.lvl)
                self.lvl = new_lvl
                equipped = _get_equipped(self.uid)
                self.eq = equipped.get(self.slot, self.eq)
                attempts += 1

                if success:
                    messages.append(f"+{old_lvl}→+{new_lvl} ✓")
                    await self._refresh(interaction, content=f"Target +{target} | " + " | ".join(messages[-5:]))
                    await asyncio.sleep(0.6)
                else:
                    if new_lvl < old_lvl:
                        messages.append(f"Failed (dropped +{old_lvl}→+{new_lvl}) ✗")
                    else:
                        messages.append(f"Failed (no change, stayed +{old_lvl}) ✗")
                    break

            if self.main_view:
                self.main_view._build()
            target_reached = self.lvl >= target
            icon = "✅" if target_reached else "❌"
            status = "Reached" if target_reached else "Not Reached"
            summary = f"## {icon} Target +{target} {status}\n" + "\n".join(messages[-12:])
            if not target_reached:
                self._plus_one_btn.disabled = (self.lvl >= 15)
                self._max_btn.disabled = (self.lvl >= 15)
            else:
                self._plus_one_btn.disabled = True
                self._max_btn.disabled = True
            await self._refresh(interaction, content=summary)
        except Exception as e:
            logger.error(f"_target_callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"Error: {e}", ephemeral=True)
            except Exception:
                pass
        finally:
            self._locked = False

    async def _back_callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
            if self.main_view:
                self.main_view._build()
                embed = self.main_view.build_embed()
                await interaction.edit_original_response(embed=embed, view=self.main_view, content="")
        except Exception as e:
            logger.error(f"EnhanceTargetView _back_callback error: {e}", exc_info=True)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════

class MMORPGEnhance(CogBase):
    """装备强化系统 / Equipment Enhancement System"""

    def __init__(self, bot):
        super().__init__()
        _init_enhance_tables()

    @app_commands.command(name="gmpt-enhance", description="🔨 装备强化 / Equipment Enhancement +1~+15")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def enhance_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        uname = interaction.user.display_name
        view = EnhanceMainView(uid, uname)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(MMORPGEnhance(bot))
    logger.info("MMORPG Enhance cog loaded")
