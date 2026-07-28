"""
GMPT Bot — MMORPG  NPC 药水商店 / NPC Potion Shop
/gmpt-potionshop browse  — 浏览所有药水（分页）
/gmpt-potionshop buy     — 购买药水（autocomplete 药水名）
/gmpt-potionshop inventory — 查看自己的药水背包
/gmpt-potionshop use     — 使用背包中的药水
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

ITEMS_PER_PAGE = 5


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


class PotionShop(CogBase):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    # ── Autocomplete for potion names ──
    async def _potion_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM potions ORDER BY min_level")
            rows = cur.fetchall()
        names = [r["name"] for r in rows]
        if current:
            names = [n for n in names if current.lower() in n.lower()]
        return [app_commands.Choice(name=n, value=n) for n in names[:25]]

    # ══════════════════════════════════════════════════════════
    # /gmpt-mmorpg — MMORPG 主面板
    # ══════════════════════════════════════════════════════════
    @app_commands.command(name="gmpt-mmorpg", description="🗡️ MMORPG 主面板 / MMORPG Main Panel")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def mmorpg_panel(self, interaction: discord.Interaction):
        """MMORPG 主面板：商店 / 技能 / PVP / Boss 四大入口."""
        uid = str(interaction.user.id)
        stats = _get_user_stats(uid)
        bal = _get_balance(uid)

        embed = discord.Embed(
            title="🗡️ MMORPG 主面板 / MMORPG Main Panel",
            description=(
                f"欢迎来到 GMPT MMORPG 世界！\nWelcome to the GMPT MMORPG world!\n\n"
                f"❤️ HP: **{stats['hp']}/{stats['max_hp']}**　"
                f"🔮 MP: **{stats['mp']}/{stats['max_mp']}**\n"
                f"⚔️ ATK: **{stats['attack']}**　🛡️ DEF: **{stats['defense']}**　"
                f"⭐ Lv.**{stats['level']}**　🪙 **{bal:,}**\n\n"
                f"点击下方按钮查看各系统 / Click a button below:"
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
        description="NPC 药水商店 / NPC Potion Shop",
    )

    @potionshop_group.command(name="browse", description="浏览所有药水 / Browse all potions")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def browse_cmd(self, interaction: discord.Interaction):
        """列出所有 potions 表药水，带按钮翻页."""
        uid = str(interaction.user.id)
        user_level = _get_user_level(uid)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM potions ORDER BY min_level, price")
            potions = [dict(r) for r in cur.fetchall()]

        if not potions:
            return await interaction.response.send_message("商店暂无药水 / No potions available.", ephemeral=True)

        view = PotionBrowseView(potions, user_level, uid)
        embed = view.build_embed(0)
        await interaction.response.send_message(embed=embed, view=view)

    @potionshop_group.command(name="buy", description="购买药水 / Buy a potion")
    @app_commands.describe(name="药水名称 / Potion name", quantity="购买数量 / Quantity (default 1)")
    @app_commands.autocomplete(name=_potion_autocomplete)
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: (i.guild_id, i.user.id))
    async def buy_cmd(self, interaction: discord.Interaction, name: str, quantity: int = 1):
        """购买药水."""
        uid = str(interaction.user.id)
        if quantity < 1:
            return await interaction.response.send_message("数量必须大于0 / Quantity must be > 0.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM potions WHERE name = ?", (name,))
            potion = cur.fetchone()

        if not potion:
            return await interaction.response.send_message(
                f"药水 '{name}' 不存在 / Potion not found.", ephemeral=True
            )

        potion = dict(potion)
        user_level = _get_user_level(uid)

        if user_level < potion["min_level"]:
            return await interaction.response.send_message(
                f"等级不足！需要 Lv.{potion['min_level']}，你当前 Lv.{user_level}\n"
                f"Level too low! Requires Lv.{potion['min_level']}, you are Lv.{user_level}",
                ephemeral=True,
            )

        total_cost = potion["price"] * quantity
        bal = _get_balance(uid)

        if bal < total_cost:
            return await interaction.response.send_message(
                f"余额不足！需要 🪙 {total_cost:,}，你只有 🪙 {bal:,}\n"
                f"Insufficient balance! Need 🪙 {total_cost:,}, you have 🪙 {bal:,}",
                ephemeral=True,
            )

        # Check stock
        if potion["stock"] != -1 and potion["stock"] < quantity:
            return await interaction.response.send_message(
                f"库存不足！仅有 {potion['stock']} 个 / Insufficient stock! Only {potion['stock']} left.",
                ephemeral=True,
            )

        # Deduct coins
        _add_coins(uid, -total_cost, f"购买药水 {name} x{quantity} / Bought potion {name} x{quantity}")

        # Decrease stock if not unlimited
        if potion["stock"] != -1:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE potions SET stock = stock - ? WHERE id = ?", (quantity, potion["id"]))
                conn.commit()

        # Add to user_inventory
        with get_db_ctx() as conn:
            cur = conn.cursor()
            # Check if user already has this potion in inventory
            cur.execute(
                "SELECT id, quantity FROM user_inventory WHERE user_id = ? AND item_id = 0 AND item_name = ? AND item_type = 'potion'",
                (uid, name),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    "UPDATE user_inventory SET quantity = quantity + ? WHERE id = ?",
                    (quantity, existing["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) VALUES (?, 0, ?, ?, 'potion')",
                    (uid, name, quantity),
                )
            conn.commit()

        new_bal = _get_balance(uid)
        embed = discord.Embed(
            title=f"{potion['emoji']} 购买成功 / Purchase Complete",
            description=f"购买了 **{name}** x{quantity}，花费 🪙 **{total_cost:,}**",
            color=0x2ECC71,
        )
        embed.add_field(name="💰 余额 / Balance", value=f"🪙 {new_bal:,}", inline=True)
        embed.add_field(name="🧪 效果 / Effect", value=potion["description"], inline=False)
        await interaction.response.send_message(embed=embed)

    @potionshop_group.command(name="inventory", description="查看药水背包 / View potion inventory")
    @app_commands.checks.cooldown(1, 2.0, key=lambda i: (i.guild_id, i.user.id))
    async def inventory_cmd(self, interaction: discord.Interaction):
        """查看自己的药水背包."""
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
                "药水背包是空的！去 `/gmpt-potionshop browse` 买一些吧。\n"
                "Your potion bag is empty! Visit `/gmpt-potionshop browse` to buy some.",
                ephemeral=True,
            )

        # Get effect info from potions table
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name, emoji, description, effect_type FROM potions")
            potion_map = {r["name"]: dict(r) for r in cur.fetchall()}

        lines = []
        for row in rows:
            p = potion_map.get(row["item_name"], {})
            emoji = p.get("emoji", "🧪")
            desc = p.get("description", "")
            lines.append(f"{emoji} **{row['item_name']}** x{row['quantity']} — {desc}")

        embed = discord.Embed(
            title=f"🎒 {interaction.user.display_name} 的药水背包 / Potion Bag",
            description="\n".join(lines) if lines else "空空如也 / Empty",
            color=0x9B59B6,
        )
        embed.set_footer(text="使用 /gmpt-potionshop use <药水名> 来喝药水")
        await interaction.response.send_message(embed=embed)

    @potionshop_group.command(name="use", description="使用药水 / Use a potion from your bag")
    @app_commands.describe(name="药水名称 / Potion name")
    @app_commands.autocomplete(name=_potion_autocomplete)
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def use_cmd(self, interaction: discord.Interaction, name: str):
        """使用背包中的药水."""
        uid = str(interaction.user.id)

        # Check if user has this potion in inventory
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, quantity FROM user_inventory WHERE user_id = ? AND item_id = 0 AND item_name = ? AND item_type = 'potion'",
                (uid, name),
            )
            inv_row = cur.fetchone()

        if not inv_row or inv_row["quantity"] <= 0:
            return await interaction.response.send_message(
                f"背包中没有 **{name}**！\nYou don't have **{name}** in your bag.",
                ephemeral=True,
            )

        # Get potion template
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM potions WHERE name = ?", (name,))
            potion = cur.fetchone()

        if not potion:
            return await interaction.response.send_message(
                f"药水模板 '{name}' 不存在 / Potion template not found.", ephemeral=True
            )

        potion = dict(potion)
        effect_type = potion["effect_type"]
        effect_value = potion["effect_value"]
        duration = potion["duration_minutes"]

        # Check level requirement
        user_level = _get_user_level(uid)
        if user_level < potion["min_level"]:
            return await interaction.response.send_message(
                f"等级不足！需要 Lv.{potion['min_level']} 才能使用此药水。",
                ephemeral=True,
            )

        # Consume 1 from inventory
        if inv_row["quantity"] > 1:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE user_inventory SET quantity = quantity - 1 WHERE id = ?",
                    (inv_row["id"],),
                )
                conn.commit()
        else:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM user_inventory WHERE id = ?", (inv_row["id"],))
                conn.commit()

        # Apply effect
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
                title=f"{potion['emoji']} 使用 {name}",
                description=f"恢复了 **{healed}** HP！（{cur_hp} → {new_hp} / {max_hp}）",
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
                title=f"{potion['emoji']} 使用 {name}",
                description=f"恢复了 **{healed}** MP！（{cur_mp} → {new_mp} / {max_mp}）",
                color=0x3498DB,
            )

        elif effect_type == "buff_atk":
            expires = datetime.datetime.now() + datetime.timedelta(minutes=duration)
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO active_buffs (user_id, buff_type, value, expires_at) VALUES (?, 'atk_up', ?, ?)",
                    (uid, effect_value, expires.isoformat()),
                )
                conn.commit()
            embed = discord.Embed(
                title=f"{potion['emoji']} 使用 {name}",
                description=f"攻击力 **+{effect_value}**，持续 **{duration}** 分钟！\nATK +{effect_value} for {duration} minutes!",
                color=0xE67E22,
            )

        elif effect_type == "buff_def":
            expires = datetime.datetime.now() + datetime.timedelta(minutes=duration)
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO active_buffs (user_id, buff_type, value, expires_at) VALUES (?, 'def_up', ?, ?)",
                    (uid, effect_value, expires.isoformat()),
                )
                conn.commit()
            embed = discord.Embed(
                title=f"{potion['emoji']} 使用 {name}",
                description=f"防御力 **+{effect_value}**，持续 **{duration}** 分钟！\nDEF +{effect_value} for {duration} minutes!",
                color=0x1ABC9C,
            )

        elif effect_type == "revive":
            stats = _get_user_stats(uid)
            cur_hp = stats["hp"]
            if cur_hp > 0:
                # Refund — can't use revive while alive
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) VALUES (?, 0, ?, 1, 'potion')",
                        (uid, name),
                    )
                    conn.commit()
                return await interaction.response.send_message(
                    "你还活着！复活药剂只能在 HP=0 时使用。\nYou're still alive! Revive potion can only be used when HP=0.",
                    ephemeral=True,
                )

            max_hp = stats["max_hp"]
            max_mp = stats["max_mp"]
            restore_hp = max(1, int(max_hp * 0.5))
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE users SET hp = ?, mp = ? WHERE discord_id = ?",
                    (restore_hp, max_mp, uid),
                )
                conn.commit()
            embed = discord.Embed(
                title=f"{potion['emoji']} 使用 {name}",
                description=f"✨ 复活成功！HP 恢复到 **{restore_hp}** / {max_hp}，MP 全满！\nRevived! HP restored to {restore_hp}/{max_hp}, MP fully restored!",
                color=0xF1C40F,
            )

        else:
            return await interaction.response.send_message(
                f"未知药水类型: {effect_type}", ephemeral=True
            )

        embed.set_footer(text=f"背包中剩余: 查看 /gmpt-potionshop inventory")
        await interaction.response.send_message(embed=embed)


class MMORPGMainView(discord.ui.View):
    """MMORPG 主面板按钮：商店 / 技能 / PVP / Boss."""

    def __init__(self, user_id: str):
        super().__init__(timeout=180)
        self.user_id = user_id

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("这不是你的面板 / Not your panel.", ephemeral=True)
            return False
        return True

    def _build_sub_embed(self, title: str, color: int, desc: str) -> discord.Embed:
        embed = discord.Embed(title=title, color=color)
        embed.description = desc
        embed.set_footer(text="使用方向键或 /gmpt-mmorpg 回到主面板")
        return embed

    @discord.ui.button(label="🧪 药水商店", style=discord.ButtonStyle.primary, row=0)
    async def shop_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**NPC 药水商店 / Potion Shop**\n\n"
            "🛒 `/gmpt-potionshop browse` — 浏览所有药水\n"
            "💰 `/gmpt-potionshop buy <药水名> [数量]` — 购买药水\n"
            "🎒 `/gmpt-potionshop inventory` — 查看背包\n"
            "🧪 `/gmpt-potionshop use <药水名>` — 使用药水\n\n"
            "药水种类：治疗/回蓝/攻击Buff/防御Buff/复活"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("🧪 药水商店 / Potion Shop", 0x3498DB, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("🧪 药水商店 / Potion Shop", 0x3498DB, desc), view=self
            )

    @discord.ui.button(label="⚔️ 技能", style=discord.ButtonStyle.primary, row=0)
    async def skills_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**技能系统 / Skill System**\n\n"
            "📚 `!learn <技能名>` — 学习技能\n"
            "📋 `!skills list` — 查看可学技能\n"
            "✅ `!equip <技能名>` — 装备技能\n"
            "❌ `!unequip <技能名>` — 卸下技能\n\n"
            "技能可在 PVP 和 Boss 战中使用！"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("⚔️ 技能系统 / Skills", 0xE67E22, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("⚔️ 技能系统 / Skills", 0xE67E22, desc), view=self
            )

    @discord.ui.button(label="🏆 PVP 对战", style=discord.ButtonStyle.primary, row=0)
    async def pvp_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**PVP 对战系统 / PVP Arena**\n\n"
            "⚔️ `!pvp_accept` — 接受挑战\n"
            "🚫 `!pvp_decline` — 拒绝挑战\n"
            "👊 `/gmpt-duel challenge` — 发起对决\n\n"
            "使用技能和药水在战斗中获得优势！"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("🏆 PVP 对战 / PVP Arena", 0xE74C3C, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("🏆 PVP 对战 / PVP Arena", 0xE74C3C, desc), view=self
            )

    @discord.ui.button(label="🐉 Boss 战", style=discord.ButtonStyle.danger, row=0)
    async def boss_btn(self, interaction: discord.Interaction, button):
        desc = (
            "**Boss 战系统 / Boss Battle**\n\n"
            "👥 `!boss_invite` — 邀请组队\n"
            "🚫 `!boss_kick` — 踢出成员\n"
            "⚔️ `!boss_attack` — 攻击 Boss\n"
            "🧪 `!boss_use_potion` — 使用药水\n\n"
            "组队挑战强大的 Boss 平分奖励！"
        )
        try:
            await interaction.response.edit_message(
                embed=self._build_sub_embed("🐉 Boss 战 / Boss Battle", 0xC0392B, desc), view=self
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                embed=self._build_sub_embed("🐉 Boss 战 / Boss Battle", 0xC0392B, desc), view=self
            )

    @discord.ui.button(label="🏠 主面板", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button):
        uid = str(interaction.user.id)
        stats = _get_user_stats(uid)
        bal = _get_balance(uid)
        embed = discord.Embed(
            title="🗡️ MMORPG 主面板 / MMORPG Main Panel",
            description=(
                f"欢迎来到 GMPT MMORPG 世界！\nWelcome to the GMPT MMORPG world!\n\n"
                f"❤️ HP: **{stats['hp']}/{stats['max_hp']}**　"
                f"🔮 MP: **{stats['mp']}/{stats['max_mp']}**\n"
                f"⚔️ ATK: **{stats['attack']}**　🛡️ DEF: **{stats['defense']}**　"
                f"⭐ Lv.**{stats['level']}**　🪙 **{bal:,}**\n\n"
                f"点击下方按钮查看各系统 / Click a button below:"
            ),
            color=0x9B59B6,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)


class PotionBrowseView(discord.ui.View):
    """分页浏览药水."""

    def __init__(self, potions: list[dict], user_level: int, user_id: str):
        super().__init__(timeout=120)
        self.potions = potions
        self.user_level = user_level
        self.user_id = user_id
        self.page = 0
        self.total_pages = max(1, (len(potions) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self._update_buttons()

    def build_embed(self, page: int) -> discord.Embed:
        start = page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_items = self.potions[start:end]

        embed = discord.Embed(
            title="🧪 NPC 药水商店 / Potion Shop",
            description=f"你的等级: **Lv.{self.user_level}**\n",
            color=0x9B59B6,
        )

        lines = []
        for p in page_items:
            locked = "🔒" if self.user_level < p["min_level"] else ""
            stock_str = "∞" if p["stock"] == -1 else str(p["stock"])
            lines.append(
                f"{p['emoji']} **{p['name']}** {locked}\n"
                f"　{p['description']} | 🪙 {p['price']:,} | 库存: {stock_str}\n"
                f"　等级要求: Lv.{p['min_level']}"
            )

        embed.add_field(
            name=f"药水列表 (第 {page + 1}/{self.total_pages} 页)",
            value="\n".join(lines) if lines else "暂无药水",
            inline=False,
        )
        embed.set_footer(text="使用 /gmpt-potionshop buy <药水名> <数量> 购买")
        return embed

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="◀ 上一页", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("这不是你的页面 / Not your page.", ephemeral=True)
        self.page -= 1
        self._update_buttons()
        try:
            await interaction.response.edit_message(embed=self.build_embed(self.page), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(self.page), view=self)

    @discord.ui.button(label="下一页 ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("这不是你的页面 / Not your page.", ephemeral=True)
        self.page += 1
        self._update_buttons()
        try:
            await interaction.response.edit_message(embed=self.build_embed(self.page), view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=self.build_embed(self.page), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


async def setup(bot):
    await bot.add_cog(PotionShop(bot))
