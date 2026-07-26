"""
GMPT Bot — 公会系统 / Clan System
/gmpt-clan create / join / leave / info / donate

Bilingual (中文 / English)
"""
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins

logger = logging.getLogger(__name__)


def _format_coins(amount: int) -> str:
    return f"🪙 {amount:,}"


def _init_clan_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                owner_id TEXT NOT NULL,
                total_contrib INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clan_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                personal_contrib INTEGER DEFAULT 0,
                joined_at TEXT DEFAULT (datetime('now')),
                UNIQUE(clan_id, user_id)
            )
        """)
        conn.commit()


_init_clan_tables()

CLAN_CREATE_COST = 5000
LEVEL_THRESHOLDS = {
    1: 0,
    2: 10000,
    3: 50000,
    4: 200000,
    5: 1000000,
}


def _get_clan_level(total_contrib: int) -> int:
    level = 1
    for lv in sorted(LEVEL_THRESHOLDS.keys()):
        if total_contrib >= LEVEL_THRESHOLDS[lv]:
            level = lv
    return level


class Clans(CogBase):
    """公会系统 / Clan System."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[Clans] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    clan_group = app_commands.Group(
        name="gmpt-clan",
        description="🏰 公会系统 / Clan System"
    )

    @app_commands.command(name="gmpt-clans", description="🏰 公会面板 / Clan button panel")
    async def clan_panel(self, interaction: discord.Interaction):
        """显示公会按钮面板"""
        embed = discord.Embed(
            title="🏰 公会系统 / Clan System",
            description="点击下方按钮操作公会！\nClick a button below!",
            color=0x9B59B6,
        )
        embed.add_field(name="🏰 创建公会", value=f"花费 🪙 {CLAN_CREATE_COST:,}", inline=True)
        embed.add_field(name="🚪 加入公会", value="输入公会名加入", inline=True)
        embed.add_field(name="💰 捐赠", value="为公会贡献金币", inline=True)
        embed.set_footer(text="保留原 /gmpt-clan 子命令组")
        view = ClanPanelView()
        await interaction.response.send_message(embed=embed, view=view)

    @clan_group.command(name="create", description="创建公会 / Create a clan (cost: 5000 coins)")
    @app_commands.describe(clan_name="公会名称 / Clan name")
    async def clan_create(self, interaction: discord.Interaction, clan_name: str):
        uid = str(interaction.user.id)

        if len(clan_name) > 30:
            return await interaction.response.send_message("公会名最多 30 字 / Max 30 chars.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM clan_members WHERE user_id=?", (uid,))
            if cur.fetchone():
                return await interaction.response.send_message(
                    "你已经在一个公会中！先 /gmpt-clan leave / You're already in a clan!", ephemeral=True)

            cur.execute("SELECT id FROM clans WHERE name=?", (clan_name,))
            if cur.fetchone():
                return await interaction.response.send_message("公会名已存在 / Name taken.", ephemeral=True)

        bal = get_balance(uid)
        if bal < CLAN_CREATE_COST:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 {CLAN_CREATE_COST:,} / Need 🪙 {CLAN_CREATE_COST:,}.", ephemeral=True)

        add_coins(uid, -CLAN_CREATE_COST, f"创建公会: {clan_name} / Created clan")

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO clans (name, owner_id, total_contrib) VALUES (?, ?, ?)",
                (clan_name, uid, CLAN_CREATE_COST),
            )
            clan_id = cur.lastrowid
            cur.execute(
                "INSERT INTO clan_members (clan_id, user_id, personal_contrib) VALUES (?, ?, ?)",
                (clan_id, uid, CLAN_CREATE_COST),
            )
            conn.commit()

        embed = discord.Embed(
            title="🏰 公会创建成功！/ Clan Created!",
            description=f"**{clan_name}** 正式成立！\nClan **{clan_name}** established!",
            color=0x9B59B6,
        )
        embed.add_field(name="👑 会长 / Owner", value=f"<@{uid}>", inline=True)
        embed.add_field(name="💰 创建费 / Cost", value=_format_coins(CLAN_CREATE_COST), inline=True)
        embed.add_field(name="📊 等级 / Level", value="1", inline=True)

        await interaction.response.send_message(embed=embed)

    @clan_group.command(name="join", description="加入公会 / Join a clan")
    @app_commands.describe(clan_name="公会名称 / Clan name")
    async def clan_join(self, interaction: discord.Interaction, clan_name: str):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM clan_members WHERE user_id=?", (uid,))
            if cur.fetchone():
                return await interaction.response.send_message(
                    "你已经在一个公会中！/ Already in a clan!", ephemeral=True)

            cur.execute("SELECT * FROM clans WHERE name=?", (clan_name,))
            clan = cur.fetchone()
            if not clan:
                return await interaction.response.send_message("公会不存在 / Clan not found.", ephemeral=True)

            cur.execute(
                "INSERT INTO clan_members (clan_id, user_id) VALUES (?, ?)",
                (clan["id"], uid),
            )
            conn.commit()

        await interaction.response.send_message(
            f"✅ 你已加入 **{clan_name}**！/ Joined **{clan_name}**!"
        )

    @clan_group.command(name="leave", description="离开公会 / Leave your clan")
    async def clan_leave(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT cm.*, c.name, c.owner_id FROM clan_members cm "
                "JOIN clans c ON c.id = cm.clan_id WHERE cm.user_id=?",
                (uid,),
            )
            row = cur.fetchone()
            if not row:
                return await interaction.response.send_message("你不在任何公会中 / Not in a clan.", ephemeral=True)
            if row["owner_id"] == uid:
                return await interaction.response.send_message(
                    "会长不能离开！请先转让会长或解散公会 / Owner cannot leave! Transfer ownership first.",
                    ephemeral=True,
                )

            cur.execute("DELETE FROM clan_members WHERE user_id=?", (uid,))
            conn.commit()

        await interaction.response.send_message(f"👋 已离开 **{row['name']}** / Left **{row['name']}**.")

    @clan_group.command(name="info", description="查看公会信息 / View clan info")
    @app_commands.describe(clan_name="公会名称（留空查看自己的公会）/ Clan name (leave blank for yours)")
    async def clan_info(self, interaction: discord.Interaction, clan_name: str = ""):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()

            if clan_name:
                cur.execute("SELECT * FROM clans WHERE name=?", (clan_name,))
            else:
                cur.execute(
                    "SELECT c.* FROM clans c "
                    "JOIN clan_members cm ON cm.clan_id = c.id WHERE cm.user_id=?",
                    (uid,),
                )
            clan = cur.fetchone()

            if not clan:
                return await interaction.response.send_message(
                    "公会不存在或你不在公会中 / Clan not found or you're not in a clan.",
                    ephemeral=True,
                )

            cur.execute("SELECT user_id, personal_contrib FROM clan_members WHERE clan_id=?", (clan["id"],))
            members = cur.fetchall()

        level = _get_clan_level(clan["total_contrib"])
        member_list = "\n".join(
            f"{'👑 ' if m['user_id'] == clan['owner_id'] else '👤 '}<@{m['user_id']}> — 🪙 {m['personal_contrib']:,}"
            for m in members
        )

        embed = discord.Embed(
            title=f"🏰 {clan['name']}",
            description=f"等级 / Level: **{level}**",
            color=0x9B59B6,
        )
        embed.add_field(name="💰 总贡献 / Total Contrib", value=_format_coins(clan["total_contrib"]), inline=True)
        embed.add_field(name="👥 成员 / Members", value=f"{len(members)} 人", inline=True)
        embed.add_field(name="📅 创建日期 / Created", value=clan["created_at"][:10] if clan["created_at"] else "Unknown", inline=True)
        embed.add_field(name="👥 成员列表 / Member List", value=member_list or "无 / None", inline=False)
        embed.set_footer(text="/gmpt-clan donate 捐赠公会金库")

        await interaction.response.send_message(embed=embed)

    @clan_group.command(name="donate", description="捐赠公会金库 / Donate to clan treasury")
    @app_commands.describe(amount="捐赠金额 / Amount")
    async def clan_donate(self, interaction: discord.Interaction, amount: int):
        uid = str(interaction.user.id)

        if amount < 1:
            return await interaction.response.send_message("捐赠金额必须 >= 1 / Amount >= 1.", ephemeral=True)

        bal = get_balance(uid)
        if bal < amount:
            return await interaction.response.send_message(
                f"金币不足！/ Balance: 🪙 {bal:,}", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT cm.*, c.name FROM clan_members cm "
                "JOIN clans c ON c.id = cm.clan_id WHERE cm.user_id=?",
                (uid,),
            )
            row = cur.fetchone()
            if not row:
                return await interaction.response.send_message("你不在任何公会中 / Not in a clan.", ephemeral=True)

            add_coins(uid, -amount, f"公会捐赠: {row['name']} / Clan donation")

            new_total = row["personal_contrib"] + amount
            cur.execute(
                "UPDATE clan_members SET personal_contrib=? WHERE user_id=?",
                (new_total, uid),
            )
            cur.execute(
                "UPDATE clans SET total_contrib = total_contrib + ? WHERE id=?",
                (amount, row["clan_id"]),
            )
            conn.commit()

        embed = discord.Embed(
            title="🏰 捐赠成功 / Donated!",
            description=f"向 **{row['name']}** 捐赠了 🪙 **{amount:,}**\n"
                        f"Donated 🪙 **{amount:,}** to **{row['name']}**",
            color=0x2ECC71,
        )
        embed.add_field(name="📊 个人贡献 / Your Contrib", value=_format_coins(new_total), inline=True)

        await interaction.response.send_message(embed=embed)

