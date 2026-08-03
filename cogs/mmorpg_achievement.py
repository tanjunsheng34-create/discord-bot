"""
GMPT Bot — MMORPG Achievement & Badges / 成就徽章系统
/gmpt-ach — 查看成就

20个成就覆盖战斗/财富/装备/等级/签到/钓鱼/特殊系统。
达成后自动解锁称号，显示在个人资料。
"""
import datetime
import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import get_db_ctx

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Achievement Definitions (20 achievements)
# ach_id: (name_zh, name_en, category, description_zh, description_en, title, check_func_name)
# ══════════════════════════════════════════════════════════════
ACHIEVEMENTS = {
    # Combat / 战斗
    1: ("首杀", "First Blood", "combat", "击败1只怪物", "Slay your first monster", "新手猎人", "check_first_kill"),
    2: ("百杀", "Centurion", "combat", "击败100只怪物", "Slay 100 monsters", "屠戮者", "check_hundred_kills"),
    3: ("千杀", "Slayer", "combat", "击败1000只怪物", "Slay 1000 monsters", "杀戮机器", "check_thousand_kills"),
    4: ("地牢全通", "Dungeon Master", "combat", "通关所有副本", "Clear all dungeons", "地牢征服者", "check_dungeon_all"),
    5: ("世界Boss猎手", "World Boss Hunter", "combat", "参与世界Boss战斗10次", "Participate in 10 world boss battles", "猎手", "check_wb_participation"),
    # Wealth / 财富
    6: ("小康", "Fortune", "wealth", "累积赚取1000金币", "Earn 1000 total coins", "富裕者", "check_wealth_1k"),
    7: ("巨富", "Wealthy", "wealth", "累积赚取10000金币", "Earn 10000 total coins", "大亨", "check_wealth_10k"),
    8: ("富翁", "Millionaire", "wealth", "累积赚取50000金币", "Earn 50000 total coins", "百万富翁", "check_wealth_50k"),
    # Equipment / 装备
    9: ("传说之握", "Legendary Touch", "equip", "拥有一件传说品质装备", "Own a legendary equipment", "传说持有者", "check_legendary_eq"),
    10: ("史诗收藏", "Epic Collector", "equip", "拥有10件史诗装备", "Own 10 epic equipments", "史诗收藏家", "check_epic_eq"),
    11: ("强化大师", "Enhance Master", "equip", "装备强化到+10", "Enhance equipment to +10", "强化师", "check_enhance_10"),
    # Level / 等级
    12: ("新手", "Novice", "level", "达到Lv.10", "Reach Lv.10", "冒险者", "check_level_10"),
    13: ("高手", "Expert", "level", "达到Lv.20", "Reach Lv.20", "精英", "check_level_20"),
    14: ("大师", "Master", "level", "达到Lv.30", "Reach Lv.30", "大师", "check_level_30"),
    15: ("传说", "Legend", "level", "达到Lv.50", "Reach Lv.50", "传说", "check_level_50"),
    # Check-in / 签到
    16: ("签到达人", "Check-in Pro", "checkin", "连续签到7天", "7-day check-in streak", "忠实玩家", "check_checkin_7"),
    17: ("签到大师", "Check-in Master", "checkin", "连续签到30天", "30-day check-in streak", "铁杆粉丝", "check_checkin_30"),
    # Fishing / 钓鱼
    18: ("渔夫", "Fisherman", "fishing", "钓到10条鱼", "Catch 10 fish", "渔夫", "check_fish_10"),
    19: ("钓鱼大师", "Master Angler", "fishing", "钓到100条鱼", "Catch 100 fish", "钓鱼大师", "check_fish_100"),
    20: ("远古发现", "Ancient Discovery", "fishing", "钓到远古鱼", "Catch the Ancient Fish", "远古探索者", "check_ancient_fish"),
}

CATEGORY_ORDER = ["combat", "wealth", "equip", "level", "checkin", "fishing"]

CATEGORY_EMOJI = {
    "combat": "⚔️",
    "wealth": "🪙",
    "equip": "🛡️",
    "level": "⭐",
    "checkin": "📅",
    "fishing": "🎣",
}


def _add_coins(uid: str, amount: int, reason: str):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (discord_id, username) VALUES (?, '') ON CONFLICT(discord_id) DO NOTHING",
            (uid,),
        )
        cur.execute("UPDATE users SET score = score + ? WHERE discord_id = ?", (amount, uid))
        cur.execute(
            "INSERT INTO transactions (discord_id, amount, reason) VALUES (?, ?, ?)",
            (uid, amount, reason),
        )
        conn.commit()


