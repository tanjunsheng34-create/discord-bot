import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")

# 自动备份配置 (Discord channel-based)
BACKUP_CHANNEL_ID = os.getenv("BACKUP_CHANNEL_ID")          # REQUIRED for auto-backup
BACKUP_INTERVAL = int(os.getenv("BACKUP_INTERVAL", "300"))  # seconds
BACKUP_TABLES = [
    "users",
    "voice_tracker",
    "daily_checkin",
    "giveaway",
    "giveaway_entries",
    "user_inventory",
    "giveaways",
    "giveaway_tickets",
    "tournaments",
    "match_signups",
    "matches",
]

# DB_PATH: env var for persistence (SparkedHost), default to local data.db
DATABASE = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))

# Ensure database directory exists
_db_dir = os.path.dirname(DATABASE)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)
