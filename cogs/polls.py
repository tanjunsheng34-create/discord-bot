"""
GMPT Bot — Poll System (Utility Bot)
Create multi-option polls with deadline and result display.
No money involved.
"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from datetime import datetime, timezone, timedelta
import logging
from utils.logger import log_error
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

# Beijing timezone for deadline display
_BJT = timezone(timedelta(hours=8))


class Polls(CogBase):
    """Poll creation and management system."""

    def __init__(self, bot):
        self.bot = bot

    poll_group = app_commands.Group(
        name="gmpt-poll",
        description="Create and manage polls / 创建和管理投票"
    )

    @poll_group.command(
        name="create",
        description="Create a multi-option poll / 创建多选投票"
    )
    @app_commands.describe(
        question="The poll question / 投票问题",
        option1="Option 1",
        option2="Option 2",
        option3="Option 3 (optional)",
        option4="Option 4 (optional)",
        option5="Option 5 (optional)",
        option6="Option 6 (optional)",
        option7="Option 7 (optional)",
        option8="Option 8 (optional)",
        option9="Option 9 (optional)",
        option10="Option 10 (optional)",
        deadline_minutes="Auto-close after N minutes (0 = no deadline) / N分钟后自动关闭 (0=不限时)",
    )
    async def create_poll(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str | None = None,
        option4: str | None = None,
        option5: str | None = None,
        option6: str | None = None,
        option7: str | None = None,
        option8: str | None = None,
        option9: str | None = None,
        option10: str | None = None,
        deadline_minutes: int = 0,
    ):
        """Create a poll with custom options."""
        options = [option1, option2]
        for opt in [option3, option4, option5, option6, option7, option8, option9, option10]:
            if opt:
                options.append(opt)

        if len(options) < 2:
            return await interaction.response.send_message(
                "至少需要 2 个选项 / At least 2 options required.", ephemeral=True
            )

        if len(options) > 10:
            options = options[:10]

        emoji_list = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

        desc_lines = [f"**{question}**\n"]
        for i, opt in enumerate(options):
            desc_lines.append(f"{emoji_list[i]} {opt}")

        deadline_str = "无限制 / No limit"
        if deadline_minutes > 0:
            deadline_dt = datetime.now(_BJT) + timedelta(minutes=deadline_minutes)
            deadline_str = deadline_dt.strftime("%Y-%m-%d %H:%M") + " (UTC+8)"

        desc_lines.append(f"\n⏰ 截止 / Deadline: **{deadline_str}**")
        desc_lines.append(f"👤 创建者 / Created by: {interaction.user.mention}")

        embed = discord.Embed(
            title="📊 投票 / Poll",
            description="\n".join(desc_lines),
            color=0x5865F2,
        )
        embed.set_footer(text="点击下方表情投票 / React to vote")

        await interaction.response.defer(ephemeral=True)
        msg = await interaction.channel.send(embed=embed)

        for i in range(len(options)):
            try:
                await msg.add_reaction(emoji_list[i])
            except Exception:
                pass

        # Save to DB for tracking
        with get_db_ctx() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS polls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    creator_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    deadline INTEGER,
                    created_at INTEGER NOT NULL,
                    closed INTEGER DEFAULT 0
                )"""
            )
            deadline_ts = None
            if deadline_minutes > 0:
                deadline_ts = int((datetime.now(_BJT) + timedelta(minutes=deadline_minutes)).timestamp())

            import json
            conn.execute(
                "INSERT INTO polls (guild_id, channel_id, message_id, creator_id, question, options_json, deadline, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(interaction.guild_id),
                    str(interaction.channel_id),
                    msg.id,
                    str(interaction.user.id),
                    question,
                    json.dumps(options),
                    deadline_ts,
                    int(datetime.now(_BJT).timestamp()),
                ),
            )
            conn.commit()

        await interaction.followup.send(
            f"投票已创建！消息 ID: {msg.id}\nPoll created! Message ID: {msg.id}",
            ephemeral=True,
        )

        # Schedule auto-close if deadline set
        if deadline_minutes > 0:
            await asyncio.sleep(deadline_minutes * 60)
            await self._close_poll_by_id(msg.id, interaction.guild)
            logger.info(f"Auto-closed poll {msg.id} after {deadline_minutes}min")

    @poll_group.command(
        name="close",
        description="Manually close a poll and show results / 手动关闭投票并显示结果"
    )
    @app_commands.describe(
        message_id="The poll message ID / 投票消息ID"
    )
    async def close_poll(self, interaction: discord.Interaction, message_id: str):
        """Close poll and tally results."""
        try:
            mid = int(message_id)
        except ValueError:
            return await interaction.response.send_message(
                "消息 ID 必须是数字 / Message ID must be a number.", ephemeral=True
            )

        await interaction.response.defer()
        await self._close_poll_by_id(mid, interaction.guild, interaction)

    async def _close_poll_by_id(
        self, message_id: int, guild: discord.Guild, interaction: discord.Interaction | None = None
    ):
        """Internal: close a poll, count reactions, post results."""
        with get_db_ctx() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS polls (id INTEGER PRIMARY KEY)")
            cur = conn.execute(
                "SELECT * FROM polls WHERE message_id=? AND guild_id=?",
                (message_id, str(guild.id)),
            )
            row = cur.fetchone()

        if row is None:
            if interaction:
                await interaction.followup.send("未找到该投票 / Poll not found.", ephemeral=True)
            return

        if row["closed"]:
            if interaction:
                await interaction.followup.send("该投票已关闭 / Poll already closed.", ephemeral=True)
            return

        channel = guild.get_channel(int(row["channel_id"]))
        if channel is None:
            if interaction:
                await interaction.followup.send("找不到投票频道 / Channel not found.", ephemeral=True)
            return

        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            if interaction:
                await interaction.followup.send("找不到投票消息 / Message not found.", ephemeral=True)
            return

        import json
        options = json.loads(row["options_json"])
        emoji_list = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

        results = []
        total_votes = 0
        for i, opt in enumerate(options):
            count = 0
            for reaction in msg.reactions:
                if str(reaction.emoji) == emoji_list[i]:
                    count = reaction.count - 1  # subtract bot's own reaction
                    if count < 0:
                        count = 0
            total_votes += count
            results.append((emoji_list[i], opt, count))

        # Build results embed
        desc_lines = [f"**{row['question']}**\n"]
        for emoji, opt, count in results:
            pct = f"({count / total_votes * 100:.1f}%)" if total_votes > 0 else "(0%)"
            bar = "█" * min(count, 20) if total_votes > 0 else ""
            desc_lines.append(f"{emoji} {opt}: **{count}** 票 {pct} {bar}")

        desc_lines.append(f"\n👥 总票数 / Total: **{total_votes}**")
        desc_lines.append(f"✅ 投票已关闭 / Poll closed")

        embed = discord.Embed(
            title="📊 投票结果 / Poll Results",
            description="\n".join(desc_lines),
            color=0x2ECC71,
        )

        await channel.send(embed=embed)

        with get_db_ctx() as conn:
            conn.execute(
                "UPDATE polls SET closed=1 WHERE message_id=? AND guild_id=?",
                (message_id, str(guild.id)),
            )
            conn.commit()

        if interaction:
            await interaction.followup.send("投票已关闭 / Poll closed.", ephemeral=True)

    @poll_group.command(
        name="results",
        description="Show current results of a poll without closing / 查看当前结果（不关闭）"
    )
    @app_commands.describe(
        message_id="The poll message ID / 投票消息ID"
    )
    async def show_results(self, interaction: discord.Interaction, message_id: str):
        """Show live poll results."""
        try:
            mid = int(message_id)
        except ValueError:
            return await interaction.response.send_message(
                "消息 ID 必须是数字 / Message ID must be a number.", ephemeral=True
            )

        with get_db_ctx() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS polls (id INTEGER PRIMARY KEY)")
            cur = conn.execute(
                "SELECT * FROM polls WHERE message_id=? AND guild_id=?",
                (mid, str(interaction.guild_id)),
            )
            row = cur.fetchone()

        if row is None:
            return await interaction.response.send_message(
                "未找到该投票 / Poll not found.", ephemeral=True
            )

        channel = interaction.guild.get_channel(int(row["channel_id"]))
        if channel is None:
            return await interaction.response.send_message(
                "找不到投票频道 / Channel not found.", ephemeral=True
            )

        try:
            msg = await channel.fetch_message(mid)
        except discord.NotFound:
            return await interaction.response.send_message(
                "找不到投票消息 / Message not found.", ephemeral=True
            )

        import json
        options = json.loads(row["options_json"])
        emoji_list = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

        results = []
        total_votes = 0
        for i, opt in enumerate(options):
            count = 0
            for reaction in msg.reactions:
                if str(reaction.emoji) == emoji_list[i]:
                    count = reaction.count - 1
                    if count < 0:
                        count = 0
            total_votes += count
            results.append((emoji_list[i], opt, count))

        desc_lines = [f"**{row['question']}**\n"]
        for emoji, opt, count in results:
            pct = f"({count / total_votes * 100:.1f}%)" if total_votes > 0 else "(0%)"
            desc_lines.append(f"{emoji} {opt}: **{count}** 票 {pct}")

        status = "已关闭 / Closed" if row["closed"] else "进行中 / Open"
        desc_lines.append(f"\n👥 总票数 / Total: **{total_votes}**")
        desc_lines.append(f"📌 状态 / Status: **{status}**")

        embed = discord.Embed(
            title="📊 投票实时结果 / Live Poll Results",
            description="\n".join(desc_lines),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Polls(bot))
