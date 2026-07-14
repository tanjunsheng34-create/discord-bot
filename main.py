"""
Discord Bot — LOL 自定义比赛 5v5
"""
import discord
from discord.ext import commands
from database import init_db
from config import TOKEN, GUILD_ID

if TOKEN is None:
    print("请在 .env 文件中设置 DISCORD_TOKEN")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.economy",
    "cogs.lol",
]


@bot.event
async def on_ready():
    init_db()
    try:
        # 同步命令（不清除旧的，避免 sync 失败导致零命令）
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Sync error: {e}")
    print(f"Bot online: {bot.user}")


async def main():
    import traceback
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            print(f"Loaded: {cog}")
        except Exception as e:
            print(f"FAILED to load {cog}: {e}")
            traceback.print_exc()
    await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
