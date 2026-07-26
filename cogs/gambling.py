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
    # /gmpt-scratch — 刮刮乐
    # ══════════════════════════════════════════════════════════
    @gmpt_gamble_group.command(name="scratch", description="🎰 刮刮乐 / Scratch card (50 coins)")
    @app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
    async def scratch_cmd(self, interaction: discord.Interaction):
        """刮刮乐."""
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
        await interaction.response.edit_message(embed=embed, view=self)

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
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.response.defer()

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


async def setup(bot):
    await bot.add_cog(Gambling(bot))
