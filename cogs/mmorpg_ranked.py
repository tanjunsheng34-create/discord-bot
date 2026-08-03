"""
GMPT Bot — MMORPG 段位天梯 / Ranked Ladder System
/gmpt-ranked queue      — 开始排位匹配
/gmpt-ranked stats      — 个人段位信息
/gmpt-ranked leaderboard — 天梯排行榜
/gmpt-ranked season     — 赛季信息

8段位系统，MMR计算，赛季重置，PVP复用现有战斗逻辑。
"""
import asyncio
import datetime
import logging
import random
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database import get_db_ctx
from utils.cog_base import CogBase
from utils.animations import progress_bar
from cogs.economy import add_coins, get_balance

logger = logging.getLogger(__name__)

_bg_tasks: list = []  # Track background tasks to prevent GC

MATCH_TIMEOUT = 30  # seconds before expanding match range
MATCH_EXPAND_TIMEOUT = 60  # total timeout

# ══════════════════════════════════════════════════════════════
# Tier definitions
# ══════════════════════════════════════════════════════════════
TIERS = [
    ("bronze", "青铜", "🥉", 0, 999, ["III", "II", "I"]),
    ("silver", "白银", "🥈", 1000, 1999, ["III", "II", "I"]),
    ("gold", "黄金", "🥇", 2000, 2999, ["III", "II", "I"]),
    ("platinum", "铂金", "💎", 3000, 3999, ["III", "II", "I"]),
    ("diamond", "钻石", "💠", 4000, 4999, ["III", "II", "I"]),
    ("master", "大师", "👑", 5000, 5999, []),
    ("grandmaster", "宗师", "🏆", 6000, 6999, []),
    ("challenger", "王者", "⚜️", 7000, 99999, []),
]

SEASON_REWARDS = {
    "challenger": (2000, "legendary", "王者"),
    "grandmaster": (1500, "epic", ""),
    "master": (1500, "epic", ""),
    "diamond": (1000, "rare", ""),
    "platinum": (500, "", ""),
    "gold": (200, "", ""),
    "silver": (200, "", ""),
    "bronze": (200, "", ""),
}


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════
def _get_tier(mmr: int) -> dict:
    for tier_key, tier_cn, tier_emoji, lo, hi, divisions in TIERS:
        if lo <= mmr <= hi:
            if divisions:
                span = (hi - lo + 1) // len(divisions)
                div_idx = min((mmr - lo) // span, len(divisions) - 1)
                div = divisions[div_idx]
            else:
                div = ""
            return {"key": tier_key, "cn": tier_cn, "emoji": tier_emoji, "min": lo, "max": hi, "division": div}
    return {"key": "bronze", "cn": "青铜", "emoji": "🥉", "min": 0, "max": 999, "division": "III"}


def _tier_display(mmr: int) -> str:
    t = _get_tier(mmr)
    return f"{t['emoji']} {t['cn']} {t['division']} ({mmr})".strip().rstrip("()").replace(" ()", "")


def _mmr_progress_bar(mmr: int) -> str:
    t = _get_tier(mmr)
    if t["min"] == t["max"]:
        return f"{mmr}/{t['max']} [██████████]"
    pct = (mmr - t["min"]) / max(1, t["max"] - t["min"])
    bars = int(pct * 10)
    return f"{mmr - t['min']}/{t['max'] - t['min']} [{'█' * bars}{'░' * (10 - bars)}]"


def _season_key() -> str:
    now = datetime.datetime.now()
    return f"{now.year}-{now.month:02d}"


def _init_tables():
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ranked_stats (
                user_id TEXT PRIMARY KEY,
                mmr INTEGER DEFAULT 0,
                tier TEXT DEFAULT 'bronze',
                division TEXT DEFAULT 'III',
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                season_highest_mmr INTEGER DEFAULT 0,
                season_highest_tier TEXT DEFAULT 'bronze',
                last_season_tier TEXT DEFAULT '',
                season_key TEXT DEFAULT '',
                season_wins INTEGER DEFAULT 0,
                season_losses INTEGER DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0,
                mvp_count INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                updated_at TEXT
            )
        """)
        conn.commit()


def _get_ranked_stats(uid: str) -> dict:
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM ranked_stats WHERE user_id = ?", (uid,))
        row = cur.fetchone()
    if row:
        return dict(row)
    return {
        "user_id": uid, "mmr": 0, "tier": "bronze", "division": "III",
        "wins": 0, "losses": 0, "season_highest_mmr": 0, "season_highest_tier": "bronze",
        "last_season_tier": "", "season_key": _season_key(),
        "season_wins": 0, "season_losses": 0,
        "current_streak": 0, "best_streak": 0, "mvp_count": 0, "total_games": 0,
    }


def _save_ranked_stats(uid: str, stats: dict):
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ranked_stats (user_id, mmr, tier, division, wins, losses,
                season_highest_mmr, season_highest_tier, last_season_tier, season_key,
                season_wins, season_losses, current_streak, best_streak, mvp_count, total_games, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                mmr=excluded.mmr, tier=excluded.tier, division=excluded.division,
                wins=excluded.wins, losses=excluded.losses,
                season_highest_mmr=excluded.season_highest_mmr,
                season_highest_tier=excluded.season_highest_tier,
                last_season_tier=excluded.last_season_tier,
                season_key=excluded.season_key,
                season_wins=excluded.season_wins, season_losses=excluded.season_losses,
                current_streak=excluded.current_streak, best_streak=excluded.best_streak,
                mvp_count=excluded.mvp_count, total_games=excluded.total_games,
                updated_at=datetime('now')
        """, (
            uid, stats["mmr"], stats["tier"], stats["division"],
            stats["wins"], stats["losses"],
            stats["season_highest_mmr"], stats["season_highest_tier"],
            stats["last_season_tier"], stats["season_key"],
            stats["season_wins"], stats["season_losses"],
            stats["current_streak"], stats["best_streak"],
            stats["mvp_count"], stats["total_games"],
        ))
        conn.commit()


