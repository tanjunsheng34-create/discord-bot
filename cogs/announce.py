"""
GMPT Bot — 公告系统 / Announcement System
/announce title:标题 content:内容 — 发送一条带标题和正文的 Embed 公告
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils.logger import log_error


class Announce(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="announce", description="Send an announcement / 发送公告")
    @app_commands.describe(
        title="Announcement title / 公告标题",
        content="Announcement body / 公告正文",
        channel="Target channel (default: current) / 目标频道（默认当前频道）",
    )
    async def announce_cmd(
        self,
        interaction: discord.Interaction,
        title: str,
        content: str,
        channel: discord.TextChannel = None,
    ):
        """Send a styled embed announcement to the specified channel."""

        # Permission check — only members with Manage Messages can announce
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message(
                "You need **Manage Messages** permission to use this command.",
                ephemeral=True,
            )

        target = channel or interaction.channel
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title=title,
            description=content,
            color=discord.Color.gold(),
        )

        await target.send(embed=embed)
        await interaction.followup.send(
            f"Announcement sent to {target.mention}.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Announce(bot))
