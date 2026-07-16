"""
Discord Bot — LOL 自定义比赛 5v5
"""
import os
import asyncio
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
    "cogs.economy",
    "cogs.tournament",
    "cogs.lol",
    "cogs.dashboard",
    "cogs.giveaway",
    "cogs.voice_tracker",
    "cogs.admin_backup",
]


@bot.event
async def on_ready():
    init_db()
    print(f"Bot online: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Sync error: {e}")


# =============================================================================
# Railway 保活 — 内置 HTTP 服务器，每 30 秒自检，防止容器休眠
# =============================================================================
async def health_server():
    """启动一个简单的 HTTP 服务器响应 /health 请求，占用 Railway 端口。"""
    from aiohttp import web

    async def health(request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/health", health)
    port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Health server running on port {port}")


async def health_check():
    """每 30 秒自检一次，确保 HTTP 路由持续活跃。"""
    import aiohttp

    while True:
        await asyncio.sleep(30)
        try:
            port = os.getenv("PORT", "8080")
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{port}/health") as resp:
                    pass
        except Exception:
            pass


async def main():
    import traceback

    # 启动保活服务
    asyncio.create_task(health_server())
    asyncio.create_task(health_check())

    for cog in COGS:
        try:
            await bot.load_extension(cog)
            print(f"Loaded: {cog}")
        except Exception as e:
            print(f"FAILED to load {cog}: {e}")
            traceback.print_exc()
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
