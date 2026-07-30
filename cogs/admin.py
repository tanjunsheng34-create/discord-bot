"""
GMPT Bot — Admin management
Only bot owner can add/remove admins.
"""
import logging
import discord
from discord import app_commands
from discord.ext import commands
from utils.cog_base import CogBase
from database import get_db_ctx

logger = logging.getLogger(__name__)

ADMIN_GROUP_NAME = "gmpt-admin"


def check_is_admin(bot, user_id: int, guild: discord.Guild | None = None) -> bool:
    """Check if user is bot owner or has is_admin flag."""
    # Check via bot.owner_id / application owner
    if bot.owner_id and int(user_id) == bot.owner_id:
        return True
    # Check application owner
    if bot.application and bot.application.owner:
        app_owner = bot.application.owner
        if hasattr(app_owner, 'id') and int(app_owner.id) == int(user_id):
            return True
    # Check guild owner
    if guild and guild.owner_id == int(user_id):
        return True
    # Check is_admin field
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT is_admin FROM users WHERE discord_id = ?", (str(user_id),))
        row = cur.fetchone()
    return bool(row and row["is_admin"])


def is_bot_owner(bot, user_id: int) -> bool:
    """Check if user is bot owner (application owner)."""
    if bot.owner_id and int(user_id) == bot.owner_id:
        return True
    if bot.application and bot.application.owner:
        app_owner = bot.application.owner
        if hasattr(app_owner, 'id') and int(app_owner.id) == int(user_id):
            return True
    return False


async def owner_only(interaction: discord.Interaction) -> bool:
    """Check if interaction user is bot owner. Send ephemeral error if not."""
    if is_bot_owner(interaction.client, interaction.user.id):
        return True
    await interaction.response.send_message(
        "此命令仅 Bot 主人可用 / Bot owner only.", ephemeral=True)
    return False


class AdminCog(CogBase):
    """Admin management commands."""

    admin_group = app_commands.Group(
        name=ADMIN_GROUP_NAME,
        description="管理员管理 / Admin management (Owner only)"
    )

    @admin_group.command(
        name="add",
        description="添加管理员 / Add admin"
    )
    @app_commands.describe(user="要添加的用户 / User to add as admin")
    async def admin_add(self, interaction: discord.Interaction, user: discord.Member):
        if not await owner_only(interaction):
            return
        uid = str(user.id)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (discord_id, is_admin) VALUES (?, 1)"
                " ON CONFLICT(discord_id) DO UPDATE SET is_admin = 1",
                (uid,),
            )
            conn.commit()
        await interaction.response.send_message(
            f"已将 {user.mention} 设为管理员 / {user.display_name} is now an admin.",
            ephemeral=True)
        logger.info(f"[admin] {interaction.user.id} added admin: {uid}")

    @admin_group.command(
        name="remove",
        description="移除管理员 / Remove admin"
    )
    @app_commands.describe(user="要移除的用户 / User to remove from admin")
    async def admin_remove(self, interaction: discord.Interaction, user: discord.Member):
        if not await owner_only(interaction):
            return
        uid = str(user.id)
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET is_admin = 0 WHERE discord_id = ?",
                (uid,),
            )
            conn.commit()
        await interaction.response.send_message(
            f"已移除 {user.mention} 的管理员 / {user.display_name} is no longer admin.",
            ephemeral=True)
        logger.info(f"[admin] {interaction.user.id} removed admin: {uid}")

    @admin_group.command(
        name="list",
        description="列出所有管理员 / List all admins"
    )
    async def admin_list(self, interaction: discord.Interaction):
        if not check_is_admin(interaction.client, interaction.user.id, interaction.guild):
            return await interaction.response.send_message(
                "你没有管理员权限 / You don't have admin permissions.", ephemeral=True)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT discord_id FROM users WHERE is_admin = 1")
            rows = cur.fetchall()

        if not rows:
            return await interaction.response.send_message("暂无管理员 / No admins.", ephemeral=True)

        lines = ["**管理员列表 / Admin List:**"]
        for row in rows:
            uid = int(row["discord_id"])
            member = interaction.guild.get_member(uid) if interaction.guild else None
            name = member.mention if member else f"<@{uid}>"
            lines.append(f"- {name}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
