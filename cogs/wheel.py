
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


def _spin() -> tuple:
    """Spin the wheel and return a prize (module-level so both View and Command can use it)."""
    total_weight = sum(p[3] for p in PRIZE_POOL)
    roll = random.randint(1, total_weight)
    cumulative = 0
    for prize in PRIZE_POOL:
        cumulative += prize[3]
        if roll <= cumulative:
            return prize
    return PRIZE_POOL[-1]  # fallback


class WheelView(discord.ui.View):
    """抽奖转盘按钮面板 / Lucky wheel button panel."""

    def __init__(self):
        super().__init__(timeout=180)

    async def _safe_edit(self, interaction: discord.Interaction, **kwargs):
        """安全编辑消息：已 defer 后用 edit_original_response，未响应用 response.edit_message。"""
        try:
            await interaction.response.edit_message(**kwargs)
        except discord.InteractionResponded:
            await interaction.edit_original_response(**kwargs)

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
        results = [_spin() for _ in range(count)]

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

        await self._safe_edit(interaction, embed=embed, view=self)

    @discord.ui.button(label="🎡 转一次 / Spin x1 (50💰)", style=discord.ButtonStyle.success, row=0)
    async def spin_once(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        try:
            await self._do_spin(interaction, 1)
        except Exception:
            logger.exception("spin_once error")
            await interaction.followup.send("❌ 抽奖出错，请重试 / Spin error, please retry.", ephemeral=True)

    @discord.ui.button(label="🎰 转十次 / Spin x10 (450💰)", style=discord.ButtonStyle.primary, row=0)
    async def spin_ten(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        try:
            await self._do_spin(interaction, 10)
        except Exception:
            logger.exception("spin_ten error")
            await interaction.followup.send("❌ 抽奖出错，请重试 / Spin error, please retry.", ephemeral=True)

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
        await self._safe_edit(interaction, embed=embed, view=self)

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
        await self._safe_edit(interaction, embed=embed, view=view)


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass

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

    @app_commands.command(name="gmpt-spin", description="直接旋转转盘 N 次 / Spin the wheel N times")
    @app_commands.describe(spin_times="旋转次数，1~10 / Number of spins (1~10)")
    async def spin_cmd(
        self,
        interaction: discord.Interaction,
        spin_times: int | None = None,
    ):
        """直接旋转转盘，spin_times 为 None 或非正整数时默认 1 次。"""
        # 参数校验：None / 非正整数 / 超出范围 → 默认值
        if spin_times is None or spin_times <= 0:
            spin_times = 1
        spin_times = min(spin_times, 10)  # 上限 10 次

        uid = str(interaction.user.id)
        bal = get_balance(uid)
        cost = spin_times * SPIN_COST

        if bal < cost:
            await interaction.response.send_message(
                f"金币不足！需要 🪙 **{cost:,}**，你只有 🪙 {bal:,} / Not enough coins! Need 🪙 {cost:,}, you have 🪙 {bal:,}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            add_coins(uid, -cost, f"Lucky wheel spin x{spin_times}")
            results = [_spin() for _ in range(spin_times)]

            total_coins = sum(r[2] for r in results if r[1] == "coins")
            new_bal = get_balance(uid)

            result_lines = []
            for i, (display, ptype, value) in enumerate(results, 1):
                result_lines.append(f"**{i}.** {display}")
            if total_coins > 0:
                result_lines.append(f"\n💎 总获得 / Total: 🪙 **{total_coins:,}**")

            embed = discord.Embed(
                title=f"🎡 转{spin_times}次结果 / {spin_times} Spins",
                description="\n".join(result_lines),
                color=0xFFD700,
            )
            embed.add_field(name="💰 新余额 / New Balance", value=f"🪙 {new_bal:,}", inline=False)
            embed.set_footer(text=f"消耗 🪙 {cost:,} | GMPT Lucky Wheel")

            await interaction.edit_original_response(embed=embed)
        except Exception:
            logger.exception("spin_cmd error")
            await interaction.edit_original_response(content="❌ 抽奖出错，请重试 / Spin error, please retry.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Wheel(bot))
    logger.info("Wheel cog loaded")
