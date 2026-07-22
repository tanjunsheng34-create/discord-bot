"""
GMPT Bot — 快速比赛系统 (Quick Match System) [DEPRECATED]
All commands migrated to Dashboard / 所有命令已迁移至控制面板
"""
import discord
from discord import app_commands
from discord.ext import commands

import logging
logger = logging.getLogger(__name__)

DEPRECATED_MSG = "此命令已迁移到控制面板 /dashboard，请使用控制面板操作。"


class Match(commands.Cog):
    async def cog_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            await interaction.followup.send(f"❌ 错误: {error}", ephemeral=True)
        except Exception:
            pass

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="gmpt-create-match",
        description="[DEPRECATED] Create a new match room / 创建比赛房间 — 请使用控制面板"
    )
    @app_commands.describe(name="Match name / 比赛名称")
    async def create_match_cmd(self, interaction: discord.Interaction, name: str):
        await interaction.response.send_message(DEPRECATED_MSG, ephemeral=True)

    @app_commands.command(
        name="gmpt-signup",
        description="[DEPRECATED] Sign up for a match / 报名参赛 — 请使用控制面板"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending) / 比赛ID（默认：最近未开始的比赛）")
    async def signup_cmd(self, interaction: discord.Interaction, match_id: int = None):
        await interaction.response.send_message(DEPRECATED_MSG, ephemeral=True)

    @app_commands.command(
        name="gmpt-random-teams",
        description="[DEPRECATED] Shuffle / 随机打乱 — 请使用控制面板"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending) / 比赛ID")
    async def random_teams_cmd(self, interaction: discord.Interaction, match_id: int = None):
        await interaction.response.send_message(DEPRECATED_MSG, ephemeral=True)

    @app_commands.command(
        name="gmpt-assign-ab",
        description="[DEPRECATED] Split into A/B / 分为A/B队 — 请使用控制面板"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending) / 比赛ID")
    async def assign_ab_cmd(self, interaction: discord.Interaction, match_id: int = None):
        await interaction.response.send_message(DEPRECATED_MSG, ephemeral=True)

    @app_commands.command(
        name="gmpt-start-match",
        description="[DEPRECATED] Start a match / 开始比赛 — 请使用控制面板"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending) / 比赛ID")
    @app_commands.default_permissions(administrator=True)
    async def start_match_cmd(self, interaction: discord.Interaction, match_id: int = None):
        await interaction.response.send_message(DEPRECATED_MSG, ephemeral=True)

    @app_commands.command(
        name="gmpt-settle",
        description="[DEPRECATED] Settle a match / 结算比赛 — 请使用控制面板"
    )
    @app_commands.describe(
        match_id="Match ID (default: latest active) / 比赛ID",
        win_team="Winning team: A or B / 获胜队伍",
    )
    @app_commands.choices(win_team=[
        app_commands.Choice(name="Team A / A队", value="A"),
        app_commands.Choice(name="Team B / B队", value="B"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def settle_cmd(self, interaction: discord.Interaction, win_team: str, match_id: int = None):
        await interaction.response.send_message(DEPRECATED_MSG, ephemeral=True)

    @app_commands.command(
        name="gmpt-pull-vc",
        description="[DEPRECATED] Pull VC / 拉语音 — 请使用控制面板"
    )
    @app_commands.describe(match_id="Match ID (default: latest active) / 比赛ID")
    async def pull_vc_cmd(self, interaction: discord.Interaction, match_id: int = None):
        await interaction.response.send_message(DEPRECATED_MSG, ephemeral=True)

    @app_commands.command(
        name="gmpt-pick-captain",
        description="[DEPRECATED] Pick 2 captains / 选2位队长 — 请使用控制面板"
    )
    @app_commands.describe(match_id="Match ID (default: latest pending) / 比赛ID")
    async def pick_captain_cmd(self, interaction: discord.Interaction, match_id: int = None):
        await interaction.response.send_message(DEPRECATED_MSG, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Match(bot))
