"""
GMPT Bot — Casino mini-games (Slots & Coinflip)
"""
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from datetime import datetime
import logging
from utils.logger import log_error

logger = logging.getLogger(__name__)

# ── Economy helpers ──
def _get_balance(uid: str) -> int:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?, 'unknown') ON CONFLICT(discord_id) DO NOTHING",
            (uid,),
        )
        cur.execute("SELECT score FROM users WHERE discord_id=?", (uid,))
        row = cur.fetchone()
    return row["score"] if row and row["score"] is not None else 0


def _add_coins(uid: str, amount: int, reason: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?, 'unknown') ON CONFLICT(discord_id) DO NOTHING",
            (uid,),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
        cur.execute("INSERT INTO transactions (discord_id, amount, reason) VALUES (?,?,?)", (uid, amount, reason))
        conn.commit()


# ── Daily limit helper (Coinflip only) ──
def _check_daily_limit(uid: int, game_type: str) -> tuple[bool, int, int]:
    """Returns (blocked, used, remaining)."""
    today = datetime.now().strftime('%Y-%m-%d')
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO game_limits (user_id, date, game_type, play_count) VALUES (?,?,?,0)",
            (uid, today, game_type),
        )
        cur.execute(
            "SELECT play_count FROM game_limits WHERE user_id=? AND date=? AND game_type=?",
            (uid, today, game_type),
        )
        row = cur.fetchone()
        used = row["play_count"] if row else 0
        remaining = 3 - used
        blocked = used >= 3
        if not blocked:
            cur.execute(
                "UPDATE game_limits SET play_count = play_count + 1 WHERE user_id=? AND date=? AND game_type=?",
                (uid, today, game_type),
            )
            conn.commit()
    return blocked, used + (0 if blocked else 1), remaining - (0 if blocked else 1)


# ── Slot machine ──
SLOT_EMOJIS = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣", "⭐"]
SLOT_WEIGHTS = [20, 20, 20, 15, 10, 3, 2]  # corresponding to emoji order

SLOT_PAYOUTS = {
    ("⭐", "⭐", "⭐"): 50,
    ("7️⃣", "7️⃣", "7️⃣"): 25,
    ("💎", "💎", "💎"): 15,
    ("🍇", "🍇", "🍇"): 8,
    ("🍒", "🍒", "🍒"): 5,
    ("🍋", "🍋", "🍋"): 3,
    ("🍊", "🍊", "🍊"): 3,
}


def _spin_slots() -> tuple[list[str], int]:
    reels = random.choices(SLOT_EMOJIS, weights=SLOT_WEIGHTS, k=3)
    result = tuple(reels)
    multiplier = SLOT_PAYOUTS.get(result, 0)
    if multiplier == 0:
        # Check 2x ⭐
        if reels.count("⭐") >= 2:
            multiplier = 2
    return reels, multiplier


