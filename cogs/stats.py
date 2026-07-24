"""
服务器统计看板 / Server Stats Dashboard
命令: /gmpt-stats — 显示服务器实时统计数据
"""

import discord
from discord import app_commands
from discord.ext import commands
from utils.cog_base import CogBase


class Stats(CogBase):
    """服务器统计看板 / Server Stats Dashboard."""

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.message_count: dict[int, int] = {}  # guild_id -> today's message count
        self.join_count: dict[int, int] = {}  # guild_id -> today's join count
        self.last_seen_from: dict[int, dict[str, int]] = {}  # guild_id -> message date tracking
        self.today: str = ""  # YYYY-MM-DD to detect day change

    # ── Event: message tracking ──────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        gid = message.guild.id
        self._check_day_reset()

        self.message_count[gid] = self.message_count.get(gid, 0) + 1

    # ── Event: member join tracking ──────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        gid = member.guild.id
        self._check_day_reset()
        self.join_count[gid] = self.join_count.get(gid, 0) + 1

    def _check_day_reset(self):
        """检测日期变更，重置每日计数器。"""
        import datetime as _dt
        t = _dt.datetime.now().strftime("%Y-%m-%d")
        if t != self.today:
            self.today = t
            self.message_count.clear()
            self.join_count.clear()

    # ── Command: /gmpt-stats ──────────────────────────────────

    @app_commands.command(name="gmpt-stats", description="📊 服务器统计看板 / Server Stats Dashboard")
    async def stats_cmd(self, interaction: discord.Interaction):
        """显示服务器实时统计数据。"""
        await interaction.response.defer()

        guild = interaction.guild
        if not guild:
            return await interaction.followup.send("仅在服务器内可用 / Server only.")

        gid = guild.id
        self._check_day_reset()

        total_members = guild.member_count or len(guild.members)
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)

        # 语音在线人数 / VC Online
        vc_online = 0
        for vc in guild.voice_channels:
            vc_online += len(vc.members)

        # 今日消息数 / Messages Today
        msgs_today = self.message_count.get(gid, 0)

        # 今日加入数 / New Joins Today
        joins_today = self.join_count.get(gid, 0)

        # 最活跃频道 / Most Active Channel (from text channels that had recent messages)
        active_channel = "N/A"
        try:
            # Sort text channels by last message time
            text_channels = [
                ch for ch in guild.text_channels
                if ch.permissions_for(guild.me).read_message_history
            ]
            if text_channels:
                # Try to find the most recently messaged channel
                recent = None
                recent_time = None
                for ch in text_channels:
                    try:
                        last_msg = ch.last_message
                        if last_msg and (recent_time is None or last_msg.created_at > recent_time):
                            recent = ch.name
                            recent_time = last_msg.created_at
                    except Exception:
                        pass
                active_channel = recent or text_channels[0].name
        except Exception:
            pass

        # 活跃度颜色 / Activity color
        if msgs_today > 50:
            color = 0x2ECC71  # 绿 Green
        elif msgs_today >= 20:
            color = 0xF1C40F  # 黄 Yellow
        else:
            color = 0xE74C3C  # 红 Red

        embed = discord.Embed(
            title="📊 服务器统计看板 / Server Stats Dashboard",
            description=f"**{guild.name}** — 实时概览 / Live Overview",
            color=color,
        )

        embed.add_field(name="👥 总成员数 / Total Members", value=str(total_members), inline=True)
        embed.add_field(name="🟢 在线成员数 / Online Members", value=str(online_members), inline=True)
        embed.add_field(name="📝 今日消息数 / Messages Today", value=str(msgs_today), inline=True)
        embed.add_field(name="➕ 今日加入数 / New Joins Today", value=str(joins_today), inline=True)
        embed.add_field(name="🔊 语音在线人数 / VC Online", value=str(vc_online), inline=True)
        embed.add_field(name="💬 最活跃频道 / Most Active Channel", value=f"#{active_channel}", inline=True)

        # Activity indicator
        if msgs_today > 50:
            status = "🔥 高活跃度 / High Activity"
        elif msgs_today >= 20:
            status = "📊 中等活跃度 / Medium Activity"
        else:
            status = "💤 低活跃度 / Low Activity"
        embed.add_field(name="📈 活跃度 / Activity", value=status, inline=False)

        embed.set_footer(text=f"GMT+8 {self.today} — 数据实时刷新 / Real-time")

        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Stats(bot))
