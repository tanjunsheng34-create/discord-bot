"""
GMPT Bot — MMORPG Pet System / 宠物系统
/gmpt-pet — 宠物管理

5种宠物蛋按稀有度孵化，宠物可升星、切换、出战。
出战宠物属性叠加到玩家战斗属性。
"""
import logging
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Pet Catalog: (name_cn, name_en, rarity, emoji, egg_emoji, drop_rate, cost, atk, def, hp)
# ══════════════════════════════════════════════════════════════
PET_CATALOG = {
    "common": {
        "name_cn": "小史莱姆", "name_en": "Slime",
        "rarity_cn": "普通", "rarity_en": "Common",
        "egg_emoji": "🥚", "pet_emoji": "🟢",
        "drop_rate": 0.50, "cost": 500,
        "atk": 0, "def": 0, "hp": 5,
    },
    "rare": {
        "name_cn": "幼龙 Whelp", "name_en": "Whelp",
        "rarity_cn": "稀有", "rarity_en": "Rare",
        "egg_emoji": "🥚", "pet_emoji": "🔵",
        "drop_rate": 0.25, "cost": 1500,
        "atk": 10, "def": 0, "hp": 0,
    },
    "epic": {
        "name_cn": "影狼", "name_en": "Shadow Wolf",
        "rarity_cn": "史诗", "rarity_en": "Epic",
        "egg_emoji": "🥚", "pet_emoji": "🟣",
        "drop_rate": 0.15, "cost": 3000,
        "atk": 15, "def": 5, "hp": 0,
    },
    "legendary": {
        "name_cn": "小男爵", "name_en": "Mini Baron",
        "rarity_cn": "传说", "rarity_en": "Legendary",
        "egg_emoji": "🥚", "pet_emoji": "🟡",
        "drop_rate": 0.08, "cost": 4000,
        "atk": 20, "def": 10, "hp": 0,
    },
    "mythic": {
        "name_cn": "远古幼龙", "name_en": "Elder Hatchling",
        "rarity_cn": "神话", "rarity_en": "Mythic",
        "egg_emoji": "🥚", "pet_emoji": "🔴",
        "drop_rate": 0.02, "cost": 5000,
        "atk": 30, "def": 20, "hp": 50,
    },
}

RARITY_ORDER = ["common", "rare", "epic", "legendary", "mythic"]

STAR_MULTIPLIERS = {1: 1.0, 2: 1.5, 3: 2.0, 4: 2.8, 5: 4.0}

UPGRADE_FRAGMENT_COST = {2: 5, 3: 10, 4: 20, 5: 40}
UPGRADE_GOLD_COST = {2: 500, 3: 1500, 4: 4000, 5: 10000}


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


def _roll_rarity() -> str:
    roll = random.random()
    cumulative = 0.0
    for rarity in RARITY_ORDER:
        cumulative += PET_CATALOG[rarity]["drop_rate"]
        if roll <= cumulative:
            return rarity
    return "common"


def _get_pet_stats(pet: dict) -> dict:
    """Calculate effective stats with star multiplier."""
    catalog = PET_CATALOG.get(pet["pet_type"], PET_CATALOG["common"])
    mult = STAR_MULTIPLIERS.get(pet["stars"], 1.0)
    return {
        "atk": int(catalog["atk"] * mult),
        "def": int(catalog["def"] * mult),
        "hp": int(catalog["hp"] * mult),
    }


