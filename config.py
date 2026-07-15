import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# DB_PATH: env var for Railway Volume persistence, default to local data.db
DATABASE = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))

# Ensure database directory exists (needed for Railway Volume mount /data)
_db_dir = os.path.dirname(DATABASE)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)
