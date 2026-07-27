"""GMPT Bot — Game Lobby placeholder (coming soon)"""
from discord.ext import commands
from utils.cog_base import CogBase
import logging

logger = logging.getLogger(__name__)


class GameLobbyCog(CogBase):
    """游戏大厅 / Game Lobby (即将上线 / Coming Soon)"""

    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(GameLobbyCog(bot))
