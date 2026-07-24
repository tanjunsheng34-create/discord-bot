"""
GMPT Bot — Texas Hold'em Poker 德州扑克
"""
import asyncio
import random
import itertools
from collections import Counter
from enum import Enum

import discord
from discord import app_commands
from discord.ext import commands

from database import get_db

import logging
logger = logging.getLogger(__name__)

# ========== Card & Deck ==========
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_ORDER = {r: i for i, r in enumerate(RANKS)}

class Phase(Enum):
    WAITING = "waiting"
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"

class HandRank(Enum):
    HIGH_CARD = 0
    ONE_PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8
    ROYAL_FLUSH = 9

HAND_NAMES = {
    0: "高牌 High Card", 1: "一对 One Pair", 2: "两对 Two Pair",
    3: "三条 Three of a Kind", 4: "顺子 Straight", 5: "同花 Flush",
    6: "葫芦 Full House", 7: "四条 Four of a Kind",
    8: "同花顺 Straight Flush", 9: "皇家同花顺 Royal Flush"
}

def new_deck():
    d = [(r, s) for s in SUITS for r in RANKS]
    random.shuffle(d)
    return d

def card_str(c):
    return f"{c[0]}{c[1]}"

def cards_str(cards):
    return " ".join(card_str(c) for c in cards)

def eval_hand(hole, community):
    """Evaluate best 5-card hand. Returns (HandRank.value, [tiebreaker k1,k2,k3,k4,k5])."""
    all_cards = hole + community
    best = (-1, [])
    for combo in itertools.combinations(all_cards, 5):
        rank, tb = _eval_5(combo)
        if (rank, tb) > (best[0], best[1]):
            best = (rank, tb)
    return best

