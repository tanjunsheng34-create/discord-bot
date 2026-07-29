"""
GMPT Bot — Leaderboard System / 排行榜系统
"""
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
import logging

logger = logging.getLogger(__name__)


class LeaderboardView(discord.ui.View):
    """排行榜按钮面板 / Leaderboard button panel."""

    def __init__(self, main_view=None):
        super().__init__(timeout=120)
        self.main_view = main_view

    async def _get_top(self, query: str, params: tuple, label: str, color: int, field_name: str, unit: str = ""):
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        embed = discord.Embed(title=label, color=color)
        if not rows:
            embed.description = "暂无数据 / No data yet."
            return embed

        lines = []
        for i, row in enumerate(rows, 1):
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"#{i}"
            lines.append(f"{medal} <@{row[0]}> — {row[1]:,}{unit}")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Top {len(rows)}")
        return embed

    @discord.ui.button(label="🪙 金币榜 / Coins", style=discord.ButtonStyle.primary, row=0)
    async def coin_lb(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        embed = await self._get_top(
            "SELECT discord_id, score FROM users ORDER BY score DESC LIMIT 20",
            (), "🪙 金币富豪榜 / Coin Leaderboard", 0xF1C40F,
            "coin", " coins"
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⚔️ 胜场王 / Wins", style=discord.ButtonStyle.primary, row=0)
    async def win_lb(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        embed = await self._get_top(
            "SELECT discord_id, wins FROM mmr ORDER BY wins DESC LIMIT 20",
            (), "⚔️ 胜场王 / Wins Leaderboard", 0x2ECC71,
            "wins", " wins"
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏆 MVP榜 / MVP", style=discord.ButtonStyle.primary, row=0)
    async def mvp_lb(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT discord_id, COUNT(*) as mvp_count
                FROM match_players WHERE mvp = 1
                GROUP BY discord_id ORDER BY mvp_count DESC LIMIT 20
            """)
            rows = cur.fetchall()
        embed = discord.Embed(title="🏆 MVP榜 / MVP Leaderboard", color=0xE74C3C)
        if not rows:
            embed.description = "暂无数据 / No data yet."
        else:
            lines = []
            for i, (uid, cnt) in enumerate(rows, 1):
                medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"#{i}"
                lines.append(f"{medal} <@{uid}> — {cnt} MVP")
            embed.description = "\n".join(lines)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📊 等级榜 / Level", style=discord.ButtonStyle.primary, row=0)
    async def level_lb(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        embed = await self._get_top(
            "SELECT discord_id, xp FROM users ORDER BY xp DESC LIMIT 20",
            (), "📊 等级榜 / Level Leaderboard", 0x9B59B6,
            "xp", " XP"
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🎤 语音榜 / Voice", style=discord.ButtonStyle.primary, row=1)
    async def voice_lb(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        embed = await self._get_top(
            "SELECT discord_id, total_minutes FROM voice_time ORDER BY total_minutes DESC LIMIT 20",
            (), "🎤 语音榜 / Voice Leaderboard", 0x3498DB,
            "minutes", " min"
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀ 返回 / Back", style=discord.ButtonStyle.danger, row=1)
    async def back_btn(self, interaction: discord.Interaction, button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(str(interaction.user.id), interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
            return
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


class Leaderboard(commands.Cog):
    """排行榜系统 / Leaderboard system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gmpt-leaderboard", description="查看排行榜 / View leaderboard")
    async def leaderboard_cmd(self, interaction: discord.Interaction):
        view = LeaderboardView()
        embed = discord.Embed(
            title="🏆 排行榜 / Leaderboard",
            description="选择一个排行榜类别 / Choose a leaderboard category:",
            color=0x3498DB,
        )
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
    logger.info("Leaderboard cog loaded")
