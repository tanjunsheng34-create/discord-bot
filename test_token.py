import asyncio
import discord
from config import TOKEN

async def test():
    try:
        async with discord.Client(intents=discord.Intents.default()) as c:
            await c.login(TOKEN)
            print(f"登录成功: {c.user}")
    except Exception as e:
        print(f"登录失败: {e}")

asyncio.run(test())
