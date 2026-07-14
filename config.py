import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE = os.path.join(os.path.dirname(__file__), "data.db")