# ══════════════════════════════════════════════════════════════
# ClanPanelView — 公会按钮面板 / Clan Button Panel
# ══════════════════════════════════════════════════════════════

class ClanPanelView(discord.ui.View):
    """公会系统按钮面板 — 点击按钮操作公会。"""

    def __init__(self, guild=None, dashboard_view=None):
        super().__init__(timeout=300)
        self.guild = guild
        self.dashboard_view = dashboard_view
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()

        btns = [
            ("🏰 创建公会", "clan_create", discord.ButtonStyle.success),
            ("🚪 加入公会", "clan_join", discord.ButtonStyle.primary),
            ("👋 退出公会", "clan_leave", discord.ButtonStyle.danger),
            ("ℹ️ 公会信息", "clan_info", discord.ButtonStyle.primary),
            ("💰 捐赠", "clan_donate", discord.ButtonStyle.success),
        ]
        for i, (label, cid, style) in enumerate(btns):
            btn = discord.ui.Button(label=label, style=style, row=0, custom_id=f"clanp_{cid}")
            btn.callback = self._make_callback(cid)
            self.add_item(btn)

        back_btn = discord.ui.Button(
            label="返回主菜单 | Back to Main",
            style=discord.ButtonStyle.danger, row=1, custom_id="clanp_back",
        )
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    async def _back_callback(self, interaction: discord.Interaction):
        if self.dashboard_view:
            self.dashboard_view.category = 0
            self.dashboard_view.build_page_buttons()
            embed = self.dashboard_view._build_page_embed()
            await interaction.response.edit_message(embed=embed, view=self.dashboard_view)
        else:
            await interaction.response.edit_message(
                content="使用 `/gmpt-dashboard` 返回主菜单 / Use `/gmpt-dashboard` to go back.",
                embed=None, view=None,
            )

    def _make_callback(self, action: str):
        async def cb(interaction: discord.Interaction):
            uid = str(interaction.user.id)

            if action == "clan_leave":
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT cm.*, c.name, c.owner_id FROM clan_members cm "
                        "JOIN clans c ON c.id = cm.clan_id WHERE cm.user_id=?",
                        (uid,),
                    )
                    row = cur.fetchone()
                if not row:
                    return await interaction.response.send_message("你不在任何公会中 / Not in a clan.", ephemeral=True)
                if row["owner_id"] == uid:
                    return await interaction.response.send_message(
                        "会长不能离开！请先转让会长或解散公会 / Owner cannot leave!", ephemeral=True)
                with get_db_ctx() as conn:
                    conn.execute("DELETE FROM clan_members WHERE user_id=?", (uid,))
                    conn.commit()
                await interaction.response.send_message(f"👋 已离开 **{row['name']}** / Left **{row['name']}**.")
                return

            if action == "clan_info":
                with get_db_ctx() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT c.* FROM clans c "
                        "JOIN clan_members cm ON cm.clan_id = c.id WHERE cm.user_id=?",
                        (uid,),
                    )
                    clan = cur.fetchone()
                if not clan:
                    return await interaction.response.send_message("你不在任何公会中 / Not in a clan.", ephemeral=True)
                cur.execute("SELECT user_id, personal_contrib FROM clan_members WHERE clan_id=?", (clan["id"],))
                members = cur.fetchall()
                level = _get_clan_level(clan["total_contrib"])
                member_list = "\n".join(
                    f"{'👑 ' if m['user_id'] == clan['owner_id'] else '👤 '}<@{m['user_id']}> — 🪙 {m['personal_contrib']:,}"
                    for m in members
                )
                embed = discord.Embed(
                    title=f"🏰 {clan['name']}",
                    description=f"等级 / Level: **{level}**",
                    color=0x9B59B6,
                )
                embed.add_field(name="💰 总贡献 / Total Contrib", value=_format_coins(clan["total_contrib"]), inline=True)
                embed.add_field(name="👥 成员 / Members", value=f"{len(members)} 人", inline=True)
                embed.add_field(name="📅 创建日期 / Created", value=clan["created_at"][:10] if clan["created_at"] else "Unknown", inline=True)
                embed.add_field(name="👥 成员列表 / Member List", value=member_list or "无 / None", inline=False)
                await interaction.response.send_message(embed=embed)
                return

            # Actions that need a modal
            if action == "clan_create":
                modal = ClanCreateModal()
            elif action == "clan_join":
                modal = ClanJoinModal()
            elif action == "clan_donate":
                modal = ClanDonateModal()
            else:
                return
            await interaction.response.send_modal(modal)

        return cb