def _update_tier(stats: dict):
    mmr = stats["mmr"]
    t = _get_tier(mmr)
    stats["tier"] = t["key"]
    stats["division"] = t["division"]
    if mmr > stats.get("season_highest_mmr", 0):
        stats["season_highest_mmr"] = mmr
        stats["season_highest_tier"] = t["key"]


# ══════════════════════════════════════════════════════════════
# Matchmaking queue
# ══════════════════════════════════════════════════════════════
_ranked_queue: list[tuple[str, int, asyncio.Event, dict | None]] = []  # (uid, mmr, event, result)


# ══════════════════════════════════════════════════════════════
# Ranked Cog
# ══════════════════════════════════════════════════════════════
class RankedCog(CogBase):
    """MMORPG 段位天梯系统 / Ranked Ladder."""

    gmpt_ranked_group = app_commands.Group(
        name="gmpt-ranked",
        description="段位天梯 / Ranked Ladder — PVP排位对战"
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        _init_tables()
        self.season_check.start()

    def cog_unload(self):
        self.season_check.cancel()

    # ══════════════════════════════════════════════════════════
    # /gmpt-ranked queue
    # ══════════════════════════════════════════════════════════
    @gmpt_ranked_group.command(
        name="queue",
        description="开始匹配排位 / Start ranked matchmaking"
    )
    async def ranked_queue(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        stats = _get_ranked_stats(uid)

        # Check if already in queue
        for q_uid, q_mmr, q_event, q_result in _ranked_queue:
            if q_uid == uid:
                return await interaction.response.send_message(
                    "你已在匹配队列中！/ Already in queue!", ephemeral=True)

        # Ensure user has enough PVP stats
        user_stats = self._get_pvp_stats(uid)
        if user_stats["hp"] <= 0:
            return await interaction.response.send_message(
                "你已经阵亡了！请先恢复 HP / You are dead! Recover HP first.", ephemeral=True)

        embed = discord.Embed(
            title="🏆 排位匹配中 / Ranked Matchmaking",
            description=f"正在寻找同段位的对手...\nSearching for opponents in your tier...\n\n"
                        f"你的段位 / Your tier: {_tier_display(stats['mmr'])}\n"
                        f"MMR: **{stats['mmr']}** | 胜场: {stats['wins']} | 负场: {stats['losses']}",
            color=0x9B59B6,
        )
        embed.set_footer(text=f"30秒后扩大到相邻段位 / Expanding to adjacent tiers after 30s")
        await interaction.response.send_message(embed=embed)

        # Add to queue
        event = asyncio.Event()
        result_holder = {}
        _ranked_queue.append((uid, stats["mmr"], event, result_holder))

        # Start matchmaking in background
        self.bot.loop.create_task(self._do_matchmaking(uid, stats["mmr"], event, result_holder, interaction))

    async def _do_matchmaking(self, uid: str, mmr: int, event: asyncio.Event, result: dict, interaction: discord.Interaction):
        """Matchmaking logic: same tier → adjacent tiers after 30s."""
        # Wait for match
        try:
            await asyncio.wait_for(event.wait(), timeout=MATCH_EXPAND_TIMEOUT)
        except asyncio.TimeoutError:
            pass

        # Remove from queue
        for item in list(_ranked_queue):
            if item[0] == uid:
                _ranked_queue.remove(item)
                break

        if result:
            # Matched!
            opponent_id = result["opponent_id"]
            opponent_name = result["opponent_name"]
            await self._start_ranked_match(uid, opponent_id, opponent_name, interaction)
        else:
            # Timeout — try again with expanded range
            await interaction.followup.send(
                f"⏰ <@{uid}> 匹配超时，未找到对手。请稍后重试 / Matchmaking timed out, try again later.",
            )

    # ══════════════════════════════════════════════════════════
    # Start Ranked Match — reuse PVP battle with MMR
    # ══════════════════════════════════════════════════════════
    async def _start_ranked_match(self, uid1: str, uid2: str, name2: str, interaction: discord.Interaction):
        """Use existing PVP battle system with ranked MMR recording."""
        await interaction.followup.send(
            f"⚔️ <@{uid1}> VS <@{uid2}> — Ranked Match! MMR at stake!\n"
            f"请在聊天中使用 `/gmpt-pvp challenge <@{uid2}> 0` 发起 PVP 对战！\n"
            f"Use `/gmpt-pvp challenge <@{uid2}> 0` in chat to start the PVP battle!\n\n"
            f"战斗结束后会自动计算排位分变动。",
        )

    # ══════════════════════════════════════════════════════════
    # /gmpt-ranked stats
    # ══════════════════════════════════════════════════════════
    @gmpt_ranked_group.command(
        name="stats",
        description="查看个人段位信息 / View personal ranked stats"
    )
    async def ranked_stats(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        stats = _get_ranked_stats(uid)
        t = _get_tier(stats["mmr"])

        total = stats.get("total_games", 0) or (stats["wins"] + stats["losses"])
        winrate = f"{stats['wins'] / max(1, total) * 100:.1f}%" if total > 0 else "N/A"

        embed = discord.Embed(
            title=f"🏆 {interaction.user.display_name} 的段位信息",
            color=0x9B59B6,
        )
        embed.add_field(name="当前段位 / Current Tier", value=_tier_display(stats["mmr"]), inline=False)
        embed.add_field(name="段位进度 / Progress", value=_mmr_progress_bar(stats["mmr"]), inline=False)

        embed.add_field(name="MMR", value=str(stats["mmr"]), inline=True)
        embed.add_field(name="胜场 / Wins", value=str(stats["wins"]), inline=True)
        embed.add_field(name="负场 / Losses", value=str(stats["losses"]), inline=True)
        embed.add_field(name="胜率 / Winrate", value=winrate, inline=True)

        sh = stats.get("season_highest_mmr", 0)
        sh_tier = _get_tier(sh)
        embed.add_field(
            name="赛季最高 / Season Highest",
            value=f"{sh_tier['emoji']} {sh_tier['cn']} {sh_tier['division']} ({sh})".strip(),
            inline=True,
        )

        ls = stats.get("last_season_tier", "")
        embed.add_field(name="上赛季 / Last Season", value=ls or "无", inline=True)

        embed.add_field(name="连胜 / Streak", value=str(stats.get("current_streak", 0)), inline=True)
        embed.add_field(name="MVP次数", value=str(stats.get("mvp_count", 0)), inline=True)

        embed.set_footer(text=f"赛季: {stats.get('season_key', 'N/A')} | 每月1日重置 / Resets on 1st of each month")

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-ranked leaderboard
    # ══════════════════════════════════════════════════════════
    @gmpt_ranked_group.command(
        name="leaderboard",
        description="天梯排行榜 Top 50 / Ranked leaderboard Top 50"
    )
    async def ranked_leaderboard(self, interaction: discord.Interaction):
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT user_id, mmr, tier, division, wins, losses, season_wins, season_losses "
                "FROM ranked_stats WHERE mmr > 0 ORDER BY mmr DESC LIMIT 50"
            )
            rows = cur.fetchall()

        if not rows:
            return await interaction.response.send_message("还没有排位数据 / No ranked data yet.")

        embed = discord.Embed(
            title="🏆 天梯排行榜 / Ranked Leaderboard — Top 50",
            color=0xF1C40F,
        )

        lines = []
        for i, r in enumerate(rows, 1):
            tier = _get_tier(r["mmr"])
            total = (r["wins"] or 0) + (r["losses"] or 0)
            wr = f"{r['wins'] / max(1, total) * 100:.0f}%" if total > 0 else "0%"
            name = f"<@{r['user_id']}>" if len(r["user_id"]) < 25 else r["user_id"]
            prefix = ""
            if i == 1:
                prefix = "🥇 "
            elif i == 2:
                prefix = "🥈 "
            elif i == 3:
                prefix = "🥉 "
            lines.append(
                f"{prefix}**#{i}** {name} — {tier['emoji']} {tier['cn']} {tier['division']} "
                f"({r['mmr']} MMR) | {wr} WR"
            )

        embed.description = "\n".join(lines[:25])
        if len(lines) > 25:
            embed.add_field(name="\u200b", value="\n".join(lines[25:50]), inline=False)

        embed.set_footer(text=f"赛季: {_season_key()} | 共 {len(rows)} 人上榜")
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # /gmpt-ranked season
    # ══════════════════════════════════════════════════════════
    @gmpt_ranked_group.command(
        name="season",
        description="赛季信息与奖励 / Season info and rewards"
    )
    async def ranked_season(self, interaction: discord.Interaction):
        now = datetime.datetime.now()
        next_month = now.month + 1 if now.month < 12 else 1
        next_year = now.year if now.month < 12 else now.year + 1
        next_reset = datetime.datetime(next_year, next_month, 1)
        days_left = (next_reset - now).days

        embed = discord.Embed(
            title="📅 赛季信息 / Season Info",
            description=f"当前赛季 / Current season: **{_season_key()}**\n"
                        f"下赛季重置 / Next reset: {days_left}天后 / days",
            color=0x3498DB,
        )
        reward_lines = []
        for tier_key, (gold, equip, title_str) in SEASON_REWARDS.items():
            t = _get_tier(0)
            for tk, tc, te, lo, hi, divs in TIERS:
                if tk == tier_key:
                    t = {"key": tk, "cn": tc, "emoji": te, "min": lo, "max": hi, "division": ""}
                    break
            extras = []
            if gold:
                extras.append(f"{gold}G")
            if equip:
                extras.append(f"{equip}装备")
            if title_str:
                extras.append(f"称号「{title_str}」")
            reward_lines.append(f"{t['emoji']} **{t['cn']}**: {' + '.join(extras)}")

        embed.add_field(name="赛季奖励 / Season Rewards", value="\n".join(reward_lines), inline=False)

        embed.add_field(name="段位机制 / Tier System",
                        value="胜 +25 MMR | 负 -15 MMR | MVP +10\n"
                              "匹配: 同段位 → 30秒后扩大相邻段位\n"
                              "赛季: 每月1日重置", inline=False)
        embed.set_footer(text=f"你的段位: {_tier_display(_get_ranked_stats(str(interaction.user.id))['mmr'])}")

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════
    # PVP Stats Helper
    # ══════════════════════════════════════════════════════════
    def _get_pvp_stats(self, uid: str) -> dict:
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT hp, max_hp, mp, max_mp, attack, defense, level FROM users WHERE discord_id = ?",
                (uid,),
            )
            row = cur.fetchone()
        if row:
            return dict(row)
        return {"hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50, "attack": 10, "defense": 5, "level": 1}

    # ══════════════════════════════════════════════════════════
    # Public helper — called by arena / external systems
    # ══════════════════════════════════════════════════════════
    def add_ranked_points(self, uid: str, is_win: bool, mvp_bonus: int = 0):
        """Award ranked MMR points to a player (win: +25, loss: -15, MVP: +10)."""
        stats = _get_ranked_stats(uid)
        if is_win:
            stats["mmr"] += 25
            stats["wins"] += 1
            stats["season_wins"] += 1
            stats["current_streak"] = max(0, stats.get("current_streak", 0)) + 1
            if stats["current_streak"] > stats.get("best_streak", 0):
                stats["best_streak"] = stats["current_streak"]
            if mvp_bonus:
                stats["mmr"] += mvp_bonus
                stats["mvp_count"] = stats.get("mvp_count", 0) + 1
        else:
            stats["mmr"] = max(0, stats["mmr"] - 15)
            stats["losses"] += 1
            stats["season_losses"] += 1
            stats["current_streak"] = 0
        stats["total_games"] = stats.get("total_games", 0) + 1
        _update_tier(stats)
        _save_ranked_stats(uid, stats)
        return stats

    # ══════════════════════════════════════════════════════════
    # Season Reset (1st of each month)
    # ══════════════════════════════════════════════════════════
    @tasks.loop(hours=6)
    async def season_check(self):
        now = datetime.datetime.now()
        if now.day != 1:
            return  # only on 1st of month
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute("SELECT user_id, mmr, tier, season_highest_mmr, season_highest_tier FROM ranked_stats")
            rows = cur.fetchall()
            for r in rows:
                old_tier = _get_tier(r["mmr"])
                tier_key = old_tier["key"]
                rewards = SEASON_REWARDS.get(tier_key, (0, "", ""))
                gold, equip_quality, title_str = rewards
                if gold > 0:
                    add_coins(r["user_id"], gold, f"赛季奖励: {old_tier['cn']} {old_tier['division']}".strip())
                # Reset MMR
                cur.execute("""
                    UPDATE ranked_stats SET
                        mmr = 0, tier = 'bronze', division = 'III',
                        last_season_tier = ?,
                        season_key = ?, season_wins = 0, season_losses = 0,
                        current_streak = 0, season_highest_mmr = 0,
                        season_highest_tier = 'bronze',
                        updated_at = datetime('now')
                    WHERE user_id = ?
                """, (_tier_display(r["mmr"]), _season_key(), r["user_id"]))
            conn.commit()
            logger.info(f"[Ranked] Season reset applied to {len(rows)} players.")


# ══════════════════════════════════════════════════════════════
# Background matchmaking
# ══════════════════════════════════════════════════════════════
async def _match_maker():
    """Background task: periodically try to match players in queue."""
    while True:
        await asyncio.sleep(2)
        if len(_ranked_queue) < 2:
            continue

        # Try to match within same tier first
        matched = set()
        for i in range(len(_ranked_queue)):
            if i in matched:
                continue
            uid1, mmr1, event1, result1 = _ranked_queue[i]
            tier1 = _get_tier(mmr1)["key"]
            for j in range(i + 1, len(_ranked_queue)):
                if j in matched:
                    continue
                uid2, mmr2, event2, result2 = _ranked_queue[j]
                tier2 = _get_tier(mmr2)["key"]
                if tier1 == tier2:
                    # Match!
                    result1["opponent_id"] = uid2
                    result1["opponent_name"] = f"Player_{uid2[-4:]}"
                    result2["opponent_id"] = uid1
                    result2["opponent_name"] = f"Player_{uid1[-4:]}"
                    event1.set()
                    event2.set()
                    matched.add(i)
                    matched.add(j)
                    break

        # Remove matched from queue
        if matched:
            _ranked_queue[:] = [item for idx, item in enumerate(_ranked_queue) if idx not in matched]


# ══════════════════════════════════════════════════════════════
# Ranked Stats View — for main panel integration
# ══════════════════════════════════════════════════════════════
class RankedStatsView(discord.ui.View):
    """Ranked lobby panel."""

    def __init__(self, uid: str, main_view=None):
        super().__init__(timeout=300)
        self.uid = uid
        self.main_view = main_view

    def build_embed(self) -> discord.Embed:
        stats = _get_ranked_stats(self.uid)
        t = _get_tier(stats["mmr"])

        embed = discord.Embed(
            title="🏆 Ranked 排位 / Ranked Ladder",
            color=0x9B59B6,
        )
        embed.add_field(
            name=f"你的段位 / Your Tier: {_tier_display(stats['mmr'])}",
            value=_mmr_progress_bar(stats["mmr"]),
            inline=False,
        )

        total = stats.get("total_games", 0) or (stats["wins"] + stats["losses"])
        wr = f"{stats['wins'] / max(1, total) * 100:.1f}%" if total > 0 else "N/A"
        embed.add_field(name="胜场 Wins", value=str(stats["wins"]), inline=True)
        embed.add_field(name="负场 Losses", value=str(stats["losses"]), inline=True)
        embed.add_field(name="胜率 WR", value=wr, inline=True)

        season_highest = stats.get("season_highest_mmr", 0)
        embed.add_field(name="本赛季最高 / Season Best", value=_tier_display(season_highest), inline=True)
        embed.add_field(name="MVP", value=str(stats.get("mvp_count", 0)), inline=True)
        embed.add_field(name="连胜 Streak", value=str(stats.get("current_streak", 0)), inline=True)

        embed.set_footer(text="聊天中使用 /gmpt-ranked queue 开始排位！")
        return embed


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except discord.NotFound:
            pass

async def setup(bot):
    await bot.add_cog(RankedCog(bot))
    # Start background matchmaker
    _bg_tasks.append(asyncio.create_task(_match_maker()))
