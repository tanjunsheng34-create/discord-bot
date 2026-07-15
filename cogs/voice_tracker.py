"""
GMPT Bot — 语音/在线时长追踪
/gmpt-voicetime — 查看语音时长统计（按钮版）
/gmpt-voice-leaderboard — 语音排行榜
"""
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db

# UTC+8 timezone
UTC8 = timezone(timedelta(hours=8))


def format_duration(total_seconds):
    """Format total_seconds into human-readable string."""
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


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
                return  # No tracked join

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

    def _build_self_embed(self, target, row):
        """Build embed for a single user's voice stats."""
        total_seconds = row["total_seconds"] or 0
        login_days = row["login_days"] or 0
        total_joins = row["total_joins"] or 0
        last_join_date = row["last_join_date"] or "N/A"
        last_join_time = row["last_join_time"] or "N/A"

        embed = discord.Embed(
            title=f"Voice Time Stats — {target.display_name}",
            color=discord.Color.purple(),
        )
        embed.add_field(name="Total Time", value=f"**{format_duration(total_seconds)}**", inline=True)
        embed.add_field(name="Login Days", value=f"**{login_days}** days", inline=True)
        embed.add_field(name="Total Joins", value=f"**{total_joins}** times", inline=True)
        embed.add_field(name="Last Login Date", value=last_join_date, inline=True)
        embed.add_field(name="Last Join Time", value=last_join_time[:19] if len(last_join_time) > 19 else last_join_time, inline=True)
        embed.set_thumbnail(url=target.display_avatar.url if target.display_avatar else None)
        return embed

    def _build_leaderboard_embed(self, data, page, guild):
        """Build leaderboard embed from voice_tracker data."""
        per_page = 10
        start = page * per_page
        end = min(start + per_page, len(data))
        page_data = data[start:end]

        total_pages = (len(data) + per_page - 1) // per_page

        embed = discord.Embed(
            title="Voice Leaderboard / Voice Leaderboard",
            description=f"Total **{len(data)}** users | Page **{page + 1}/{total_pages}**",
            color=discord.Color.purple(),
        )

        lines = []
        for i, row in enumerate(page_data, start + 1):
            uid = row["user_id"]
            member = guild.get_member(int(uid)) if guild else None
            name = member.display_name if member else f"<@{uid}>"

            total_seconds = row["total_seconds"] or 0
            login_days = row["login_days"] or 0
            total_joins = row["total_joins"] or 0

            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" #{i}"
            lines.append(
                f"{medal} **{name}**\n"
                f"　　Time: `{format_duration(total_seconds)}` | Days: `{login_days}` | Joins: `{total_joins}`"
            )

        embed.add_field(
            name=f"Top {start + 1}-{end}",
            value="\n".join(lines) if lines else "(Empty)",
            inline=False,
        )
        return embed

    @app_commands.command(name="gmpt-voicetime", description="Check voice time stats / 查看语音时长统计")
    @app_commands.describe(user="User to check (admin only) / 要查看的用户（管理员可用）")
    async def voicetime_cmd(self, interaction: discord.Interaction, user: discord.Member = None):
        """Button-based voice time stats."""
        is_admin = interaction.user.guild_permissions.administrator

        if user:
            # Direct lookup — viewing someone else
            if not is_admin:
                return await interaction.response.send_message(
                    "Admin only / Admin only.", ephemeral=True
                )
            uid = str(user.id)
            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT * FROM voice_tracker WHERE user_id=?", (uid,))
            row = cur.fetchone()
            conn.close()

            if not row:
                return await interaction.response.send_message(
                    f"{user.display_name} no voice data yet.", ephemeral=True
                )
            embed = self._build_self_embed(user, row)
            await interaction.response.send_message(embed=embed)
        else:
            # No args — show button panel
            embed = discord.Embed(
                title="Voice Time Stats",
                description=(
                    "Choose an action below / Choose below:\n"
                    "- **View Self** — your own stats\n"
                    "- **View Leaderboard** — full ranking\n"
                    + ("- **View Someone** — check another user\n" if is_admin else "")
                ),
                color=discord.Color.purple(),
            )
            view = VoiceTimeView(user=interaction.user, guild=interaction.guild, is_admin=is_admin, cog=self)
            await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="gmpt-voice-leaderboard", description="Voice time leaderboard / 语音时长排行榜")
    async def voice_leaderboard_cmd(self, interaction: discord.Interaction):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT user_id, total_seconds, login_days, total_joins "
            "FROM voice_tracker ORDER BY total_seconds DESC"
        )
        data = cur.fetchall()
        conn.close()

        if not data:
            return await interaction.response.send_message("No voice data yet.", ephemeral=True)

        view = VoiceLeaderboardView(data=data, page=0, guild=interaction.guild, cog=self)
        embed = self._build_leaderboard_embed(data, 0, interaction.guild)
        await interaction.response.send_message(embed=embed, view=view)


