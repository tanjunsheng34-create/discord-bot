"""
GMPT Bot — MMORPG Daily Check-in / 每日签到
/gmpt-checkin — 每日签到

每天可签到一次（UTC+8 零点重置），连续签到奖励递增。
断签重置到 Day 1。
"""
import datetime
import logging
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx

logger = logging.getLogger(__name__)


def _tz_now():
    """Get current time in UTC+8."""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def _get_today_str():
    """Get today's date string in UTC+8."""
    return _tz_now().strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════
# Streak rewards: day -> (coins, bonus description, equipment quality or None)
# ══════════════════════════════════════════════════════════════
STREAK_REWARDS = {
    1: (50, "", None),
    2: (80, "", None),
    3: (120, "+ 随机普通装备 / Random Common Equipment", "common"),
    4: (160, "", None),
    5: (200, "+ 随机稀有装备 / Random Rare Equipment", "rare"),
    6: (300, "", None),
    7: (500, "+ 随机史诗装备 / Random Epic Equipment", "epic"),
}


def _add_coins(uid: str, amount: int, reason: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING",
            (uid,),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
        cur.execute(
            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
            (uid, amount, reason),
        )
        conn.commit()


def _add_xp(uid: str, xp: int):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT xp, level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
        if not row:
            return
        new_xp = (row["xp"] or 0) + xp
        level = row["level"] or 1
        while new_xp >= level * 1000:
            new_xp -= level * 1000
            level += 1
        cur.execute("UPDATE users SET xp = ?, level = ? WHERE discord_id = ?", (new_xp, level, uid))
        conn.commit()


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_checkin_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_checkin (
                user_id TEXT PRIMARY KEY,
                streak INTEGER NOT NULL DEFAULT 0,
                last_checkin_ts TEXT
            )
        """)
        conn.commit()

_init_checkin_tables()


def _get_checkin_data(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT streak, last_checkin_ts FROM mmorpg_checkin WHERE user_id = ?", (uid,))
        row = cur.fetchone()
    if row:
        return {"streak": row["streak"], "last_checkin_ts": row["last_checkin_ts"]}
    return {"streak": 0, "last_checkin_ts": None}


def _do_checkin(uid: str) -> tuple:
    """Perform check-in. Returns (streak, coins, bonus_text, equipment_quality, already_checked)."""
    data = _get_checkin_data(uid)
    today = _get_today_str()

    # Check if already checked in today
    if data["last_checkin_ts"] and data["last_checkin_ts"] == today:
        return (data["streak"], 0, "", None, True)

    # Check if streak should break
    streak = data["streak"]
    if data["last_checkin_ts"]:
        try:
            last_date = datetime.datetime.strptime(data["last_checkin_ts"], "%Y-%m-%d").date()
            yesterday = (datetime.datetime.strptime(today, "%Y-%m-%d") - datetime.timedelta(days=1)).date()
            if last_date < yesterday:
                streak = 0  # missed a day
        except (ValueError, TypeError):
            streak = 0

    new_streak = streak + 1
    if new_streak > 7:
        new_streak = 1  # wrap around after day 7

    coins, bonus_text, eq_quality = STREAK_REWARDS.get(new_streak, STREAK_REWARDS[1])

    # Save
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO mmorpg_checkin (user_id, streak, last_checkin_ts) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET streak = ?, last_checkin_ts = ?",
            (uid, new_streak, today, new_streak, today),
        )
        conn.commit()

    # Give coins
    _add_coins(uid, coins, f"每日签到 Day {new_streak}")
    _add_xp(uid, 30)

    # Give equipment if applicable
    if eq_quality:
        gear_name = f"签到_{eq_quality}_装备"
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO user_inventory (user_id, item_id, item_name, quantity, item_type) VALUES (?, ?, ?, 1, 'equipment')",
                (uid, f"checkin_{gear_name}", f"Check-in {eq_quality.title()} Gear|||hp:{10 + new_streak * 3}|||{eq_quality}"),
            )
            conn.commit()

    return (new_streak, coins, bonus_text, eq_quality, False)


# ══════════════════════════════════════════════════════════════
# Views
# ══════════════════════════════════════════════════════════════

class CheckinView(discord.ui.View):
    """每日签到面板 / Daily Check-in panel."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        data = _get_checkin_data(self.uid)
        streak = data["streak"]
        today = _get_today_str()
        already = data["last_checkin_ts"] == today

        # Build 7-day progress bar
        bar_parts = []
        for d in range(1, 8):
            if d <= streak and already:
                bar_parts.append("✅")
            elif d <= streak and not already:
                bar_parts.append("✅" if data["last_checkin_ts"] else "⬜")
            else:
                bar_parts.append("⬜")
        progress_bar_str = " ".join(bar_parts)

        embed = discord.Embed(
            title="📅 Daily Check-in / 每日签到",
            description=f"**Streak / 连续签到: {streak} 天**\n\n{progress_bar_str}\nDay 1 → 2 → 3 → 4 → 5 → 6 → 7",
            color=0x2ECC71 if not already else 0x95A5A6,
        )

        rewards_desc = "\n".join([
            f"Day {d}: 🪙 {coins}" + (f" {bonus}" if bonus else "")
            for d, (coins, bonus, _) in STREAK_REWARDS.items()
        ])
        embed.add_field(name="Rewards / 奖励", value=rewards_desc, inline=False)

        if already:
            embed.add_field(
                name="Status / 状态",
                value="✅ Already checked in today! / 今日已签到！\nCome back tomorrow for Day " + str(streak % 7 + 1),
                inline=False,
            )
        else:
            embed.add_field(
                name="Status / 状态",
                value="⬜ Ready to check in! / 可以签到！",
                inline=False,
            )

        embed.set_footer(text="签到在 UTC+8 每天零点重置 | 断签重置到 Day 1")
        return embed

    @discord.ui.button(label="Sign In 签到", emoji="📅", style=discord.ButtonStyle.success, row=0)
    async def checkin_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return

        new_streak, coins, bonus_text, eq_quality, already = _do_checkin(uid)

        if already:
            embed = discord.Embed(
                title="📅 Daily Check-in / 每日签到",
                description=f"✅ **Already checked in today!** / 今日已签到！\n\n"
                            f"Current streak: **{new_streak}** days / 连续签到 **{new_streak}** 天\n"
                            f"Come back tomorrow! / 明天再来！",
                color=0xF39C12,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self)
            return

        desc = f"🎉 **Signed in! / 签到成功！**\n\n"
        desc += f"Streak: **Day {new_streak}** / 连续签到第 **{new_streak}** 天\n"
        desc += f"Reward / 奖励: 🪙 **{coins:,}**\n"
        if bonus_text:
            desc += f"{bonus_text}\n"
        desc += f"+ ⚡ 30 EXP"

        embed = discord.Embed(
            title="📅 Check-in Complete! / 签到完成！",
            description=desc,
            color=0x2ECC71,
        )
        embed.set_footer(text=f"Tomorrow: Day {new_streak % 7 + 1} | 明天签到 Day {new_streak % 7 + 1}")

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Records 记录", emoji="📊", style=discord.ButtonStyle.primary, row=0)
    async def records_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = _get_checkin_data(self.uid)
        streak = data["streak"]
        last = data["last_checkin_ts"] or "Never / 从未签到"

        # Get transaction history for check-ins
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT amount, reason, timestamp FROM transactions WHERE discord_id = ? AND reason LIKE '%每日签到%' ORDER BY timestamp DESC LIMIT 10",
                (self.uid,),
            )
            rows = cur.fetchall()

        lines = []
        for r in rows:
            ts = r["timestamp"][:10] if r["timestamp"] else "?"
            lines.append(f"📅 {ts} — 🪙 +{r['amount']} ({r['reason']})")

        embed = discord.Embed(
            title="📊 Check-in History / 签到记录",
            description=(
                f"**Current Streak / 当前连续: {streak} 天**\n"
                f"**Last Check-in / 上次签到: {last}**\n\n"
                f"**Recent / 最近签到:**\n" + ("\n".join(lines) if lines else "No records / 无记录")
            ),
            color=0x3498DB,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
        else:
            embed = discord.Embed(
                title="Check-in / 签到",
                description="Use `/gmpt-mmorpg` to return.\n使用 `/gmpt-mmorpg` 返回。",
                color=0x95A5A6,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)


# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════

class CheckinCog(commands.Cog):
    """每日签到系统 / Daily Check-in system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gmpt-checkin", description="每日签到 / Daily Check-in — earn streak rewards!")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def checkin_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        view = CheckinView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(CheckinCog(bot))
    logger.info("Checkin cog loaded")
