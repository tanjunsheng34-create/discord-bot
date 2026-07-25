"""
GMPT Bot — Casino Games (Blackjack, Tic Tac Toe, Horse Race)
Bilingual (中文 / English)
"""
import asyncio
import random
import discord
import logging
from discord import app_commands
from discord.ext import commands
from database import get_db, get_db_ctx
from utils.cog_base import CogBase
from cogs.economy import get_balance, add_coins

logger = logging.getLogger(__name__)

# ── 辅助函数 ──
def _format_coins(amount: int) -> str:
    return f"🪙 {amount:,}"


# ══════════════════════════════════════════════════════════════
# 🃏 21点 / Blackjack
# ══════════════════════════════════════════════════════════════

class BlackjackView(discord.ui.View):
    """21点交互按钮视图 / Blackjack interactive button view."""

    def __init__(self, player_id: str, player_name: str, bet: int, deck: list):
        super().__init__(timeout=60)
        self.player_id = player_id
        self.player_name = player_name
        self.bet = bet
        self.deck = deck
        self.finished = False

        self.player_hand = [self._draw(), self._draw()]
        self.dealer_hand = [self._draw(), self._draw()]

        self.player_blackjack = self._hand_value(self.player_hand) == 21
        self.dealer_blackjack = self._hand_value(self.dealer_hand) == 21

    def _draw(self):
        if not self.deck:
            suits = ['♠', '♥', '♦', '♣']
            ranks = ['A','2','3','4','5','6','7','8','9','10','J','Q','K']
            self.deck = [(r, s) for s in suits for r in ranks]
            random.shuffle(self.deck)
        return self.deck.pop()

    def _hand_value(self, hand):
        total = 0
        aces = 0
        for rank, _ in hand:
            if rank in ['J','Q','K']:
                total += 10
            elif rank == 'A':
                aces += 1
                total += 11
            else:
                total += int(rank)
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1
        return total

    def _hand_str(self, hand, hide_second=False):
        if hide_second:
            return f"{hand[0][0]}{hand[0][1]} ??"
        return ' '.join(f"{r}{s}" for r, s in hand)

    async def _build_embed(self, show_dealer=False):
        pv = self._hand_value(self.player_hand)
        embed = discord.Embed(
            title="🃏 21点 / Blackjack",
            color=0x1ABC9C,
        )
        if show_dealer:
            dv = self._hand_value(self.dealer_hand)
            embed.add_field(
                name=f"🏦 庄家 / Dealer — {dv}点",
                value=self._hand_str(self.dealer_hand),
                inline=False,
            )
        else:
            embed.add_field(
                name="🏦 庄家 / Dealer — ?点",
                value=self._hand_str(self.dealer_hand, hide_second=True),
                inline=False,
            )
        embed.add_field(
            name=f"👤 你 / You ({self.player_name}) — {pv}点",
            value=self._hand_str(self.player_hand),
            inline=False,
        )
        embed.add_field(name="赌注 / Bet", value=f"🪙 {self.bet:,}", inline=True)
        embed.set_footer(text="GMPT Casino — 21点 Blackjack")
        return embed

    @discord.ui.button(label="🃏 Hit 要牌", style=discord.ButtonStyle.primary)
    async def hit_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.player_id:
            return await interaction.response.send_message("不是你的牌局 / Not your game!", ephemeral=True)
        if self.finished:
            return await interaction.response.send_message("牌局已结束 / Game over.", ephemeral=True)

        self.player_hand.append(self._draw())
        pv = self._hand_value(self.player_hand)

        if pv > 21:
            self.finished = True
            uid = self.player_id
            bal = get_balance(uid)
            embed = await self._build_embed(show_dealer=True)
            embed.color = 0xE74C3C
            embed.add_field(name="结果 / Result", value=f"💥 爆牌 / Bust! 🪙 -{self.bet:,}", inline=False)
            embed.add_field(name="余额 / Balance", value=f"🪙 {bal:,}", inline=True)
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=embed, view=self)
        elif pv == 21:
            await self._stand(interaction)
        else:
            embed = await self._build_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✋ Stand 停牌", style=discord.ButtonStyle.secondary)
    async def stand_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.player_id:
            return await interaction.response.send_message("不是你的牌局 / Not your game!", ephemeral=True)
        if self.finished:
            return await interaction.response.send_message("牌局已结束 / Game over.", ephemeral=True)
        await self._stand(interaction)

    @discord.ui.button(label="⬇️ Double 双倍", style=discord.ButtonStyle.success)
    async def double_btn(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.player_id:
            return await interaction.response.send_message("不是你的牌局 / Not your game!", ephemeral=True)
        if self.finished:
            return await interaction.response.send_message("牌局已结束 / Game over.", ephemeral=True)
        if len(self.player_hand) != 2:
            return await interaction.response.send_message("只能在首轮双倍 / Double only on first turn!", ephemeral=True)

        uid = self.player_id
        bal = get_balance(uid)
        if bal < self.bet:
            return await interaction.response.send_message(f"金币不足！需要 {self.bet:,} / Not enough coins!", ephemeral=True)

        add_coins(uid, -self.bet, "21点双倍追加 / Blackjack double down")
        self.bet *= 2
        self.player_hand.append(self._draw())
        pv = self._hand_value(self.player_hand)

        if pv > 21:
            self.finished = True
            bal2 = get_balance(uid)
            embed = await self._build_embed(show_dealer=True)
            embed.color = 0xE74C3C
            embed.add_field(name="结果 / Result", value=f"💥 爆牌 / Bust! 🪙 -{self.bet:,}", inline=False)
            embed.add_field(name="余额 / Balance", value=f"🪙 {bal2:,}", inline=True)
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await self._stand(interaction)

    async def _stand(self, interaction):
        if self.finished:
            return
        self.finished = True
        uid = self.player_id

        while self._hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self._draw())

        pv = self._hand_value(self.player_hand)
        dv = self._hand_value(self.dealer_hand)

        embed = await self._build_embed(show_dealer=True)

        is_blackjack = len(self.player_hand) == 2 and pv == 21

        if dv > 21 or pv > dv:
            if is_blackjack:
                profit = int(self.bet * 1.5)
                reason = "21点Blackjack获胜 / Blackjack win"
            else:
                profit = self.bet
                reason = "21点获胜 / Blackjack win"
            add_coins(uid, profit, reason)
            embed.color = 0x2ECC71
            embed.add_field(name="结果 / Result", value=f"🎉 你赢了 / You Win! 🪙 +{profit:,}", inline=False)
        elif pv == dv:
            add_coins(uid, self.bet, "21点平局 / Blackjack push")  # Return bet
            embed.color = 0xF1C40F
            embed.add_field(name="结果 / Result", value=f"🤝 平局 / Push! 🪙 0 (已退还/refunded)", inline=False)
        else:
            embed.color = 0xE74C3C
            embed.add_field(name="结果 / Result", value=f"😢 庄家赢 / Dealer Wins! 🪙 -{self.bet:,}", inline=False)

        bal = get_balance(uid)
        embed.add_field(name="余额 / Balance", value=f"🪙 {bal:,}", inline=True)

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if not self.finished:
            self.finished = True
            uid = self.player_id
            while self._hand_value(self.dealer_hand) < 17:
                self.dealer_hand.append(self._draw())
            pv = self._hand_value(self.player_hand)
            dv = self._hand_value(self.dealer_hand)
            if dv > 21 or pv > dv:
                profit = self.bet
                add_coins(uid, profit, "21点超时获胜 / Blackjack timeout win")
            elif pv == dv:
                add_coins(uid, self.bet, "21点超时平局 / Blackjack timeout push")
            for child in self.children:
                child.disabled = True
            if self.message:
                embed = await self._build_embed(show_dealer=True)
                embed.set_footer(text="⏰ 超时 / Timed out")
                try:
                    await self.message.edit(embed=embed, view=self)
                except Exception:
                    pass


