"""
GMPT Bot — 每日语音签到奖励系统 (Daily Voice Reward)
/gmpt-daily set    — Admin: set reward amount & required minutes / 管理员设置每日奖励
/gmpt-daily claim  — Claim daily voice reward / 领取每日语音奖励
/gmpt-daily status — Check today's voice progress / 查看今日语音进度
中英双语 · 按钮交互
"""
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, date, timezone, timedelta
from database import get_db, get_db_ctx

import logging
import sqlite3
import time as time_mod
import random
from utils.logger import log_error
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

UTC8 = timezone(timedelta(hours=8))
MYT = timezone(timedelta(hours=8))

# ── Default config ──
DEFAULT_MINUTES = 30
DEFAULT_REWARD = 50

# ── Streak rewards ──
STREAK_REWARDS = {
    1: 50, 2: 50, 3: 50, 4: 50, 5: 50, 6: 50,
    7: 200, 14: 350, 21: 500, 30: 1000,
    60: 2000, 100: 5000,
}


# ══════════════════════════════════════════════════
#  Command Group
# ══════════════════════════════════════════════════
class Daily(CogBase):
    daily_group = app_commands.Group(
        name="gmpt-daily",
        description="Daily voice reward system / 每日语音奖励系统",
    )

    def __init__(self, bot):
        self.bot = bot
        self._daily_join_times: dict[str, datetime] = {}  # daily tracking, distinct from voice_tracker
        self.last_reminder_date = None  # 防重复：记录上次发送提醒的日期

    # ── 每日签到提醒 ──
    def cog_unload(self):
        self.daily_reminder_loop.cancel()

    @tasks.loop(minutes=1)
    async def daily_reminder_loop(self):
        now = datetime.now(MYT)
        today = now.date()

        if now.hour == 10 and now.minute == 0:
            if self.last_reminder_date == today:
                return

            self.last_reminder_date = today
            channel = self.bot.get_channel(1528241061007327354)
            if channel:
                embed = discord.Embed(
                    title="🎁 每日签到提醒 | Daily Check-in",
                    description="输入 `/gmpt-daily claim` 领取今日奖励！\nClaim your daily reward now!",
                    color=0xFFA500,
                )
                await channel.send(embed=embed)

    @daily_reminder_loop.before_loop
    async def before_daily_reminder(self):
        await self.bot.wait_until_ready()

    # ═══════════════════════════════════════
    #  Config helpers
    # ═══════════════════════════════════════
    def _get_config(self) -> dict:
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM daily_config")
            config = {}
            for row in cur.fetchall():
                try:
                    config[row["key"]] = int(row["value"])
                except (ValueError, TypeError):
                    config[row["key"]] = row["value"]
        return {
            "minutes": config.get("minutes", DEFAULT_MINUTES),
            "reward": config.get("reward", DEFAULT_REWARD),
            "channel": config.get("channel", None),
        }

    # ═══════════════════════════════════════
    #  Voice state tracking
    # ═══════════════════════════════════════
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track daily voice minutes per-user for reward eligibility."""
        if member.bot:
            return

        uid = str(member.id)
        now = datetime.now(UTC8)
        today_str = now.strftime("%Y-%m-%d")

        # Joined a voice channel
        if before.channel is None and after.channel is not None:
            self._daily_join_times[uid] = now

        # Left a voice channel
        elif before.channel is not None and after.channel is None:
            try:
                await self._commit_minutes(uid, today_str)
            except Exception:
                logger.exception("Failed to commit minutes on leave for %s", uid)

        # Switched voice channels
        elif (
            before.channel is not None
            and after.channel is not None
            and before.channel.id != after.channel.id
        ):
            try:
                await self._commit_minutes(uid, today_str)
            except Exception:
                logger.exception("Failed to commit minutes on switch for %s", uid)
            self._daily_join_times[uid] = now

    async def _commit_minutes(self, uid: str, today_str: str) -> bool:
        """Flush in-memory join time to daily_rewards table, with retry on DB lock.

        Returns True if minutes were committed, False if no tracked join_time.
        Join_time is popped only on success so a failed flush can be retried.
        """
        join_time = self._daily_join_times.get(uid, None)
        if not join_time:
            return False

        elapsed = max(1, int((datetime.now(UTC8) - join_time).total_seconds()))
        minutes = max(1, elapsed // 60)

        last_error = None
        for attempt in range(3):
            with get_db_ctx() as conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """INSERT INTO daily_rewards (discord_id, date, voice_minutes, claimed)
                        VALUES (?, ?, ?, 0)
                        ON CONFLICT(discord_id, date) DO UPDATE SET voice_minutes = voice_minutes + ?""",
                        (uid, today_str, minutes, minutes),
                    )
                    conn.commit()
                    self._daily_join_times.pop(uid, None)
                    return True
                except sqlite3.OperationalError as e:
                    last_error = e
                    if "locked" in str(e).lower() and attempt < 2:
                        time_mod.sleep(0.2 * (attempt + 1))
                        continue
                    raise
                finally:
                    conn.close()
        raise last_error

    # ═══════════════════════════════════════
    #  /gmpt-daily status
    # ═══════════════════════════════════════
    @daily_group.command(
        name="status",
        description="Check your daily voice reward progress / 查看每日语音进度",
    )
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: (i.guild_id, i.user.id))
    async def status_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        today_str = datetime.now(UTC8).strftime("%Y-%m-%d")
        config = self._get_config()

        # Flush any in-progress session first
        if uid in self._daily_join_times:
            await self._commit_minutes(uid, today_str)
            # If still in VC, restart the timer so later minutes are still tracked
            if interaction.user.voice and interaction.user.voice.channel:
                self._daily_join_times[uid] = datetime.now(UTC8)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT voice_minutes, claimed, reward_amount FROM daily_rewards "
                "WHERE discord_id=? AND date=?",
                (uid, today_str),
            )
            row = cur.fetchone()

            # ── Fetch streak & total days ──
            cur.execute("SELECT last_date, streak, total_days FROM daily_checkin WHERE discord_id=?", (uid,))
            streak_row = cur.fetchone()
            today_date = date.today().isoformat()
            yesterday_date = date.today().fromordinal(date.today().toordinal() - 1).isoformat()
            current_streak = 0
            total_days = 0
            if streak_row:
                if streak_row["last_date"] == today_date or streak_row["last_date"] == yesterday_date:
                    current_streak = streak_row["streak"]
                total_days = streak_row["total_days"] or 0

        # ── Next milestone preview ──
        milestones = [7, 14, 21, 30, 60, 100]
        next_ms = None
        for ms in milestones:
            if current_streak < ms:
                next_ms = ms
                break
        if next_ms:
            ms_reward = STREAK_REWARDS.get(next_ms, 0)
            ms_preview = f"Day {next_ms} → +{ms_reward} 💰（还需 {next_ms - current_streak} 天）"
        else:
            ms_preview = "已达成全部里程碑！🏆"

        voice_minutes = row["voice_minutes"] if row else 0
        claimed = row["claimed"] if row else 0

        if claimed:
            reward = row["reward_amount"] if row else config["reward"]
            embed = discord.Embed(
                title="Daily Voice Reward / 每日语音奖励",
                description="Already claimed today! / 今日已领取！",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Voice Time / 语音时长",
                value=f"**{voice_minutes}** / {config['minutes']} min",
            )
            embed.add_field(name="Reward / 奖励", value=f"+**{reward}** coins")
            embed.add_field(name="Streak / 连胜", value=f"**{current_streak}** days")
            embed.add_field(name="Total / 累计签到", value=f"**{total_days}** days")
            embed.add_field(name="Next Milestone / 下个里程碑", value=ms_preview, inline=False)
            embed.set_footer(text="Come back tomorrow! / 明天再来吧！")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        else:
            progress = min(voice_minutes, config["minutes"])
            pct = progress * 100 // config["minutes"] if config["minutes"] else 100
            bar_filled = "█" * (pct // 10)
            bar_empty = "░" * (10 - len(bar_filled))

            if voice_minutes >= config["minutes"]:
                status_text = "Ready to claim! / 可以领取了！"
                color = discord.Color.gold()
            else:
                remaining = config["minutes"] - voice_minutes
                status_text = f"Keep going! {remaining} min remaining / 还需 {remaining} 分钟"
                color = discord.Color.blurple()

            embed = discord.Embed(
                title="Daily Voice Reward / 每日语音奖励",
                description=status_text,
                color=color,
            )
            embed.add_field(
                name=f"Progress / 进度  [{bar_filled}{bar_empty}]",
                value=f"**{progress}** / **{config['minutes']}** min  ({pct}%)",
                inline=False,
            )
            embed.add_field(
                name="Reward / 奖励",
                value=f"**{config['reward']}** coins",
                inline=True,
            )
            embed.add_field(
                name="Streak / 连胜",
                value=f"**{current_streak}** days",
                inline=True,
            )
            embed.add_field(
                name="Total / 累计",
                value=f"**{total_days}** days",
                inline=True,
            )
            embed.add_field(
                name="Next Milestone / 下个里程碑",
                value=ms_preview,
                inline=False,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ═══════════════════════════════════════
    #  /gmpt-daily claim  (voice reward + streak)
    # ═══════════════════════════════════════
    @daily_group.command(
        name="claim",
        description="Claim your daily voice reward / 领取每日语音奖励",
    )
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def claim_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        today_str = datetime.now(UTC8).strftime("%Y-%m-%d")
        config = self._get_config()

        # Flush any in-progress session first
        if uid in self._daily_join_times:
            await self._commit_minutes(uid, today_str)
            # If still in VC, restart the timer so later minutes are still tracked
            if interaction.user.voice and interaction.user.voice.channel:
                self._daily_join_times[uid] = datetime.now(UTC8)

        with get_db_ctx() as conn:
            cur = conn.cursor()

            cur.execute(
                "SELECT voice_minutes, claimed FROM daily_rewards "
                "WHERE discord_id=? AND date=?",
                (uid, today_str),
            )
            row = cur.fetchone()

            if not row:
                return await interaction.response.send_message(
                    f"You haven't been in voice channels today! "
                    f"Spend **{config['minutes']}** min in voice to claim **{config['reward']}** coins. / "
                    f"你今天还没进入语音频道！在语音频道累计 **{config['minutes']}** 分钟可领取 **{config['reward']}** 金币。",
                    ephemeral=True,
                )

            voice_minutes = row["voice_minutes"]
            claimed = row["claimed"]

            if claimed:
                return await interaction.response.send_message(
                    "You already claimed your daily voice reward today! / "
                    "你今天已经领取过每日语音奖励了！",
                    ephemeral=True,
                )

            if voice_minutes < config["minutes"]:
                remaining = config["minutes"] - voice_minutes
                return await interaction.response.send_message(
                    f"Not enough voice time! **{voice_minutes}**/**{config['minutes']}** min "
                    f"(need **{remaining}** more). / "
                    f"语音时长不足！**{voice_minutes}**/**{config['minutes']}** 分钟（还需 **{remaining}** 分钟）。",
                    ephemeral=True,
                )

            # ── Streak calculation ──
            today_date = date.today().isoformat()
            cur.execute("SELECT last_date, streak FROM daily_checkin WHERE discord_id=?", (uid,))
            streak_row = cur.fetchone()

            if streak_row and streak_row["last_date"] == today_date:
                return await interaction.response.send_message(
                    f"Already checked in today! Streak: {streak_row['streak']} days / "
                    f"你今天已经签到过了！连胜 {streak_row['streak']} 天",
                    ephemeral=True,
                )

            yesterday = date.today().fromordinal(date.today().toordinal() - 1).isoformat()
            if streak_row and streak_row["last_date"] == yesterday:
                new_streak = streak_row["streak"] + 1
            else:
                new_streak = 1

            # ── Milestone bonus ──
            milestone_bonus = 0
            milestone_msg = ""
            extra_tomorrow = "+0"

            if new_streak == 7:
                milestone_bonus = 100
                milestone_msg = "7-day milestone! / 7天里程碑！"
            elif new_streak == 14:
                milestone_bonus = 200
                milestone_msg = "14-day advanced milestone! / 14天高级里程碑！"
            elif new_streak == 21:
                milestone_bonus = 200
                milestone_msg = "21-day milestone! / 21天里程碑！"
            elif new_streak == 30:
                milestone_bonus = 500
                milestone_msg = "30-day legendary milestone! / 30天传奇里程碑！"
            elif new_streak == 60:
                milestone_bonus = 1000
                milestone_msg = "60-day insane milestone! / 60天疯狂里程碑！"
            elif new_streak == 100:
                milestone_bonus = 3000
                milestone_msg = "100-day milestone! / 100天里程碑！"

            # Tomorrow's streak bonus preview
            tomorrow_streak = new_streak + 1
            for days, coins in sorted(STREAK_REWARDS.items()):
                if tomorrow_streak == days:
                    extra_tomorrow = f"+{coins}"
                    break
                elif tomorrow_streak < days:
                    break

            total_reward = config["reward"] + milestone_bonus

            # ── Award coins ──
            try:
                cur.execute(
                    "INSERT INTO users (discord_id, username) VALUES (?, ?) ON CONFLICT(discord_id) DO NOTHING",
                    (uid, interaction.user.name),
                )
                cur.execute(
                    "UPDATE users SET score = score + ? WHERE discord_id = ?",
                    (total_reward, uid),
                )
                cur.execute(
                    "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
                    (
                        uid,
                        total_reward,
                        f"Daily Voice Reward Day {new_streak} / 每日语音签到 Day {new_streak} ({voice_minutes} min)",
                    ),
                )
                cur.execute(
                    "UPDATE daily_rewards SET claimed=1, claimed_at=?, reward_amount=? "
                    "WHERE discord_id=? AND date=?",
                    (datetime.now(UTC8).isoformat(), total_reward, uid, today_str),
                )
                # ── Update streak ──
                cur.execute(
                    "INSERT INTO daily_checkin (discord_id, last_date, streak, total_days) VALUES (?,?,?,1) "
                    "ON CONFLICT(discord_id) DO UPDATE SET last_date=?, streak=?, total_days=total_days+1",
                    (uid, today_date, new_streak, today_date, new_streak),
                )

                # ── Easter egg 签到彩蛋 (15% chance) ──
                easter_egg_msg = None
                easter_bonus = 0
                easter_ticket = 0
                if random.random() < 0.15:
                    easter_eggs = [
                        {"type": "double", "msg": "🎉 彩蛋！本日签到金币翻倍！", "fn": lambda: total_reward},
                        {"type": "bonus", "msg": "✨ 彩蛋！额外获得 50💰 金币雨！", "fn": lambda: 50},
                        {"type": "ticket", "msg": "🎟️ 彩蛋！获得 1 张抽奖券！", "fn": lambda: 1},
                        {"type": "trivia_bonus", "msg": "🌟 彩蛋！额外获得 100💰 好彩头！", "fn": lambda: 100},
                    ]
                    egg = random.choice(easter_eggs)
                    egg_type = egg["type"]
                    egg_val = egg["fn"]()
                    if egg_type == "double":
                        extra = total_reward  # double means add original again
                        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (extra, uid))
                        cur.execute(
                            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
                            (uid, extra, f"Easter Egg: Double Reward / 彩蛋：翻倍"),
                        )
                        total_reward += extra
                        easter_egg_msg = egg["msg"]
                    elif egg_type == "ticket":
                        cur.execute(
                            "INSERT INTO user_inventory (discord_id, item_name, quantity) VALUES (?, 'lottery_ticket', ?) "
                            "ON CONFLICT(discord_id, item_name) DO UPDATE SET quantity = quantity + ?",
                            (uid, egg_val, egg_val),
                        )
                        easter_egg_msg = egg["msg"]
                    else:
                        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (egg_val, uid))
                        cur.execute(
                            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
                            (uid, egg_val, f"Easter Egg: Bonus / 彩蛋：额外金币"),
                        )
                        total_reward += egg_val
                        easter_egg_msg = egg["msg"]

                conn.commit()
            except Exception as e:
                log_error("daily", "claim_cmd", e)
                conn.rollback()
                return await interaction.response.send_message(
                    "An error occurred while awarding coins. Please try again. / "
                    "发放金币时出错，请重试。",
                    ephemeral=True,
                )

        # ── Build embed ──
        embed = discord.Embed(
            title="Reward Claimed! / 奖励已领取！",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Reward / 奖励",
            value=f"+**{total_reward}** coins",
            inline=True,
        )
        embed.add_field(
            name="Voice Time / 语音时长",
            value=f"**{voice_minutes}** min",
            inline=True,
        )
        embed.add_field(
            name="Streak / 连胜",
            value=f"**{new_streak}** days",
            inline=True,
        )
        if milestone_msg:
            embed.add_field(
                name="Milestone / 里程碑",
                value=milestone_msg,
                inline=False,
            )
        if easter_egg_msg:
            embed.add_field(
                name="Easter Egg / 彩蛋",
                value=easter_egg_msg,
                inline=False,
            )
        if extra_tomorrow != "+0":
            embed.add_field(
                name="Tomorrow's bonus / 明天额外",
                value=f"+{extra_tomorrow} coins",
                inline=False,
            )
        embed.set_footer(text="See you tomorrow! / 明天见！")
        await interaction.response.send_message(embed=embed)

    # ═══════════════════════════════════════
    #  /gmpt-daily set  (Admin only)
    # ═══════════════════════════════════════
    @daily_group.command(
        name="set",
        description="Admin: Set daily voice reward config / 管理员：设置每日语音奖励",
    )
    @app_commands.describe(
        reward="Gold coins per claim / 每次领取的金币数",
        minutes="Required voice minutes / 所需语音分钟数（默认30）",
        channel="Announcement channel / 公告频道（可选，留空不发送公告）",
    )
    @app_commands.default_permissions(administrator=True)
    async def set_cmd(
        self,
        interaction: discord.Interaction,
        reward: int,
        minutes: int = DEFAULT_MINUTES,
        channel: discord.TextChannel | None = None,
    ):
        if reward < 1:
            return await interaction.response.send_message(
                "Reward must be at least 1 / 奖励至少为 1。", ephemeral=True
            )
        if minutes < 1:
            return await interaction.response.send_message(
                "Minutes must be at least 1 / 分钟数至少为 1。", ephemeral=True
            )

        with get_db_ctx() as conn:
            cur = conn.cursor()
            for key, val in [("minutes", str(minutes)), ("reward", str(reward))]:
                cur.execute(
                    "INSERT INTO daily_config (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = ?",
                    (key, val, val),
                )
            if channel:
                cur.execute(
                    "INSERT INTO daily_config (key, value) VALUES ('channel', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = ?",
                    (str(channel.id), str(channel.id)),
                )
            conn.commit()

        # ── Send announcement embed to designated channel ──
        if channel:
            embed = discord.Embed(
                title="Daily Voice Reward / 每日语音奖励",
                description=(
                    f"每天在语音频道累计 **{minutes}** 分钟即可领取 **{reward}** 金币\n"
                    f"Stay in voice channels for **{minutes}** minutes daily to claim **{reward}** coins"
                ),
                color=discord.Color.gold(),
            )
            embed.add_field(
                name="How to claim / 领取方式",
                value="使用 `/gmpt-daily claim` 领取奖励 / Use `/gmpt-daily claim` to claim",
                inline=False,
            )
            embed.add_field(
                name="Check progress / 查看进度",
                value="使用 `/gmpt-daily status` / Use `/gmpt-daily status`",
                inline=False,
            )
            embed.set_footer(text="Good luck! / 加油！")
            await channel.send(embed=embed)

        await interaction.response.send_message(
            f"Daily voice reward configured / 每日语音奖励已设置：\n"
            f"Required: **{minutes}** min  |  Reward: **{reward}** coins\n"
            f"Announcement channel: {channel.mention if channel else 'None / 无'}",
            ephemeral=True,
        )


async def setup(bot):
    cog = Daily(bot)
    await bot.add_cog(cog)
    cog.daily_reminder_loop.start()
