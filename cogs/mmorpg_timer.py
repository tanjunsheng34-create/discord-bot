"""
MMORPG Timer Cog — 定时任务系统
"""
import asyncio
import discord
from discord.ext import commands
from utils.cog_base import CogBase
import logging

logger = logging.getLogger(__name__)


class TimerCog(CogBase):
    """定时任务系统 / Timer System"""

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self._timer_task: asyncio.Task | None = None

    async def cog_load(self):
        logger.info("[Timer] 定时系统已加载 / Timer system loaded")

    async def cog_unload(self):
        if self._timer_task:
            self._timer_task.cancel()
        logger.info("[Timer] 定时系统已关闭 / Timer system stopped")


async def setup(bot: commands.Bot):
    await bot.add_cog(TimerCog(bot))
    logger.info("MMORPG Timer cog loaded")
