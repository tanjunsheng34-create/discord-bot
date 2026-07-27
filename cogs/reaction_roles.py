"""
GMPT Bot — Reaction Role System (Utility Bot)
Let admin set a message + emoji → users click emoji to auto-get role.
No money involved.
"""
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
import logging
from utils.logger import log_error
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)


class ReactionRoles(CogBase):
    """Reaction-based role assignment system."""

    def __init__(self, bot):
        self.bot = bot

    reactionrole_group = app_commands.Group(
        name="gmpt-reactionrole",
        description="Manage reaction roles / 管理反应角色"
    )

    @reactionrole_group.command(
        name="add",
        description="Add a reaction-role mapping to a message / 添加消息表情→角色映射"
    )
    @app_commands.describe(
        message_id="The message ID to watch",
        emoji="The emoji to react with",
        role="The role to assign"
    )
    async def add(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        """Set up a reaction-role binding."""
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message(
                "需要管理角色权限 / Manage Roles permission required.", ephemeral=True
            )

        try:
            mid = int(message_id)
        except ValueError:
            return await interaction.response.send_message(
                "消息 ID 必须是数字 / Message ID must be a number.", ephemeral=True
            )

        with get_db_ctx() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS reaction_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    emoji TEXT NOT NULL,
                    role_id TEXT NOT NULL,
                    UNIQUE(message_id, emoji)
                )"""
            )
            try:
                conn.execute(
                    "INSERT INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id) VALUES (?,?,?,?,?)",
                    (str(interaction.guild_id), str(interaction.channel_id), mid, emoji, str(role.id)),
                )
                conn.commit()
            except Exception:
                return await interaction.response.send_message(
                    f"该消息的 {emoji} 已绑定角色 / That emoji is already bound to a role on this message.",
                    ephemeral=True,
                )

        await interaction.response.send_message(
            f"已绑定：在消息 {message_id} 点 {emoji} → 获得 {role.mention}\n"
            f"Bound: react {emoji} on message {message_id} → get {role.name}",
            ephemeral=True,
        )

    @reactionrole_group.command(
        name="setup",
        description="Create a reaction-role message in this channel / 在当前频道创建反应角色消息"
    )
    @app_commands.describe(
        title="Embed title",
        description_text="Embed description (use \\n for new line)",
        emoji1="Emoji 1",
        role1="Role for emoji 1",
        emoji2="Emoji 2 (optional)",
        role2="Role for emoji 2 (optional)",
        emoji3="Emoji 3 (optional)",
        role3="Role for emoji 3 (optional)",
        emoji4="Emoji 4 (optional)",
        role4="Role for emoji 4 (optional)",
        emoji5="Emoji 5 (optional)",
        role5="Role for emoji 5 (optional)",
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        title: str,
        description_text: str,
        emoji1: str,
        role1: discord.Role,
        emoji2: str | None = None,
        role2: discord.Role | None = None,
        emoji3: str | None = None,
        role3: discord.Role | None = None,
        emoji4: str | None = None,
        role4: discord.Role | None = None,
        emoji5: str | None = None,
        role5: discord.Role | None = None,
    ):
        """Create a reaction-role message."""
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message(
                "需要管理角色权限 / Manage Roles permission required.", ephemeral=True
            )

        pairs = [(emoji1, role1)]
        for e, r in [(emoji2, role2), (emoji3, role3), (emoji4, role4), (emoji5, role5)]:
            if e and r:
                pairs.append((e, r))

        desc = description_text.replace("\\n", "\n")
        embed = discord.Embed(title=title, description=desc, color=0x5865F2)
        embed.set_footer(text="点击下方表情获取角色 / React to get roles")

        await interaction.response.defer(ephemeral=True)
        msg = await interaction.channel.send(embed=embed)

        with get_db_ctx() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS reaction_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    emoji TEXT NOT NULL,
                    role_id TEXT NOT NULL,
                    UNIQUE(message_id, emoji)
                )"""
            )
            for emoji, role in pairs:
                try:
                    await msg.add_reaction(emoji)
                except Exception as e:
                    logger.warning(f"Failed to add reaction {emoji}: {e}")
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id) VALUES (?,?,?,?,?)",
                    (str(interaction.guild_id), str(interaction.channel_id), msg.id, emoji, str(role.id)),
                )
            conn.commit()

        await interaction.followup.send(
            f"已创建反应角色消息！消息 ID: {msg.id}\nCreated reaction-role message! Message ID: {msg.id}",
            ephemeral=True,
        )

    @reactionrole_group.command(
        name="list",
        description="List all reaction-role bindings in this server / 列出所有反应角色绑定"
    )
    async def list_bindings(self, interaction: discord.Interaction):
        """Show all reaction-role mappings."""
        with get_db_ctx() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS reaction_roles (id INTEGER PRIMARY KEY)"
            )
            cur = conn.execute(
                "SELECT message_id, emoji, role_id FROM reaction_roles WHERE guild_id=?",
                (str(interaction.guild_id),),
            )
            rows = cur.fetchall()

        if not rows:
            return await interaction.response.send_message(
                "暂无反应角色绑定 / No reaction-role bindings yet.", ephemeral=True
            )

        lines = []
        for r in rows:
            role = interaction.guild.get_role(int(r["role_id"]))
            role_name = role.name if role else f"Deleted ({r['role_id']})"
            lines.append(
                f"消息 {r['message_id']} | {r['emoji']} → {role_name}"
            )

        embed = discord.Embed(
            title="反应角色绑定 / Reaction-Role Bindings",
            description="\n".join(lines[:25]),
            color=0x5865F2,
        )
        if len(lines) > 25:
            embed.set_footer(text=f"... and {len(lines) - 25} more")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reactionrole_group.command(
        name="remove",
        description="Remove a reaction-role binding / 移除反应角色绑定"
    )
    @app_commands.describe(
        message_id="The message ID",
        emoji="The emoji to unbind"
    )
    async def remove(self, interaction: discord.Interaction, message_id: str, emoji: str):
        """Remove a reaction-role mapping."""
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message(
                "需要管理角色权限 / Manage Roles permission required.", ephemeral=True
            )

        try:
            mid = int(message_id)
        except ValueError:
            return await interaction.response.send_message(
                "消息 ID 必须是数字 / Message ID must be a number.", ephemeral=True
            )

        with get_db_ctx() as conn:
            cur = conn.execute(
                "DELETE FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
                (str(interaction.guild_id), mid, emoji),
            )
            conn.commit()
            if cur.rowcount == 0:
                return await interaction.response.send_message(
                    "未找到该绑定 / Binding not found.", ephemeral=True
                )

        await interaction.response.send_message(
            f"已移除消息 {message_id} 上 {emoji} 的绑定 / Removed binding.", ephemeral=True
        )

    # ── Event: raw_reaction_add / remove ──
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Assign role when user reacts."""
        if payload.member is None or payload.member.bot:
            return

        with get_db_ctx() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS reaction_roles (id INTEGER PRIMARY KEY)"
            )
            cur = conn.execute(
                "SELECT role_id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
                (str(payload.guild_id), payload.message_id, str(payload.emoji)),
            )
            row = cur.fetchone()

        if row is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(int(row["role_id"]))
        if role is None:
            return
        try:
            await payload.member.add_roles(role, reason="Reaction role")
        except discord.Forbidden:
            logger.warning(f"Cannot assign role {role.name} — missing permissions")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Remove role when user un-reacts."""
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        with get_db_ctx() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS reaction_roles (id INTEGER PRIMARY KEY)"
            )
            cur = conn.execute(
                "SELECT role_id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",
                (str(payload.guild_id), payload.message_id, str(payload.emoji)),
            )
            row = cur.fetchone()

        if row is None:
            return

        role = guild.get_role(int(row["role_id"]))
        if role is None:
            return
        try:
            await member.remove_roles(role, reason="Reaction role removed")
        except discord.Forbidden:
            logger.warning(f"Cannot remove role {role.name} — missing permissions")


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