def _get_equipped_pet(uid: str) -> dict | None:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM mmorpg_pets WHERE user_id = ? AND equipped = 1",
            (uid,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _count_pet_fragments(uid: str, pet_type: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT count FROM mmorpg_pet_fragments WHERE user_id = ? AND pet_type = ?",
            (uid, pet_type),
        )
        row = cur.fetchone()
    return row["count"] if row else 0


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_pet_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_pets (
                pet_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                pet_type TEXT NOT NULL,
                name TEXT,
                rarity TEXT NOT NULL,
                stars INTEGER NOT NULL DEFAULT 1,
                exp INTEGER NOT NULL DEFAULT 0,
                equipped INTEGER NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_pet_fragments (
                user_id TEXT NOT NULL,
                pet_type TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, pet_type)
            )
        """)
        conn.commit()

_init_pet_tables()


# ══════════════════════════════════════════════════════════════
# PetPanelView — Main UI
# ══════════════════════════════════════════════════════════════
class PetPanelView(discord.ui.View):
    """宠物主面板 / Pet main panel."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        equipped = _get_equipped_pet(self.uid)
        if equipped:
            cat = PET_CATALOG.get(equipped["pet_type"], PET_CATALOG["common"])
            stats = _get_pet_stats(equipped)
            stars_str = "★" * equipped["stars"] + "☆" * (5 - equipped["stars"])
            desc = (
                f"**{cat['pet_emoji']} {equipped['name'] or cat['name_cn']} / {cat['name_en']}**\n"
                f"Rarity / 稀有度: {cat['rarity_cn']} / {cat['rarity_en']}\n"
                f"Stars / 星级: {stars_str} (x{STAR_MULTIPLIERS[equipped['stars']]}倍率)\n"
                f"ATK +{stats['atk']} | DEF +{stats['def']} | HP +{stats['hp']}\n"
                f"EXP: {equipped['exp']}"
            )
        else:
            desc = "No pet equipped / 未出战宠物\n\nUse 🥚 Hatch to get your first pet!\n点击 🥚 Hatch 获得第一只宠物！"

        embed = discord.Embed(
            title="🐾 Pet System / 宠物系统",
            description=desc,
            color=0xE91E63 if equipped else 0x607D8B,
        )

        # Show fragment counts
        frag_lines = []
        for rarity in RARITY_ORDER:
            cat = PET_CATALOG[rarity]
            count = _count_pet_fragments(self.uid, rarity)
            if count > 0:
                frag_lines.append(f"{cat['pet_emoji']} {cat['name_cn']} 碎片: {count}")
        if frag_lines:
            embed.add_field(
                name="Fragments / 宠物碎片",
                value="\n".join(frag_lines),
                inline=False,
            )

        # Egg shop prices
        shop_lines = []
        for rarity in RARITY_ORDER:
            cat = PET_CATALOG[rarity]
            shop_lines.append(
                f"{cat['egg_emoji']} {cat['name_cn']} ({cat['rarity_cn']}): 🪙 {cat['cost']:,}"
            )
        embed.add_field(
            name="Egg Shop / 宠物蛋商店",
            value="\n".join(shop_lines),
            inline=False,
        )

        embed.set_footer(text="Only 1 pet can be equipped | 只能出战1只宠物")
        return embed

    @discord.ui.button(label="Hatch 孵化", emoji="🥚", style=discord.ButtonStyle.success, row=0)
    async def hatch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return

        cost = 500
        coins = _get_coins(uid)
        if coins < cost:
            embed = discord.Embed(
                title="🥚 Hatch Failed / 孵化失败",
                description=f"Need 🪙 {cost:,} but you have {coins:,}.\n需要 🪙 {cost:,}，你只有 {coins:,}。",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        _add_coins(uid, -cost, f"宠物孵化 — Pet Hatching")
        rarity = _roll_rarity()
        cat = PET_CATALOG[rarity]

        pet_name = cat["name_cn"]
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO mmorpg_pets (user_id, pet_type, name, rarity, stars, exp, equipped) VALUES (?, ?, ?, ?, 1, 0, 0)",
                (uid, rarity, pet_name, rarity),
            )
            conn.commit()

        stats = _get_pet_stats({"pet_type": rarity, "stars": 1})

        # Also give 1 fragment of the hatched type
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO mmorpg_pet_fragments (user_id, pet_type, count) VALUES (?, ?, 1) "
                "ON CONFLICT(user_id, pet_type) DO UPDATE SET count = count + 1",
                (uid, rarity),
            )
            conn.commit()

        embed = discord.Embed(
            title="🥚 Egg Hatched! / 孵化成功！",
            description=(
                f"You got: **{cat['pet_emoji']} {pet_name} / {cat['name_en']}**\n"
                f"Rarity: {cat['rarity_cn']} / {cat['rarity_en']}\n"
                f"Stars: ★☆☆☆☆ (x1.0)\n"
                f"ATK +{stats['atk']} | DEF +{stats['def']} | HP +{stats['hp']}\n\n"
                f"+1 {cat['name_cn']} Fragment / 碎片"
            ),
            color=0x2ECC71,
        )
        embed.set_footer(text="Use 🔄 Switch to equip this pet!")

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Upgrade 升星", emoji="⭐", style=discord.ButtonStyle.primary, row=0)
    async def upgrade_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return

        equipped = _get_equipped_pet(uid)
        if not equipped:
            embed = discord.Embed(
                title="⭐ Upgrade / 升星",
                description="No pet equipped! Equip a pet first.\n没有出战宠物！请先出战一只宠物。",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        if equipped["stars"] >= 5:
            embed = discord.Embed(
                title="⭐ Upgrade / 升星",
                description="Already at max stars (★5)!\n已是最高星级 (★5)！",
                color=0xF39C12,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        next_star = equipped["stars"] + 1
        frag_needed = UPGRADE_FRAGMENT_COST.get(next_star, 999)
        gold_needed = UPGRADE_GOLD_COST.get(next_star, 99999)

        fragments = _count_pet_fragments(uid, equipped["pet_type"])
        coins = _get_coins(uid)

        if fragments < frag_needed or coins < gold_needed:
            cat = PET_CATALOG.get(equipped["pet_type"], PET_CATALOG["common"])
            embed = discord.Embed(
                title="⭐ Upgrade Failed / 升星失败",
                description=(
                    f"Need / 需要:\n"
                    f"{cat['pet_emoji']} {cat['name_cn']} Fragments: {fragments}/{frag_needed}\n"
                    f"🪙 Gold: {coins:,}/{gold_needed:,}"
                ),
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        # Deduct fragments and gold
        _add_coins(uid, -gold_needed, f"宠物升星 ★{equipped['stars']}→★{next_star}")
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE mmorpg_pet_fragments SET count = count - ? WHERE user_id = ? AND pet_type = ?",
                (frag_needed, uid, equipped["pet_type"]),
            )
            cur.execute(
                "UPDATE mmorpg_pets SET stars = ? WHERE pet_id = ?",
                (next_star, equipped["pet_id"]),
            )
            conn.commit()

        new_stats = _get_pet_stats({"pet_type": equipped["pet_type"], "stars": next_star})
        cat = PET_CATALOG.get(equipped["pet_type"], PET_CATALOG["common"])
        embed = discord.Embed(
            title="⭐ Upgrade Success! / 升星成功！",
            description=(
                f"{cat['pet_emoji']} **{equipped['name'] or cat['name_cn']}**\n"
                f"Stars: {'★' * next_star}{'☆' * (5 - next_star)} (x{STAR_MULTIPLIERS[next_star]}倍率)\n"
                f"ATK +{new_stats['atk']} | DEF +{new_stats['def']} | HP +{new_stats['hp']}"
            ),
            color=0xF1C40F,
        )

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Switch 切换", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def switch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT pet_id, pet_type, name, rarity, stars FROM mmorpg_pets WHERE user_id = ? ORDER BY "
                "CASE rarity WHEN 'mythic' THEN 1 WHEN 'legendary' THEN 2 WHEN 'epic' THEN 3 WHEN 'rare' THEN 4 ELSE 5 END, pet_id",
                (uid,),
            )
            pets = cur.fetchall()

        if not pets:
            embed = discord.Embed(
                title="🔄 Switch Pet / 切换宠物",
                description="You have no pets! Hatch one first.\n你还没有宠物！请先孵化。",
                color=0xE74C3C,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        # Create a select menu for switching
        view = PetSwitchView(self.uid, pets, main_view=self)
        embed = discord.Embed(
            title="🔄 Switch Pet / 切换宠物",
            description="Select a pet to equip:\n选择要出战的宠物：",
            color=0x9B59B6,
        )
        for p in pets:
            cat = PET_CATALOG.get(p["pet_type"], PET_CATALOG["common"])
            stats = _get_pet_stats({"pet_type": p["pet_type"], "stars": p["stars"]})
            stars_str = "★" * p["stars"] + "☆" * (5 - p["stars"])
            embed.add_field(
                name=f"{cat['pet_emoji']} {p['name'] or cat['name_cn']} ({cat['rarity_cn']})",
                value=f"{stars_str} | ATK +{stats['atk']} DEF +{stats['def']} HP +{stats['hp']}",
                inline=False,
            )

        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="Inventory 宠物栏", emoji="📦", style=discord.ButtonStyle.primary, row=0)
    async def inventory_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT pet_id, pet_type, name, rarity, stars, exp, equipped FROM mmorpg_pets WHERE user_id = ? ORDER BY pet_id",
                (uid,),
            )
            pets = cur.fetchall()

        if not pets:
            embed = discord.Embed(
                title="📦 Pet Inventory / 宠物栏",
                description="No pets! / 还没有宠物！",
                color=0x607D8B,
            )
        else:
            desc_lines = []
            for p in pets:
                cat = PET_CATALOG.get(p["pet_type"], PET_CATALOG["common"])
                stats = _get_pet_stats({"pet_type": p["pet_type"], "stars": p["stars"]})
                stars_str = "★" * p["stars"] + "☆" * (5 - p["stars"])
                eq_tag = " [出战]" if p["equipped"] else ""
                desc_lines.append(
                    f"{cat['pet_emoji']} **{p['name'] or cat['name_cn']}** ({cat['rarity_cn']}){eq_tag}\n"
                    f"  {stars_str} | ATK +{stats['atk']} DEF +{stats['def']} HP +{stats['hp']} | EXP: {p['exp']}"
                )
            embed = discord.Embed(
                title="📦 Pet Inventory / 宠物栏",
                description="\n\n".join(desc_lines),
                color=0x8E44AD,
            )

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=1)
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
                title="🐾 Pets / 宠物",
                description="Use `/gmpt-mmorpg` to return.\n使用 `/gmpt-mmorpg` 返回。",
                color=0x95A5A6,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass



