import os
from datetime import timezone, timedelta
from typing import Optional

from dotenv import load_dotenv

# Load .env if present; silently skip if missing (Pterodactyl injects env vars directly).
try:
    load_dotenv()
except Exception:
    pass

# UTC+8 timezone — single source of truth
TZ_UTC8 = timezone(timedelta(hours=8))
# Tier constants (was in tournament.py)
TIER_SEED = {"CHALLENGER": 1, "GRANDMASTER": 2, "MASTER": 3,
             "DIAMOND": 4, "EMERALD": 5, "PLATINUM": 6,
             "GOLD": 7, "SILVER": 8, "BRONZE": 9, "IRON": 10}

TIER_SCORE = {
    "CHALLENGER": 5, "GRANDMASTER": 5, "MASTER": 5,
    "DIAMOND": 4, "EMERALD": 3, "PLATINUM": 3,
    "GOLD": 2, "SILVER": 1, "BRONZE": 1, "IRON": 1, "UNRANKED": 1,
}

TOKEN: Optional[str] = os.getenv("TOKEN_FULL") or os.getenv("DISCORD_TOKEN")

# ── 多实例 TOKEN 字典 ──
# 不设置 BOT_ROLE 时为多实例模式，每个角色独立 TOKEN
TOKENS: dict = {
    "full": os.getenv("TOKEN_FULL", ""),
    "mmorpg": os.getenv("TOKEN_ECONOMY", ""),
    "community": os.getenv("TOKEN_COMMUNITY", ""),
    "arena": os.getenv("TOKEN_ARENA", ""),
}

# 向后兼容：BOT_ROLE 指定时走单实例模式
BOT_ROLE = os.getenv("BOT_ROLE", "").strip().lower()
if BOT_ROLE:
    TOKEN = TOKENS.get(BOT_ROLE, TOKEN) if BOT_ROLE in TOKENS else TOKEN
RIOT_API_KEY: str = os.getenv("RIOT_API_KEY", "")

# 自动备份配置 (Discord channel-based)
BACKUP_CHANNEL_ID: Optional[str] = os.getenv("BACKUP_CHANNEL_ID")          # REQUIRED for auto-backup
BACKUP_INTERVAL: int = int(os.getenv("BACKUP_INTERVAL", "300"))  # seconds
BACKUP_TABLES: list = [
    "users",
    "voice_tracker",
    "daily_checkin",
    "giveaway_entries",
    "user_inventory",
    "giveaways",
    "giveaway_tickets",
    "tournaments",
    "match_signups",
    "matches",
]

# DB_PATH: env var for persistence (SparkedHost), default to local data.db
DATABASE: str = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))

# =============================================================================
# Discord Channel/Server IDs — centralized for maintainability
# =============================================================================

# Dashboard / Match channels
POST_MATCH_VC_TEAM_A: int = 1453208983358935121
POST_MATCH_VC_TEAM_B: int = 1438050912814895186
TEAM_B_VC_ID: int = 1437626921394372658
LIVE_ROOM_ID: int = 1442412877301416006
RESULT_CHANNEL_ID: int = 1442412993269731452
LOL_VOTE_CHANNEL_ID: int = 1397073481627340961
MEMBER_LEAVE_LOG_CHANNEL_ID: int = 1435096093737222336

# 比赛开始通知频道 (可配置, 默认与 POST_MATCH_VC_TEAM_A 一致)
MATCH_START_NOTIFY_CHANNEL_ID: int = int(os.getenv("MATCH_START_NOTIFY_CHANNEL_ID", str(POST_MATCH_VC_TEAM_A)))

# Daily reminder channel
DAILY_REMINDER_CHANNEL_ID: int = 1528241061007327354

# Welcome channel
WELCOME_CHANNEL_ID: int = 1398991787523313675

# Economy channels
SHOP_LOG_CHANNEL_ID: int = 1528241284177854624
ACHIEVEMENTS_CHANNEL_ID: int = 1528241092640768101
ITEM_REQUESTS_CHANNEL_ID: int = 1528249993914220625

# Whisper (匿名树洞) channel — also used as game center
WHISPER_CHANNEL_ID: Optional[int] = 1394296801246445708

