"""
GMPT Bot — 宠物系统 / Pet System
/gmpt-pet adopt / feed / play / status / rename

Bilingual (中文 / English)
"""
import random
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins
from datetime import datetime

logger = logging.getLogger(__name__)


def _format_coins(amount: int) -> str:
    return f"🪙 {amount:,}"


PET_TYPES = {
    "狗": {"emoji": "🐕", "price": 500, "en": "Dog"},
    "dog": {"emoji": "🐕", "price": 500, "zh": "狗"},
    "猫": {"emoji": "🐈", "price": 500, "en": "Cat"},
    "cat": {"emoji": "🐈", "price": 500, "zh": "猫"},
    "龙": {"emoji": "🐉", "price": 2000, "en": "Dragon"},
    "dragon": {"emoji": "🐉", "price": 2000, "zh": "龙"},
    "独角兽": {"emoji": "🦄", "price": 5000, "en": "Unicorn"},
    "unicorn": {"emoji": "🦄", "price": 5000, "zh": "独角兽"},
}


def _init_pet_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                pet_name TEXT NOT NULL,
                pet_type TEXT NOT NULL,
                happiness INTEGER DEFAULT 50,
                adopted_at TEXT DEFAULT (datetime('now')),
                last_fed TEXT,
                last_played TEXT
            )
        """)
        conn.commit()


_init_pet_tables()


class Pets(CogBase):
    """宠物系统 / Pet System."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[Pets] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    pet_group = app_commands.Group(
        name="gmpt-pet",
        description="🐾 宠物系统 / Pet System"
    )

    @app_commands.command(name="gmpt-pets", description="🐾 宠物面板 / Pet button panel")
    async def pet_panel_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🐾 宠物系统 / Pet System",
            description="点击下方按钮管理你的宠物！\nClick a button below!",
            color=0xE67E22,
        )
        pet_info = "\n".join(f"{v['emoji']} {v.get('zh', k)} — 🪙 {v['price']:,}" for k, v in PET_TYPES.items())
        embed.add_field(name="🐾 可领养宠物 / Available Pets", value=pet_info, inline=False)
        embed.add_field(name="按钮功能", value="领养 | 查看 | 喂养 | 玩耍 | 改名", inline=False)
        embed.set_footer(text="保留原 /gmpt-pet 子命令组")
        view = PetPanelView()
        await interaction.response.send_message(embed=embed, view=view)

    @pet_group.command(name="adopt", description="领养宠物 / Adopt a pet")
    @app_commands.describe(pet_type="宠物类型: 狗/猫/龙/独角兽 / Pet type: dog/cat/dragon/unicorn")
    @app_commands.checks.cooldown(1, 30, key=lambda i: (i.guild_id, i.user.id))
    async def pet_adopt(self, interaction: discord.Interaction, pet_type: str):
        uid = str(interaction.user.id)
        pet_type_lower = pet_type.lower()

        info = PET_TYPES.get(pet_type_lower) or PET_TYPES.get(pet_type)
        if not info:
            return await interaction.response.send_message(
                "可选宠物: 狗(dog) 🪙500 / 猫(cat) 🪙500 / 龙(dragon) 🪙2000 / 独角兽(unicorn) 🪙5000",
                ephemeral=True,
            )

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM pets WHERE owner_id=?", (uid,))
            if cur.fetchone():
                return await interaction.response.send_message(
                    "你已经有一只宠物了！/ You already have a pet!", ephemeral=True)

        bal = get_balance(uid)
        if bal < info["price"]:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 {info['price']:,}，你只有 🪙 {bal:,} / Not enough coins.",
                ephemeral=True,
            )

        add_coins(uid, -info["price"], f"领养宠物: {pet_type_lower} / Adopted pet")

        display_name = info.get("zh", pet_type)
        display_type = info.get("zh", pet_type)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO pets (owner_id, pet_name, pet_type) VALUES (?, ?, ?)",
                (uid, display_name, display_type),
            )
            conn.commit()

        embed = discord.Embed(
            title=f"{info['emoji']} 领养成功！/ Adopted!",
            description=f"你领养了一只 **{display_name}**！\nYou adopted a **{info.get('en', display_name)}**!",
            color=0x2ECC71,
        )
        embed.add_field(name="💰 花费 / Cost", value=_format_coins(info["price"]), inline=True)
        embed.add_field(name="❤️ 心情 / Happiness", value="50/100", inline=True)
        embed.set_footer(text="使用 /gmpt-pet status 查看 | /gmpt-pet feed 喂食 | /gmpt-pet play 玩耍")

        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="status", description="查看宠物状态 / View pet status")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def pet_status(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
            row = cur.fetchone()

        if not row:
            return await interaction.response.send_message(
                "你还没有宠物！使用 /gmpt-pet adopt 领养一只 / No pet yet! Use /gmpt-pet adopt.",
                ephemeral=True,
            )

        info = PET_TYPES.get(row["pet_type"].lower(), {"emoji": "🐾"})
        adopted_date = row["adopted_at"][:10] if row["adopted_at"] else "Unknown"
        days_old = "N/A"
        try:
            if row["adopted_at"]:
                dt = datetime.strptime(row["adopted_at"][:10], "%Y-%m-%d")
                days_old = str((datetime.now() - dt).days)
        except Exception:
            pass

        embed = discord.Embed(
            title=f"{info['emoji']} {row['pet_name']}",
            description=f"类型 / Type: **{row['pet_type']}**\n"
                        f"年龄 / Age: **{days_old} 天 / days**",
            color=0xE67E22,
        )
        embed.add_field(name="❤️ 心情 / Happiness", value=f"{row['happiness']}/100", inline=True)
        embed.add_field(name="📅 领养日期 / Adopted", value=adopted_date, inline=True)
        embed.set_footer(text="/gmpt-pet feed | /gmpt-pet play | /gmpt-pet rename")

        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="feed", description="喂食宠物 / Feed your pet (once per day)")
    async def pet_feed(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "你还没有宠物！/ No pet yet!", ephemeral=True)

            # Check daily limit
            today = datetime.now().strftime("%Y-%m-%d")
            if row["last_fed"] and row["last_fed"][:10] == today:
                return await interaction.response.send_message(
                    "今天已经喂过了！明天再来吧 / Already fed today! Come back tomorrow.",
                    ephemeral=True,
                )

            boost = random.randint(1, 5)
            new_happiness = min(row["happiness"] + boost, 100)

            cur.execute(
                "UPDATE pets SET happiness=?, last_fed=? WHERE id=?",
                (new_happiness, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"]),
            )
            conn.commit()

        info = PET_TYPES.get(row["pet_type"].lower(), {"emoji": "🐾"})
        embed = discord.Embed(
            title=f"{info['emoji']} 喂食 / Fed!",
            description=f"{row['pet_name']} 吃饱了！心情 +{boost}\n{row['pet_name']} is full! Happiness +{boost}",
            color=0x2ECC71,
        )
        embed.add_field(name="❤️ 心情 / Happiness", value=f"{new_happiness}/100", inline=True)

        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="play", description="和宠物玩耍 / Play with your pet (once per day, costs 50 coins)")
    async def pet_play(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        bal = get_balance(uid)
        if bal < 50:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 50 / Need 🪙 50.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "你还没有宠物！/ No pet yet!", ephemeral=True)

            today = datetime.now().strftime("%Y-%m-%d")
            if row["last_played"] and row["last_played"][:10] == today:
                return await interaction.response.send_message(
                    "今天已经玩过了！明天再来吧 / Already played today!",
                    ephemeral=True,
                )

            add_coins(uid, -50, f"宠物玩耍 / Pet play: {row['pet_name']}")

            boost = random.randint(1, 5)
            new_happiness = min(row["happiness"] + boost, 100)

            cur.execute(
                "UPDATE pets SET happiness=?, last_played=? WHERE id=?",
                (new_happiness, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"]),
            )
            conn.commit()

        info = PET_TYPES.get(row["pet_type"].lower(), {"emoji": "🐾"})
        embed = discord.Embed(
            title=f"{info['emoji']} 玩耍 / Play!",
            description=f"和 {row['pet_name']} 玩得很开心！心情 +{boost}\n"
                        f"Played with {row['pet_name']}! Happiness +{boost}\n"
                        f"花费 / Cost: 🪙 50",
            color=0x3498DB,
        )
        embed.add_field(name="❤️ 心情 / Happiness", value=f"{new_happiness}/100", inline=True)

        await interaction.response.send_message(embed=embed)

    @pet_group.command(name="rename", description="给宠物改名 / Rename your pet")
    @app_commands.describe(new_name="新名字 / New name")
    async def pet_rename(self, interaction: discord.Interaction, new_name: str):
        uid = str(interaction.user.id)

        if len(new_name) > 30:
            return await interaction.response.send_message("名字最多 30 字 / Max 30 characters.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
            row = cur.fetchone()
            if not row:
                return await interaction.response.send_message("你还没有宠物！/ No pet yet!", ephemeral=True)

            old_name = row["pet_name"]
            cur.execute("UPDATE pets SET pet_name=? WHERE id=?", (new_name, row["id"]))
            conn.commit()

        await interaction.response.send_message(
            f"✅ 改名成功！**{old_name}** → **{new_name}** / Renamed!",
            ephemeral=True,
        )

# ══════════════════════════════════════════════════════════════
# PetPanelView — 宠物按钮面板 / Pet Button Panel
# ══════════════════════════════════════════════════════════════

class PetPanelView(discord.ui.View):
    """宠物系统按钮面板 — 点击按钮操作宠物。"""

    def __init__(self, user_id_or_guild=None, guild=None, dashboard_view=None, main_view=None):
        super().__init__(timeout=300)
        # Support both old calling conventions and new main_view
        if isinstance(user_id_or_guild, discord.Guild) or guild is not None or dashboard_view is not None:
            self.guild = user_id_or_guild if isinstance(user_id_or_guild, discord.Guild) else guild
            self.dashboard_view = dashboard_view
            self.main_view = main_view
        else:
            # New convention: PetPanelView(uid, main_view=mv)
            self.uid = str(user_id_or_guild)
            self.guild = None
            self.dashboard_view = None
            self.main_view = main_view
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()

        btns = [
            ("🐾 领养", "pet_adopt", discord.ButtonStyle.success),
            ("📋 查看宠物", "pet_status", discord.ButtonStyle.primary),
            ("🍖 喂养", "pet_feed", discord.ButtonStyle.primary),
            ("🎾 玩耍", "pet_play", discord.ButtonStyle.primary),
            ("✏️ 改名", "pet_rename", discord.ButtonStyle.secondary),
        ]
        for i, (label, cid, style) in enumerate(btns):
            btn = discord.ui.Button(label=label, style=style, row=0, custom_id=f"petp_{cid}")
            btn.callback = self._make_callback(cid)
            self.add_item(btn)

        back_btn = discord.ui.Button(
            label="返回主菜单 | Back to Main",
            style=discord.ButtonStyle.danger, row=1, custom_id="petp_back",
        )
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    async def _back_callback(self, interaction: discord.Interaction):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            uid = getattr(self, 'uid', str(interaction.user.id))
            embed = build_main_embed(uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
        elif self.dashboard_view:
            self.dashboard_view.category = 0
            self.dashboard_view.build_page_buttons()
            embed = self.dashboard_view._build_page_embed()
            try:
                await interaction.response.edit_message(embed=embed, view=self.dashboard_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.dashboard_view)
        else:
            try:
                await interaction.response.edit_message(
                    content="使用 `/gmpt-dashboard` 返回主菜单 / Use `/gmpt-dashboard` to go back.",
                    embed=None, view=None,
                )
            except discord.InteractionResponded:
                await interaction.edit_original_response(
                    content="使用 `/gmpt-dashboard` 返回主菜单 / Use `/gmpt-dashboard` to go back.",
                    embed=None, view=None,
                )

    def _make_callback(self, action: str):
        async def cb(interaction: discord.Interaction):
            uid = str(interaction.user.id)

            if action == "pet_status":
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
                    row = cur.fetchone()
                if not row:
                    return await interaction.response.send_message(
                        "你还没有宠物！使用「领养」按钮领养一只 / No pet yet! Use the Adopt button.",
                        ephemeral=True,
                    )
                info = PET_TYPES.get(row["pet_type"].lower(), {"emoji": "🐾"})
                adopted_date = row["adopted_at"][:10] if row["adopted_at"] else "Unknown"
                days_old = "N/A"
                try:
                    if row["adopted_at"]:
                        dt = datetime.strptime(row["adopted_at"][:10], "%Y-%m-%d")
                        days_old = str((datetime.now() - dt).days)
                except Exception:
                    pass
                embed = discord.Embed(
                    title=f"{info['emoji']} {row['pet_name']}",
                    description=f"类型 / Type: **{row['pet_type']}**\n年龄 / Age: **{days_old} 天 / days**",
                    color=0xE67E22,
                )
                embed.add_field(name="❤️ 心情 / Happiness", value=f"{row['happiness']}/100", inline=True)
                embed.add_field(name="📅 领养日期 / Adopted", value=adopted_date, inline=True)
                embed.set_footer(text="面板版宠物系统")
                await interaction.response.send_message(embed=embed)
                return

            if action == "pet_feed":
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
                    row = cur.fetchone()
                if not row:
                    return await interaction.response.send_message("你还没有宠物！/ No pet yet!", ephemeral=True)
                today = datetime.now().strftime("%Y-%m-%d")
                if row["last_fed"] and row["last_fed"][:10] == today:
                    return await interaction.response.send_message(
                        "今天已经喂过了！明天再来吧 / Already fed today!", ephemeral=True)
                boost = random.randint(1, 5)
                new_happiness = min(row["happiness"] + boost, 100)
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE pets SET happiness=?, last_fed=? WHERE id=?",
                        (new_happiness, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"]),
                    )
                    conn.commit()
                info = PET_TYPES.get(row["pet_type"].lower(), {"emoji": "🐾"})
                embed = discord.Embed(
                    title=f"{info['emoji']} 喂食 / Fed!",
                    description=f"{row['pet_name']} 吃饱了！心情 +{boost}\n{row['pet_name']} is full! Happiness +{boost}",
                    color=0x2ECC71,
                )
                embed.add_field(name="❤️ 心情 / Happiness", value=f"{new_happiness}/100", inline=True)
                await interaction.response.send_message(embed=embed)
                return

            if action == "pet_play":
                bal = get_balance(uid)
                if bal < 50:
                    return await interaction.response.send_message(
                        f"金币不足！需要 🪙 50 / Need 🪙 50.", ephemeral=True)
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
                    row = cur.fetchone()
                if not row:
                    return await interaction.response.send_message("你还没有宠物！/ No pet yet!", ephemeral=True)
                today = datetime.now().strftime("%Y-%m-%d")
                if row["last_played"] and row["last_played"][:10] == today:
                    return await interaction.response.send_message(
                        "今天已经玩过了！明天再来吧 / Already played today!", ephemeral=True)
                add_coins(uid, -50, f"宠物玩耍 / Pet play: {row['pet_name']}")
                boost = random.randint(1, 5)
                new_happiness = min(row["happiness"] + boost, 100)
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE pets SET happiness=?, last_played=? WHERE id=?",
                        (new_happiness, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"]),
                    )
                    conn.commit()
                info = PET_TYPES.get(row["pet_type"].lower(), {"emoji": "🐾"})
                embed = discord.Embed(
                    title=f"{info['emoji']} 玩耍 / Play!",
                    description=f"和 {row['pet_name']} 玩得很开心！心情 +{boost}\n"
                                f"Played with {row['pet_name']}! Happiness +{boost}\n花费 / Cost: 🪙 50",
                    color=0x3498DB,
                )
                embed.add_field(name="❤️ 心情 / Happiness", value=f"{new_happiness}/100", inline=True)
                await interaction.response.send_message(embed=embed)
                return

            # Modal actions
            if action == "pet_adopt":
                modal = PetAdoptModal()
            elif action == "pet_rename":
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
                    if not cur.fetchone():
                        return await interaction.response.send_message("你还没有宠物！/ No pet yet!", ephemeral=True)
                modal = PetRenameModal()
            else:
                return
            await interaction.response.send_modal(modal)

        return cb


class PetAdoptModal(discord.ui.Modal, title="🐾 领养宠物 / Adopt Pet"):
    pet_type = discord.ui.TextInput(
        label="宠物类型 / Pet Type",
        placeholder="狗(dog) 🪙500 | 猫(cat) 🪙500 | 龙(dragon) 🪙2000 | 独角兽(unicorn) 🪙5000",
        max_length=20, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        pet_type_lower = self.pet_type.value.strip().lower()

        info = PET_TYPES.get(pet_type_lower) or PET_TYPES.get(pet_type_lower.capitalize())
        if not info:
            pet_list = " | ".join(f"{k}({v.get('zh',k)}) 🪙{v['price']:,}" for k, v in PET_TYPES.items())
            return await interaction.response.send_message(
                f"可选宠物: {pet_list}", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM pets WHERE owner_id=?", (uid,))
            if cur.fetchone():
                return await interaction.response.send_message(
                    "你已经有一只宠物了！/ You already have a pet!", ephemeral=True)

        bal = get_balance(uid)
        if bal < info["price"]:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 {info['price']:,}，你只有 🪙 {bal:,} / Not enough coins.", ephemeral=True)

        add_coins(uid, -info["price"], f"领养宠物: {pet_type_lower} / Adopted pet")
        display_name = info.get("zh", pet_type_lower)
        display_type = info.get("zh", pet_type_lower)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO pets (owner_id, pet_name, pet_type) VALUES (?, ?, ?)",
                (uid, display_name, display_type),
            )
            conn.commit()

        embed = discord.Embed(
            title=f"{info['emoji']} 领养成功！/ Adopted!",
            description=f"你领养了一只 **{display_name}**！\nYou adopted a **{info.get('en', display_name)}**!",
            color=0x2ECC71,
        )
        embed.add_field(name="💰 花费 / Cost", value=_format_coins(info["price"]), inline=True)
        embed.add_field(name="❤️ 心情 / Happiness", value="50/100", inline=True)
        embed.set_footer(text="面板版宠物系统 | 使用按钮喂养/玩耍")
        await interaction.response.send_message(embed=embed)


class PetRenameModal(discord.ui.Modal, title="✏️ 宠物改名 / Rename Pet"):
    new_name = discord.ui.TextInput(
        label="新名字 / New Name",
        placeholder="输入新名字（最多30字）/ Max 30 chars",
        max_length=30, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        new_name = self.new_name.value.strip()

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pets WHERE owner_id=?", (uid,))
            row = cur.fetchone()
            if not row:
                return await interaction.response.send_message("你还没有宠物！/ No pet yet!", ephemeral=True)
            old_name = row["pet_name"]
            cur.execute("UPDATE pets SET pet_name=? WHERE id=?", (new_name, row["id"]))
            conn.commit()

        await interaction.response.send_message(
            f"✅ 改名成功！**{old_name}** → **{new_name}** / Renamed!", ephemeral=True)



async def setup(bot):
    await bot.add_cog(Pets(bot))
