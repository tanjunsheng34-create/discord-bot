import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE = os.path.join(os.path.dirname(__file__), "data.db")
GUILD_ID = int(os.getenv("GUILD_ID", "1394150073826279664"))
