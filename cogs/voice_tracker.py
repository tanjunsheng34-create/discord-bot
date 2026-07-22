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
from cogs.shared_views import ConfirmView


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
    async def cog_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            if isinstance(error, app_commands.CommandOnCooldown):
                remaining = int(error.retry_after)
                msg = f"⏳ 冷却中，请等 {remaining} 秒 / Cooldown, wait {remaining}s."
                if not interaction.response.is_done():
                    await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await interaction.followup.send(msg, ephemeral=True)
            else:
                err_msg = f"❌ 错误: {error}"
                if not interaction.response.is_done():
                    await interaction.response.send_message(err_msg, ephemeral=True)
                else:
                    await interaction.followup.send(err_msg, ephemeral=True)
        except Exception:
            pass

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
            # ── XP gain: +5 per minute ──
            xp_gain = max(1, elapsed // 60) * 5
            cur.execute(
                "UPDATE users SET xp = xp + ? WHERE discord_id=?",
                (xp_gain, uid),
            )
            # Check level-up
            cur.execute("SELECT xp, level FROM users WHERE discord_id=?", (uid,))
            xp_row = cur.fetchone()
            if xp_row:
                current_xp = xp_row["xp"]
                current_level = xp_row["level"] or 1
                while current_xp >= int(current_level ** 1.5 * 100):
                    current_xp -= int(current_level ** 1.5 * 100)
                    current_level += 1
                if current_level != xp_row["level"]:
                    cur.execute("UPDATE users SET level = ?, xp = ? WHERE discord_id=?", (current_level, current_xp, uid))
            conn.commit()
            conn.close()

    def _build_self_embed(self, target, row):
        """Build embed for a single user's voice stats (cumulative)."""
        total_seconds = row["total_seconds"] or 0
        login_days = row["login_days"] or 0
        total_joins = row["total_joins"] or 0
        last_join_date = row["last_join_date"] or "N/A"
        last_join_time = row["last_join_time"] or "N/A"

        embed = discord.Embed(
            title=f"Voice Time Stats — {target.display_name}",
            description="**Cumulative Stats / 累计统计**",
            color=discord.Color.purple(),
        )
        embed.add_field(name="Total Time", value=f"**{format_duration(total_seconds)}**", inline=True)
        embed.add_field(name="Total Login Days", value=f"**{login_days}** days", inline=True)
        embed.add_field(name="Total Joins", value=f"**{total_joins}** times", inline=True)
        embed.add_field(name="Last Login Date", value=last_join_date, inline=True)
        embed.add_field(name="Last Join Time", value=last_join_time[:19] if len(last_join_time) > 19 else last_join_time, inline=True)
        embed.set_thumbnail(url=target.display_avatar.url if target.display_avatar else None)
        return embed

    def _build_leaderboard_embed(self, data, page, guild):
        """Build leaderboard embed from voice_tracker data, with global summary footer."""
        per_page = 10
        start = page * per_page
        end = min(start + per_page, len(data))
        page_data = data[start:end]

        total_pages = (len(data) + per_page - 1) // per_page

        # Global cumulative totals across all tracked users
        sum_seconds = sum((r["total_seconds"] or 0) for r in data)
        sum_days = sum((r["login_days"] or 0) for r in data)
        sum_joins = sum((r["total_joins"] or 0) for r in data)

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
        embed.add_field(
            name="Global Summary / 全局汇总",
            value=(
                f"**Total Time:** {format_duration(sum_seconds)}\n"
                f"**Total Login Days:** {sum_days} days\n"
                f"**Total Joins:** {sum_joins} times"
            ),
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
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def voice_leaderboard_cmd(self, interaction: discord.Interaction):
        data = VoiceLeaderboardView._fetch_leaderboard_data()
        if not data:
            return await interaction.response.send_message("No voice data yet.", ephemeral=True)

        view = VoiceLeaderboardView()
        embed = VoiceLeaderboardView._build_embed(data, 0, interaction.guild)
        view.prev_btn.disabled = True
        view.next_btn.disabled = len(data) <= 10
        await interaction.response.send_message(embed=embed, view=view)


# =============================================================================
# VoiceTimeView — 按钮版语音面板 / Button-based Voice Time Panel
# =============================================================================
class VoiceTimeView(discord.ui.View):
    def __init__(self, user, guild, is_admin, cog, timeout=120):
        super().__init__(timeout=None)
        self.user = user
        self.guild = guild
        self.is_admin = is_admin
        self.cog = cog

        if not is_admin:
            # Hide admin-only buttons for non-admins
            self.view_other_btn.disabled = True
            self.view_other_btn.style = discord.ButtonStyle.secondary
            self.view_other_btn.label = "View Someone (Admin Only)"
            self.reset_all_voice_btn.disabled = True
            self.reset_all_voice_btn.style = discord.ButtonStyle.secondary
            self.reset_all_voice_btn.label = "Reset All Voice (Admin Only)"

    @discord.ui.button(label="View Self", style=discord.ButtonStyle.primary, emoji="👤", row=0)
    async def view_self_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        uid = str(self.user.id)
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM voice_tracker WHERE user_id=?", (uid,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return await interaction.followup.send(
                f"{self.user.display_name} no voice data yet.", ephemeral=True
            )
        embed = self.cog._build_self_embed(self.user, row)
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="View Leaderboard", style=discord.ButtonStyle.success, emoji="🏆", row=0)
    async def view_leaderboard_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        data = VoiceLeaderboardView._fetch_leaderboard_data()
        if not data:
            return await interaction.followup.send("No voice data yet.", ephemeral=True)

        view = VoiceLeaderboardView()
        embed = VoiceLeaderboardView._build_embed(data, 0, self.guild)
        view.prev_btn.disabled = True
        view.next_btn.disabled = len(data) <= 10
        await interaction.edit_original_response(embed=embed, view=view)

    @discord.ui.button(label="View Someone", style=discord.ButtonStyle.secondary, emoji="🔍", row=0)
    async def view_other_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not self.is_admin:
            return await interaction.followup.send("Admin only.", ephemeral=True)

        members = [m for m in self.guild.members if not m.bot][:25]
        if not members:
            return await interaction.followup.send("No members found.", ephemeral=True)

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
        await interaction.followup.send(view=view, ephemeral=True)

    @discord.ui.button(label="Reset All Voice", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def reset_all_voice_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        """Admin-only: reset all voice tracker data to zero."""
        if not self.is_admin:
            return await interaction.followup.send("Admin only.", ephemeral=True)

        confirm = ConfirmView(timeout=60)
        embed = discord.Embed(
            title="Reset All Voice Data?",
            description=(
                "This will reset **all** voice tracking stats to zero for **everyone**.\n"
                "所有人语音统计数据将被清零。\n\n"
                "Are you sure? / 确定吗？"
            ),
            color=discord.Color.red(),
        )
        await interaction.followup.send(embed=embed, view=confirm, ephemeral=True)
        await confirm.wait()

        if confirm.value is None or not confirm.value:
            return await interaction.edit_original_response(
                content="Cancelled.", embed=None, view=None
            )

        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE voice_tracker SET total_seconds=0, login_days=0, total_joins=0")
        affected = cur.rowcount
        conn.commit()
        conn.close()

        await interaction.edit_original_response(
            content=f"Reset {affected} voice tracking record(s). / 已重置 {affected} 条语音追踪记录。",
            embed=None,
            view=None,
        )


# =============================================================================
# VoiceLeaderboardView — 分页排行榜 / Paginated Leaderboard
# =============================================================================
class VoiceLeaderboardView(discord.ui.View):
    """持久化分页排行榜 View。按钮通过 custom_id 持久化，Bot 重启后仍可翻页。

    状态完全从 interaction 和 DB 实时派生，不存实例字段：
    - 当前页：从 embed description 的 "Page X/Y" 解析
    - 数据：从 SQLite voice_tracker 表实时查询
    """

    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def _parse_page_from_embed(embed: discord.Embed) -> int:
        """从 embed description 中提取当前页码（1-based → 0-based）。"""
        if embed.description:
            # "Total **N** users | Page **P/T**"
            import re
            m = re.search(r"Page \*\*(\d+)/(\d+)\*\*", embed.description)
            if m:
                return int(m.group(1)) - 1
        return 0

    @staticmethod
    def _fetch_leaderboard_data():
        conn = get_db(); cur = conn.cursor()
        cur.execute(
            "SELECT user_id, total_seconds, login_days, total_joins "
            "FROM voice_tracker ORDER BY total_seconds DESC"
        )
        data = cur.fetchall()
        conn.close()
        return data

    @classmethod
    def _build_embed(cls, data, page, guild):
        """Build leaderboard embed — standalone version that doesn't need a cog."""
        per_page = 10
        start = page * per_page
        end = min(start + per_page, len(data))
        page_data = data[start:end]

        total_pages = max((len(data) + per_page - 1) // per_page, 1)
        sum_seconds = sum((r["total_seconds"] or 0) for r in data)
        sum_days = sum((r["login_days"] or 0) for r in data)
        sum_joins = sum((r["total_joins"] or 0) for r in data)

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
        embed.add_field(
            name="Global Summary / 全局汇总",
            value=(
                f"**Total Time:** {format_duration(sum_seconds)}\n"
                f"**Total Login Days:** {sum_days} days\n"
                f"**Total Joins:** {sum_joins} times"
            ),
            inline=False,
        )
        return embed

    @discord.ui.button(label="Prev", emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="vl_prev")
    async def prev_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        page = self._parse_page_from_embed(interaction.message.embeds[0])
        if page > 0:
            page -= 1
        data = self._fetch_leaderboard_data()
        if not data:
            return await interaction.edit_original_response(content="No voice data yet.", embed=None, view=None)
        # Clamp page
        total_pages = max((len(data) + 9) // 10, 1)
        page = max(0, min(page, total_pages - 1))
        embed = self._build_embed(data, page, interaction.guild)
        # Update button states
        self.prev_btn.disabled = page == 0
        self.next_btn.disabled = (page + 1) * 10 >= len(data)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Next", emoji="➡️", style=discord.ButtonStyle.secondary, custom_id="vl_next")
    async def next_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        page = self._parse_page_from_embed(interaction.message.embeds[0])
        data = self._fetch_leaderboard_data()
        if not data:
            return await interaction.edit_original_response(content="No voice data yet.", embed=None, view=None)
        total_pages = max((len(data) + 9) // 10, 1)
        if page < total_pages - 1:
            page += 1
        # Clamp page
        page = max(0, min(page, total_pages - 1))
        embed = self._build_embed(data, page, interaction.guild)
        self.prev_btn.disabled = page == 0
        self.next_btn.disabled = (page + 1) * 10 >= len(data)
        await interaction.edit_original_response(embed=embed, view=self)


async def setup(bot):
    # Register persistent VoiceLeaderboardView so buttons survive restarts
    bot.add_view(VoiceLeaderboardView())
    await bot.add_cog(VoiceTracker(bot))

