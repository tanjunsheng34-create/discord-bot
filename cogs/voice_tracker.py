"""
GMPT Bot — 语音/在线时长追踪
/gmpt-voicetime — 查看语音时长统计
"""
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db

# UTC+8 timezone
UTC8 = timezone(timedelta(hours=8))


class VoiceTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track join times in memory: user_id -> join_datetime
        self._join_times = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track voice channel join/leave and accumulate time."""
        uid = str(member.id)

        # User joined a voice channel
        if before.channel is None and after.channel is not None:
            now = datetime.now()
            self._join_times[uid] = now

            conn = get_db(); cur = conn.cursor()
            # Ensure user row exists
            cur.execute(
                "INSERT INTO voice_tracker (user_id, total_seconds, login_days, total_joins, last_join_date, last_join_time) "
                "VALUES (?, 0, 0, 0, NULL, NULL) "
                "ON CONFLICT(user_id) DO NOTHING",
                (uid,),
            )

            # Increment total_joins
            cur.execute("UPDATE voice_tracker SET total_joins = total_joins + 1 WHERE user_id=?", (uid,))

            # Check login_days: UTC+8 date, first join per day increments
            today_str = now.astimezone(UTC8).strftime("%Y-%m-%d")
            cur.execute("SELECT last_join_date FROM voice_tracker WHERE user_id=?", (uid,))
            row = cur.fetchone()
            last_date = row["last_join_date"] if row else None

            if last_date != today_str:
                cur.execute(
                    "UPDATE voice_tracker SET login_days = login_days + 1, last_join_date = ? WHERE user_id=?",
                    (today_str, uid),
                )
            else:
                # Still update last_join_date even if same day (keep it fresh)
                cur.execute(
                    "UPDATE voice_tracker SET last_join_date = ? WHERE user_id=?",
                    (today_str, uid),
                )

            # Update last_join_time
            cur.execute(
                "UPDATE voice_tracker SET last_join_time = ? WHERE user_id=?",
                (now.isoformat(), uid),
            )

            conn.commit()
            conn.close()

        # User left a voice channel
        elif before.channel is not None and after.channel is None:
            join_time = self._join_times.pop(uid, None)
            if join_time is None:
                return  # No tracked join — probably started tracking after join

            elapsed = int((datetime.now() - join_time).total_seconds())
            if elapsed <= 0:
                return

            conn = get_db(); cur = conn.cursor()
            # Ensure row exists
            cur.execute(
                "INSERT INTO voice_tracker (user_id, total_seconds, login_days, total_joins, last_join_date, last_join_time) "
                "VALUES (?, ?, 0, 0, NULL, NULL) "
                "ON CONFLICT(user_id) DO NOTHING",
                (uid, elapsed),
            )
            # Add elapsed seconds
            cur.execute(
                "UPDATE voice_tracker SET total_seconds = total_seconds + ? WHERE user_id=?",
                (elapsed, uid),
            )
            conn.commit()
            conn.close()

    @app_commands.command(name="gmpt-voicetime", description="查看语音在线时长 / View voice time stats")
    @app_commands.describe(user="要查看的用户 (管理员) / User to check (admin)")
    async def voicetime_cmd(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user if user else interaction.user
        uid = str(target.id)

        # If checking someone else, require admin
        if user and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "仅管理员可查看他人数据 / Admin only to check others.", ephemeral=True
            )

        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM voice_tracker WHERE user_id=?", (uid,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return await interaction.response.send_message(
                f"{target.display_name} 暂无语音记录 / No voice data yet.", ephemeral=True
            )

        total_seconds = row["total_seconds"] or 0
        login_days = row["login_days"] or 0
        total_joins = row["total_joins"] or 0
        last_join_date = row["last_join_date"] or "N/A"
        last_join_time = row["last_join_time"] or "N/A"

        # Format time
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        embed = discord.Embed(
            title=f"语音时长统计 / Voice Time Stats — {target.display_name}",
            color=discord.Color.purple(),
        )
        embed.add_field(name="总时长 / Total Time", value=f"**{hours}h {minutes}m {seconds}s**", inline=True)
        embed.add_field(name="登录天数 / Login Days", value=f"**{login_days}** 天", inline=True)
        embed.add_field(name="进入次数 / Total Joins", value=f"**{total_joins}** 次", inline=True)
        embed.add_field(name="最后登录日期 / Last Login Date", value=last_join_date, inline=True)
        embed.add_field(name="最后加入时间 / Last Join Time", value=last_join_time[:19] if len(last_join_time) > 19 else last_join_time, inline=True)
        embed.set_thumbnail(url=target.display_avatar.url if target.display_avatar else None)

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(VoiceTracker(bot))
