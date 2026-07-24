import os
from datetime import timezone, timedelta
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

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

TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")
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
RESULT_CHANNEL_ID: int = 1442412993269731452
LOL_VOTE_CHANNEL_ID: int = 1397073481627340961
MEMBER_LEAVE_LOG_CHANNEL_ID: int = 1435096093737222336

# Economy channels
SHOP_LOG_CHANNEL_ID: int = 1528241284177854624
ACHIEVEMENTS_CHANNEL_ID: int = 1528241092640768101
ITEM_REQUESTS_CHANNEL_ID: int = 1528249993914220625

# Whisper (匿名树洞) channel
WHISPER_CHANNEL_ID: Optional[int] = None


def _get_env_int(key: str, default: int = 0) -> int:
    """Helper to read integer env var."""
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


# Ensure database directory exists
_db_dir = os.path.dirname(DATABASE)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)
