"""
一次性清理脚本：用旧 Bot Token 登录后清除 Discord 上残留的命令缓存。
GMPT-2/3/4 的容器已关，但其 slash 命令仍缓存在 Discord 侧。
本脚本依次登录这三个 Bot，逐一 clear_commands + sync 清除。
运行一次即可：python clear_old_bots.py
"""
import asyncio
import os
import sys

import discord
from discord import Object
from discord.ext import commands

from config import GUILD_ID

# ── 旧 Bot Token 映射 ──
# Pterodactyl 环境变量已注入，直接 os.getenv 读取
TOKENS: dict[str, str] = {
    "GMPT-2": os.getenv("TOKEN_ECONOMY", ""),
    "GMPT-3": os.getenv("TOKEN_COMMUNITY", ""),
    "GMPT-4": os.getenv("TOKEN_ARENA", ""),
}

GUILD_ID_INT: int = int(GUILD_ID) if GUILD_ID else 0


async def clear_bot(label: str, token: str) -> None:
    """用指定 token 登录 → 清除 guild + 全局命令 → 登出。"""
    if not token:
        print(f"[跳过] {label}: 环境变量未设置 TOKEN")
        return

    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"[{label}] 已登录: {bot.user} (ID: {bot.user.id})")

        guild_obj = Object(id=GUILD_ID_INT)
        guild_cleared = 0
        global_cleared = 0

        # ── 清除 guild 命令 ──
        if GUILD_ID_INT:
            bot.tree.clear_commands(guild=guild_obj)
            try:
                synced = await bot.tree.sync(guild=guild_obj)
                guild_cleared = len(synced)
                print(f"[{label}] guild sync 返回 {guild_cleared} 条 (应为 0)")
            except Exception as e:
                print(f"[{label}] guild sync 失败: {e}")

        # ── 清除全局命令 ──
        bot.tree.clear_commands(guild=None)
        try:
            synced = await bot.tree.sync()
            global_cleared = len(synced)
            print(f"[{label}] 全局 sync 返回 {global_cleared} 条 (应为 0)")
        except Exception as e:
            print(f"[{label}] 全局 sync 失败: {e}")

        print(f"[{label}] 完成: guild={guild_cleared}, global={global_cleared}")
        await bot.close()

    await bot.start(token)


async def main() -> None:
    if not GUILD_ID_INT:
        print("错误: GUILD_ID 未设置，无法清除 guild 命令。")
        print("请在 Pterodactyl 环境变量中设置 GUILD_ID 或 .env 文件中添加 GUILD_ID=...")
        sys.exit(1)

    print("=" * 50)
    print("清理 GMPT-2/3/4 残留命令")
    print(f"目标 Guild ID: {GUILD_ID_INT}")
    print("=" * 50)

    for label, token in TOKENS.items():
        print(f"\n--- {label} ---")
        await clear_bot(label, token)

    print("\n" + "=" * 50)
    print("全部清理完成。重启 GMPT-1 后应只显示其自身的 71 条命令。")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
