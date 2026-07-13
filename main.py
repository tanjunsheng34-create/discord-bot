"""
Discord Bot — LOL 自定义比赛 5v5
"""
import discord
from discord.ext import commands
from database import init_db
from config import TOKEN

if TOKEN is None:
    print("请在 .env 文件中设置 DISCORD_TOKEN")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.lol",
    "cogs.economy",
]


@bot.event
async def on_ready():
    init_db()
    # 先清除 Discord 上所有旧全局命令，再同步新命令
    try:
        old_cmds = await bot.tree.fetch_commands()
        for cmd in old_cmds:
            await cmd.delete()
            print(f"Deleted old: {cmd.name}")
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Sync error: {e}")
    print(f"Bot online: {bot.user}")


async def main():
    for cog in COGS:
        await bot.load_extension(cog)
        print(f"Loaded: {cog}")
    await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