# ── Cog ──
class Casino(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    gmpt_casino2_group = app_commands.Group(
        name="gmpt-casino2",
        description="Additional casino games / 额外赌场游戏"
    )

    @gmpt_casino2_group.command(name="slots", description="Play the slot machine / 玩老虎机")
    @app_commands.describe(bet="Bet amount / 下注金额（正整数）")
    async def slots_cmd(self, interaction: discord.Interaction, bet: int):
        uid = str(interaction.user.id)

        if bet <= 0:
            return await interaction.response.send_message("下注金额必须为正整数 / Bet must be a positive integer.", ephemeral=True)

        balance = _get_balance(uid)
        if balance < bet:
            return await interaction.response.send_message(
                f"金币不足 / Insufficient coins. 余额: 🪙 {balance}", ephemeral=True
            )

        _add_coins(uid, -bet, f"Slots bet / 老虎机下注")

        # Jackpot contribution (5%)
        from utils.jackpot import contribute_to_jackpot, try_win_jackpot, get_jackpot
        jackpot_contrib = contribute_to_jackpot(bet)

        reels, multiplier = _spin_slots()
        win_amount = bet * multiplier
        net = win_amount - bet

        if win_amount > 0:
            _add_coins(uid, win_amount, f"Slots win / 老虎机获胜 x{multiplier}")
        else:
            _add_coins(uid, 0, "Slots loss / 老虎机未中奖")

        # Jackpot win check (0.5%)
        jackpot_won = False
        jackpot_amount = 0
        if random.random() < 0.005:
            won, jackpot_amount, _ = try_win_jackpot(uid, interaction.user.display_name)
            if won and jackpot_amount > 0:
                jackpot_won = True
                _add_coins(uid, jackpot_amount, "🎉 Jackpot win / 老虎机大奖!")

        new_balance = _get_balance(uid)

        embed = discord.Embed(
            title="🎰 老虎机",
            color=discord.Color.gold(),
            description=f"**{reels[0]}  {reels[1]}  {reels[2]}**",
        )
        embed.add_field(name="下注 / Bet", value=f"🪙 {bet}", inline=True)
        if multiplier > 0:
            embed.add_field(name="赢取 / Win", value=f"🪙 {win_amount} (x{multiplier})", inline=True)
            embed.add_field(name="净收益 / Net", value=f"🪙 +{net}", inline=True)
        else:
            embed.add_field(name="结果 / Result", value="❌ 未中奖 / No win", inline=True)
            embed.add_field(name="亏损 / Loss", value=f"🪙 -{bet}", inline=True)
        embed.add_field(name="新余额 / New Balance", value=f"🪙 {new_balance}", inline=False)

        # Jackpot info
        current_jackpot = get_jackpot()
        embed.add_field(name="🎉 Jackpot奖池 / Pool", value=f"🪙 {current_jackpot:,}", inline=True)
        embed.add_field(name="本次贡献 / Contributed", value=f"🪙 {jackpot_contrib}", inline=True)

        if jackpot_won:
            embed.add_field(
                name="🌟 JACKPOT! 🌟",
                value=f"🎉🎉🎉 **{interaction.user.display_name} 中了 Jackpot!** 🎉🎉🎉\n获得 🪙 **{jackpot_amount:,}** 金币！\n\nHit the JACKPOT! Won 🪙 **{jackpot_amount:,}** coins!",
                inline=False,
            )
            embed.color = 0xFFD700

        await interaction.response.send_message(embed=embed)

        # Jackpot announcement
        if jackpot_won and interaction.guild:
            try:
                announce_embed = discord.Embed(
                    title="🌟 JACKPOT WINNER! 🌟",
                    description=(
                        f"🎉 **{interaction.user.display_name}** 中了 **Jackpot**！\n"
                        f"获得了 🪙 **{jackpot_amount:,}** 金币！\n\n"
                        f"Jackpot hit! {interaction.user.display_name} won 🪙 **{jackpot_amount:,}** coins!"
                    ),
                    color=0xFFD700,
                )
                await interaction.channel.send(content="@here", embed=announce_embed)
            except Exception:
                pass

    @gmpt_casino2_group.command(name="coinflip", description="Flip a coin / 猜硬币正反面")
    @app_commands.describe(
        bet="Bet amount / 下注金额（正整数）",
        choice="正面 or 反面 / Heads or Tails",
    )
    @app_commands.choices(choice=[
        app_commands.Choice(name="正面 / Heads", value="正面"),
        app_commands.Choice(name="反面 / Tails", value="反面"),
    ])
    async def coinflip_cmd(self, interaction: discord.Interaction, bet: int, choice: str):
        uid = str(interaction.user.id)

        # Daily limit check
        blocked, used, remaining = _check_daily_limit(interaction.user.id, 'coinflip')
        if blocked:
            return await interaction.response.send_message(
                "你今天已玩了 3 次猜硬币，明天再来！\nYou've played 3 times today, come back tomorrow!",
                ephemeral=True,
            )

        if bet <= 0:
            return await interaction.response.send_message("下注金额必须为正整数 / Bet must be a positive integer.", ephemeral=True)

        balance = _get_balance(uid)
        if balance < bet:
            return await interaction.response.send_message(
                f"金币不足 / Insufficient coins. 余额: 🪙 {balance}", ephemeral=True
            )

        _add_coins(uid, -bet, f"Coinflip bet / 猜硬币下注")

        result = random.choice(["正面", "反面"])
        won = (choice == result)

        if won:
            payout = bet * 2
            _add_coins(uid, payout, f"Coinflip win / 猜硬币获胜 x2")
        else:
            payout = 0
            _add_coins(uid, 0, "Coinflip loss / 猜硬币失败")

        new_balance = _get_balance(uid)
        coin_emoji = "🪙 正面" if result == "正面" else "🪙 反面"

        embed = discord.Embed(
            title="🪙 猜硬币",
            color=discord.Color.green() if won else discord.Color.red(),
            description=f"硬币结果: **{coin_emoji}**\n你的选择: **{choice}**",
        )
        if won:
            embed.add_field(name="结果", value=f"✅ 猜对了！+🪙 {payout} (净赚 +{bet})", inline=False)
        else:
            embed.add_field(name="结果", value=f"❌ 猜错了！-🪙 {bet}", inline=False)
        embed.add_field(name="新余额 / New Balance", value=f"🪙 {new_balance}", inline=False)
        embed.set_footer(text=f"📊 今日剩余 / Remaining: {remaining}/3")

        await interaction.response.send_message(embed=embed)

    @slots_cmd.error
    @coinflip_cmd.error
    async def casino_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            remaining = int(error.retry_after)
            msg = f"⏳ 冷却中，请等 {remaining} 秒 / Cooldown, wait {remaining}s."
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        else:
            log_error("casino", interaction.command.name if interaction.command else "unknown", error)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("发生错误 / An error occurred.", ephemeral=True)
                else:
                    await interaction.followup.send("发生错误 / An error occurred.", ephemeral=True)
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(Casino(bot))