class ClanCreateModal(discord.ui.Modal, title="🏰 创建公会 / Create Clan"):
    clan_name = discord.ui.TextInput(
        label="公会名称 / Clan Name",
        placeholder="输入公会名（最多30字）/ Max 30 chars",
        max_length=30, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        clan_name = self.clan_name.value.strip()

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM clan_members WHERE user_id=?", (uid,))
            if cur.fetchone():
                return await interaction.response.send_message("你已经在一个公会中！/ Already in a clan!", ephemeral=True)
            cur.execute("SELECT id FROM clans WHERE name=?", (clan_name,))
            if cur.fetchone():
                return await interaction.response.send_message("公会名已存在 / Name taken.", ephemeral=True)

        bal = get_balance(uid)
        if bal < CLAN_CREATE_COST:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 {CLAN_CREATE_COST:,} / Need 🪙 {CLAN_CREATE_COST:,}.", ephemeral=True)

        add_coins(uid, -CLAN_CREATE_COST, f"创建公会: {clan_name} / Created clan")
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO clans (name, owner_id, total_contrib) VALUES (?, ?, ?)",
                        (clan_name, uid, CLAN_CREATE_COST))
            clan_id = cur.lastrowid
            cur.execute("INSERT INTO clan_members (clan_id, user_id, personal_contrib) VALUES (?, ?, ?)",
                        (clan_id, uid, CLAN_CREATE_COST))
            conn.commit()

        embed = discord.Embed(
            title="🏰 公会创建成功！/ Clan Created!",
            description=f"**{clan_name}** 正式成立！\nClan **{clan_name}** established!",
            color=0x9B59B6,
        )
        embed.add_field(name="👑 会长 / Owner", value=f"<@{uid}>", inline=True)
        embed.add_field(name="💰 创建费 / Cost", value=_format_coins(CLAN_CREATE_COST), inline=True)
        embed.add_field(name="📊 等级 / Level", value="1", inline=True)
        await interaction.response.send_message(embed=embed)


