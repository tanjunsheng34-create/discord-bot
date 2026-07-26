"""
GMPT Bot — Lucky Wheel / 抽奖转盘
"""
import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
from cogs.economy import get_balance, add_coins
import logging

logger = logging.getLogger(__name__)

PRIZE_POOL = [
    ("🪙 50金币", "coins", 50, 30),      # (display, type, value, weight)
    ("🪙 100金币", "coins", 100, 25),
    ("🪙 200金币", "coins", 200, 15),
    ("🪙 500金币", "coins", 500, 10),
    ("🪙 1000金币", "coins", 1000, 5),
    ("🎟️ 抽奖券 x1", "ticket", 1, 8),
    ("🎟️ 抽奖券 x3", "ticket", 3, 3),
    ("🎁 神秘道具", "item", 1, 2),
    ("💨 谢谢参与", "none", 0, 2),
]

SPIN_COST = 50
BULK_COST = 450


class WheelView(discord.ui.View):
    """抽奖转盘按钮面板 / Lucky wheel button panel."""

    def __init__(self):
        super().__init__(timeout=180)

    def _spin(self) -> tuple:
        """Spin the wheel and return a prize."""
        total_weight = sum(p[3] for p in PRIZE_POOL)
        roll = random.randint(1, total_weight)
        cumulative = 0
        for prize in PRIZE_POOL:
            cumulative += prize[3]
            if roll <= cumulative:
                return prize
        return PRIZE_POOL[-1]  # fallback

    async def _do_spin(self, interaction: discord.Interaction, count: int):
        uid = str(interaction.user.id)
        cost = SPIN_COST if count == 1 else BULK_COST
        bal = get_balance(uid)
        if bal < cost:
            return await interaction.followup.send(
                f"金币不足！你需要 🪙 {cost:,}，当前余额 🪙 {bal:,} / Not enough coins!",
                ephemeral=True,
            )

        add_coins(uid, -cost, f"Lucky wheel spin x{count}")
        results = [self._spin() for _ in range(count)]

        total_coins = 0
        total_tickets = 0
        items = 0
        none_count = 0

        for ptype, _, value, _ in results:
            if ptype == "coins":
                total_coins += value
            elif ptype == "ticket":
                total_tickets += value
            elif ptype == "item":
                items += 1
            elif ptype == "none":
                none_count += 1

        if total_coins > 0:
            add_coins(uid, total_coins, f"Lucky wheel win coins")
        if total_tickets > 0:
            with get_db_ctx() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO giveaway_tickets (discord_id, tickets)
                    VALUES (?, ?)
                    ON CONFLICT(discord_id) DO UPDATE SET tickets = tickets + ?
                """, (uid, total_tickets, total_tickets))
                conn.commit()

        # Build result embed
        embed = discord.Embed(
            title="🎡 幸运大转盘 / Lucky Wheel",
            color=0xFFD700,
        )

        result_lines = []
        for i, (display, _, _, _) in enumerate(results, 1):
            result_lines.append(f"**#{i}** — {display}")

        embed.description = (
            f"转{count}次结果 / {count} Spins:\n\n" + "\n".join(result_lines)
        )

        if total_coins > 0:
            embed.add_field(name="🪙 金币获得", value=f"+{total_coins:,}", inline=True)
        if total_tickets > 0:
            embed.add_field(name="🎟️ 抽奖券", value=f"+{total_tickets}", inline=True)
        if items > 0:
            embed.add_field(name="🎁 道具", value=f"+{items}", inline=True)
        if none_count > 0:
            embed.add_field(name="💨 未中奖", value=f"{none_count}次", inline=True)

        new_bal = get_balance(uid)
        embed.add_field(name="💰 新余额", value=f"🪙 {new_bal:,}", inline=False)
        embed.set_footer(text=f"消耗 🪙 {cost:,} | GMPT Lucky Wheel")

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🎡 转一次 / Spin x1 (50💰)", style=discord.ButtonStyle.success, row=0)
    async def spin_once(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        await self._do_spin(interaction, 1)

    @discord.ui.button(label="🎰 转十次 / Spin x10 (450💰)", style=discord.ButtonStyle.primary, row=0)
    async def spin_ten(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        await self._do_spin(interaction, 10)

    @discord.ui.button(label="📋 奖品预览 / Prizes", style=discord.ButtonStyle.secondary, row=0)
    async def preview_btn(self, interaction: discord.Interaction, button):
        embed = discord.Embed(title="🎡 奖品预览 / Prize Preview", color=0xFFD700)
        lines = []
        for display, ptype, value, weight in PRIZE_POOL:
            pct = weight / sum(p[3] for p in PRIZE_POOL) * 100
            lines.append(f"{display} — {pct:.1f}%")
        embed.description = "\n".join(lines)
        embed.add_field(name="🪙 单次价格 / Single Spin", value=f"{SPIN_COST} 金币 / coins", inline=True)
        embed.add_field(name="🎰 十连价格 / Bulk (10)", value=f"{BULK_COST} 金币 / coins (省/save 50!)", inline=True)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀ 返回 / Back", style=discord.ButtonStyle.danger, row=1)
    async def back_btn(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        try:
            from cogs.dashboard import DashboardView
        except ImportError:
            from cogs.dashboard import DashboardView
        view = DashboardView(guild=interaction.guild, bot=None)
        view.category = 0
        view.build_page_buttons()
        embed = view._build_page_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class Wheel(commands.Cog):
    """幸运大转盘 / Lucky wheel system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gmpt-wheel", description="打开幸运大转盘 / Open lucky wheel")
    async def wheel_cmd(self, interaction: discord.Interaction):
        view = WheelView()
        embed = discord.Embed(
            title="🎡 幸运大转盘 / Lucky Wheel",
            description=f"每次旋转消耗 🪙 **{SPIN_COST}** 金币\n十连只需 🪙 **{BULK_COST}** (省50!)\n\n选择操作:",
            color=0xFFD700,
        )
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Wheel(bot))
    logger.info("Wheel cog loaded")