# ══════════════════════════════════════════════════════════════
# ❌⭕ 井字棋 / Tic Tac Toe
# ══════════════════════════════════════════════════════════════

class TicTacToeView(discord.ui.View):
    """井字棋 3x3 按钮棋盘 / Tic Tac Toe interactive board."""

    def __init__(self, player_x_id: str, player_x_name: str, player_o_id: str, player_o_name: str):
        super().__init__(timeout=90)
        self.player_x_id = player_x_id
        self.player_x_name = player_x_name
        self.player_o_id = player_o_id
        self.player_o_name = player_o_name
        self.board = [['', '', ''], ['', '', ''], ['', '', '']]
        self.current_turn = player_x_id
        self.current_mark = 'X'
        self.finished = False
        self.move_task = None

        for r in range(3):
            for c in range(3):
                btn = discord.ui.Button(
                    label='\u200b',
                    style=discord.ButtonStyle.secondary,
                    row=r,
                    custom_id=f"ttt_{r}_{c}"
                )
                btn.callback = self.make_cell_callback(r, c)
                self.add_item(btn)

    def _current_player_name(self):
        return self.player_x_name if self.current_turn == self.player_x_id else self.player_o_name

    def _other_player_name(self):
        return self.player_o_name if self.current_turn == self.player_x_id else self.player_x_name

    def _check_winner(self):
        b = self.board
        for r in range(3):
            if b[r][0] == b[r][1] == b[r][2] != '':
                return b[r][0]
        for c in range(3):
            if b[0][c] == b[1][c] == b[2][c] != '':
                return b[0][c]
        if b[0][0] == b[1][1] == b[2][2] != '':
            return b[0][0]
        if b[0][2] == b[1][1] == b[2][0] != '':
            return b[0][2]
        return None

    def _is_draw(self):
        return all(self.board[r][c] != '' for r in range(3) for c in range(3))

    def _build_embed(self):
        board_str = ""
        for r in range(3):
            row = [self.board[r][c] if self.board[r][c] else '·' for c in range(3)]
            board_str += ' | '.join(row) + '\n'
            if r < 2:
                board_str += '──┼───┼──\n'

        current_name = self._current_player_name()
        current_mark = self.current_mark

        embed = discord.Embed(
            title="❌⭕ 井字棋 / Tic Tac Toe",
            description=f"```\n{board_str}```\n**轮到 / Turn:** {current_name} ({current_mark})",
            color=0x9B59B6,
        )
        embed.add_field(name="❌ X", value=self.player_x_name, inline=True)
        embed.add_field(name="⭕ O", value=self.player_o_name, inline=True)
        embed.set_footer(text="15秒内落子 / 15s per move")
        return embed

    def make_cell_callback(self, r, c):
        async def inner(interaction: discord.Interaction):
            uid = str(interaction.user.id)

            if self.finished:
                return await interaction.response.send_message("游戏已结束 / Game over.", ephemeral=True)
            if uid != self.current_turn:
                return await interaction.response.send_message("还没轮到你 / Not your turn!", ephemeral=True)
            if self.board[r][c] != '':
                return await interaction.response.send_message("这里已经有子了 / Cell taken!", ephemeral=True)

            if self.move_task and not self.move_task.done():
                self.move_task.cancel()

            self.board[r][c] = self.current_mark

            idx = r * 3 + c
            self.children[idx].label = self.current_mark
            if self.current_mark == 'X':
                self.children[idx].style = discord.ButtonStyle.danger
            else:
                self.children[idx].style = discord.ButtonStyle.primary
            self.children[idx].disabled = True

            winner = self._check_winner()
            is_draw = (winner is None and self._is_draw())

            if winner or is_draw:
                self.finished = True
                for child in self.children:
                    child.disabled = True

                embed = discord.Embed(
                    title="❌⭕ 井字棋 / Tic Tac Toe",
                    color=0x2ECC71 if winner else 0xF1C40F,
                )
                board_str = ""
                for rr in range(3):
                    row = [self.board[rr][cc] if self.board[rr][cc] else '·' for cc in range(3)]
                    board_str += ' | '.join(row) + '\n'
                    if rr < 2:
                        board_str += '──┼───┼──\n'
                embed.description = f"```\n{board_str}```"

                if is_draw:
                    embed.add_field(name="结果 / Result", value="🤝 平局 / Draw!", inline=False)
                    add_coins(self.player_x_id, 0, "井字棋平局 / TicTacToe draw")
                    add_coins(self.player_o_id, 0, "井字棋平局 / TicTacToe draw")
                else:
                    if winner == 'X':
                        winner_name = self.player_x_name
                        winner_id = self.player_x_id
                    else:
                        winner_name = self.player_o_name
                        winner_id = self.player_o_id
                    embed.add_field(name="结果 / Result", value=f"🎉 {winner_name} 获胜 / Wins! 🪙 +50", inline=False)
                    add_coins(winner_id, 50, "井字棋获胜 / TicTacToe win")

                await interaction.response.edit_message(embed=embed, view=self)
            else:
                self.current_turn = self.player_o_id if self.current_turn == self.player_x_id else self.player_x_id
                self.current_mark = 'O' if self.current_mark == 'X' else 'X'

                embed = self._build_embed()
                await interaction.response.edit_message(embed=embed, view=self)

                self.move_task = asyncio.create_task(self._move_timeout(interaction))

        return inner

    async def _move_timeout(self, interaction):
        await asyncio.sleep(15)
        if not self.finished:
            self.finished = True
            for child in self.children:
                child.disabled = True

            loser = self._current_player_name()
            winner = self._other_player_name()
            winner_id = self.player_o_id if self.current_turn == self.player_x_id else self.player_x_id

            embed = discord.Embed(
                title="❌⭕ 井字棋 / Tic Tac Toe",
                description=f"⏰ **{loser}** 超时 / Timed out!",
                color=0xE74C3C,
            )
            board_str = ""
            for rr in range(3):
                row = [self.board[rr][cc] if self.board[rr][cc] else '·' for cc in range(3)]
                board_str += ' | '.join(row) + '\n'
                if rr < 2:
                    board_str += '──┼───┼──\n'
            embed.description += f"\n```\n{board_str}```"
            embed.add_field(name="结果 / Result", value=f"🎉 {winner} 获胜 / Wins! 🪙 +50", inline=False)
            add_coins(winner_id, 50, "井字棋对手超时获胜 / TicTacToe timeout win")

            try:
                await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