# ══════════════════════════════════════════════════════════════
# DB Init
# ══════════════════════════════════════════════════════════════
def _init_achievement_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mmorpg_achievements (
                user_id TEXT NOT NULL,
                ach_id INTEGER NOT NULL,
                unlocked_at TEXT NOT NULL,
                PRIMARY KEY (user_id, ach_id)
            )
        """)
        conn.commit()

_init_achievement_tables()


def _get_unlocked_achievements(uid: str) -> set:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT ach_id FROM mmorpg_achievements WHERE user_id = ?", (uid,))
        return {row["ach_id"] for row in cur.fetchall()}


def _get_user_titles(uid: str) -> list:
    """Get list of unlocked titles for the user."""
    unlocked = _get_unlocked_achievements(uid)
    return [ACHIEVEMENTS[a][5] for a in unlocked if a in ACHIEVEMENTS]


def _get_primary_title(uid: str) -> str:
    """Get the highest-rarity (legendary) title or the most recent."""
    unlocked = _get_unlocked_achievements(uid)
    if not unlocked:
        return ""
    # Prefer legendary achievements (15, 20, 9, 8)
    priority = [15, 20, 9, 8, 14, 17, 11, 5, 4, 3, 10, 7, 13, 19, 16, 18, 6, 12, 2, 1]
    for ach_id in priority:
        if ach_id in unlocked:
            return ACHIEVEMENTS[ach_id][5]
    return ACHIEVEMENTS[max(unlocked)][5]


# ══════════════════════════════════════════════════════════════
# Check functions — called by other systems to auto-unlock
# ══════════════════════════════════════════════════════════════

def unlock_achievement(uid: str, ach_id: int) -> bool:
    """Try to unlock an achievement. Returns True if newly unlocked."""
    if ach_id not in ACHIEVEMENTS:
        return False

    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM mmorpg_achievements WHERE user_id = ? AND ach_id = ?", (uid, ach_id))
        if cur.fetchone():
            return False  # Already unlocked

        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
        cur.execute(
            "INSERT INTO mmorpg_achievements (user_id, ach_id, unlocked_at) VALUES (?, ?, ?)",
            (uid, ach_id, now),
        )
        conn.commit()

    # Give coin reward
    _, _, _, _, _, title, _ = ACHIEVEMENTS[ach_id]
    reward = {1: 50, 2: 200, 3: 500, 4: 300, 5: 200, 6: 100, 7: 300, 8: 500,
              9: 400, 10: 300, 11: 300, 12: 100, 13: 200, 14: 300, 15: 500,
              16: 200, 17: 400, 18: 100, 19: 300, 20: 500}.get(ach_id, 100)

    _add_coins(uid, reward, f"Achievement Unlocked: {title} (ach_id={ach_id})")
    logger.info(f"User {uid} unlocked achievement {ach_id} — {title}")
    return True


def check_and_unlock_all(uid: str):
    """Run all check functions and unlock any newly completed achievements."""
    for ach_id in ACHIEVEMENTS:
        func_name = ACHIEVEMENTS[ach_id][6]
        try:
            func = globals().get(func_name)
            if func and func(uid):
                unlock_achievement(uid, ach_id)
        except Exception as e:
            logger.warning(f"Failed to check achievement {ach_id}: {e}")


# --- Check implementations (stub — return bool) ---

def check_first_kill(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM world_boss_damage WHERE user_id = ?", (uid,))
        cnt = cur.fetchone()["cnt"] if cur.fetchone() else 0
    # Also check boss kills table
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM boss_stats WHERE user_id = ? AND kills > 0", (uid,))
        boss_kills = cur.fetchone() is not None
    return cnt > 0 or boss_kills


def check_hundred_kills(uid: str) -> bool:
    total = 0
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COALESCE(SUM(kills), 0) as total FROM boss_stats WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            if row:
                total += row["total"]
        except Exception:
            pass
        try:
            cur.execute("SELECT COUNT(*) as cnt FROM world_boss_damage WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            if row:
                total += row["cnt"]
        except Exception:
            pass
    return total >= 100


def check_thousand_kills(uid: str) -> bool:
    total = 0
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COALESCE(SUM(kills), 0) as total FROM boss_stats WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            if row:
                total += row["total"]
        except Exception:
            pass
        try:
            cur.execute("SELECT COUNT(*) as cnt FROM world_boss_damage WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            if row:
                total += row["cnt"]
        except Exception:
            pass
    return total >= 1000


def check_dungeon_all(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(DISTINCT floor) as cnt FROM dungeon_progress WHERE user_id = ? AND cleared = 1", (uid,))
            row = cur.fetchone()
            if row:
                return row["cnt"] >= 10
        except Exception:
            pass
    return False


def check_wb_participation(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(DISTINCT boss_id) as cnt FROM world_boss_damage WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            if row and row["cnt"] >= 10:
                return True
        except Exception:
            pass
    return False


def check_wealth_1k(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE discord_id = ? AND amount > 0", (uid,))
            row = cur.fetchone()
            if row:
                return row["total"] >= 1000
        except Exception:
            pass
    return False


def check_wealth_10k(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE discord_id = ? AND amount > 0", (uid,))
            row = cur.fetchone()
            if row:
                return row["total"] >= 10000
        except Exception:
            pass
    return False


def check_wealth_50k(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE discord_id = ? AND amount > 0", (uid,))
            row = cur.fetchone()
            if row:
                return row["total"] >= 50000
        except Exception:
            pass
    return False


def check_legendary_eq(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM user_inventory WHERE user_id = ? AND item_name LIKE '%legendary%' AND item_type = 'equipment'", (uid,))
            return cur.fetchone() is not None
        except Exception:
            return False


def check_epic_eq(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) as cnt FROM user_inventory WHERE user_id = ? AND item_name LIKE '%epic%' AND item_type = 'equipment'", (uid,))
            row = cur.fetchone()
            if row:
                return row["cnt"] >= 10
        except Exception:
            pass
    return False


def check_enhance_10(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM user_equipment WHERE user_id = ? AND enhance_level >= 10", (uid,))
            return cur.fetchone() is not None
        except Exception:
            return False


def check_level_10(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["level"] or 0) >= 10 if row else False


def check_level_20(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["level"] or 0) >= 20 if row else False


def check_level_30(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["level"] or 0) >= 30 if row else False


def check_level_50(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT level FROM users WHERE discord_id = ?", (uid,))
        row = cur.fetchone()
    return (row["level"] or 0) >= 50 if row else False


def check_checkin_7(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT streak FROM mmorpg_checkin WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            if row:
                return row["streak"] >= 7
        except Exception:
            pass
    return False


def check_checkin_30(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT streak FROM mmorpg_checkin WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            if row:
                return row["streak"] >= 30
        except Exception:
            pass
    return False


def check_fish_10(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) as cnt FROM mmorpg_fish_collection WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            if row:
                return row["cnt"] >= 10
        except Exception:
            pass
    return False


def check_fish_100(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) as cnt FROM mmorpg_fish_collection WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            if row:
                return row["cnt"] >= 100
        except Exception:
            pass
    return False


def check_ancient_fish(uid: str) -> bool:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM mmorpg_fish_collection WHERE user_id = ? AND fish_name LIKE '%Ancient Fish%'", (uid,))
            return cur.fetchone() is not None
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════
# Views
# ══════════════════════════════════════════════════════════════

PAGE_SIZE = 5


class AchievementsView(discord.ui.View):
    """成就徽章面板 / Achievements & Badges Panel — paginated."""

    def __init__(self, uid: str, main_view=None, page: int = 0):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view
        self.page = page

    @property
    def _flat_achievements(self):
        """Flatten categories into ordered achievement list."""
        result = []
        for cat in CATEGORY_ORDER:
            for ach_id, data in ACHIEVEMENTS.items():
                if data[2] == cat:
                    result.append((ach_id,) + data)
        return result

    @property
    def _total_pages(self):
        return max(1, (len(self._flat_achievements) + PAGE_SIZE - 1) // PAGE_SIZE)

    def build_embed(self) -> discord.Embed:
        unlocked = _get_unlocked_achievements(self.uid)
        title = _get_primary_title(self.uid)
        flat = self._flat_achievements

        total = len(flat)
        unlocked_count = len(unlocked)

        start = self.page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)

        embed = discord.Embed(
            title="🏆 Achievements & Badges / 成就徽章",
            description=(
                f"**Progress / 进度: {unlocked_count}/{total}**\n"
                + (f"**Title / 称号: 「{title}」**\n" if title else "")
                + f"Page {self.page + 1}/{self._total_pages}"
            ),
            color=0xF1C40F,
        )

        for ach_id, name_zh, name_en, category, desc_zh, desc_en, ach_title, _ in flat[start:end]:
            is_unlocked = ach_id in unlocked
            emoji = CATEGORY_EMOJI.get(category, "📍")
            status = "✅" if is_unlocked else "🔒"

            line = (
                f"{status} {emoji} **{name_zh} / {name_en}**\n"
                f"   {desc_zh} | {desc_en}\n"
                f"   Title / 称号: 「{ach_title}」"
            )
            embed.add_field(name=f"#{ach_id}", value=line, inline=False)

        embed.set_footer(text="Achievements auto-unlock as you play! | 成就自动解锁！")
        return embed

    @discord.ui.button(label="Prev 上一页", emoji="◀️", style=discord.ButtonStyle.primary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return
        self.page = (self.page - 1) % self._total_pages
        embed = self.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Next 下一页", emoji="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return
        self.page = (self.page + 1) % self._total_pages
        embed = self.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Refresh 刷新", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if uid != self.uid:
            await interaction.response.send_message("Not your panel / 不是你的面板", ephemeral=True)
            return
        check_and_unlock_all(uid)
        embed = self.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.InteractionResponded:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Back 返回", emoji="🔙", style=discord.ButtonStyle.danger, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
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
                description="Use `/gmpt-mmorpg` to return.\n使用 `/gmpt-mmorpg` 返回。",
                color=0xF1C40F,
            )
            try:
                await interaction.response.edit_message(embed=embed, view=None)
            except discord.InteractionResponded:
                await interaction.edit_original_response(embed=embed, view=None)


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass

# ══════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════

class AchievementCog(commands.Cog):
    """成就徽章系统 / Achievement & Badges system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gmpt-ach", description="查看成就徽章 / View achievements & badges")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def ach_cmd(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        check_and_unlock_all(uid)  # Auto-unlock any completed achievements
        view = AchievementsView(uid)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(AchievementCog(bot))
    logger.info("MMORPG Achievement cog loaded")
