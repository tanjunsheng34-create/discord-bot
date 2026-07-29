"""
GMPT Bot — 博彩扩展 / Gambling Extensions
/gmpt-lottery   彩票系统 / Lottery
/gmpt-diceduel  骰子对决 / Dice Duel
/gmpt-crash     Crash游戏 / Crash Game
/gmpt-scratch   刮刮乐 / Scratch Card

Bilingual (中文 / English)
"""
import asyncio
import random
import logging
import time
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins

logger = logging.getLogger(__name__)


def _format_coins(amount: int) -> str:
    return f"🪙 {amount:,}"


def _init_lottery_tables():
    """Initialize lottery-related tables."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lottery_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                purchased_at TEXT DEFAULT (datetime('now')),
                drawn INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lottery_draws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_amount INTEGER NOT NULL DEFAULT 0,
                total_tickets INTEGER NOT NULL DEFAULT 0,
                winner_id TEXT,
                drawn_at TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        conn.commit()


_init_lottery_tables()


class Gambling(CogBase):
    """博彩扩展 / Gambling extensions."""

    def __init__(self, bot):
        self.bot = bot

    gmpt_gamble_group = app_commands.Group(
        name="gmpt-gamble",
        description="Gambling & betting / 博彩投注"
    )

    async def cog_load(self):
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[Gambling] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    # ══════════════════════════════════════════════════════════
    # /gmpt-lottery — 彩票系统
    # ══════════════════════════════════════════════════════════
    lottery_group = app_commands.Group(
        name="gmpt-lottery",
        description="🎟️ 彩票系统 / Lottery System"
    )

    @lottery_group.command(name="buy", description="购买彩票 / Buy lottery tickets")
    @app_commands.describe(quantity="购买数量 / Quantity (default 1)")
    async def lottery_buy(self, interaction: discord.Interaction, quantity: int = 1):
        """购买彩票."""
        uid = str(interaction.user.id)

        if quantity < 1 or quantity > 100:
            return await interaction.response.send_message(
                "数量需在 1-100 之间 / Quantity must be 1-100.", ephemeral=True)

        cost = quantity * 50
        bal = get_balance(uid)
        if bal < cost:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 {cost:,}，你只有 🪙 {bal:,} / "
                f"Not enough coins! Need 🪙 {cost:,}, you have 🪙 {bal:,}.",
                ephemeral=True,
            )

        add_coins(uid, -cost, f"购买 {quantity} 张彩票 / Bought {quantity} lottery tickets")

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO lottery_tickets (user_id, quantity) VALUES (?, ?)",
                (uid, quantity),
            )
            cur.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM lottery_tickets WHERE drawn=0"
            )
            total = cur.fetchone()[0]
            conn.commit()

        pool = total * 50 * 7 // 10  # 70% to pool

        embed = discord.Embed(
            title="🎟️ 彩票 / Lottery",
            description=f"购买了 **{quantity}** 张彩票，花费 🪙 **{cost:,}**\n"
                        f"Bought **{quantity}** tickets for 🪙 **{cost:,}**",
            color=0xF1C40F,
        )
        embed.add_field(name="🎫 总售出 / Total Tickets", value=str(total), inline=True)
        embed.add_field(name="🏆 奖池 / Prize Pool", value=_format_coins(pool), inline=True)
        embed.add_field(name="💰 余额 / Balance", value=_format_coins(get_balance(uid)), inline=False)
        embed.set_footer(text="使用 /gmpt-lottery status 查看状态 | /gmpt-lottery draw 开奖")

        await interaction.response.send_message(embed=embed)

    @lottery_group.command(name="status", description="查看彩票状态 / View lottery status")
    async def lottery_status(self, interaction: discord.Interaction):
        """查看彩票状态."""
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(SUM(quantity), 0) FROM lottery_tickets WHERE drawn=0")
            total_tix = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM lottery_tickets WHERE drawn=0")
            players = cur.fetchone()[0]

        pool = int(total_tix * 50 * 0.70)

        embed = discord.Embed(
            title="🎟️ 彩票状态 / Lottery Status",
            description=f"当前奖池 / Current Pool: 🪙 **{pool:,}**",
            color=0xF1C40F,
        )
        embed.add_field(name="🎫 售出彩票 / Tickets Sold", value=str(total_tix), inline=True)
        embed.add_field(name="👥 参与人数 / Players", value=str(players), inline=True)
        embed.add_field(name="💵 单价 / Price", value="🪙 50 / 张", inline=True)
        embed.set_footer(text="购买 /gmpt-lottery buy | 开奖 /gmpt-lottery draw")

        await interaction.response.send_message(embed=embed)

    @lottery_group.command(name="draw", description="手动开奖 / Draw lottery manually")
    async def lottery_draw(self, interaction: discord.Interaction):
        """手动开奖."""
        uid = str(interaction.user.id)

        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(SUM(quantity), 0) FROM lottery_tickets WHERE drawn=0")
            total_tix = cur.fetchone()[0]

            if total_tix == 0:
                return await interaction.response.send_message(
                    "本期无彩票 / No tickets purchased.", ephemeral=True)

            pool = int(total_tix * 50 * 0.70)

            # Build weighted list
            cur.execute("SELECT user_id, quantity FROM lottery_tickets WHERE drawn=0")
            entries = []
            for row in cur.fetchall():
                entries.extend([row["user_id"]] * row["quantity"])

            winner_id = random.choice(entries)

            # Mark all as drawn
            cur.execute("UPDATE lottery_tickets SET drawn=1 WHERE drawn=0")
            cur.execute(
                "INSERT INTO lottery_draws (pool_amount, total_tickets, winner_id, drawn_at, status) "
                "VALUES (?, ?, ?, datetime('now'), 'drawn')",
                (pool, total_tix, winner_id),
            )
            conn.commit()

        add_coins(winner_id, pool, f"彩票中奖 / Lottery winner — Pool: {pool}")

        embed = discord.Embed(
            title="🎉 开奖！/ Lottery Draw!",
            description=f"🏆 中奖者: <@{winner_id}>\n"
                        f"🏆 Winner: <@{winner_id}>\n\n"
                        f"奖金 / Prize: 🪙 **{pool:,}**",
            color=0x2ECC71,
        )
        embed.add_field(name="🎫 总彩票 / Total Tickets", value=str(total_tix), inline=True)
        embed.add_field(name="📊 中奖率 / Odds", value=f"1 in {total_tix}", inline=True)

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-diceduel — 骰子对决
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="diceduel", description="🎲 骰子对决 / Dice Duel — bet against another player")
    @app_commands.describe(opponent="对手 / Opponent", bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def diceduel_cmd(self, interaction: discord.Interaction, opponent: discord.Member, bet: int):
        """骰子对决."""
        uid = str(interaction.user.id)
        oid = str(opponent.id)
        uname = interaction.user.display_name
        oname = opponent.display_name

        if opponent.id == interaction.user.id:
            return await interaction.response.send_message("不能和自己对决 / Cannot duel yourself!", ephemeral=True)
        if opponent.bot:
            return await interaction.response.send_message("不能和机器人对决 / Cannot duel bots!", ephemeral=True)
        if bet < 10:
            return await interaction.response.send_message("最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)

        my_bal = get_balance(uid)
        op_bal = get_balance(oid)
        if my_bal < bet:
            return await interaction.response.send_message(
                f"你余额不足！/ Your balance: 🪙 {my_bal:,}", ephemeral=True)
        if op_bal < bet:
            return await interaction.response.send_message(
                f"{oname} 余额不足！/ {oname}'s balance: 🪙 {op_bal:,}", ephemeral=True)

        # Deduct both
        add_coins(uid, -bet, f"骰子对决 vs {oname} / Dice duel vs {oname}")
        add_coins(oid, -bet, f"骰子对决 vs {uname} / Dice duel vs {uname}")

        # Roll
        my_rolls = [random.randint(1, 6), random.randint(1, 6)]
        op_rolls = [random.randint(1, 6), random.randint(1, 6)]
        my_total = sum(my_rolls)
        op_total = sum(op_rolls)

        total_pot = bet * 2
        fee = int(total_pot * 0.10)
        prize = total_pot - fee

        if my_total > op_total:
            winner_id = uid
            winner_name = uname
            loser_name = oname
            result_str = f"🎉 **{uname}** 获胜！/ Wins!"
        elif op_total > my_total:
            winner_id = oid
            winner_name = oname
            loser_name = uname
            result_str = f"🎉 **{oname}** 获胜！/ Wins!"
        else:
            # Tie — refund
            add_coins(uid, bet, "骰子对决平局退款 / Dice duel tie refund")
            add_coins(oid, bet, "骰子对决平局退款 / Dice duel tie refund")
            embed = discord.Embed(
                title="🎲 骰子对决 / Dice Duel",
                description=f"🤝 平局！各退回 🪙 **{bet:,}**\nTie! Both refunded 🪙 **{bet:,}**",
                color=0x95A5A6,
            )
            embed.add_field(name=f"{uname} 掷出 / Rolled", value=f"🎲 {my_rolls[0]} + {my_rolls[1]} = **{my_total}**", inline=True)
            embed.add_field(name=f"{oname} 掷出 / Rolled", value=f"🎲 {op_rolls[0]} + {op_rolls[1]} = **{op_total}**", inline=True)
            return await interaction.response.send_message(embed=embed)

        add_coins(winner_id, prize, f"骰子对决获胜 vs {loser_name} / Dice duel win vs {loser_name}")

        embed = discord.Embed(
            title="🎲 骰子对决 / Dice Duel",
            description=result_str,
            color=0x2ECC71,
        )
        embed.add_field(name=f"{uname} 掷出 / Rolled", value=f"🎲 {my_rolls[0]} + {my_rolls[1]} = **{my_total}**", inline=True)
        embed.add_field(name=f"{oname} 掷出 / Rolled", value=f"🎲 {op_rolls[0]} + {op_rolls[1]} = **{op_total}**", inline=True)
        embed.add_field(name="🏆 奖金 / Prize", value=_format_coins(prize), inline=False)
        embed.add_field(name="🏦 手续费 / Fee", value=_format_coins(fee), inline=True)

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-crash — Crash 游戏
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="crash", description="📈 Crash游戏 / Crash Game — cash out before it crashes!")
    @app_commands.describe(bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
    async def crash_cmd(self, interaction: discord.Interaction, bet: int):
        """Crash 游戏."""
        uid = str(interaction.user.id)
        uname = interaction.user.display_name

        if bet < 10:
            return await interaction.response.send_message("最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)

        bal = get_balance(uid)
        if bal < bet:
            return await interaction.response.send_message(
                f"金币不足！/ Balance: 🪙 {bal:,}", ephemeral=True)

        add_coins(uid, -bet, "Crash下注 / Crash bet")

        crash_point = round(random.uniform(1.10, 5.0), 2)
        if random.random() < 0.05:
            crash_point = round(random.uniform(1.0, 1.09), 2)  # early crash

        view = CrashView(uid, uname, bet, crash_point)
        embed = discord.Embed(
            title="📈 Crash 游戏 / Crash Game",
            description=f"{uname} 下注 🪙 **{bet:,}**\n当前倍率 / Current Multiplier: **1.00x**\n\n"
                        f"点击 Cash Out 按钮提现！\nClick Cash Out to collect!",
            color=0x3498DB,
        )

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()
        asyncio.create_task(view._tick_loop())

    # ══════════════════════════════════════════════════════════
    # /gmpt-gamble scratch — 刮刮乐 (group command)
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="scratch", description="🎰 刮刮乐 / Scratch card (50 coins)")
    @app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
    async def scratch_cmd(self, interaction: discord.Interaction):
        """刮刮乐."""
        await self._do_scratch(interaction)

    # ══════════════════════════════════════════════════════════
    # /gmpt-scratch — 刮刮乐 (standalone command)
    # ══════════════════════════════════════════════════════════
    @app_commands.command(name="gmpt-scratch", description="🎰 刮刮乐 / Scratch card (50 coins)")
    @app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
    async def scratch_standalone(self, interaction: discord.Interaction):
        """刮刮乐 standalone."""
        await self._do_scratch(interaction)

    async def _do_scratch(self, interaction: discord.Interaction):
        """Shared scratch logic."""
        uid = str(interaction.user.id)

        bal = get_balance(uid)
        if bal < 50:
            return await interaction.response.send_message(
                f"金币不足！需要 🪙 50，你只有 🪙 {bal:,} / Need 🪙 50.", ephemeral=True)

        add_coins(uid, -50, "刮刮乐 / Scratch card")

        symbols = ['💎', '🍀', '⭐', '🍒', '🍋', '🔔']
        grid = [random.choices(symbols, k=3) for _ in range(3)]

        view = ScratchView(uid, grid)
        embed = discord.Embed(
            title="🎰 刮刮乐 / Scratch Card",
            description="点击格子翻开！匹配 3 个相同符号即可中奖！\nClick to reveal! Match 3 same symbols to win!",
            color=0xF1C40F,
        )
        embed.add_field(name="💎💎💎", value="🪙 500", inline=True)
        embed.add_field(name="🍀🍀🍀", value="🪙 200", inline=True)
        embed.add_field(name="⭐⭐⭐", value="🪙 100", inline=True)

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    # ══════════════════════════════════════════════════════════
    # /gmpt-gamble roulette — 🎡 俄罗斯轮盘 / Russian Roulette
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="roulette", description="🎡 俄罗斯轮盘 / Russian Roulette — 红黑/奇偶/单数字")
    @app_commands.describe(bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def roulette_cmd(self, interaction: discord.Interaction, bet: int):
        """🎡 俄罗斯轮盘."""
        uid = str(interaction.user.id)

        if bet < 10:
            return await interaction.response.send_message(
                "最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)

        balance = get_balance(uid)
        if balance < bet:
            return await interaction.response.send_message(
                f"❌ 余额不足！你的余额: {balance:,}G / Insufficient balance! Your balance: {balance:,}G",
                ephemeral=True,
            )
        add_coins(uid, -bet, "轮盘下注 / Roulette bet")

        view = RouletteView(uid, interaction.user.display_name, bet)
        embed = discord.Embed(
            title="🎡 俄罗斯轮盘 / Russian Roulette",
            description=(
                f"下注 / Bet: 🪙 **{bet:,}**\n\n"
                "选择你的押注方式 / Choose your bet type:\n\n"
                "🔴 红 Red — **2x**（偶数为红 / even = red）\n"
                "⚫ 黑 Black — **2x**（奇数为黑 / odd = black）\n"
                "🔢 奇数 Odd / 偶数 Even — **2x**\n"
                "🎯 单数字 Single Number (1-36) — **36x**"
            ),
            color=0xE74C3C,
        )
        await interaction.response.send_message(embed=embed, view=view)

    # ══════════════════════════════════════════════════════════
    # /gmpt-gamble highlow — 📈 比大小 / High & Low
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="highlow", description="📈 比大小 / High & Low — 猜下一张牌大小")
    @app_commands.describe(bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def highlow_cmd(self, interaction: discord.Interaction, bet: int):
        """📈 比大小."""
        uid = str(interaction.user.id)

        if bet < 10:
            return await interaction.response.send_message(
                "最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)

        balance = get_balance(uid)
        if balance < bet:
            return await interaction.response.send_message(
                f"❌ 余额不足！你的余额: {balance:,}G / Insufficient balance! Your balance: {balance:,}G",
                ephemeral=True,
            )
        add_coins(uid, -bet, "比大小下注 / HighLow bet")

        suits = ['♠', '♥', '♦', '♣']
        ranks_list = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        card1 = (random.choice(ranks_list), random.choice(suits))

        view = HighLowView(uid, bet, card1)
        embed = discord.Embed(
            title="📈 比大小 / High & Low",
            description=(
                f"下注 / Bet: 🪙 **{bet:,}**\n\n"
                f"你的牌 / Your card: **{card1[0]}{card1[1]}**\n"
                f"对手牌 / Opponent: **🂠 ?**\n\n"
                "猜对手的牌比你的大还是小？\n"
                "Guess if the next card is higher or lower!\n\n"
                "✅ 猜对 **2x** | 🤝 平局退注 / Tie refunds bet"
            ),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed, view=view)

    # ══════════════════════════════════════════════════════════
    # /gmpt-gamble guess — 🔢 猜数字 / Number Guessing
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="guess", description="🔢 猜数字 / Number Guessing — 1-100，5 次机会")
    @app_commands.describe(bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
    async def guess_cmd(self, interaction: discord.Interaction, bet: int):
        """🔢 猜数字."""
        uid = str(interaction.user.id)

        if bet < 10:
            return await interaction.response.send_message(
                "最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)

        balance = get_balance(uid)
        if balance < bet:
            return await interaction.response.send_message(
                f"❌ 余额不足！你的余额: {balance:,}G / Insufficient balance! Your balance: {balance:,}G",
                ephemeral=True,
            )
        add_coins(uid, -bet, "猜数字下注 / NumberGuess bet")

        secret = random.randint(1, 100)
        view = NumberGuessView(uid, bet, secret)
        embed = discord.Embed(
            title="🔢 猜数字 / Number Guessing (1-100)",
            description=(
                f"下注 / Bet: 🪙 **{bet:,}**\n\n"
                "我想了一个 1-100 的数字，你有 **5 次**机会！\n"
                "I picked a number 1-100. You have **5 chances**!\n\n"
                "🎯 猜中 / Exact — **10x**\n"
                "🔥 差距 ≤3 / Within 3 — **5x**\n"
                "✨ 差距 ≤10 / Within 10 — **2x**"
            ),
            color=0x9B59B6,
        )
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    # ══════════════════════════════════════════════════════════
    # /gmpt-gamble slot — 🎰 老虎机 / Slot Machine
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="slot", description="🎰 老虎机 / Slot Machine — 3连10x 双连3x")
    @app_commands.describe(bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def slot_cmd(self, interaction: discord.Interaction, bet: int):
        """🎰 老虎机."""
        uid = str(interaction.user.id)
        if bet < 10:
            return await interaction.response.send_message(
                "最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)
        balance = get_balance(uid)
        if balance < bet:
            return await interaction.response.send_message(
                f"❌ 余额不足！你的余额: {balance:,}G / Insufficient balance! Your balance: {balance:,}G",
                ephemeral=True)
        add_coins(uid, -bet, "老虎机下注 / Slot bet")
        view = SlotView(uid, interaction.user.display_name, bet)
        embed = discord.Embed(
            title="🎰 老虎机 / Slot Machine",
            description=(
                f"下注 / Bet: 🪙 **{bet:,}**\n\n"
                "点击 Spin 旋转！三连 10x，双连 3x！\n"
                "Click Spin! Triple 10x, Double 3x!\n\n"
                f"🍒🍋🍊🍇💎7️⃣⭐"
            ),
            color=0xF1C40F,
        )
        await interaction.response.send_message(embed=embed, view=view)

    # ══════════════════════════════════════════════════════════
    # /gmpt-gamble dice — 🎲 掷骰子 / Dice Roll
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="dice", description="🎲 掷骰子 / Dice Roll — 猜大小2x 猜7点3x 猜数字5x")
    @app_commands.describe(bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def dice_cmd(self, interaction: discord.Interaction, bet: int):
        """🎲 掷骰子."""
        uid = str(interaction.user.id)
        if bet < 10:
            return await interaction.response.send_message(
                "最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)
        balance = get_balance(uid)
        if balance < bet:
            return await interaction.response.send_message(
                f"❌ 余额不足！你的余额: {balance:,}G / Insufficient balance! Your balance: {balance:,}G",
                ephemeral=True)
        add_coins(uid, -bet, "骰子下注 / Dice bet")
        view = DiceRollView(uid, interaction.user.display_name, bet)
        embed = discord.Embed(
            title="🎲 掷骰子 / Dice Roll",
            description=(
                f"下注 / Bet: 🪙 **{bet:,}**\n\n"
                "🔺 大 Big (8-12) — **2x**\n"
                "🔻 小 Small (2-6) — **2x**\n"
                "🎲 7点 — **3x**\n"
                "🎯 精确数字 (2-12) — **5x**"
            ),
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed, view=view)

    # ══════════════════════════════════════════════════════════
    # /gmpt-gamble coinflip — 🪙 硬币翻转 / Coin Flip
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="coinflip", description="🪙 硬币翻转 / Coin Flip — 猜正反面1:1")
    @app_commands.describe(bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def coinflip_cmd(self, interaction: discord.Interaction, bet: int):
        """🪙 掷硬币."""
        uid = str(interaction.user.id)
        if bet < 10:
            return await interaction.response.send_message(
                "最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)
        balance = get_balance(uid)
        if balance < bet:
            return await interaction.response.send_message(
                f"❌ 余额不足！你的余额: {balance:,}G / Insufficient balance! Your balance: {balance:,}G",
                ephemeral=True)
        add_coins(uid, -bet, "硬币下注 / Coin flip bet")
        view = CoinFlipView(uid, interaction.user.display_name, bet)
        embed = discord.Embed(
            title="🪙 硬币翻转 / Coin Flip",
            description=(
                f"下注 / Bet: 🪙 **{bet:,}**\n\n"
                "猜正面还是反面？1:1 赔率！\n"
                "Guess Heads or Tails? 1:1 payout!"
            ),
            color=0xF1C40F,
        )
        await interaction.response.send_message(embed=embed, view=view)


# ══════════════════════════════════════════════════════════════
# Crash View
# ══════════════════════════════════════════════════════════════

class CrashView(discord.ui.View):
    def __init__(self, player_id: str, player_name: str, bet: int, crash_point: float):
        super().__init__(timeout=60)
        self.player_id = player_id
        self.player_name = player_name
        self.bet = bet
        self.crash_point = crash_point
        self.multiplier = 1.00
        self.cashed_out = False
        self.crashed = False
        self.message = None

    @discord.ui.button(label="💵 Cash Out!", style=discord.ButtonStyle.success)
    async def cashout_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.player_id:
            return await interaction.response.send_message("不是你的游戏 / Not your game!", ephemeral=True)

        if self.crashed:
            return await interaction.response.send_message("已经 Crash 了！/ Already crashed!", ephemeral=True)

        if self.cashed_out:
            return await interaction.response.send_message("已经提现过了！/ Already cashed out!", ephemeral=True)

        self.cashed_out = True
        profit = int(self.bet * self.multiplier)
        add_coins(self.player_id, profit, f"Crash提现 {self.multiplier}x / Crash cashout")

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="📈 Crash 游戏 / Crash Game",
            description=f"💵 **Cash Out!** 在 **{self.multiplier:.2f}x** 提现成功！\n"
                        f"Cashed out at **{self.multiplier:.2f}x**!\n\n"
                        f"赢利 / Profit: 🪙 **{profit:,}**",
            color=0x2ECC71,
        )
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    async def _tick_loop(self):
        while not self.crashed and not self.cashed_out:
            await asyncio.sleep(0.8)
            increment = round(random.uniform(0.05, 0.15), 2)
            self.multiplier = round(self.multiplier + increment, 2)

            if self.multiplier >= self.crash_point:
                self.crashed = True
                for child in self.children:
                    child.disabled = True

                embed = discord.Embed(
                    title="📈 Crash 游戏 / Crash Game",
                    description=f"💥 **CRASH!** 在 **{self.multiplier:.2f}x** 崩了！\n"
                                f"Crashed at **{self.multiplier:.2f}x**!\n\n"
                                f"损失 / Lost: 🪙 **{self.bet:,}**",
                    color=0xE74C3C,
                )
                try:
                    if self.message:
                        await self.message.edit(embed=embed, view=self)
                except Exception:
                    pass
                break

            if self.multiplier >= 100:
                self.crashed = True
                embed = discord.Embed(
                    title="📈 Crash 游戏 / Crash Game",
                    description=f"💰 达到上限 **{self.multiplier:.2f}x**！自动提现！\n"
                                f"Max reached! Auto cashout!",
                    color=0xF1C40F,
                )
                profit = int(self.bet * self.multiplier)
                add_coins(self.player_id, profit, f"Crash上限提现 {self.multiplier}x")
                self.cashed_out = True
                for child in self.children:
                    child.disabled = True
                try:
                    if self.message:
                        await self.message.edit(embed=embed, view=self)
                except Exception:
                    pass
                break

            embed = discord.Embed(
                title="📈 Crash 游戏 / Crash Game",
                description=f"📈 当前倍率 / Multiplier: **{self.multiplier:.2f}x**\n"
                            f"当前价值 / Current Value: 🪙 **{int(self.bet * self.multiplier):,}**",
                color=0x3498DB if self.multiplier < 2.0 else 0xE67E22,
            )
            try:
                if self.message:
                    await self.message.edit(embed=embed, view=self)
            except Exception:
                pass

    async def on_timeout(self):
        if not self.cashed_out and not self.crashed:
            self.crashed = True
            for child in self.children:
                child.disabled = True
            embed = discord.Embed(
                title="📈 Crash 游戏 / Crash Game",
                description=f"⏰ 超时！损失 🪙 **{self.bet:,}**\nTimed out!",
                color=0xE74C3C,
            )
            try:
                if self.message:
                    await self.message.edit(embed=embed, view=self)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
# Scratch View
# ══════════════════════════════════════════════════════════════

class ScratchView(discord.ui.View):
    def __init__(self, player_id: str, grid: list):
        super().__init__(timeout=60)
        self.player_id = player_id
        self.grid = grid
        self.revealed = [[False] * 3 for _ in range(3)]
        self.message = None

        for r in range(3):
            for c in range(3):
                btn = discord.ui.Button(
                    label="❓",
                    style=discord.ButtonStyle.secondary,
                    row=r,
                    custom_id=f"scratch_{r}_{c}",
                )
                btn.callback = self._make_callback(r, c)
                self.add_item(btn)

    def _make_callback(self, r: int, c: int):
        async def cb(interaction: discord.Interaction):
            if str(interaction.user.id) != self.player_id:
                return await interaction.response.send_message("不是你的刮刮乐 / Not yours!", ephemeral=True)

            if self.revealed[r][c]:
                return await interaction.response.defer()

            # Always defer first to prevent "InteractionResponded" race
            await interaction.response.defer()

            self.revealed[r][c] = True
            symbol = self.grid[r][c]
            btn = self.children[r * 3 + c]
            btn.label = symbol
            btn.style = discord.ButtonStyle.primary
            btn.disabled = True

            # Check if all revealed
            all_revealed = all(self.revealed[i][j] for i in range(3) for j in range(3))

            if all_revealed:
                # Check winnings
                prize = self._calculate_prize()
                if prize > 0:
                    add_coins(self.player_id, prize, f"刮刮乐中奖 / Scratch card win")

                embed = discord.Embed(
                    title="🎰 刮刮乐 / Scratch Card",
                    description=self._build_board(),
                    color=0x2ECC71 if prize > 0 else 0x95A5A6,
                )
                if prize > 0:
                    embed.add_field(name="🎉 中奖 / Win!", value=_format_coins(prize), inline=False)
                else:
                    embed.add_field(name="😢 未中奖 / No Win", value="下次好运！/ Better luck next time!", inline=False)

                for child in self.children:
                    child.disabled = True
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                # Partial reveal: update the button visual
                await interaction.edit_original_response(view=self)

        return cb

    def _calculate_prize(self) -> int:
        # Check each row
        for row in self.grid:
            if row[0] == row[1] == row[2]:
                if row[0] == '💎':
                    return 500
                elif row[0] == '🍀':
                    return 200
                elif row[0] == '⭐':
                    return 100
        return 0

    def _build_board(self) -> str:
        lines = []
        for r in range(3):
            row_str = ' '.join(self.grid[r][c] if self.revealed[r][c] else '❓' for c in range(3))
            lines.append(row_str)
        return '\n'.join(lines)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="🎰 刮刮乐 — 已过期 / Expired",
            description="超时未翻开全部格子 / Timed out.",
            color=0x95A5A6,
        )
        try:
            if self.message:
                await self.message.edit(embed=embed, view=self)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
# 🎡 俄罗斯轮盘 / Russian Roulette
# ══════════════════════════════════════════════════════════════

class RouletteView(discord.ui.View):
    """View for placing bets on roulette."""

    def __init__(self, user_id: str, user_name: str, bet: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.user_name = user_name
        self.bet = bet

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "Not your game / 这不是你的游戏", ephemeral=True
            )
            return False
        return True

    async def _play_round(self, interaction: discord.Interaction, label: str,
                          win_condition, odds: int, desc_detail: str):
        """Generic roulette play."""
        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            pass

        number = random.randint(1, 36)
        if number % 2 == 0:
            color = "🔴"  # Red for even
        else:
            color = "⚫"  # Black for odd

        from utils.animations import roulette_spin_animation
        await roulette_spin_animation(interaction, number, color)

        if win_condition(number, color):
            profit = self.bet * odds
            add_coins(self.user_id, profit, f"轮盘{label} / Roulette {label} win x{odds}")
            bal = get_balance(self.user_id)
            embed = discord.Embed(
                title="🎡 轮盘 / Roulette",
                description=(
                    f"🎯 结果 / Result: {color} **{number}**\n"
                    f"🎲 你的选择 / Your bet: **{desc_detail}**\n\n"
                    f"# 💰 中奖！/ You Win!\n"
                    f"🪙 +{profit:,}  |  余额 / Balance: **{bal:,}**"
                ),
                color=0x2ECC71,
            )
        else:
            bal = get_balance(self.user_id)
            embed = discord.Embed(
                title="🎡 轮盘 / Roulette",
                description=(
                    f"🎯 结果 / Result: {color} **{number}**\n"
                    f"🎲 你的选择 / Your bet: **{desc_detail}**\n\n"
                    f"# 😢 未中奖 / No Win\n"
                    f"余额 / Balance: **{bal:,}**"
                ),
                color=0xE74C3C,
            )

        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="🔴 红 / Red (2x)", style=discord.ButtonStyle.danger, row=0)
    async def red_btn(self, interaction: discord.Interaction, button):
        def cond(n, c): return c == "🔴"
        await self._play_round(interaction, "Red", cond, 2, "🔴 红 Red")

    @discord.ui.button(label="⚫ 黑 / Black (2x)", style=discord.ButtonStyle.secondary, row=0)
    async def black_btn(self, interaction: discord.Interaction, button):
        def cond(n, c): return c == "⚫"
        await self._play_round(interaction, "Black", cond, 2, "⚫ 黑 Black")

    @discord.ui.button(label="🔢 奇数 / Odd (2x)", style=discord.ButtonStyle.primary, row=0)
    async def odd_btn(self, interaction: discord.Interaction, button):
        def cond(n, c): return n % 2 == 1
        await self._play_round(interaction, "Odd", cond, 2, "🔢 奇数 Odd")

    @discord.ui.button(label="🔢 偶数 / Even (2x)", style=discord.ButtonStyle.primary, row=0)
    async def even_btn(self, interaction: discord.Interaction, button):
        def cond(n, c): return n % 2 == 0
        await self._play_round(interaction, "Even", cond, 2, "🔢 偶数 Even")

    @discord.ui.button(label="🎯 单数字 / Single (36x)", style=discord.ButtonStyle.success, row=1,
                       custom_id="roulette_single")
    async def single_btn(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(RouletteNumberModal(self))


class RouletteNumberModal(discord.ui.Modal, title="选择数字 / Pick Number (1-36)"):
    """Modal for single number roulette bet."""
    number_input = discord.ui.TextInput(
        label="Number / 数字 (1-36)",
        placeholder="Enter a number 1-36",
        max_length=2,
    )

    def __init__(self, view: RouletteView):
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            num = int(self.number_input.value)
        except ValueError:
            return await interaction.response.send_message(
                "请输入数字 1-36 / Please enter a number 1-36.", ephemeral=True)
        if num < 1 or num > 36:
            return await interaction.response.send_message(
                "请输入数字 1-36 / Please enter a number 1-36.", ephemeral=True)

        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            pass

        result = random.randint(1, 36)
        color = "🔴" if result % 2 == 0 else "⚫"

        from utils.animations import roulette_spin_animation
        await roulette_spin_animation(interaction, result, color)

        uid = self._view.user_id
        if result == num:
            profit = self._view.bet * 36
            add_coins(uid, profit, f"轮盘单数字 / Roulette single {num} win x36")
            bal = get_balance(uid)
            embed = discord.Embed(
                title="🎡 轮盘 / Roulette — 单数字",
                description=(
                    f"🎯 结果 / Result: {color} **{result}**\n"
                    f"🎲 你的数字 / Your number: **{num}**\n\n"
                    f"# 💰 中奖！/ Jackpot!\n"
                    f"🪙 +{profit:,}  |  余额 / Balance: **{bal:,}**"
                ),
                color=0xF1C40F,
            )
        else:
            bal = get_balance(uid)
            embed = discord.Embed(
                title="🎡 轮盘 / Roulette — 单数字",
                description=(
                    f"🎯 结果 / Result: {color} **{result}**\n"
                    f"🎲 你的数字 / Your number: **{num}**\n\n"
                    f"# 😢 未中奖 / No Win\n"
                    f"余额 / Balance: **{bal:,}**"
                ),
                color=0xE74C3C,
            )

        for child in self._view.children:
            child.disabled = True
        await interaction.edit_original_response(embed=embed, view=self._view)


# ══════════════════════════════════════════════════════════════
# 📈 比大小 / High/Low
# ══════════════════════════════════════════════════════════════

class HighLowView(discord.ui.View):
    def __init__(self, user_id: str, bet: int, card1: tuple):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.bet = bet
        self.card1 = card1  # (rank, suit)
        self.card2 = None

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "Not your game / 这不是你的游戏", ephemeral=True
            )
            return False
        return True

    def _format_card(self, card: tuple) -> str:
        if card is None:
            return "🂠 ?"
        return f"{card[0]}{card[1]}"

    def _card_value(self, card: tuple) -> int:
        rank_map = {str(i): i for i in range(2, 11)}
        rank_map.update({'J': 11, 'Q': 12, 'K': 13, 'A': 14})
        return rank_map.get(card[0], 0)

    async def _do_result(self, interaction: discord.Interaction, guessed_high: bool):
        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            pass

        suits = ['♠', '♥', '♦', '♣']
        ranks_list = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']

        # Deal card2 (different from card1)
        while True:
            self.card2 = (random.choice(ranks_list), random.choice(suits))
            if self.card2 != self.card1:
                break

        # Animate flip
        from utils.animations import card_flip_animation
        await card_flip_animation(
            interaction,
            self._format_card(self.card2),
            "📈 比大小 / High & Low",
        )

        v1 = self._card_value(self.card1)
        v2 = self._card_value(self.card2)
        actual_high = v2 > v1
        is_tie = v1 == v2
        uid = self.user_id

        if is_tie:
            add_coins(uid, self.bet, "比大小平局退款 / HighLow tie refund")
            bal = get_balance(uid)
            embed = discord.Embed(
                title="📈 比大小 / High & Low",
                description=(
                    f"你的牌 / Your card: **{self._format_card(self.card1)}**\n"
                    f"对手牌 / Opponent: **{self._format_card(self.card2)}**\n\n"
                    f"# 🤝 平局！/ Tie!\n"
                    f"下注退还 / Bet refunded: 🪙 {self.bet:,}\n"
                    f"余额 / Balance: **{bal:,}**"
                ),
                color=0xF1C40F,
            )
        elif guessed_high == actual_high:
            profit = self.bet * 2
            add_coins(uid, profit, "比大小获胜 / HighLow win")
            bal = get_balance(uid)
            embed = discord.Embed(
                title="📈 比大小 / High & Low",
                description=(
                    f"你的牌 / Your card: **{self._format_card(self.card1)}**\n"
                    f"对手牌 / Opponent: **{self._format_card(self.card2)}**\n\n"
                    f"# 🎉 猜对了！/ You Win!\n"
                    f"🪙 +{profit:,}  |  余额 / Balance: **{bal:,}**"
                ),
                color=0x2ECC71,
            )
        else:
            bal = get_balance(uid)
            embed = discord.Embed(
                title="📈 比大小 / High & Low",
                description=(
                    f"你的牌 / Your card: **{self._format_card(self.card1)}**\n"
                    f"对手牌 / Opponent: **{self._format_card(self.card2)}**\n\n"
                    f"# ❌ 猜错了 / Wrong!\n"
                    f"余额 / Balance: **{bal:,}**"
                ),
                color=0xE74C3C,
            )

        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="📈 更大 / Higher", style=discord.ButtonStyle.success)
    async def higher_btn(self, interaction: discord.Interaction, button):
        await self._do_result(interaction, True)

    @discord.ui.button(label="📉 更小 / Lower", style=discord.ButtonStyle.danger)
    async def lower_btn(self, interaction: discord.Interaction, button):
        await self._do_result(interaction, False)


# ══════════════════════════════════════════════════════════════
# 🔢 猜数字 / Number Guessing
# ══════════════════════════════════════════════════════════════

class NumberGuessView(discord.ui.View):
    def __init__(self, user_id: str, bet: int, secret: int):
        super().__init__(timeout=90)
        self.user_id = user_id
        self.bet = bet
        self.secret = secret
        self.attempts = 0
        self.max_attempts = 5

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "Not your game / 这不是你的游戏", ephemeral=True
            )
            return False
        return True

    def _calc_payout(self, diff: int) -> float:
        """Payout multiplier based on closeness: """
        if diff == 0:
            return 10.0
        elif diff <= 3:
            return 5.0
        elif diff <= 10:
            return 2.0
        else:
            return 0.0

    def _build_embed(self, text: str, guess: int | None, color: int) -> discord.Embed:
        remaining = self.max_attempts - self.attempts
        embed = discord.Embed(
            title="🔢 猜数字 / Number Guessing (1-100)",
            description=(
                f"猜一个 1-100 之间的数字 / Guess a number 1-100\n"
                f"剩 {remaining} 次机会 / {remaining} chances left\n\n{text}"
            ),
            color=color,
        )
        if guess is not None:
            embed.set_footer(text=f"上次猜 / Last guess: {guess}")
        return embed

    @discord.ui.button(label="输入猜数 / Enter Guess", style=discord.ButtonStyle.primary, emoji="🔢")
    async def guess_btn(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(NumberGuessModal(self))

    async def on_timeout(self):
        # Player didn't guess — lose
        for child in self.children:
            child.disabled = True
        embed = discord.Embed(
            title="🔢 猜数字 — 超时 / Timed Out",
            description=f"目标数字是: **{self.secret}**\nThe number was: **{self.secret}**",
            color=0x95A5A6,
        )
        try:
            if self.message:
                await self.message.edit(embed=embed, view=self)
        except Exception:
            pass


class NumberGuessModal(discord.ui.Modal, title="猜数字 / Number Guessing"):
    guess_input = discord.ui.TextInput(
        label="Your guess / 你的猜测 (1-100)",
        placeholder="1-100",
        max_length=3,
    )

    def __init__(self, view: NumberGuessView):
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guess = int(self.guess_input.value)
        except ValueError:
            return await interaction.response.send_message(
                "请输入 1-100 的数字 / Please enter 1-100.", ephemeral=True)
        if guess < 1 or guess > 100:
            return await interaction.response.send_message(
                "请输入 1-100 的数字 / Please enter 1-100.", ephemeral=True)

        self._view.attempts += 1
        attempt = self._view.attempts
        diff = abs(guess - self._view.secret)
        multiplier = self._view._calc_payout(diff)

        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            pass

        # Reveal animation
        from utils.animations import number_reveal_animation

        uid = self._view.user_id

        if multiplier > 0:
            profit = int(self._view.bet * multiplier)
            add_coins(uid, profit, f"猜数字获胜 x{multiplier} / NumberGuess win")
            bal = get_balance(uid)
            await number_reveal_animation(interaction, self._view.secret)
            embed = discord.Embed(
                title="🔢 猜数字 / Number Guessing",
                description=(
                    f"你的猜测 / Your guess: **{guess}**\n"
                    f"目标数字 / Answer: **{self._view.secret}**\n"
                    f"差距 / Difference: **{diff}**\n\n"
                    f"# 🎉 猜中了！/ Win! (x{multiplier})\n"
                    f"🪙 +{profit:,}  |  余额 / Balance: **{bal:,}**"
                ),
                color=0x2ECC71,
            )
            for child in self._view.children:
                child.disabled = True
            await interaction.edit_original_response(embed=embed, view=self._view)
        elif attempt >= self._view.max_attempts:
            # No more attempts — reveal and lose
            await number_reveal_animation(interaction, self._view.secret)
            bal = get_balance(uid)
            embed = discord.Embed(
                title="🔢 猜数字 / Number Guessing",
                description=(
                    f"你的猜测 / Your guess: **{guess}**\n"
                    f"目标数字 / Answer: **{self._view.secret}**\n"
                    f"差距 / Difference: **{diff}**\n\n"
                    f"# ❌ 机会用完！/ Out of chances!\n"
                    f"余额 / Balance: **{bal:,}**"
                ),
                color=0xE74C3C,
            )
            for child in self._view.children:
                child.disabled = True
            await interaction.edit_original_response(embed=embed, view=self._view)
        else:
            # Still have chances — give hint
            hint = "⬆️ 太小了！/ Too low!" if guess < self._view.secret else "⬇️ 太大了！/ Too high!"
            remaining = self._view.max_attempts - attempt
            embed = discord.Embed(
                title="🔢 猜数字 / Number Guessing",
                description=(
                    f"你的猜测 / Your guess: **{guess}**\n"
                    f"提示 / Hint: {hint}\n"
                    f"剩 {remaining} 次机会 / {remaining} chances left"
                ),
                color=0x3498DB,
            )
            embed.set_footer(text=f"第 {attempt}/{self._view.max_attempts} 次 / Attempt {attempt}/{self._view.max_attempts}")
            await interaction.edit_original_response(embed=embed, view=self._view)


# ══════════════════════════════════════════════════════════════
# 🎰 老虎机 / Slot Machine (Task D)
# ══════════════════════════════════════════════════════════════

SLOT_EMOJI_LIST = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣", "⭐"]


class SlotView(discord.ui.View):
    """Slot machine game: 3 reels with spin button."""

    def __init__(self, user_id: str, user_name: str, bet: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.user_name = user_name
        self.bet = bet
        self.spinning = False

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "Not your game / 这不是你的游戏", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🎰 Spin! 旋转！", style=discord.ButtonStyle.primary, row=0)
    async def spin_btn(self, interaction: discord.Interaction, button):
        if self.spinning:
            return await interaction.response.send_message(
                "Already spinning! / 正在旋转中！", ephemeral=True)

        self.spinning = True
        button.disabled = True
        await interaction.response.edit_message(view=self)

        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            pass

        # Roll 3 reels
        c1 = random.choice(SLOT_EMOJI_LIST)
        c2 = random.choice(SLOT_EMOJI_LIST)
        c3 = random.choice(SLOT_EMOJI_LIST)

        from utils.animations import slot_spin_animation
        await slot_spin_animation(interaction, [c1, c2, c3])

        uid = self.user_id

        # Payout logic
        if c1 == c2 == c3:
            multiplier = 10
            profit = self.bet * multiplier
            add_coins(uid, profit, f"老虎机三连 x{multiplier} / Slot triple match")
            result_text = f"🎉 三连！/ TRIPLE! x{multiplier}"
            color = 0xF1C40F
        elif c1 == c2 or c2 == c3 or c1 == c3:
            multiplier = 3
            profit = self.bet * multiplier
            add_coins(uid, profit, f"老虎机双连 x{multiplier} / Slot double match")
            result_text = f"✨ 双连！/ DOUBLE! x{multiplier}"
            color = 0x2ECC71
        else:
            profit = 0
            result_text = "😢 没有匹配 / No match"
            color = 0xE74C3C

        bal = get_balance(uid)
        embed = discord.Embed(
            title="🎰 老虎机 / Slot Machine",
            description=(
                f"| {c1} | {c2} | {c3} |\n\n"
                f"# {result_text}\n"
                f"下注 / Bet: 🪙 {self.bet:,}\n"
                f"奖金 / Payout: 🪙 {profit:,}\n"
                f"余额 / Balance: **{bal:,}**"
            ),
            color=color,
        )
        await interaction.edit_original_response(embed=embed, view=self)


# ══════════════════════════════════════════════════════════════
# 🎲 掷骰子 / Dice Roll (Task D)
# ══════════════════════════════════════════════════════════════

class DiceRollView(discord.ui.View):
    """Dice roll betting: guess Big/Small or exact number."""

    def __init__(self, user_id: str, user_name: str, bet: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.user_name = user_name
        self.bet = bet

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "Not your game / 这不是你的游戏", ephemeral=True)
            return False
        return True

    async def _do_roll(self, interaction: discord.Interaction, guess: str, number: int = 0):
        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            pass

        d1 = random.randint(1, 6)
        d2 = random.randint(1, 6)
        total = d1 + d2
        is_big = total >= 8
        is_small = total <= 6
        is_seven = total == 7

        from utils.animations import dice_roll_animation
        await dice_roll_animation(interaction, d1, d2)

        uid = self.user_id

        if guess == "seven" and is_seven:
            profit = self.bet * 3
            add_coins(uid, profit, "掷骰子猜中7点 / Dice roll win (7)")
            result = f"🎯 猜中7点！x3!"
            color = 0xF1C40F
        elif guess == "number" and total == number:
            profit = self.bet * 5
            add_coins(uid, profit, f"掷骰子猜中数字{number} / Dice roll exact {number}")
            result = f"🎯 猜中精确数字 {number}！x5!"
            color = 0xF1C40F
        elif guess == "big" and is_big:
            profit = self.bet * 2
            add_coins(uid, profit, "掷骰子猜大赢 / Dice roll win (Big)")
            result = "📈 开大！猜中!"
            color = 0x2ECC71
        elif guess == "small" and is_small:
            profit = self.bet * 2
            add_coins(uid, profit, "掷骰子猜小赢 / Dice roll win (Small)")
            result = "📉 开小！猜中!"
            color = 0x2ECC71
        elif guess == "number" and total != number and number > 0:
            profit = 0
            result = f"❌ 没猜中 {number}，实际 {total}"
            color = 0xE74C3C
        else:
            profit = 0
            result = f"❌ 猜错了！实际 {total}"
            color = 0xE74C3C

        bal = get_balance(uid)
        size_label = "大 Big" if is_big else ("小 Small" if is_small else "7点 Seven")
        embed = discord.Embed(
            title="🎲 掷骰子 / Dice Roll",
            description=(
                f"🎲 结果 / Result: **{d1} + {d2} = {total}** ({size_label})\n\n"
                f"# {result}\n"
                f"下注 / Bet: 🪙 {self.bet:,}\n"
                f"奖金 / Payout: 🪙 {profit:,}\n"
                f"余额 / Balance: **{bal:,}**"
            ),
            color=color,
        )
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="🔺 Big 大 (8-12)", style=discord.ButtonStyle.success, row=0)
    async def big_btn(self, interaction: discord.Interaction, button):
        await self._do_roll(interaction, "big")

    @discord.ui.button(label="🔻 Small 小 (2-6)", style=discord.ButtonStyle.danger, row=0)
    async def small_btn(self, interaction: discord.Interaction, button):
        await self._do_roll(interaction, "small")

    @discord.ui.button(label="🎯 猜具体数字 (x5)", style=discord.ButtonStyle.primary, row=0)
    async def number_btn(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(DiceNumberModal(self))

    @discord.ui.button(label="🎲 押7点 (x3)", style=discord.ButtonStyle.secondary, row=0)
    async def seven_btn(self, interaction: discord.Interaction, button):
        await self._do_roll(interaction, "seven")


class DiceNumberModal(discord.ui.Modal, title="猜具体数字 / Pick Number (2-12)"):
    number_input = discord.ui.TextInput(
        label="数字 / Number (2-12)",
        placeholder="Enter 2-12",
        max_length=2,
    )

    def __init__(self, view: DiceRollView):
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            num = int(self.number_input.value)
        except ValueError:
            return await interaction.response.send_message(
                "请输入数字 2-12 / Please enter 2-12.", ephemeral=True)
        if num < 2 or num > 12:
            return await interaction.response.send_message(
                "请输入数字 2-12 / Please enter 2-12.", ephemeral=True)
        await self._view._do_roll(interaction, "number", num)


# ══════════════════════════════════════════════════════════════
# 🪙 硬币翻转 / Coin Flip (Task D)
# ══════════════════════════════════════════════════════════════

class CoinFlipView(discord.ui.View):
    """Coin flip: guess heads or tails, 1:1 payout."""

    def __init__(self, user_id: str, user_name: str, bet: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.user_name = user_name
        self.bet = bet

    async def _interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "Not your game / 这不是你的游戏", ephemeral=True)
            return False
        return True

    async def _do_flip(self, interaction: discord.Interaction, guess: str):
        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            pass

        result = random.choice(["heads", "tails"])
        from utils.animations import coin_flip_animation
        await coin_flip_animation(interaction, result)

        uid = self.user_id
        if guess == result:
            profit = self.bet * 2
            add_coins(uid, profit, "硬币翻转猜中 / Coin flip win")
            result_text = f"🎉 猜中了！/ Correct! +{profit:,}"
            color = 0x2ECC71
        else:
            profit = 0
            result_text = "❌ 猜错了！/ Wrong!"
            color = 0xE74C3C

        bal = get_balance(uid)
        result_label = "🪙 正面 Heads!" if result == "heads" else "🪙 反面 Tails!"
        embed = discord.Embed(
            title="🪙 硬币翻转 / Coin Flip",
            description=(
                f"结果 / Result: **{result_label}**\n"
                f"你的选择 / Your guess: **{'正面 Heads' if guess == 'heads' else '反面 Tails'}**\n\n"
                f"# {result_text}\n"
                f"下注 / Bet: 🪙 {self.bet:,}\n"
                f"余额 / Balance: **{bal:,}**"
            ),
            color=color,
        )
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="🪙 Heads 正面", style=discord.ButtonStyle.primary, row=0)
    async def heads_btn(self, interaction: discord.Interaction, button):
        await self._do_flip(interaction, "heads")

    @discord.ui.button(label="🪙 Tails 反面", style=discord.ButtonStyle.secondary, row=0)
    async def tails_btn(self, interaction: discord.Interaction, button):
        await self._do_flip(interaction, "tails")


# ══════════════════════════════════════════════════════════════
# GamblingLobbyView — Unified gambling lobby for MMORPG Main Panel
# ══════════════════════════════════════════════════════════════
class GamblingLobbyView(discord.ui.View):
    """Lobby panel for all gambling games. Players enter via slash commands."""
    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=None)
        self.uid = uid
        self.main_view = main_view

    @discord.ui.button(label="Roulette 轮盘赌", emoji="🎡", style=discord.ButtonStyle.primary, row=0)
    async def roulette_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.uid)
        await interaction.response.send_message(
            f"🎡 **轮盘赌 Roulette**\n"
            f"余额 / Balance: 🪙 **{bal:,}**\n\n"
            f"使用 `/gmpt-gamble roulette <bet>` 开始游戏！\n"
            f"Use `/gmpt-gamble roulette <bet>` to start!\n\n"
            f"赔率 / Odds: 🔴红/⚫黑 2x | 🔢奇/偶 2x | 🎯单数字 36x",
            ephemeral=True)

    @discord.ui.button(label="Slot 老虎机", emoji="🎰", style=discord.ButtonStyle.primary, row=0)
    async def slot_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.uid)
        await interaction.response.send_message(
            f"🎰 **老虎机 Slot Machine**\n"
            f"余额 / Balance: 🪙 **{bal:,}**\n\n"
            f"使用 `/gmpt-gamble slot <bet>` 开始游戏！\n"
            f"Use `/gmpt-gamble slot <bet>` to start!\n\n"
            f"赔率 / Odds: 三连 10x | 双连 3x",
            ephemeral=True)

    @discord.ui.button(label="Dice 掷骰子", emoji="🎲", style=discord.ButtonStyle.primary, row=0)
    async def dice_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.uid)
        await interaction.response.send_message(
            f"🎲 **掷骰子 Dice Roll**\n"
            f"余额 / Balance: 🪙 **{bal:,}**\n\n"
            f"使用 `/gmpt-gamble dice <bet>` 开始游戏！\n"
            f"Use `/gmpt-gamble dice <bet>` to start!\n\n"
            f"赔率 / Odds: 大小 2x | 7点 3x | 精确数字 5x",
            ephemeral=True)

    @discord.ui.button(label="Coin 硬币翻转", emoji="🪙", style=discord.ButtonStyle.primary, row=1)
    async def coin_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.uid)
        await interaction.response.send_message(
            f"🪙 **硬币翻转 Coin Flip**\n"
            f"余额 / Balance: 🪙 **{bal:,}**\n\n"
            f"使用 `/gmpt-gamble coinflip <bet>` 开始游戏！\n"
            f"Use `/gmpt-gamble coinflip <bet>` to start!\n\n"
            f"赔率 / Odds: 1:1",
            ephemeral=True)

    @discord.ui.button(label="Crash 爆爆乐", emoji="💥", style=discord.ButtonStyle.danger, row=1)
    async def crash_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.uid)
        await interaction.response.send_message(
            f"💥 **Crash 爆爆乐**\n"
            f"余额 / Balance: 🪙 **{bal:,}**\n\n"
            f"使用 `/gmpt-gamble crash <bet>` 开始游戏！\n"
            f"Use `/gmpt-gamble crash <bet>` to start!\n\n"
            f"在崩盘前提现！Cash out before it crashes!",
            ephemeral=True)

    @discord.ui.button(label="Scratch 刮刮乐", emoji="💳", style=discord.ButtonStyle.success, row=1)
    async def scratch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.uid)
        await interaction.response.send_message(
            f"💳 **Scratch Card 刮刮乐 (50G)**\n"
            f"余额 / Balance: 🪙 **{bal:,}**\n\n"
            f"使用 `/gmpt-gamble scratch` 刮一张！\n"
            f"Use `/gmpt-gamble scratch` to play!\n\n"
            f"奖池 / Prizes: 💎x3=500 | 🍀x3=200 | ⭐x3=100",
            ephemeral=True)

    @discord.ui.button(label="High-Low 比大小", emoji="🔺", style=discord.ButtonStyle.secondary, row=2)
    async def highlow_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.uid)
        await interaction.response.send_message(
            f"🔺 **High-Low 比大小**\n"
            f"余额 / Balance: 🪙 **{bal:,}**\n\n"
            f"使用 `/gmpt-gamble highlow <bet>` 开始游戏！\n"
            f"Use `/gmpt-gamble highlow <bet>` to start!\n\n"
            f"赔率 / Odds: 猜中 2x | 平局退本",
            ephemeral=True)

    @discord.ui.button(label="Guess 猜数字", emoji="🎯", style=discord.ButtonStyle.secondary, row=2)
    async def guess_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.uid)
        await interaction.response.send_message(
            f"🎯 **Number Guess 猜数字**\n"
            f"余额 / Balance: 🪙 **{bal:,}**\n\n"
            f"使用 `/gmpt-gamble guess <bet>` 开始游戏！\n"
            f"Use `/gmpt-gamble guess <bet>` to start!\n\n"
            f"赔率 / Odds: 完全猜中 10x | 差≤3 5x | 差≤10 2x",
            ephemeral=True)

    @discord.ui.button(label="Dice Duel 骰子对决", emoji="⚔️", style=discord.ButtonStyle.secondary, row=2)
    async def duel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        bal = get_balance(self.uid)
        await interaction.response.send_message(
            f"⚔️ **Dice Duel 骰子对决**\n"
            f"余额 / Balance: 🪙 **{bal:,}**\n\n"
            f"使用 `/gmpt-gamble diceduel <opponent> <bet>` 发起对决！\n"
            f"Use `/gmpt-gamble diceduel <opponent> <bet>` to challenge!",
            ephemeral=True)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.danger, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.followup.edit_message(embed=embed, view=self.main_view)
        else:
            embed = discord.Embed(title="Back", description="Main panel not available.", color=0xFF0000)
            await interaction.response.edit_message(embed=embed, view=None)


async def setup(bot):
    await bot.add_cog(Gambling(bot))