class ClanJoinModal(discord.ui.Modal, title="🚪 加入公会 / Join Clan"):
    clan_name = discord.ui.TextInput(
        label="公会名称 / Clan Name",
        placeholder="输入要加入的公会名",
        max_length=30, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        clan_name = self.clan_name.value.strip()

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM clan_members WHERE user_id=?", (uid,))
            if cur.fetchone():
                return await interaction.response.send_message("你已经在一个公会中！/ Already in a clan!", ephemeral=True)
            cur.execute("SELECT * FROM clans WHERE name=?", (clan_name,))
            clan = cur.fetchone()
            if not clan:
                return await interaction.response.send_message("公会不存在 / Clan not found.", ephemeral=True)
            cur.execute("INSERT INTO clan_members (clan_id, user_id) VALUES (?, ?)", (clan["id"], uid))
            conn.commit()

        await interaction.response.send_message(f"✅ 你已加入 **{clan_name}**！/ Joined **{clan_name}**!")


class ClanDonateModal(discord.ui.Modal, title="💰 捐赠公会 / Donate to Clan"):
    amount = discord.ui.TextInput(
        label="捐赠金额 / Amount",
        placeholder="输入金额（最小1）",
        max_length=10, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        try:
            amount = int(self.amount.value)
        except ValueError:
            return await interaction.response.send_message("请输入有效数字 / Enter a valid number.", ephemeral=True)
        if amount < 1:
            return await interaction.response.send_message("捐赠金额必须 >= 1 / Amount >= 1.", ephemeral=True)

        bal = get_balance(uid)
        if bal < amount:
            return await interaction.response.send_message(f"金币不足！/ Balance: 🪙 {bal:,}", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT cm.*, c.name FROM clan_members cm "
                "JOIN clans c ON c.id = cm.clan_id WHERE cm.user_id=?", (uid,))
            row = cur.fetchone()
            if not row:
                return await interaction.response.send_message("你不在任何公会中 / Not in a clan.", ephemeral=True)

            add_coins(uid, -amount, f"公会捐赠: {row['name']} / Clan donation")
            new_total = row["personal_contrib"] + amount
            cur.execute("UPDATE clan_members SET personal_contrib=? WHERE user_id=?", (new_total, uid))
            cur.execute("UPDATE clans SET total_contrib = total_contrib + ? WHERE id=?", (amount, row["clan_id"]))
            conn.commit()

        embed = discord.Embed(
            title="🏰 捐赠成功 / Donated!",
            description=f"向 **{row['name']}** 捐赠了 🪙 **{amount:,}**\nDonated 🪙 **{amount:,}** to **{row['name']}**",
            color=0x2ECC71,
        )
        embed.add_field(name="📊 个人贡献 / Your Contrib", value=_format_coins(new_total), inline=True)
        await interaction.response.send_message(embed=embed)



async def setup(bot):
    await bot.add_cog(Clans(bot))
