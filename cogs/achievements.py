"""
GMPT Bot — Achievement System / 成就系统
"""
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx
import logging
import datetime

logger = logging.getLogger(__name__)

DEFAULT_ACHIEVEMENTS = [
    # name, description, reward, hidden
    ("First Steps / 初入江湖", "Join the MMORPG system / 首次进入MMORPG系统", 100, 0),
    ("Rich / 家财万贯", "Reach 10,000 coins / 累积拥有10000金币", 500, 0),
    ("Millionaire / 百万富翁", "Reach 1,000,000 coins / 累积拥有100万金币", 5000, 0),
    ("Hard Worker / 勤劳致富", "Complete 50 jobs / 完成50次打工", 300, 0),
    ("Workaholic / 打工皇帝", "Complete 500 jobs / 完成500次打工", 2000, 0),
    ("Casino King / 赌神", "Win 10 times in gambling / 赌博赢10次", 300, 0),
    ("Boss Slayer / 屠龙勇士", "Defeat 5 bosses / 击败5个Boss", 400, 0),
    ("Dungeon Explorer / 地城探险家", "Complete 10 dungeon floors / 通关10层副本", 400, 0),
    ("PVP Champion / 竞技场之王", "Win 5 PVP matches / PVP胜利5次", 400, 0),
    ("Collector / 收藏家", "Own 10 unique items / 拥有10种不同物品", 200, 0),
    ("Skill Master / 技能大师", "Learn 5 skills / 学会5个技能", 200, 0),
    ("Level Up! / 升级了!", "Reach level 5 / 达到5级", 200, 0),
    ("Master / 大师", "Reach level 10 / 达到10级", 500, 0),
    ("Grandmaster / 宗师", "Reach level 20 / 达到20级", 1000, 0),
    ("Legend / 传说", "Reach level 50 / 达到50级", 5000, 0),
    ("Social Butterfly / 社交达人", "Join a clan / 加入公会", 100, 0),
    ("Pet Owner / 宠物主人", "Adopt a pet / 领养一只宠物", 100, 0),
    ("Equipment Upgrader / 装备强化师", "Upgrade equipment 5 times / 强化装备5次", 300, 0),
    ("Daily Hero / 每日英雄", "Complete 10 daily quests / 完成10个每日任务", 200, 0),
    ("Streak Master / 连续签到王", "7-day checkin streak / 连续签到7天", 300, 0),
]


class AchievementsView(discord.ui.View):
    """成就面板 / Achievement panel."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view

    async def _get_achievements_embed(self):
        """Build the achievements status embed."""
        with get_db_ctx() as conn:
            cur = conn.cursor()
            # Get all achievements
            cur.execute("SELECT id, name, description, reward, hidden FROM achievements ORDER BY id")
            all_achs = cur.fetchall()
            # Get user unlocked achievements
            cur.execute("SELECT achievement_id FROM user_achievements WHERE user_id = ?", (self.uid,))
            unlocked = {row[0] for row in cur.fetchall()}

        embed = discord.Embed(
            title="Achievements / 成就系统",
            description="Your achievement progress / 你的成就进度:",
            color=0xF1C40F,
        )

        unlocked_count = 0
        lines = []
        for ach_id, name, desc, reward, hidden in all_achs:
            if hidden and ach_id not in unlocked:
                lines.append(f"????? — ??? (Hidden / 隐藏成就)")
                continue
            if ach_id in unlocked:
                lines.append(f"✅ **{name}** — +🪙{reward}\n     {desc}")
                unlocked_count += 1
            else:
                lines.append(f"⬜ **{name}** — +🪙{reward}\n     {desc}")

        embed.add_field(
            name=f"Progress / 进度: {unlocked_count}/{len(all_achs)}",
            value="\n".join(lines) if lines else "No achievements found / 暂无成就",
            inline=False,
        )
        embed.set_footer(text="Achievements unlock automatically as you play! / 成就会在游戏中自动解锁！")
        return embed

    @discord.ui.button(label="Refresh 刷新", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def refresh_btn(self, interaction: discord.Interaction, button):
        embed = await self._get_achievements_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Back 返回主面板", emoji="🔙", style=discord.ButtonStyle.danger, row=0)
    async def back_btn(self, interaction: discord.Interaction, button):
        if self.main_view:
            from cogs.mmorpg_shop import build_main_embed
            embed = build_main_embed(self.uid, interaction.user.display_name)
            try:
                await interaction.response.edit_message(embed=embed, view=self.main_view)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=self.main_view)
        else:
            embed = discord.Embed(
                title="Achievements / 成就",
                description="Use `/gmpt-mmorpg` to go back / 使用 `/gmpt-mmorpg` 返回",
                color=0xF1C40F,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)


def init_achievements():
    """Ensure default achievements exist in the database."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM achievements")
        count = cur.fetchone()[0]
        if count == 0:
            for name, desc, reward, hidden in DEFAULT_ACHIEVEMENTS:
                cur.execute(
                    "INSERT INTO achievements (name, description, reward, hidden) VALUES (?, ?, ?, ?)",
                    (name, desc, reward, hidden),
                )
            conn.commit()
            logger.info(f"Inserted {len(DEFAULT_ACHIEVEMENTS)} default achievements")


def unlock_achievement(user_id: str, achievement_name: str):
    """Try to unlock an achievement by exact name match. Returns (success, reward)."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        # Find the achievement
        cur.execute("SELECT id, reward FROM achievements WHERE name = ?", (achievement_name,))
        row = cur.fetchone()
        if not row:
            return False, 0
        ach_id, reward = row
        # Check if already unlocked
        cur.execute("SELECT 1 FROM user_achievements WHERE user_id = ? AND achievement_id = ?", (user_id, ach_id))
        if cur.fetchone():
            return False, 0  # Already unlocked
        # Unlock it
        cur.execute(
            "INSERT OR IGNORE INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
            (user_id, ach_id),
        )
        conn.commit()
        return True, reward


class Achievements(commands.Cog):
    """成就系统 / Achievement system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_achievements()

    @app_commands.command(name="gmpt-achievements", description="View achievements / 查看成就")
    async def achievements_cmd(self, interaction: discord.Interaction):
        view = AchievementsView(uid=str(interaction.user.id))
        embed = await view._get_achievements_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Achievements(bot))
    logger.info("Achievements cog loaded")
