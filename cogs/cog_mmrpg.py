"""
MMORPG Core Cog — MMORPG 核心系统
"""
import asyncio
import discord
from discord.ext import commands
from utils.cog_base import CogBase
import logging

logger = logging.getLogger(__name__)


class MMRPGCog(CogBase):
    """MMORPG 核心系统 / MMORPG Core System"""

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def cog_load(self):
        logger.info("[MMRPG] MMORPG 核心系统已加载 / MMORPG core loaded")

    async def cog_unload(self):
        logger.info("[MMRPG] MMORPG 核心系统已关闭 / MMORPG core stopped")


async def setup(bot: commands.Bot):
    await bot.add_cog(MMRPGCog(bot))
    logger.info("MMORPG core cog loaded")
