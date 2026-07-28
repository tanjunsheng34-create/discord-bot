"""
GMPT Bot — Duel / Shootout System (Economy Bot)
Players challenge each other, take turns shooting, winner takes the pot.
Money involved — economy bot only.
"""
import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from cogs.economy import get_balance, add_coins
from datetime import datetime
import logging
from utils.logger import log_error
from utils.cog_base import CogBase

logger = logging.getLogger(__name__)

# Active duel challenges: challenge_message_id → {challenger_id, target_id, amount, embed, view}
_active_duels: dict[int, dict] = {}

# HP per player
MAX_HP = 3


class DuelChallengeView(discord.ui.View):
    """View for the challenged player to accept/decline."""

    def __init__(self, duel_data: dict, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.duel_data = duel_data

    @discord.ui.button(label="接受 / Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.duel_data["target_id"]:
            return await interaction.response.send_message(
                "这不是你的决斗 / This is not your duel.", ephemeral=True
            )

        await interaction.response.defer()
        self.duel_data["msg_id"] = interaction.message.id
        await self._start_duel(interaction)

    @discord.ui.button(label="拒绝 / Decline", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.duel_data["target_id"]:
            return await interaction.response.send_message(
                "这不是你的决斗 / This is not your duel.", ephemeral=True
            )

        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(
                content=f"❌ {interaction.user.mention} 拒绝了决斗！/ Duel declined!",
                view=self,
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                content=f"❌ {interaction.user.mention} 拒绝了决斗！/ Duel declined!",
                view=self,
            )
        # Cleanup
        if self.duel_data.get("msg_id"):
            _active_duels.pop(self.duel_data["msg_id"], None)

    async def on_timeout(self):
        if self.duel_data.get("msg_id"):
            _active_duels.pop(self.duel_data["msg_id"], None)

    async def _start_duel(self, interaction: discord.Interaction):
        """Begin the duel!"""
        d = self.duel_data
        challenger = interaction.guild.get_member(d["challenger_id"])
        target = interaction.guild.get_member(d["target_id"])
        if challenger is None or target is None:
            return await interaction.followup.send("有玩家已离开服务器 / A player has left the server.")

        # Check both have enough coins
        bal_c = get_balance(str(challenger.id))
        bal_t = get_balance(str(target.id))
        if bal_c < d["amount"] or bal_t < d["amount"]:
            return await interaction.followup.send(
                "有一方金币不足！/ One player has insufficient coins!"
            )

        # Initialize duel state
        d["hp_c"] = MAX_HP
        d["hp_t"] = MAX_HP
        d["turn"] = "challenger"
        d["round"] = 1
        d["log"] = []
        d["channel_id"] = interaction.channel_id
        d["challenger_name"] = challenger.display_name
        d["target_name"] = target.display_name

        embed = _build_duel_embed(d)
        view = ShootView(d)
        await interaction.followup.send(
            f"⚔️ **决斗开始！/ Duel Start!**\n"
            f"{challenger.mention} ({d['challenger_name']}) **VS** {target.mention} ({d['target_name']})\n"
            f"赌注 / Bet: 🪙 **{d['amount']:,}**\n"
            f"每人 {MAX_HP} 发子弹 / {MAX_HP} shots each. 命中多者获胜！/ Most hits wins!",
            embed=embed,
            view=view,
        )
        self.stop()


class ShootView(discord.ui.View):
    """Turn-based shooting buttons."""

    def __init__(self, duel_data: dict, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.duel_data = duel_data

    def _build_embed(self):
        return _build_duel_embed(self.duel_data)

    @discord.ui.button(label="🔫 射击！/ Shoot!", style=discord.ButtonStyle.primary)
    async def shoot(self, interaction: discord.Interaction, button: discord.ui.Button):
        d = self.duel_data

        # Determine if it's this user's turn
        if d["turn"] == "challenger" and interaction.user.id != d["challenger_id"]:
            return await interaction.response.send_message("还没轮到你！/ Not your turn!", ephemeral=True)
        if d["turn"] == "target" and interaction.user.id != d["target_id"]:
            return await interaction.response.send_message("还没轮到你！/ Not your turn!", ephemeral=True)

        await interaction.response.defer()

        shooter_id = interaction.user.id
        shooter_name = interaction.user.display_name

        if d["turn"] == "challenger":
            d["turn"] = "target"
            target_hp_key = "hp_t"
            shooter_hp_key = "hp_c"
            defender_name = d["target_name"]
        else:
            d["turn"] = "challenger"
            target_hp_key = "hp_c"
            shooter_hp_key = "hp_t"
            defender_name = d["challenger_name"]

        # Roll: 50% hit chance
        hit = random.random() < 0.5

        if hit:
            d[target_hp_key] -= 1
            d["log"].append(f"🔫 **{shooter_name}** 命中 **{defender_name}**！/ Hit!")
        else:
            d["log"].append(f"💨 **{shooter_name}** 未命中！/ Missed **{defender_name}**!")

        d["round"] += 1

        # Check if duel is over (after both have shot their 3 bullets)
        shots_fired = len(d["log"])
        max_shots = MAX_HP * 2  # 3 shots each = 6 total

        embed = self._build_embed()

        if shots_fired >= max_shots:
            # Duel over — settle
            await self._settle_duel(interaction, embed)
            self.stop()
            return

        await interaction.edit_original_response(embed=embed, view=self)

    async def _settle_duel(self, interaction: discord.Interaction, embed: discord.Embed):
        d = self.duel_data
        challenges = MAX_HP - d["hp_t"]  # hits landed by challenger
        targets = MAX_HP - d["hp_c"]     # hits landed by target

        cid = str(d["challenger_id"])
        tid = str(d["target_id"])
        amount = d["amount"]

        for child in self.children:
            child.disabled = True

        if challenges > targets:
            # Challenger wins
            add_coins(cid, amount, f"Duel win vs {d['target_name']}")
            add_coins(tid, -amount, f"Duel loss vs {d['challenger_name']}")
            result = f"🏆 **{d['challenger_name']}** 获胜！赢得 🪙 **{amount:,}** / Wins!"
        elif targets > challenges:
            # Target wins
            add_coins(tid, amount, f"Duel win vs {d['challenger_name']}")
            add_coins(cid, -amount, f"Duel loss vs {d['target_name']}")
            result = f"🏆 **{d['target_name']}** 获胜！赢得 🪙 **{amount:,}** / Wins!"
        else:
            # Draw — refund
            result = "🤝 平局！赌注已退还 / Draw! Bet refunded."

        embed.add_field(
            name="结算 / Settlement",
            value=f"命中 / Hits: {d['challenger_name']} {challenges} - {targets} {d['target_name']}\n{result}",
            inline=False,
        )

        await interaction.edit_original_response(embed=embed, view=self)
        # Cleanup finished duel from active registry
        if d.get("msg_id"):
            _active_duels.pop(d["msg_id"], None)


def _build_duel_embed(d: dict) -> discord.Embed:
    """Build the duel status embed with HP bars."""
    hp_c = max(0, d.get("hp_c", MAX_HP))
    hp_t = max(0, d.get("hp_t", MAX_HP))
    bar_c = "❤️" * hp_c + "🖤" * (MAX_HP - hp_c)
    bar_t = "❤️" * hp_t + "🖤" * (MAX_HP - hp_t)

    challenger_name = d.get("challenger_name", "挑战者")
    target_name = d.get("target_name", "被挑战者")

    desc = (
        f"**{challenger_name}**  {bar_c}  HP: {hp_c}/{MAX_HP}\n"
        f"**{target_name}**  {bar_t}  HP: {hp_t}/{MAX_HP}\n"
        f"\n回合 / Round: **{len(d.get('log', [])) // 2 + 1}**  |  赌注 / Bet: 🪙 **{d.get('amount', 0):,}**"
    )

    if d.get("log"):
        desc += "\n\n" + "\n".join(d["log"][-4:])  # last 4 log entries

    now = "challenger" if d.get("turn") == "challenger" else "target"
    now_name = challenger_name if now == "challenger" else target_name
    desc += f"\n\n🎯 轮到 / Turn: **{now_name}**"

    return discord.Embed(
        title="⚔️ 决斗 / Duel",
        description=desc,
        color=0xE74C3C,
    )


class Duel(CogBase):
    """Player-vs-player duel/shootout system with coin betting."""

    def __init__(self, bot):
        self.bot = bot

    duel_group = app_commands.Group(
        name="gmpt-duel",
        description="Challenge players to a duel / 向玩家发起决斗"
    )

    @duel_group.command(
        name="challenge",
        description="Challenge a player to a duel / 挑战一名玩家"
    )
    @app_commands.describe(
        opponent="The player to challenge / 要挑战的玩家",
        amount="Bet amount in coins / 赌注金额（金币）"
    )
    async def challenge(self, interaction: discord.Interaction, opponent: discord.Member, amount: int):
        """Initiate a duel challenge."""
        if opponent.id == interaction.user.id:
            return await interaction.response.send_message(
                "你不能挑战自己！/ You can't duel yourself!", ephemeral=True
            )
        if opponent.bot:
            return await interaction.response.send_message(
                "不能挑战机器人！/ Can't challenge bots!", ephemeral=True
            )
        if amount <= 0:
            return await interaction.response.send_message(
                "赌注必须大于 0 / Bet must be positive.", ephemeral=True
            )

        # Check challenger balance
        bal = get_balance(str(interaction.user.id))
        if bal < amount:
            return await interaction.response.send_message(
                f"你的金币不足！余额: 🪙 {bal:,} / Insufficient coins!", ephemeral=True
            )

        duel_data = {
            "challenger_id": interaction.user.id,
            "target_id": opponent.id,
            "amount": amount,
        }

        embed = discord.Embed(
            title="⚔️ 决斗挑战 / Duel Challenge",
            description=(
                f"{interaction.user.mention} 向你发起决斗挑战！\n"
                f"challenges you to a duel!\n\n"
                f"💰 赌注 / Bet: 🪙 **{amount:,}**\n"
                f"⏰ {opponent.mention} 有 **30 秒** 决定 / has **30 seconds** to respond\n\n"
                f"每人 {MAX_HP} 发子弹，命中多者获胜！/ {MAX_HP} shots each, most hits wins!"
            ),
            color=0xE74C3C,
        )

        view = DuelChallengeView(duel_data, timeout=30.0)
        await interaction.response.send_message(
            f"{opponent.mention}", embed=embed, view=view
        )

        msg = await interaction.original_response()
        duel_data["msg_id"] = msg.id
        _active_duels[msg.id] = duel_data


async def setup(bot):
    await bot.add_cog(Duel(bot))