class PetSwitchView(discord.ui.View):
    """宠物切换选择面板."""

    def __init__(self, uid: str, pets: list, main_view=None):
        super().__init__(timeout=60)
        self.uid = uid
        self.main_view = main_view

        options = []
        for p in pets[:25]:
            cat = PET_CATALOG.get(p["pet_type"], PET_CATALOG["common"])
            label = f"{p['name'] or cat['name_cn']} ({cat['rarity_cn']}) ★{p['stars']}"
            options.append(discord.SelectOption(label=label[:100], value=str(p["pet_id"])))

        select = discord.ui.Select(
            placeholder="Choose a pet to equip... / 选择要出战的宠物...",
            options=options,
            row=0,
        )
        select.callback = self._select_callback
        self.add_item(select)

    async def _select_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return

        pet_id = int(interaction.data["values"][0])

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE mmorpg_pets SET equipped = 0 WHERE user_id = ?", (uid,))
            cur.execute("UPDATE mmorpg_pets SET equipped = 1 WHERE pet_id = ?", (pet_id,))
            cur.execute("SELECT pet_type, name, rarity, stars FROM mmorpg_pets WHERE pet_id = ?", (pet_id,))
            pet = cur.fetchone()
            conn.commit()

        cat = PET_CATALOG.get(pet["pet_type"], PET_CATALOG["common"])
        stats = _get_pet_stats({"pet_type": pet["pet_type"], "stars": pet["stars"]})
        stars_str = "★" * pet["stars"] + "☆" * (5 - pet["stars"])

        embed = discord.Embed(
            title="🔄 Pet Equipped! / 宠物已出战！",
            description=(
                f"{cat['pet_emoji']} **{pet['name'] or cat['name_cn']} / {cat['name_en']}**\n"
                f"Rarity: {cat['rarity_cn']} | Stars: {stars_str}\n"
                f"ATK +{stats['atk']} | DEF +{stats['def']} | HP +{stats['hp']}"
            ),
            color=0x2ECC71,
        )

        # Back to main pet panel
        main_panel = PetPanelView(self.uid, main_view=self.main_view)
        try:
            await interaction.response.edit_message(embed=embed, view=main_panel)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=main_panel)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PetPanelView(self.uid, main_view=self.main_view)
        embed = view.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=view)


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass


class PetCog(commands.Cog):
    """宠物系统 / Pet System."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gmpt-pet", description="Pet System / 宠物系统 — hatch, upgrade, switch pets!")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def pet_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        view = PetPanelView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(PetCog(bot))
    logger.info("MMORPG Pet cog loaded")