# Game center channel (shared with whisper / 游戏中心 | Games)
GAMES_CHANNEL_ID: int = 1394296801246445708


# ── Guild ID for instant guild sync ──
GUILD_ID = os.getenv("GUILD_ID")

# ══════════════════════════════════════════════════════════════
# MMORPG Element System
# ══════════════════════════════════════════════════════════════
ELEMENTS = ["Fire", "Water", "Wind", "Earth"]

ELEMENT_WEAKNESS = {
    "Fire": "Water",   # Fire is weak to Water
    "Water": "Earth",  # Water is weak to Earth
    "Earth": "Wind",   # Earth is weak to Wind
    "Wind": "Fire",    # Wind is weak to Fire
}

ELEMENT_STRONG = {
    "Fire": "Wind",    # Fire > Wind
    "Wind": "Earth",   # Wind > Earth
    "Earth": "Water",  # Earth > Water
    "Water": "Fire",   # Water > Fire
}

ELEMENT_ADVANTAGE_MULTIPLIER = 1.30  # +30% damage when element advantage
ELEMENT_GEAR_BONUS = 0.10            # +10% stat boost for matching element gear

# Element assignment by class
CLASS_ELEMENT = {
    "warrior": "Earth",
    "mage": "Fire",
    "assassin": "Wind",  # Rogue class
    "priest": "Water",
    "paladin": "Earth",
    "archer": "Wind",
}

# ── Boss auto-spawn ──
BOSS_SPAWN_CHANNEL_ID: int = 1532937712041066647
BOSS_SPAWN_INTERVAL: int = 7200  # 2 hours in seconds
BOSS_SPAWN_DIFFICULTY_WEIGHTS = {"简单": 40, "普通": 30, "困难": 20, "极限": 10}
BOSS_AUTO_TIMEOUT: int = 1800  # 30 minutes in seconds

# Boss name pool for auto-spawn
BOSS_NAME_POOL = [
    "烈焰魔龙", "冰霜巨人", "暗影领主", "地狱犬",
    "风暴之鹰", "深海巨兽", "岩石巨像", "雷霆战熊",
    "幽冥猎手", "炽焰凤凰", "剧毒蛇皇", "幻影刺客",
    "虚空行者", "岩浆巨人", "暴风之眼", "月影狼王",
]

# ══════════════════════════════════════════════════════════════
# MMORPG Event Schedule / 限时活动日程
# ══════════════════════════════════════════════════════════════
# month → day → (event_key, event_name, boss_name)
EVENT_SCHEDULE = {
    1: {  # January - New Year
        1: ("newyear_dragon", "新年 Dragon", "年兽龙王"),
        2: ("newyear_dragon", "新年 Dragon", "年兽龙王"),
        3: ("newyear_dragon", "新年 Dragon", "年兽龙王"),
    },
    10: {  # October - Halloween
        30: ("halloween_pumpkin", "万圣 Pumpkin King", "南瓜王"),
        31: ("halloween_pumpkin", "万圣 Pumpkin King", "南瓜王"),
    },
    12: {  # December - Christmas
        24: ("christmas_ice", "圣诞 Ice Lord", "冰霜领主"),
        25: ("christmas_ice", "圣诞 Ice Lord", "冰霜领主"),
    },
    7: {  # July - Summer
        1: ("summer_beach", "暑假 Beach Boss", "沙滩霸主"),
        15: ("summer_beach", "暑假 Beach Boss", "沙滩霸主"),
    },
    8: {  # August - Summer
        1: ("summer_beach", "暑假 Beach Boss", "沙滩霸主"),
    },
}

# Event channel ID (same as boss spawn channel by default)
EVENT_CHANNEL_ID: int = 1532937712041066647

# Event boss survival time (2 hours in seconds)
EVENT_BOSS_SURVIVAL: int = 7200

# Weekend double drop event (random: 20% chance each Saturday/Sunday)
DOUBLE_DROP_WEEKEND_CHANCE: float = 0.20

# Ensure database directory exists
_db_dir = os.path.dirname(DATABASE)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)
