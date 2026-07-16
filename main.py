"""
Discord Bot — LOL 自定义比赛 5v5
"""
import os
import sys
import json
import asyncio
import atexit
import discord
from discord.ext import commands
from database import get_db
from config import TOKEN

if TOKEN is None:
    print("请在 .env 文件中设置 DISCORD_TOKEN")
    exit(1)

# =============================================================================
# Auto-backup configuration
# =============================================================================
BACKUP_PATH = os.getenv("BACKUP_PATH", "/data/backup.json")
BACKUP_INTERVAL = int(os.getenv("BACKUP_INTERVAL", "300"))  # seconds
BACKUP_TABLES = [
    "users",
    "voice_tracker",
    "daily_checkin",
    "giveaway",
    "giveaway_entries",
    "user_inventory",
]

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


# =============================================================================
# Auto-backup: synchronous core (safe for atexit / signal handlers)
# =============================================================================
def do_backup_sync():
    """Export all database tables to BACKUP_PATH. Fully synchronous — safe for atexit."""
    try:
        from database import get_db as _get_db
        conn = _get_db()
        cur = conn.cursor()
        data = {}
        for table in BACKUP_TABLES:
            try:
                cur.execute(f"SELECT * FROM {table}")
                rows = [dict(row) for row in cur.fetchall()]
                data[table] = rows
            except Exception:
                data[table] = []
        conn.close()

        backup_dir = os.path.dirname(BACKUP_PATH)
        if backup_dir:
            os.makedirs(backup_dir, exist_ok=True)
        with open(BACKUP_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        total = sum(len(v) for v in data.values())
        print(f"[Backup] Saved {total} records across {len(BACKUP_TABLES)} tables → {BACKUP_PATH}")
    except Exception as e:
        print(f"[Backup] Failed: {e}", file=sys.stderr)


async def do_backup():
    """Async wrapper around do_backup_sync — runs in a thread to avoid blocking."""
    await asyncio.to_thread(do_backup_sync)


async def auto_backup_loop():
    """Background task: save backup periodically."""
    await asyncio.sleep(10)  # let bot fully start
    while True:
        await asyncio.sleep(BACKUP_INTERVAL)
        await do_backup()


# =============================================================================
# Auto-restore: load backup on startup
# =============================================================================
async def auto_restore():
    """Restore database tables from BACKUP_PATH if the file exists."""
    if not os.path.exists(BACKUP_PATH):
        print(f"[Restore] No backup found at {BACKUP_PATH}, skipping.")
        return

    try:
        with open(BACKUP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Restore] Failed to read backup: {e}", file=sys.stderr)
        return

    conn = get_db()
    cur = conn.cursor()
    restored = {}

    try:
        # users
        if "users" in data and data["users"]:
            for u in data["users"]:
                cur.execute(
                    "INSERT OR REPLACE INTO users (discord_id, username, score, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (u.get("discord_id"), u.get("username", ""), u.get("score", 500),
                     u.get("created_at", "")),
                )
            restored["users"] = len(data["users"])

        # voice_tracker
        if "voice_tracker" in data and data["voice_tracker"]:
            for v in data["voice_tracker"]:
                cur.execute(
                    "INSERT OR REPLACE INTO voice_tracker "
                    "(user_id, total_seconds, login_days, total_joins, last_join_date, last_join_time) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (v.get("user_id"), v.get("total_seconds", 0), v.get("login_days", 0),
                     v.get("total_joins", 0), v.get("last_join_date"), v.get("last_join_time")),
                )
            restored["voice_tracker"] = len(data["voice_tracker"])

        # daily_checkin
        if "daily_checkin" in data and data["daily_checkin"]:
            for c in data["daily_checkin"]:
                cur.execute(
                    "INSERT OR REPLACE INTO daily_checkin (discord_id, last_date, streak) "
                    "VALUES (?, ?, ?)",
                    (c.get("discord_id"), c.get("last_date", ""), c.get("streak", 0)),
                )
            restored["daily_checkin"] = len(data["daily_checkin"])

        # giveaway
        if "giveaway" in data and data["giveaway"]:
            for g in data["giveaway"]:
                cur.execute(
                    "INSERT OR REPLACE INTO giveaway "
                    "(id, guild_id, channel_id, message_id, prize, duration_minutes, "
                    "winner_count, created_by, ends_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (g.get("id"), g.get("guild_id"), g.get("channel_id"), g.get("message_id"),
                     g.get("prize"), g.get("duration_minutes"), g.get("winner_count"),
                     g.get("created_by"), g.get("ends_at"), g.get("status", "active")),
                )
            restored["giveaway"] = len(data["giveaway"])

        # giveaway_entries
        if "giveaway_entries" in data and data["giveaway_entries"]:
            for e in data["giveaway_entries"]:
                cur.execute(
                    "INSERT OR REPLACE INTO giveaway_entries (id, giveaway_id, user_id) "
                    "VALUES (?, ?, ?)",
                    (e.get("id"), e.get("giveaway_id"), e.get("user_id")),
                )
            restored["giveaway_entries"] = len(data["giveaway_entries"])

        # user_inventory
        if "user_inventory" in data and data["user_inventory"]:
            for inv in data["user_inventory"]:
                cur.execute(
                    "INSERT OR REPLACE INTO user_inventory (user_id, item_id, quantity) "
                    "VALUES (?, ?, ?)",
                    (inv.get("user_id"), inv.get("item_id"), inv.get("quantity", 1)),
                )
            restored["user_inventory"] = len(data["user_inventory"])

        conn.commit()

        summary = ", ".join(f"{k}: {v}" for k, v in restored.items())
        print(f"[Restore] Complete: {summary}")
    except Exception as e:
        print(f"[Restore] Failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


# =============================================================================
# Bot events
# =============================================================================
@bot.event
async def on_ready():
    init_db()
    # Auto-restore backup data before anything else
    await auto_restore()
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

    # Register atexit: one last backup on normal shutdown
    atexit.register(do_backup_sync)

    # Start background backup loop
    asyncio.create_task(auto_backup_loop())

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