def _eval_5(cards):
    ranks = sorted([RANK_ORDER[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    is_flush = len(set(suits)) == 1
    is_straight = False
    straight_high = -1
    # Normal straight
    if len(set(ranks)) == 5 and max(ranks) - min(ranks) == 4:
        is_straight = True
        straight_high = max(ranks)
    # Wheel (A-2-3-4-5)
    if set(ranks) == {12, 0, 1, 2, 3}:
        is_straight = True
        straight_high = 3  # 5-high

    if is_flush and is_straight:
        if straight_high == 12:
            return (HandRank.ROYAL_FLUSH.value, [12, 11, 10, 9, 8])
        return (HandRank.STRAIGHT_FLUSH.value, [straight_high])

    counter = Counter(ranks)
    counts = sorted(counter.values(), reverse=True)
    # Sort by count desc then rank desc
    by_count = sorted(counter.items(), key=lambda x: (x[1], x[0]), reverse=True)
    kickers = [r for r, c in by_count]

    if counts == [4, 1]:
        return (HandRank.FOUR_OF_A_KIND.value, kickers)
    if counts == [3, 2]:
        return (HandRank.FULL_HOUSE.value, kickers)
    if is_flush:
        return (HandRank.FLUSH.value, ranks)
    if is_straight:
        return (HandRank.STRAIGHT.value, [straight_high])
    if counts == [3, 1, 1]:
        return (HandRank.THREE_OF_A_KIND.value, kickers)
    if counts == [2, 2, 1]:
        return (HandRank.TWO_PAIR.value, kickers)
    if counts == [2, 1, 1, 1]:
        return (HandRank.ONE_PAIR.value, kickers)
    return (HandRank.HIGH_CARD.value, ranks)


# ========== Game State ==========
class PokerGame:
    def __init__(self, channel_id: int, buy_in: int):
        self.channel_id = channel_id
        self.buy_in = buy_in
        self.players: dict[int, dict] = {}  # user_id → {hand, chips, bet, folded, name}
        self.order: list[int] = []  # player order
        self.deck = []
        self.community: list = []
        self.pot = 0
        self.current_bet = 0
        self.dealer_idx = 0
        self.current_idx = 0
        self.phase = Phase.WAITING
        self.small_blind = max(1, buy_in // 20)
        self.big_blind = self.small_blind * 2
        self.hand_count = 0

    @property
    def active_players(self):
        return [uid for uid in self.order if not self.players[uid]["folded"]]

    def current_player_id(self):
        active = self.active_players
        if not active:
            return None
        return active[self.current_idx % len(active)]

    def next_player(self):
        self.current_idx = (self.current_idx + 1) % max(1, len(self.active_players))


# In-memory game store: channel_id → PokerGame
_games: dict[int, PokerGame] = {}


# ========== Views ==========
class PokerActionView(discord.ui.View):
    def __init__(self, game: PokerGame):
        super().__init__(timeout=120)
        self.game = game
        self._update_buttons()

    def _update_buttons(self):
        g = self.game
        uid = g.current_player_id()
        if uid is None:
            self.clear_items()
            return
        p = g.players[uid]
        call_amt = g.current_bet - p["bet"]
        self.clear_items()
        self.add_item(discord.ui.Button(label="Fold 弃牌", style=discord.ButtonStyle.danger, custom_id="fold"))
        if call_amt == 0:
            self.add_item(discord.ui.Button(label="Check 过牌", style=discord.ButtonStyle.secondary, custom_id="check"))
        else:
            self.add_item(discord.ui.Button(label=f"Call 跟注 {call_amt}", style=discord.ButtonStyle.primary, custom_id="call"))
        min_raise = g.current_bet + g.big_blind
        self.add_item(discord.ui.Button(label=f"Raise {min_raise}", style=discord.ButtonStyle.success, custom_id=f"raise_{min_raise}"))
        self.add_item(discord.ui.Button(label="All-in 全下", style=discord.ButtonStyle.danger, custom_id="allin"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        g = self.game
        uid = g.current_player_id()
        if interaction.user.id != uid:
            await interaction.response.send_message("不是你的回合 / Not your turn.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Fold 弃牌", style=discord.ButtonStyle.danger, custom_id="fold")
    async def fold_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_action(interaction, "fold")

    @discord.ui.button(label="Check 过牌", style=discord.ButtonStyle.secondary, custom_id="check")
    async def check_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_action(interaction, "check")

    @discord.ui.button(label="Call 跟注", style=discord.ButtonStyle.primary, custom_id="call")
    async def call_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_action(interaction, "call")

    @discord.ui.button(label="Raise", style=discord.ButtonStyle.success, custom_id="raise")
    async def raise_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = self.game
        min_raise = g.current_bet + g.big_blind
        await interaction.response.send_modal(PokerRaiseModal(g, min_raise))

    @discord.ui.button(label="All-in 全下", style=discord.ButtonStyle.danger, custom_id="allin")
    async def allin_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_action(interaction, "allin")

    async def _do_action(self, interaction: discord.Interaction, action: str):
        g = self.game
        uid = interaction.user.id
        p = g.players[uid]
        call_amt = g.current_bet - p["bet"]

        if action == "fold":
            p["folded"] = True
            await interaction.response.send_message(f"{p['name']} folds 弃牌", ephemeral=False)
        elif action == "check":
            await interaction.response.send_message(f"{p['name']} checks 过牌", ephemeral=False)
        elif action == "call":
            actual = min(call_amt, p["chips"])
            p["chips"] -= actual
            p["bet"] += actual
            g.pot += actual
            await interaction.response.send_message(f"{p['name']} calls 跟注 {actual}", ephemeral=False)
        elif action == "allin":
            amt = p["chips"]
            p["chips"] = 0
            p["bet"] += amt
            g.pot += amt
            if p["bet"] > g.current_bet:
                g.current_bet = p["bet"]
            await interaction.response.send_message(f"{p['name']} goes ALL-IN 全下 {amt}!", ephemeral=False)

        # Advance
        await advance_game(g, interaction.channel)


class PokerRaiseModal(discord.ui.Modal, title="Raise 加注"):
    def __init__(self, game: PokerGame, min_raise: int):
        super().__init__()
        self.game = game
        self.min_raise = min_raise
        self.amount = discord.ui.TextInput(
            label=f"Amount (min {min_raise})",
            placeholder=str(min_raise),
            min_length=1, max_length=10
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        g = self.game
        uid = interaction.user.id
        p = g.players[uid]
        try:
            amt = int(self.amount.value)
        except ValueError:
            await interaction.response.send_message("Invalid amount.", ephemeral=True)
            return
        max_raise = p["chips"] + p["bet"]
        if amt < self.min_raise or amt > max_raise:
            await interaction.response.send_message(f"Amount must be between {self.min_raise} and {max_raise}.", ephemeral=True)
            return
        call_amt = g.current_bet - p["bet"]
        p["chips"] -= (amt - call_amt)
        p["bet"] = amt
        g.pot += (amt - call_amt)
        g.current_bet = amt
        await interaction.response.send_message(f"{p['name']} raises to {amt} 加注到 {amt}!", ephemeral=False)
        await advance_game(g, interaction.channel)


# ========== Game Engine ==========
async def advance_game(game: PokerGame, channel: discord.TextChannel):
    """After an action, advance to next player or next phase."""
    game.next_player()

    # Check if only one player remains
    active = game.active_players
    if len(active) <= 1:
        await showdown(game, channel)
        return

    # Check if all active players have matched the current bet
    all_matched = all(game.players[uid]["bet"] == game.current_bet for uid in active)
    # Also check all-in players don't block progression
    all_allin = all(game.players[uid]["chips"] == 0 for uid in active)

    if all_matched or all_allin:
        await next_phase(game, channel)
    else:
        await prompt_player(game, channel)


async def next_phase(game: PokerGame, channel: discord.TextChannel):
    """Move to next phase."""
    g = game
    # Reset bets for new phase
    for uid in g.order:
        g.players[uid]["bet"] = 0
    g.current_bet = 0
    g.current_idx = 0

    if g.phase == Phase.PREFLOP:
        g.phase = Phase.FLOP
        g.community = g.deck[:3]
        g.deck = g.deck[3:]
    elif g.phase == Phase.FLOP:
        g.phase = Phase.TURN
        g.community.append(g.deck[0])
        g.deck = g.deck[1:]
    elif g.phase == Phase.TURN:
        g.phase = Phase.RIVER
        g.community.append(g.deck[0])
        g.deck = g.deck[1:]
    elif g.phase == Phase.RIVER:
        await showdown(game, channel)
        return

    await show_table(game, channel)
    await prompt_player(game, channel)


async def showdown(game: PokerGame, channel: discord.TextChannel):
    """Evaluate hands and determine winner."""
    g = game
    active = g.active_players

    if len(active) == 1:
        winner_id = active[0]
        winner_name = g.players[winner_id]["name"]
        g.players[winner_id]["chips"] += g.pot
        winnings = g.pot
        g.pot = 0

        embed = discord.Embed(title="🏆 Hand Over 牌局结束", color=discord.Color.gold())
        embed.description = f"**{winner_name}** wins {winnings} chips by default! (everyone else folded)"
        await channel.send(embed=embed)
    else:
        # Evaluate all hands
        scores = {}
        for uid in active:
            scores[uid] = eval_hand(g.players[uid]["hand"], g.community)

        # Find winner(s)
        best_score = max(scores.values(), key=lambda x: (x[0], x[1]))
        winners = [uid for uid, s in scores.items() if (s[0], s[1]) == (best_score[0], best_score[1])]

        per_winner = g.pot // len(winners)
        remainder = g.pot % len(winners)

        lines = []
        for uid in active:
            hand = g.players[uid]["hand"]
            rank_name = HAND_NAMES[scores[uid][0]]
            hand_str = cards_str(hand)
            marker = "👑" if uid in winners else ""
            lines.append(f"{marker} **{g.players[uid]['name']}**: {hand_str} → {rank_name}")

        for uid in winners:
            award = per_winner + (remainder if uid == winners[0] else 0)
            g.players[uid]["chips"] += award

        embed = discord.Embed(title="🏆 Showdown 摊牌", color=discord.Color.gold())
        embed.add_field(name="Community 公共牌", value=cards_str(g.community) if g.community else "None", inline=False)
        embed.add_field(name="Hands 手牌", value="\n".join(lines), inline=False)
        winner_names = ", ".join(g.players[uid]["name"] for uid in winners)
        embed.set_footer(text=f"Winner: {winner_names} | Pot: {g.pot} → {per_winner} each")
        await channel.send(embed=embed)

    # Settle economy - convert leftover chips back to coins
    await settle_economy(game, channel)

    # Clean up or prompt new hand
    await prompt_new_hand(game, channel)


async def settle_economy(game: PokerGame, channel: discord.TextChannel):
    """Convert remaining chips to coins, log results."""
    g = game
    lines = []
    for uid in g.order:
        p = g.players[uid]
        net = p["chips"] - g.buy_in
        if net != 0:
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (net, str(uid)))
                conn.commit()
                conn.close()
                emoji = "📈" if net > 0 else "📉"
                lines.append(f"{emoji} **{p['name']}**: {'+' if net > 0 else ''}{net} coins")
            except Exception as e:
                logger.error(f"Settle economy error for {uid}: {e}")

    if lines:
        embed = discord.Embed(title="💰 Payout 结算", color=discord.Color.green())
        embed.description = "\n".join(lines)
        await channel.send(embed=embed)


async def prompt_new_hand(game: PokerGame, channel: discord.TextChannel):
    """Prompt dealer to start a new hand or end the game."""
    active = [uid for uid in game.order if game.players[uid]["chips"] > 0]
    if len(active) < 2:
        await channel.send("Game over — not enough players with chips. Use `/poker start` to begin a new game.")
        _games.pop(game.channel_id, None)
        return

    view = NewHandView(game)
    dealer_id = game.order[game.dealer_idx]
    await channel.send(
        f"<@{dealer_id}> Deal next hand? 发下一手牌？Use buttons below or `/poker deal`.",
        view=view
    )


class NewHandView(discord.ui.View):
    def __init__(self, game: PokerGame):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(label="Deal 发牌", style=discord.ButtonStyle.primary)
    async def deal(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = self.game
        dealer_id = g.order[g.dealer_idx]
        if interaction.user.id != dealer_id:
            await interaction.response.send_message("Only the dealer can deal.", ephemeral=True)
            return
        await interaction.response.defer()
        await start_hand(g, interaction.channel)


async def prompt_player(game: PokerGame, channel: discord.TextChannel):
    """Send action prompt to current player."""
    g = game
    uid = g.current_player_id()
    if uid is None:
        await showdown(game, channel)
        return
    p = g.players[uid]
    view = PokerActionView(g)
    # Public message: no hole cards
    await channel.send(
        f"<@{uid}> 你的回合 Your turn | 筹码 Chips: {p['chips']} | Pot: {g.pot} | 当前注 Current bet: {g.current_bet}",
        view=view
    )
    # DM hole cards privately
    user = channel.guild.get_member(uid) if channel.guild else None
    if user:
        try:
            await user.send(f"🃏 Hand #{g.hand_count} | Your cards 你的手牌: `{cards_str(p['hand'])}`")
        except discord.Forbidden:
            pass


async def show_table(game: PokerGame, channel: discord.TextChannel):
    """Display current table state."""
    g = game
    phase_names = {
        Phase.PREFLOP: "Pre-flop 翻牌前",
        Phase.FLOP: "Flop 翻牌",
        Phase.TURN: "Turn 转牌",
        Phase.RIVER: "River 河牌",
    }
    embed = discord.Embed(
        title=f"🃏 {phase_names.get(g.phase, g.phase.value)}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Community 公共牌", value=cards_str(g.community) if g.community else "—", inline=False)
    embed.add_field(name="Pot 底池", value=str(g.pot), inline=True)

    p_lines = []
    for uid in g.order:
        p = g.players[uid]
        status = ""
        if p["folded"]:
            status = " (folded)"
        elif p["chips"] == 0:
            status = " (all-in)"
        p_lines.append(f"{p['name']}: {p['chips']} chips{status}")
    embed.add_field(name="Players 玩家", value="\n".join(p_lines), inline=False)
    await channel.send(embed=embed)


async def start_hand(game: PokerGame, channel: discord.TextChannel):
    """Deal a new hand."""
    g = game
    g.hand_count += 1
    # Shift dealer
    if g.hand_count > 1:
        g.dealer_idx = (g.dealer_idx + 1) % len(g.order)
    g.phase = Phase.PREFLOP
    g.current_idx = 0
    g.current_bet = 0
    g.pot = 0
    g.community = []
    g.deck = new_deck()

    # Reset player state
    for uid in g.order:
        g.players[uid]["folded"] = False
        g.players[uid]["bet"] = 0

    # Remove busted players
    active_before = [uid for uid in g.order if g.players[uid]["chips"] > 0]
    if len(active_before) < 2:
        await channel.send("Not enough players with chips. Game over.")
        await settle_economy(game, channel)
        _games.pop(g.channel_id, None)
        return

    # Deal 2 cards to each active player
    for uid in active_before:
        g.players[uid]["hand"] = [g.deck.pop(0), g.deck.pop(0)]

    # Post blinds
    if len(active_before) >= 2:
        sb_idx = (g.dealer_idx + 1) % len(g.order)
        bb_idx = (g.dealer_idx + 2) % len(g.order)
        sb_uid = g.order[sb_idx]
        bb_uid = g.order[bb_idx]

        sb_amt = min(g.small_blind, g.players[sb_uid]["chips"])
        bb_amt = min(g.big_blind, g.players[bb_uid]["chips"])

        g.players[sb_uid]["chips"] -= sb_amt
        g.players[sb_uid]["bet"] = sb_amt
        g.players[bb_uid]["chips"] -= bb_amt
        g.players[bb_uid]["bet"] = bb_amt
        g.pot = sb_amt + bb_amt
        g.current_bet = bb_amt

    # Set current player to UTG (after big blind)
    utg_idx = (g.dealer_idx + 3) % len(g.order)
    # Find the first active player starting from UTG
    active_uids = [uid for uid in g.order if not g.players[uid]["folded"] and g.players[uid]["chips"] > 0]
    if not active_uids:
        await showdown(game, channel)
        return
    g.current_idx = active_uids.index(g.order[utg_idx]) if g.order[utg_idx] in active_uids else 0

    # DM each player their hand
    for uid in active_before:
        p = g.players[uid]
        user = channel.guild.get_member(uid)
        if user:
            try:
                await user.send(f"🃏 Hand #{g.hand_count} | Your cards 你的手牌: `{cards_str(p['hand'])}`")
            except discord.Forbidden:
                pass  # DMs closed

    await show_table(game, channel)
    await prompt_player(game, channel)


# ========== Cog ==========
class Poker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    poker_group = app_commands.Group(
        name="poker",
        description="Texas Hold'em Poker 德州扑克",
    )

    @poker_group.command(name="start", description="Start a poker game 开始一局德州扑克")
    @app_commands.describe(buy_in="Buy-in amount 买入金额 (default 500)")
    async def poker_start(self, interaction: discord.Interaction, buy_in: int = 500):
        cid = interaction.channel_id
        if cid in _games:
            await interaction.response.send_message("A game is already running in this channel.", ephemeral=True)
            return
        if buy_in < 50 or buy_in > 100000:
            await interaction.response.send_message("Buy-in must be between 50 and 100,000.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
            row = cur.fetchone()
            conn.close()
            if not row or row[0] < buy_in:
                await interaction.response.send_message(f"余额不足 Insufficient balance. You have {row[0] if row else 0} coins.", ephemeral=True)
                return
            # Deduct buy-in immediately
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE users SET score = score - ? WHERE discord_id = ?", (buy_in, uid))
            conn.commit()
            conn.close()
        except Exception as e:
            await interaction.response.send_message(f"Database error: {e}", ephemeral=True)
            return

        game = PokerGame(cid, buy_in)
        game.players[interaction.user.id] = {
            "hand": [], "chips": buy_in, "bet": 0,
            "folded": False, "name": interaction.user.display_name
        }
        game.order.append(interaction.user.id)
        game.dealer_idx = 0
        _games[cid] = game

        embed = discord.Embed(
            title="🃏 Texas Hold'em 德州扑克",
            description=f"Buy-in: {buy_in} | Min players: 2 | Max: 9\n\n"
                        f"**{interaction.user.display_name}** created the game!\n"
                        f"Use `/poker join` to join.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Game starts when dealer uses /poker deal")
        await interaction.response.send_message(embed=embed)

    @poker_group.command(name="join", description="Join the poker game 加入牌局")
    async def poker_join(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid not in _games:
            await interaction.response.send_message("No active game in this channel. Use `/poker start`.", ephemeral=True)
            return
        g = _games[cid]
        if g.phase != Phase.WAITING:
            await interaction.response.send_message("Game already in progress. Wait for next hand.", ephemeral=True)
            return
        if interaction.user.id in g.players:
            await interaction.response.send_message("You're already in the game.", ephemeral=True)
            return
        if len(g.players) >= 9:
            await interaction.response.send_message("Table full (max 9).", ephemeral=True)
            return

        uid = str(interaction.user.id)
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT score FROM users WHERE discord_id = ?", (uid,))
            row = cur.fetchone()
            conn.close()
            if not row or row[0] < g.buy_in:
                await interaction.response.send_message(f"余额不足 Insufficient balance. Need {g.buy_in} coins.", ephemeral=True)
                return
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE users SET score = score - ? WHERE discord_id = ?", (g.buy_in, uid))
            conn.commit()
            conn.close()
        except Exception as e:
            await interaction.response.send_message(f"Database error: {e}", ephemeral=True)
            return

        g.players[interaction.user.id] = {
            "hand": [], "chips": g.buy_in, "bet": 0,
            "folded": False, "name": interaction.user.display_name
        }
        g.order.append(interaction.user.id)

        names = ", ".join(g.players[uid]["name"] for uid in g.order)
        await interaction.response.send_message(
            f"**{interaction.user.display_name}** joined! ({len(g.players)} players)\n"
            f"Players: {names}"
        )

    @poker_group.command(name="deal", description="Deal the next hand 发牌 (dealer only)")
    async def poker_deal(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid not in _games:
            await interaction.response.send_message("No active game.", ephemeral=True)
            return
        g = _games[cid]
        if g.phase not in (Phase.WAITING, Phase.SHOWDOWN):
            await interaction.response.send_message("Hand already in progress.", ephemeral=True)
            return

        active = [uid for uid in g.order if g.players[uid]["chips"] > 0]
        if len(active) < 2:
            await interaction.response.send_message("Need at least 2 players with chips.", ephemeral=True)
            return

        dealer_id = g.order[g.dealer_idx]
        if interaction.user.id != dealer_id:
            await interaction.response.send_message(f"Only the dealer (<@{dealer_id}>) can deal.", ephemeral=True)
            return

        await interaction.response.defer()
        await start_hand(g, interaction.channel)

    @poker_group.command(name="status", description="Show current game status 查看牌局状态")
    async def poker_status(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid not in _games:
            await interaction.response.send_message("No active game in this channel.", ephemeral=True)
            return
        g = _games[cid]
        p_lines = []
        for uid in g.order:
            p = g.players[uid]
            status = ""
            if p["folded"]:
                status = " (folded)"
            elif p["chips"] == 0:
                status = " (all-in)"
            p_lines.append(f"{p['name']}: {p['chips']} chips{status}")
        embed = discord.Embed(title="Poker Game Status", color=discord.Color.blue())
        embed.add_field(name="Buy-in", value=str(g.buy_in), inline=True)
        embed.add_field(name="Phase", value=g.phase.value, inline=True)
        embed.add_field(name="Pot", value=str(g.pot), inline=True)
        embed.add_field(name="Players", value="\n".join(p_lines), inline=False)
        await interaction.response.send_message(embed=embed)

    @poker_group.command(name="end", description="End the game 结束牌局 (any player can vote)")
    async def poker_end(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid not in _games:
            await interaction.response.send_message("No active game.", ephemeral=True)
            return
        g = _games[cid]
        if interaction.user.id not in g.players:
            await interaction.response.send_message("You're not in the game.", ephemeral=True)
            return

        await interaction.response.defer()
        await settle_economy(g, interaction.channel)
        await interaction.followup.send(f"Game ended by {interaction.user.display_name}.")
        _games.pop(cid, None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Poker(bot))
    logger.info("Poker cog loaded")
