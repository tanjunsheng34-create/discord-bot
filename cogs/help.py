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
            name="⚔️ 比赛 / Match",
            value=(
                "`/gmpt-create` — 创建比赛 | Create match\n"
                "`/gmpt-join` — 报名 | Sign up\n"
                "`/gmpt-shuffle` — 随机分队 | Random teams\n"
                "`/gmpt-settle` — 结算 | Settle\n"
                "`/gmpt-pull-vc` — 拉入语音 | Pull VC\n"
                "`/gmpt-pick-captain` — 选队长 | Pick captain"
            ),
            inline=False,
        )

        embed.add_field(
            name="🏆 赛事 / Tournament",
            value=(
                "`/gmpt-tournament create` — 创建赛事 | Create\n"
                "`/gmpt-tournament signup` — 报名 | Sign up\n"
                "`/gmpt-tournament captain` — 队长选秀 | Draft\n"
                "`/gmpt-tournament bracket` — 对阵图 | Bracket\n"
                "`/gmpt-tournament standings` — 排名 | Standings\n"
                "`/gmpt-tournament report` — 上报比分 | Report"
            ),
            inline=False,
        )

        embed.add_field(
            name="💰 经济 / Economy",
            value=(
                "`/gmpt-balance` — 余额 | Balance\n"
                "`/gmpt-shop` — 商店 | Shop\n"
                "`/gmpt-buy` — 购买 | Buy\n"
                "`/gmpt-inventory` — 背包 | Inventory\n"
                "`/gmpt-gift` — 送礼 | Gift\n"
                "`/gmpt-daily claim` — 签到 | Daily\n"
                "`/gmpt-achievements` — 成就 | Achievements\n"
                "`/gmpt-bet` — 下注 | Bet"
            ),
            inline=False,
        )

        embed.add_field(
            name="💬 社交 / Social",
            value=(
                "`/gmpt-hug <user>` — 拥抱 | Hug\n"
                "`/gmpt-slap <user>` — 拍打 | Slap\n"
                "`/gmpt-pat <user>` — 摸头 | Pat\n"
                "`/gmpt-kiss <user>` — 亲吻 | Kiss\n"
                "`/gmpt-kill <user>` — 击杀 | Kill\n"
                "`/gmpt-level` — 我的等级 | My level\n"
                "`/gmpt-level-leaderboard` — 等级排行 | Level LB"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎮 小游戏 / Mini Games",
            value=(
                "`/gmpt-slots` — 老虎机 | Slots\n"
                "`/gmpt-coinflip` — 猜硬币 | Coinflip\n"
                "`/gmpt-trivia` — 知识问答 | Trivia\n"
                "`/gmpt-guess-champion` — 猜英雄 | Guess champ\n"
                "`/gmpt-predict` — 比赛预测竞猜 | Predict\n"
                "`/gmpt-meme` — 表情包生成 | Meme"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎮 LoL / League",
            value=(
                "`/gmpt-profile-lol` — 战绩查询 | Profile\n"
                "`/gmpt-rank` — 段位查询 | Rank\n"
                "`/gmpt-stream` — 直播通知 | Stream\n"
                "`/gmpt-match-history` — 比赛历史 | History\n"
                "`/gmpt-lol-settle` — 比赛结算 | Settle\n"
                "`/gmpt-vc-setup` — 语音分区配置 | VC setup"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔧 工具 / Tools",
            value=(
                "`/gmpt-dashboard` — 控制面板 | Dashboard\n"
                "`/gmpt-stats` — 数据统计 | Stats\n"
                "`/gmpt-finance` — 财务统计 | Finance\n"
                "`/gmpt-voicetime` — 语音时长 | Voice time\n"
                "`/gmpt-queue` — 排队 | Queue\n"
                "`/gmpt-transactions` — 交易记录 | Transactions\n"
                "`/gmpt-daily-tasks` — 每日任务 | Daily tasks\n"
                "`/announce` — 公告(管理) | Announce"
            ),
            inline=False,
        )

        embed.set_footer(text="🔒 带锁标的命令仅管理员可用 | Lock icon = Admin only")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
