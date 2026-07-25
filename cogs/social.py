"""
GMPT Bot — 社交趣味 / Social & Fun
/gmpt-marry 结婚系统 / Marriage
/gmpt-rep   声望系统 / Reputation

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


def _init_social_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS marriages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposer_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                married_at TEXT,
                divorced_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reputation (
                user_id TEXT PRIMARY KEY,
                rep_count INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rep_cooldowns (
                giver_id TEXT NOT NULL,
                date TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (giver_id, date)
            )
        """)
        conn.commit()


_init_social_tables()

PROPOSE_COST = 2000
DIVORCE_COST = 5000
MAX_DAILY_REP = 3


class Social(CogBase):
    """社交趣味系统 / Social & Fun."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[Social] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    # ══════════════════════════════════════════════════════════
    # /gmpt-marry — 结婚系统
    # ══════════════════════════════════════════════════════════
    marry_group = app_commands.Group(
        name="gmpt-marry",
        description="💍 结婚系统 / Marriage System"
    )

    @marry_group.command(name="propose", description="向某人求婚 / Propose to someone (cost: 2000 coins)")
    @app_commands.describe(target="求婚对象 / Target")
    @app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
    async def marry_propose(self, interaction: discord.Interaction, target: discord.Member):
        uid = str(interaction.user.id)
        tid = str(target.id)

        if target.id == interaction.user.id:
            return await interaction.response.send_message("不能和自己结婚 / Cannot marry yourself!", ephemeral=True)
        if target.bot:
            return await interaction.response.send_message("不能和机器人结婚 / Cannot marry bots!", ephemeral=True)

        bal = get_balance(uid)
        if bal < PROPOSE_COST:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 {PROPOSE_COST:,} / Need 🪙 {PROPOSE_COST:,}.", ephemeral=True)

        # Check existing marriage
        with get_db_ctx() as conn:
            conn.execute("BEGIN")
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM marriages WHERE "
                "(proposer_id=? OR target_id=?) AND status='married'",
                (uid, uid),
            )
            if cur.fetchone():
                conn.rollback()
                return await interaction.response.send_message("你已经结婚了！/ You're already married!", ephemeral=True)

            cur.execute(
                "SELECT * FROM marriages WHERE "
                "(proposer_id=? OR target_id=?) AND status='married'",
                (tid, tid),
            )
            if cur.fetchone():
                conn.rollback()
                return await interaction.response.send_message(
                    f"{target.display_name} 已经结婚了！/ Already married!", ephemeral=True)

            # Check pending proposal
            cur.execute(
                "SELECT * FROM marriages WHERE "
                "proposer_id=? AND target_id=? AND status='pending'",
                (uid, tid),
            )
            if cur.fetchone():
                conn.rollback()
                return await interaction.response.send_message("你已经向此人求过婚了！/ Already proposed!", ephemeral=True)

            add_coins(uid, -PROPOSE_COST, f"求婚: {target.display_name} / Proposed to {target.display_name}")

            cur.execute(
                "INSERT INTO marriages (proposer_id, target_id) VALUES (?, ?)",
                (uid, tid),
            )
            conn.commit()

        embed = discord.Embed(
            title="💍 求婚！/ Proposal!",
            description=f"{interaction.user.mention} 向 {target.mention} 求婚了！\n"
                        f"Proposed to {target.mention}!\n\n"
                        f"💍 使用 `/gmpt-marry accept` 接受\n"
                        f"💔 使用 `/gmpt-marry decline` 拒绝\n\n"
                        f"花费 / Cost: 🪙 {PROPOSE_COST:,}",
            color=0xE91E63,
        )
        await interaction.response.send_message(embed=embed)

    @marry_group.command(name="accept", description="接受求婚 / Accept a marriage proposal")
    @app_commands.checks.cooldown(1, 30, key=lambda i: (i.guild_id, i.user.id))
    async def marry_accept(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM marriages WHERE target_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
                (uid,),
            )
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "没有待处理的求婚 / No pending proposals.", ephemeral=True)

            cur.execute(
                "UPDATE marriages SET status='married', married_at=datetime('now') WHERE id=?",
                (row["id"],),
            )
            conn.commit()

        proposer = await self.bot.fetch_user(int(row["proposer_id"]))
        pname = proposer.display_name if proposer else row["proposer_id"]

        embed = discord.Embed(
            title="💒 结婚啦！/ Married!",
            description=f"🎉 **{pname}** 和 **{interaction.user.display_name}** 喜结连理！\n"
                        f"**{pname}** and **{interaction.user.display_name}** are now married!",
            color=0xE91E63,
        )
        await interaction.response.send_message(embed=embed)

    @marry_group.command(name="decline", description="拒绝求婚 / Decline a marriage proposal")
    @app_commands.checks.cooldown(1, 30, key=lambda i: (i.guild_id, i.user.id))
    async def marry_decline(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM marriages WHERE target_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
                (uid,),
            )
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "没有待处理的求婚 / No pending proposals.", ephemeral=True)

            cur.execute("UPDATE marriages SET status='declined' WHERE id=?", (row["id"],))
            conn.commit()

        proposer = await self.bot.fetch_user(int(row["proposer_id"]))
        pname = proposer.display_name if proposer else row["proposer_id"]

        await interaction.response.send_message(
            f"💔 {interaction.user.display_name} 拒绝了 **{pname}** 的求婚... / Declined."
        )

    @marry_group.command(name="divorce", description="离婚 / Divorce (cost: 5000 coins)")
    @app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
    async def marry_divorce(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        bal = get_balance(uid)
        if bal < DIVORCE_COST:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 {DIVORCE_COST:,} / Need 🪙 {DIVORCE_COST:,}.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM marriages WHERE "
                "(proposer_id=? OR target_id=?) AND status='married'",
                (uid, uid),
            )
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    "你没有结婚 / You're not married.", ephemeral=True)

            add_coins(uid, -DIVORCE_COST, "离婚费 / Divorce fee")

            cur.execute(
                "UPDATE marriages SET status='divorced', divorced_at=datetime('now') WHERE id=?",
                (row["id"],),
            )
            conn.commit()

        await interaction.response.send_message(
            f"💔 离婚成功 / Divorced. 花费 / Cost: 🪙 {DIVORCE_COST:,}"
        )

    @marry_group.command(name="status", description="查看婚姻状态 / View marriage status")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def marry_status(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM marriages WHERE "
                "(proposer_id=? OR target_id=?) AND status='married'",
                (uid, uid),
            )
            row = cur.fetchone()

        if not row:
            return await interaction.response.send_message(
                "💔 你还没结婚 / You're not married.", ephemeral=True)

        partner_id = row["target_id"] if row["proposer_id"] == uid else row["proposer_id"]
        married_date = row["married_at"][:10] if row["married_at"] else "Unknown"

        embed = discord.Embed(
            title="💍 婚姻状态 / Marriage Status",
            description=f"💑 与 / Married to: <@{partner_id}>\n"
                        f"📅 结婚日期 / Since: {married_date}",
            color=0xE91E63,
        )

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-rep — 声望系统
    # ══════════════════════════════════════════════════════════
    rep_group = app_commands.Group(
        name="gmpt-rep",
        description="⭐ 声望系统 / Reputation System"
    )

    @rep_group.command(name="give", description="给予声望 / Give reputation (max 3/day)")
    @app_commands.describe(target="目标用户 / Target user")
    async def rep_give(self, interaction: discord.Interaction, target: discord.Member):
        uid = str(interaction.user.id)
        tid = str(target.id)

        if target.id == interaction.user.id:
            return await interaction.response.send_message("不能给自己声望 / Cannot rep yourself!", ephemeral=True)
        if target.bot:
            return await interaction.response.send_message("不能给机器人声望 / Cannot rep bots!", ephemeral=True)

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        with get_db_ctx() as conn:
            cur = conn.cursor()

            # Check daily limit
            cur.execute(
                "SELECT count FROM rep_cooldowns WHERE giver_id=? AND date=?",
                (uid, today),
            )
            row = cur.fetchone()
            if row and row["count"] >= MAX_DAILY_REP:
                return await interaction.response.send_message(
                    f"今日声望已达上限 ({MAX_DAILY_REP}/天) / Daily rep limit reached.",
                    ephemeral=True,
                )

            # Update cooldown
            cur.execute(
                "INSERT INTO rep_cooldowns (giver_id, date, count) VALUES (?, ?, 1) "
                "ON CONFLICT(giver_id, date) DO UPDATE SET count=count+1",
                (uid, today),
            )

            # Update reputation
            cur.execute(
                "INSERT INTO reputation (user_id, rep_count) VALUES (?, 1) "
                "ON CONFLICT(user_id) DO UPDATE SET rep_count=rep_count+1",
                (tid,),
            )

            cur.execute("SELECT rep_count FROM reputation WHERE user_id=?", (tid,))
            new_count = cur.fetchone()["rep_count"]
            conn.commit()

        await interaction.response.send_message(
            f"⭐ {interaction.user.mention} 给了 {target.mention} 声望！"
            f" (**{new_count}** 总声望 / total rep)"
        )

    @rep_group.command(name="check", description="查看声望 / Check reputation")
    @app_commands.describe(target="目标用户（留空查看自己）/ Target (leave blank for self)")
    async def rep_check(self, interaction: discord.Interaction, target: discord.Member = None):
        if target is None:
            target = interaction.user
        tid = str(target.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT rep_count FROM reputation WHERE user_id=?", (tid,))
            row = cur.fetchone()

        count = row["rep_count"] if row else 0

        embed = discord.Embed(
            title="⭐ 声望 / Reputation",
            description=f"{target.mention} 声望: **{count}**",
            color=0xF1C40F,
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Social(bot))