# 🏇 赛马 / Horse Race
# ══════════════════════════════════════════════════════════════

HORSE_EMOJIS = ['🐎', '🐴', '🦄', '🐂', '🐃', '🐏']
HORSE_ODDS = [5.0, 4.0, 3.0, 2.0, 1.5, 5.0]


class HorseRaceView(discord.ui.View):
    """赛马下注选择视图 / Horse race betting view."""

    def __init__(self, bet: int, player_id: str, player_name: str):
        super().__init__(timeout=30)
        self.bet = bet
        self.player_id = player_id
        self.player_name = player_name
        self.chosen = None

        for i in range(6):
            btn = discord.ui.Button(
                label=f"{HORSE_EMOJIS[i]} 马{i+1}",
                style=discord.ButtonStyle.secondary,
                row=i // 3,
                custom_id=f"horse_{i}"
            )
            btn.callback = self.make_horse_callback(i)
            self.add_item(btn)

    def make_horse_callback(self, idx):
        async def inner(interaction: discord.Interaction):
            if str(interaction.user.id) != self.player_id:
                return await interaction.response.send_message("不是你的比赛 / Not your race!", ephemeral=True)
            if self.chosen is not None:
                return await interaction.response.send_message("已经选过了 / Already chosen!", ephemeral=True)

            self.chosen = idx
            for child in self.children:
                child.disabled = True
            self.children[idx].style = discord.ButtonStyle.success

            embed = discord.Embed(
                title="🏇 赛马 / Horse Race",
                description=f"你选了 **{HORSE_EMOJIS[idx]} 马{idx+1}**\n赔率 / Odds: **{HORSE_ODDS[idx]}:1**\n\n比赛开始 / Race starting...",
                color=0xE67E22,
            )
            embed.add_field(name="赌注 / Bet", value=f"🪙 {self.bet:,}", inline=True)
            await interaction.response.edit_message(embed=embed, view=self)

            asyncio.create_task(self._run_race(interaction, idx))

        return inner

    async def _run_race(self, interaction, chosen_idx):
        await asyncio.sleep(1)

        TRACK_LENGTH = 20
        positions = [0] * 6
        winner = None

        embed = discord.Embed(title="🏇 赛马 / Horse Race", color=0xE67E22)

        while winner is None:
            for i in range(6):
                step = random.randint(1, 3)
                positions[i] += step
                if positions[i] >= TRACK_LENGTH:
                    positions[i] = TRACK_LENGTH
                    if winner is None:
                        winner = i

            track_lines = []
            for i in range(6):
                horse = HORSE_EMOJIS[i]
                track = '─' * positions[i] + horse + '─' * (TRACK_LENGTH - positions[i]) + '🏁'
                marker = ' ◀' if i == chosen_idx else ''
                track_lines.append(f"马{i+1}{marker}: {track}")

            embed.description = '\n'.join(track_lines)
            embed.clear_fields()
            embed.add_field(name="你的马 / Your Horse", value=f"{HORSE_EMOJIS[chosen_idx]} 马{chosen_idx+1}", inline=True)
            embed.add_field(name="赌注 / Bet", value=f"🪙 {self.bet:,}", inline=True)

            if winner is not None:
                uid = self.player_id
                if winner == chosen_idx:
                    payout = int(self.bet * HORSE_ODDS[chosen_idx])
                    add_coins(uid, payout, f"赛马获胜 / Horse race win (马{chosen_idx+1})")
                    embed.color = 0x2ECC71
                    embed.add_field(name="结果 / Result", value=f"🎉 你的马赢了! / Your horse wins! 🪙 +{payout:,}", inline=False)
                else:
                    add_coins(uid, -self.bet, f"赛马输 / Horse race loss (bet on 马{chosen_idx+1}, winner 马{winner+1})")
                    embed.color = 0xE74C3C
                    embed.add_field(name="结果 / Result", value=f"😢 马{winner+1} ({HORSE_EMOJIS[winner]}) 赢了 / 马{winner+1} wins! 🪙 -{self.bet:,}", inline=False)
                bal = get_balance(uid)
                embed.add_field(name="余额 / Balance", value=f"🪙 {bal:,}", inline=True)

                for child in self.children:
                    child.disabled = True

            try:
                await interaction.edit_original_response(embed=embed, view=self if winner is None else None)
            except Exception:
                pass

            if winner is None:
                await asyncio.sleep(0.6)

    async def on_timeout(self):
        if self.chosen is None:
            for child in self.children:
                child.disabled = True
            if self.message:
                embed = discord.Embed(
                    title="🏇 赛马 / Horse Race",
                    description="⏰ 超时未选择 / Timed out — no horse chosen",
                    color=0x95A5A6,
                )
                await self.message.edit(embed=embed, view=self)



