"""
GMPT Bot — CogBase 统一异常处理基类

所有 cog 继承此类后可删除自己的 cog_command_error，
统一处理 cooldown / 通用异常，包含 is_done() 检查。
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)


class CogBase(commands.Cog):
    """统一的 cog_command_error 处理基类。"""

    async def cog_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            if isinstance(error, app_commands.CommandOnCooldown):
                remaining = int(error.retry_after)
                msg = f"⏳ 冷却中，请等 {remaining} 秒 / Cooldown, wait {remaining}s."
                if not interaction.response.is_done():
                    await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await interaction.followup.send(msg, ephemeral=True)
            else:
                err_msg = f"❌ 错误: {error}"
                if not interaction.response.is_done():
                    await interaction.response.send_message(err_msg, ephemeral=True)
                else:
                    await interaction.followup.send(err_msg, ephemeral=True)
        except Exception:
            pass
