"""
GMPT Bot — Help Command / 帮助命令
"""
import discord
from discord import app_commands
from discord.ext import commands


class HelpCog(commands.Cog):
    async def cog_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            await interaction.followup.send(f"❌ 错误: {error}", ephemeral=True)
        except Exception:
            pass

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
            name="🏆 比赛 | Match",
            value=(
                "`/gmpt-create-match` — 创建比赛\n"
                "`/gmpt-signup` — 报名\n"
                "`/gmpt-start-match` — 开始\n"
                "`/gmpt-lol-settle` — 结算（锦标赛）\n"
                "`/gmpt-settle` — 结算（比赛）\n"
                "`/gmpt-pull-vc` — 拉语音\n"
                "`/gmpt-players` — 名单\n"
                "`/gmpt-random-teams` — 随机分队\n"
                "`/gmpt-pick-captain` — 队长选人"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎮 LoL",
            value=(
                "`/gmpt-create` — 创建房间\n"
                "`/gmpt-join` — 加入\n"
                "`/gmpt-rank` — 排行榜\n"
                "`/gmpt-profile-lol` — 个人主页\n"
                "`/gmpt-live-game` — 当前对局\n"
                "`/gmpt-link-riot` — 绑定Riot\n"
                "`/gmpt-zone` — 大区设置"
            ),
            inline=False,
        )

        embed.add_field(
            name="🏅 锦标赛 | Tournament",
            value=(
                "`/gmpt-tournament create` — 创建\n"
                "`/gmpt-tournament signup` — 报名\n"
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
            name="🎪 抽奖 | Giveaway",
            value=(
                "`/gmpt-giveaway` — 参与抽奖\n"
                "`/gmpt-giveaway-admin create` — 创建抽奖"
            ),
            inline=False,
        )

        embed.add_field(
            name="📊 其他 | Other",
            value=(
                "`/gmpt-dashboard` — 控制面板\n"
                "`/gmpt-stats` — 数据统计\n"
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
