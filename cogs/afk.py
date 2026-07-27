"""
GMPT Bot — AFK System (Utility Bot)
Users set AFK status; when pinged, bot auto-replies.
No money involved.
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import logging
from utils.logger import log_error
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

_BJT = timezone(timedelta(hours=8))

# In-memory AFK store: user_id (str) -> {"reason": str, "since": float}
_afk_users: dict[str, dict] = {}


class AFK(CogBase):
    """AFK (Away From Keyboard) status system."""

    def __init__(self, bot):
        self.bot = bot

    afk_group = app_commands.Group(
        name="gmpt-afk",
        description="Set or manage AFK status / 设置暂离状态"
    )

    @afk_group.command(
        name="set",
        description="Set your AFK status / 设置暂离状态"
    )
    @app_commands.describe(
        reason="Reason for being AFK / 暂离原因"
    )
    async def set_afk(self, interaction: discord.Interaction, reason: str = "暂离中 / Away"):
        """Mark yourself as AFK."""
        uid = str(interaction.user.id)
        _afk_users[uid] = {
            "reason": reason,
            "since": datetime.now(_BJT).timestamp(),
        }
        await interaction.response.send_message(
            f"已将你设为 AFK: {reason}\nYou are now AFK: {reason}",
            ephemeral=True,
        )

    @afk_group.command(
        name="list",
        description="List all AFK users / 列出所有暂离用户"
    )
    async def list_afk(self, interaction: discord.Interaction):
        """Show all AFK users."""
        if not _afk_users:
            return await interaction.response.send_message(
                "当前无人 AFK / No one is currently AFK.", ephemeral=True
            )

        lines = []
        for uid, data in list(_afk_users.items()):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"Unknown ({uid})"
            dt = datetime.fromtimestamp(data["since"], _BJT).strftime("%H:%M")
            lines.append(f"• **{name}** — {data['reason']} (自/from {dt})")

        embed = discord.Embed(
            title="暂离用户 / AFK Users",
            description="\n".join(lines[:25]),
            color=0xF39C12,
        )
        if len(lines) > 25:
            embed.set_footer(text=f"... and {len(lines) - 25} more")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @afk_group.command(
        name="remove",
        description="Remove someone's AFK status (admin only) / 移除某人的暂离状态"
    )
    @app_commands.describe(
        member="The member to remove AFK from / 要移除暂离的成员"
    )
    async def remove_afk(self, interaction: discord.Interaction, member: discord.Member):
        """Admin: remove a user's AFK status."""
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message(
                "需要管理成员权限 / Moderate Members permission required.", ephemeral=True
            )

        uid = str(member.id)
        if uid not in _afk_users:
            return await interaction.response.send_message(
                f"{member.display_name} 没有 AFK 状态 / is not AFK.", ephemeral=True
            )

        del _afk_users[uid]
        await interaction.response.send_message(
            f"已移除 {member.mention} 的 AFK 状态 / Removed AFK status.", ephemeral=True
        )

    # ── Event: auto-reply when AFK user is pinged ──
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Auto-reply when an AFK user is mentioned."""
        if message.author.bot or message.guild is None:
            return

        # Check if the author was AFK and came back
        author_uid = str(message.author.id)
        if author_uid in _afk_users:
            del _afk_users[author_uid]
            await message.channel.send(
                f"👋 欢迎回来 {message.author.mention}！已自动解除 AFK 状态。\n"
                f"Welcome back! AFK status removed.",
                delete_after=10,
            )
            return

        # Check if any mentioned users are AFK
        if not message.mentions:
            return

        afk_mentions = []
        for member in message.mentions:
            uid = str(member.id)
            if uid in _afk_users:
                data = _afk_users[uid]
                dt = datetime.fromtimestamp(data["since"], _BJT).strftime("%Y-%m-%d %H:%M")
                afk_mentions.append(
                    f"• **{member.display_name}** — {data['reason']} (自/from {dt})"
                )

        if afk_mentions:
            embed = discord.Embed(
                title="暂离通知 / AFK Notice",
                description="\n".join(afk_mentions),
                color=0xF39C12,
            )
            await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AFK(bot))