# ══════════════════════════════════════════════════════════════
# 🎮 游戏大厅 / Game Lobby — Modals & View
# ══════════════════════════════════════════════════════════════

class BlackjackBetModal(discord.ui.Modal, title="🃏 21点下注 / Blackjack Bet"):
    """Modal for entering Blackjack bet amount."""

    bet_input = discord.ui.TextInput(
        label="下注金额 / Bet Amount",
        placeholder="输入下注金额，最低10金币 / Min 10 coins",
        max_length=10,
        required=True,
    )

    def __init__(self, player_id: str, player_name: str):
        super().__init__()
        self.player_id = player_id
        self.player_name = player_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value.strip())
        except ValueError:
            return await interaction.response.send_message(
                "❌ 请输入有效数字 / Please enter a valid number.", ephemeral=True)

        if bet < 10:
            return await interaction.response.send_message(
                "最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)

        uid = self.player_id
        bal = get_balance(uid)
        if bal < bet:
            return await interaction.response.send_message(
                f"金币不足！你只有 {bal:,} 金币 / Not enough coins! You have {bal:,}.",
                ephemeral=True,
            )

        add_coins(uid, -bet, "21点下注(大厅) / Blackjack bet (lobby)")

        suits = ['♠', '♥', '♦', '♣']
        ranks = ['A','2','3','4','5','6','7','8','9','10','J','Q','K']
        deck = [(r, s) for s in suits for r in ranks]
        random.shuffle(deck)

        view = BlackjackView(uid, self.player_name, bet, deck)

        if view.player_blackjack and not view.dealer_blackjack:
            view.finished = True
            profit = int(bet * 1.5)
            add_coins(uid, profit, "21点Blackjack获胜(大厅) / Blackjack win (lobby)")
            bal2 = get_balance(uid)
            embed = await view._build_embed(show_dealer=True)
            embed.color = 0x2ECC71
            embed.add_field(name="结果 / Result", value=f"🎉 Blackjack! 🪙 +{profit:,}", inline=False)
            embed.add_field(name="余额 / Balance", value=f"🪙 {bal2:,}", inline=True)
            for child in view.children:
                child.disabled = True
            await interaction.response.send_message(embed=embed, view=view)
        elif view.player_blackjack and view.dealer_blackjack:
            view.finished = True
            add_coins(uid, bet, "21点平局(大厅) / Blackjack push (lobby)")
            bal2 = get_balance(uid)
            embed = await view._build_embed(show_dealer=True)
            embed.color = 0xF1C40F
            embed.add_field(name="结果 / Result", value=f"🤝 双方Blackjack平局 / Both Blackjack — Push!", inline=False)
            embed.add_field(name="余额 / Balance", value=f"🪙 {bal2:,}", inline=True)
            for child in view.children:
                child.disabled = True
            await interaction.response.send_message(embed=embed, view=view)
        else:
            embed = await view._build_embed()
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()


class TicTacToeModal(discord.ui.Modal, title="❌⭕ 井字棋 / Tic Tac Toe"):
    """Modal for entering opponent and optional bet."""

    opponent_input = discord.ui.TextInput(
        label="对手 Discord ID 或 @mention",
        placeholder="输入对手的 Discord ID 或 @用户名",
        max_length=100,
        required=True,
    )
    bet_input = discord.ui.TextInput(
        label="下注金额（可选，默认0）/ Bet (optional, default 0)",
        placeholder="0",
        max_length=10,
        required=False,
        default="0",
    )

    def __init__(self, player_id: str, player_name: str, guild: discord.Guild):
        super().__init__()
        self.player_id = player_id
        self.player_name = player_name
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.opponent_input.value.strip()
        member = None

        # Resolve opponent
        if raw.startswith("<@") and raw.endswith(">"):
            uid = raw.replace("<@", "").replace("!", "").replace(">", "")
            member = self.guild.get_member(int(uid))
        elif raw.isdigit():
            member = self.guild.get_member(int(raw))
        if not member:
            member = discord.utils.get(self.guild.members, name=raw)
        if not member:
            member = discord.utils.get(self.guild.members, display_name=raw)
        if not member:
            lower = raw.lower()
            for m in self.guild.members:
                if m.name.lower() == lower or m.display_name.lower() == lower:
                    member = m
                    break

        if not member:
            return await interaction.response.send_message(
                f"找不到用户: `{raw}` / User not found.", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message(
                "不能和自己下棋 / Cannot play against yourself!", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message(
                "不能和机器人下棋 / Cannot play against bots!", ephemeral=True)

        # Parse bet
        try:
            bet = int(self.bet_input.value.strip() or "0")
        except ValueError:
            bet = 0

        if bet < 0:
            return await interaction.response.send_message(
                "下注金额不能为负数 / Bet cannot be negative.", ephemeral=True)

        if bet > 0:
            uid = self.player_id
            bal = get_balance(uid)
            if bal < bet:
                return await interaction.response.send_message(
                    f"金币不足！你只有 {bal:,} 金币 / Not enough coins! You have {bal:,}.",
                    ephemeral=True,
                )
            add_coins(uid, -bet, "井字棋下注(大厅) / TicTacToe bet (lobby)")

        view = TicTacToeView(
            self.player_id, self.player_name,
            str(member.id), member.display_name,
        )
        view.bet = bet  # Store bet for later use

        # Override _check_winner behavior to handle bets
        embed = view._build_embed()
        await interaction.response.send_message(
            f"{member.mention} 你被挑战了 / You've been challenged!",
            embed=embed,
            view=view,
        )
        view.message = await interaction.original_response()
        view.move_task = asyncio.create_task(view._move_timeout(interaction))


class HorseRaceBetModal(discord.ui.Modal, title="🏇 赛马下注 / Horse Race Bet"):
    """Modal for entering Horse Race bet amount."""

    bet_input = discord.ui.TextInput(
        label="下注金额 / Bet Amount",
        placeholder="输入下注金额，最低10金币 / Min 10 coins",
        max_length=10,
        required=True,
    )

    def __init__(self, player_id: str, player_name: str):
        super().__init__()
        self.player_id = player_id
        self.player_name = player_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bet = int(self.bet_input.value.strip())
        except ValueError:
            return await interaction.response.send_message(
                "❌ 请输入有效数字 / Please enter a valid number.", ephemeral=True)

        if bet < 10:
            return await interaction.response.send_message(
                "最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)

        uid = self.player_id
        bal = get_balance(uid)
        if bal < bet:
            return await interaction.response.send_message(
                f"金币不足！你只有 {bal:,} 金币 / Not enough coins! You have {bal:,}.",
                ephemeral=True,
            )

        add_coins(uid, -bet, "赛马下注(大厅) / Horse Race bet (lobby)")

        view = HorseRaceView(bet, uid, self.player_name)
        embed = discord.Embed(
            title="🏇 赛马 / Horse Race",
            description="选择一匹马来下注 / Choose a horse to bet on!\n\n" + '\n'.join(
                f"{HORSE_EMOJIS[i]} **马{i+1}** — 赔率/Odds: **{HORSE_ODDS[i]}:1**"
                for i in range(6)
            ),
            color=0xE67E22,
        )
        embed.set_footer(text="30秒内选择 / 30s to choose")
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


class GameLobbyView(discord.ui.View):
    """游戏大厅按钮面板 / Game Lobby button panel."""

    def __init__(self, player_id: str, player_name: str, guild: discord.Guild):
        super().__init__(timeout=300)
        self.player_id = player_id
        self.player_name = player_name
        self.guild = guild

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.player_id:
            await interaction.response.send_message(
                "❌ 这不是你的面板！请使用 `/gmpt-gamelobby` 打开你自己的大厅。\n"
                "Not your panel! Use `/gmpt-gamelobby` to open your own lobby.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="🃏 21点 Blackjack", style=discord.ButtonStyle.primary, row=0)
    async def blackjack_btn(self, interaction: discord.Interaction, button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.send_modal(
            BlackjackBetModal(self.player_id, self.player_name)
        )

    @discord.ui.button(label="❌⭕ 井字棋 Tic Tac Toe", style=discord.ButtonStyle.success, row=0)
    async def tictactoe_btn(self, interaction: discord.Interaction, button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.send_modal(
            TicTacToeModal(self.player_id, self.player_name, self.guild)
        )

    @discord.ui.button(label="🏇 赛马 Horse Race", style=discord.ButtonStyle.danger, row=0)
    async def horserace_btn(self, interaction: discord.Interaction, button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.send_modal(
            HorseRaceBetModal(self.player_id, self.player_name)
        )


# ══════════════════════════════════════════════════════════════
# CasinoGames Cog
# ══════════════════════════════════════════════════════════════

class CasinoGames(CogBase):
    """赌场小游戏 / Casino Mini Games — Blackjack, Tic Tac Toe, Horse Race"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """在 Cog 加载时打印已注册命令名称用于调试."""
        cmds = [cmd.qualified_name for cmd in self.get_app_commands()]
        logger.info(f"[CasinoGames] cog_load — 已注册 {len(cmds)} 个命令: {', '.join(cmds)}")

    @app_commands.command(name="gmpt-blackjack", description="🃏 21点 / Blackjack — 与庄家对决")
    @app_commands.describe(bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def blackjack_cmd(self, interaction: discord.Interaction, bet: int):
        """🃏 21点 / Blackjack"""
        try:
            uid = str(interaction.user.id)
            uname = interaction.user.display_name

            if bet < 10:
                return await interaction.response.send_message("最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)

            bal = get_balance(uid)
            if bal < bet:
                return await interaction.response.send_message(
                    f"金币不足！你只有 {bal:,} 金币 / Not enough coins! You have {bal:,}.",
                    ephemeral=True,
                )

            add_coins(uid, -bet, "21点下注 / Blackjack bet")

            suits = ['♠', '♥', '♦', '♣']
            ranks = ['A','2','3','4','5','6','7','8','9','10','J','Q','K']
            deck = [(r, s) for s in suits for r in ranks]
            random.shuffle(deck)

            view = BlackjackView(uid, uname, bet, deck)

            if view.player_blackjack and not view.dealer_blackjack:
                view.finished = True
                profit = int(bet * 1.5)
                add_coins(uid, profit, "21点Blackjack获胜 / Blackjack win")
                bal2 = get_balance(uid)
                embed = await view._build_embed(show_dealer=True)
                embed.color = 0x2ECC71
                embed.add_field(name="结果 / Result", value=f"🎉 Blackjack! 🪙 +{profit:,}", inline=False)
                embed.add_field(name="余额 / Balance", value=f"🪙 {bal2:,}", inline=True)
                for child in view.children:
                    child.disabled = True
                await interaction.response.send_message(embed=embed, view=view)
            elif view.player_blackjack and view.dealer_blackjack:
                view.finished = True
                add_coins(uid, bet, "21点平局 / Blackjack push")
                bal2 = get_balance(uid)
                embed = await view._build_embed(show_dealer=True)
                embed.color = 0xF1C40F
                embed.add_field(name="结果 / Result", value=f"🤝 双方Blackjack平局 / Both Blackjack — Push!", inline=False)
                embed.add_field(name="余额 / Balance", value=f"🪙 {bal2:,}", inline=True)
                for child in view.children:
                    child.disabled = True
                await interaction.response.send_message(embed=embed, view=view)
            else:
                embed = await view._build_embed()
                await interaction.response.send_message(embed=embed, view=view)
                view.message = await interaction.original_response()
        except Exception as e:
            logger.error(f"[blackjack_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 21点游戏出错，请重试 / Blackjack error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 21点游戏出错，请重试 / Blackjack error, please retry.", ephemeral=True)

    @app_commands.command(name="gmpt-tictactoe", description="❌⭕ 井字棋 / Tic Tac Toe — 两人对战")
    @app_commands.describe(opponent="对手 / Opponent")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def tictactoe_cmd(self, interaction: discord.Interaction, opponent: discord.Member):
        """❌⭕ 井字棋 / Tic Tac Toe"""
        try:
            if opponent.id == interaction.user.id:
                return await interaction.response.send_message("不能和自己下棋 / Cannot play against yourself!", ephemeral=True)
            if opponent.bot:
                return await interaction.response.send_message("不能和机器人下棋 / Cannot play against bots!", ephemeral=True)

            view = TicTacToeView(
                str(interaction.user.id), interaction.user.display_name,
                str(opponent.id), opponent.display_name,
            )
            embed = view._build_embed()
            await interaction.response.send_message(
                f"{opponent.mention} 你被挑战了 / You've been challenged!",
                embed=embed,
                view=view,
            )
            view.message = await interaction.original_response()
            view.move_task = asyncio.create_task(view._move_timeout(interaction))
        except Exception as e:
            logger.error(f"[tictactoe_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 井字棋出错，请重试 / Tic Tac Toe error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 井字棋出错，请重试 / Tic Tac Toe error, please retry.", ephemeral=True)

    @app_commands.command(name="gmpt-horserace", description="🏇 赛马 / Horse Race — 下注赛马")
    @app_commands.describe(bet="下注金额 / Bet amount")
    @app_commands.checks.cooldown(1, 3, key=lambda i: (i.guild_id, i.user.id))
    async def horserace_cmd(self, interaction: discord.Interaction, bet: int):
        """🏇 赛马 / Horse Race"""
        try:
            uid = str(interaction.user.id)
            uname = interaction.user.display_name

            if bet < 10:
                return await interaction.response.send_message("最低下注 10 金币 / Min bet 10 coins.", ephemeral=True)

            bal = get_balance(uid)
            if bal < bet:
                return await interaction.response.send_message(
                    f"金币不足！你只有 {bal:,} 金币 / Not enough coins! You have {bal:,}.",
                    ephemeral=True,
                )

            add_coins(uid, -bet, "赛马下注 / Horse Race bet")

            view = HorseRaceView(bet, uid, uname)
            embed = discord.Embed(
                title="🏇 赛马 / Horse Race",
                description="选择一匹马来下注 / Choose a horse to bet on!\n\n" + '\n'.join(
                    f"{HORSE_EMOJIS[i]} **马{i+1}** — 赔率/Odds: **{HORSE_ODDS[i]}:1**"
                    for i in range(6)
                ),
                color=0xE67E22,
            )
            embed.set_footer(text="30秒内选择 / 30s to choose")
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()
        except Exception as e:
            logger.error(f"[horserace_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 赛马出错，请重试 / Horse Race error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 赛马出错，请重试 / Horse Race error, please retry.", ephemeral=True)

    # ══════════════════════════════════════════════════════════
    # /gmpt-gamelobby — 游戏大厅 / Game Lobby
    # ══════════════════════════════════════════════════════════
    @app_commands.command(name="gmpt-gamelobby", description="🎮 游戏大厅 / Game Lobby — 一站式游戏入口")
    @app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
    async def gamelobby_cmd(self, interaction: discord.Interaction):
        """🎮 游戏大厅 / Game Lobby"""
        try:
            uid = str(interaction.user.id)
            uname = interaction.user.display_name
            guild = interaction.guild
            bal = get_balance(uid)

            embed = discord.Embed(
                title="🎮 游戏大厅 / Game Lobby",
                description=(
                    "选择一个游戏开始游玩 / Choose a game to start playing!\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🃏 **21点 / Blackjack**\n"
                    "经典纸牌游戏，与庄家对决！下注金额决定你的风险和收益。\n"
                    "Classic card game vs the dealer! Your bet determines risk & reward.\n\n"
                    "❌⭕ **井字棋 / Tic Tac Toe**\n"
                    "两人对战，三子连线即获胜！可邀请好友对战。\n"
                    "Two-player strategy game! Invite a friend to play.\n\n"
                    "🏇 **赛马 / Horse Race**\n"
                    "六匹马随机竞速，下注你支持的马匹赢取丰厚赔率！\n"
                    "Bet on one of 6 horses and watch the race unfold!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=0x5865F2,
            )
            embed.add_field(name="💰 余额 / Balance", value=f"🪙 {bal:,}", inline=True)
            embed.add_field(name="👤 玩家 / Player", value=uname, inline=True)
            embed.set_footer(text="GMPT Casino v3.5 | 点击按钮开始 / Click buttons to start")
            embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)

            view = GameLobbyView(uid, uname, guild)
            await interaction.response.send_message(embed=embed, view=view)
            logger.info(f"[gamelobby] {uname} (uid={uid}) opened game lobby")
        except Exception as e:
            logger.error(f"[gamelobby_cmd] error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ 游戏大厅出错，请重试 / Game Lobby error, please retry.", ephemeral=True)
            else:
                await interaction.followup.send(
                    "❌ 游戏大厅出错，请重试 / Game Lobby error, please retry.", ephemeral=True)


# ══════════════════════════════════════════════════════════════
# Cog setup
# ══════════════════════════════════════════════════════════════

async def setup(bot):
    await bot.add_cog(CasinoGames(bot))