# =============================================================================
# VoiceTimeView — 按钮版语音面板 / Button-based Voice Time Panel
# =============================================================================
class VoiceTimeView(discord.ui.View):
    def __init__(self, user, guild, is_admin, cog, timeout=120):
        super().__init__(timeout=timeout)
        self.user = user
        self.guild = guild
        self.is_admin = is_admin
        self.cog = cog

        if not is_admin:
            # Remove "View Someone" button for non-admins
            self.view_other_btn.disabled = True
            self.view_other_btn.style = discord.ButtonStyle.secondary
            self.view_other_btn.label = "View Someone (Admin Only)"

    @discord.ui.button(label="View Self", style=discord.ButtonStyle.primary, emoji="👤", row=0)
    async def view_self_btn(self, interaction: discord.Interaction, button):
        uid = str(self.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM voice_tracker WHERE user_id=?", (uid,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return await interaction.response.send_message(
                f"{self.user.display_name} no voice data yet.", ephemeral=True
            )
        embed = self.cog._build_self_embed(self.user, row)
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="View Leaderboard", style=discord.ButtonStyle.success, emoji="🏆", row=0)
    async def view_leaderboard_btn(self, interaction: discord.Interaction, button):
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT user_id, total_seconds, login_days, total_joins "
            "FROM voice_tracker ORDER BY total_seconds DESC"
        )
        data = cur.fetchall()
        conn.close()

        if not data:
            return await interaction.response.send_message("No voice data yet.", ephemeral=True)

        view = VoiceLeaderboardView(data=data, page=0, guild=self.guild, cog=self.cog)
        embed = self.cog._build_leaderboard_embed(data, 0, self.guild)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="View Someone", style=discord.ButtonStyle.secondary, emoji="🔍", row=0)
    async def view_other_btn(self, interaction: discord.Interaction, button):
        if not self.is_admin:
            return await interaction.response.send_message("Admin only.", ephemeral=True)

        members = [m for m in self.guild.members if not m.bot][:25]
        if not members:
            return await interaction.response.send_message("No members found.", ephemeral=True)

        options = [
            discord.SelectOption(label=m.display_name[:100], value=str(m.id))
            for m in members
        ]

        select = discord.ui.Select(
            placeholder="Select a user...",
            options=options[:25],
        )

        async def user_callback(sel_int: discord.Interaction):
            uid = sel_int.data["values"][0]
            member = self.guild.get_member(int(uid))
            if not member:
                return await sel_int.response.send_message("User not found.", ephemeral=True)

            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT * FROM voice_tracker WHERE user_id=?", (uid,))
            row = cur.fetchone()
            conn.close()

            if not row:
                return await sel_int.response.send_message(
                    f"{member.display_name} no voice data yet.", ephemeral=True
                )
            embed = self.cog._build_self_embed(member, row)
            await sel_int.response.edit_message(embed=embed, view=None)

        select.callback = user_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message(view=view, ephemeral=True)


# =============================================================================
# VoiceLeaderboardView — 分页排行榜 / Paginated Leaderboard
# =============================================================================
class VoiceLeaderboardView(discord.ui.View):
    def __init__(self, data, page=0, guild=None, cog=None, timeout=180):
        super().__init__(timeout=timeout)
        self.data = data
        self.page = page
        self.per_page = 10
        self.guild = guild
        self.cog = cog
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = (self.page + 1) * self.per_page >= len(self.data)

    @discord.ui.button(label="Prev", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button):
        if self.page > 0:
            self.page -= 1
            self._update_buttons()
            embed = self.cog._build_leaderboard_embed(self.data, self.page, self.guild)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button):
        if (self.page + 1) * self.per_page < len(self.data):
            self.page += 1
            self._update_buttons()
            embed = self.cog._build_leaderboard_embed(self.data, self.page, self.guild)
            await interaction.response.edit_message(embed=embed, view=self)


async def setup(bot):
    await bot.add_cog(VoiceTracker(bot))
