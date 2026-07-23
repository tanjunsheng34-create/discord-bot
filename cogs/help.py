"""
GMPT Bot — Help Command / 帮助命令
"""
import discord
from discord import app_commands
from discord.ext import commands
from utils.cog_base import CogBase


class HelpCog(CogBase):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="gmpt-help", description="Show all commands")
    async def gmpt_help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📖 GMPT 帮助 | Help",
            description="以下是所有可用命令 | All available commands:",
            color=0x2ECC71,
        )

        embed.add_field(
            name="🏅 锦标赛 | Tournament",
            value=(
                "`/gmpt-tournament create` — 创建\n"
                "`/gmpt-tournament signup` — 报名\n"
                "`/gmpt-tournament captain` — 队长选秀\n"
                "`/gmpt-tournament bracket` — 对阵图\n"
                "`/gmpt-tournament standings` — 排名\n"
                "`/gmpt-tournament report` — 上报比分"
            ),
            inline=False,
        )

        embed.add_field(
            name="💰 经济 | Economy",
            value=(
                "`/gmpt-balance` — 余额\n"
                "`/gmpt-shop` — 商店\n"
                "`/gmpt-buy` — 购买\n"
                "`/gmpt-inventory` — 背包\n"
                "`/gmpt-gift` — 送礼\n"
                "`/gmpt-daily claim` — 签到\n"
                "`/gmpt-achievements` — 成就\n"
                "`/gmpt-bet` — 下注"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎪 升级 | Level",
            value=(
                "`/gmpt-level` — 我的等级\n"
                "`/gmpt-level-leaderboard` — 等级排行\n"
                "`/gmpt-daily-tasks` — 每日任务"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎮 小游戏 | Mini Games",
            value=(
                "`/gmpt-slots` — 老虎机\n"
                "`/gmpt-coinflip` — 猜硬币\n"
                "`/gmpt-trivia` — 知识问答\n"
                "`/gmpt-guess-champion` — 猜英雄\n"
                "`/gmpt-predict` — 比赛预测竞猜\n"
                "`/gmpt-meme` — 表情包生成"
            ),
            inline=False,
        )

        embed.add_field(
            name="💕 虚拟动作 | Actions",
            value=(
                "`/gmpt-hug <user>` — 拥抱\n"
                "`/gmpt-slap <user>` — 拍打\n"
                "`/gmpt-pat <user>` — 摸头\n"
                "`/gmpt-kiss <user>` — 亲吻\n"
                "`/gmpt-kill <user>` — 击杀"
            ),
            inline=False,
        )

        embed.add_field(
            name="📊 其他 | Other",
            value=(
                "`/gmpt-dashboard` — 控制面板\n"
                "`/gmpt-stats` — 数据统计\n"
                "`/gmpt-finance` — 财务统计\n"
                "`/gmpt-voicetime` — 语音时长\n"
                "`/gmpt-queue` — 排队\n"
                "`/gmpt-transactions` — 交易记录\n"
                "`/announce` — 公告(管理)"
            ),
            inline=False,
        )

        embed.set_footer(text="🔒 带锁标的命令仅管理员可用 | Lock icon = Admin only")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
