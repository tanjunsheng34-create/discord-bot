"""
Discord Bot — LOL 自定义比赛 5v5
"""
import os
import sys
import json
import io
import asyncio
import discord
from discord.ext import commands
from database import get_db, init_db
from config import TOKEN

if TOKEN is None:
    print("请在 .env 文件中设置 DISCORD_TOKEN")
    exit(1)

# =============================================================================
# Auto-backup configuration (Discord channel-based, no volume needed)
# =============================================================================
BACKUP_CHANNEL_ID = os.getenv("BACKUP_CHANNEL_ID")          # REQUIRED for auto-backup
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
# Auto-backup → Discord channel
# =============================================================================
def export_backup_data():
    """Export all BACKUP_TABLES rows as a dict. Runs in thread — sync safe."""
    conn = get_db()
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
    return data


async def _get_backup_channel():
    """Resolve BACKUP_CHANNEL_ID → discord.TextChannel, or None if not configured."""
    if not BACKUP_CHANNEL_ID:
        return None
    try:
        cid = int(BACKUP_CHANNEL_ID)
    except ValueError:
        print(f"[Backup] Invalid BACKUP_CHANNEL_ID: {BACKUP_CHANNEL_ID}", file=sys.stderr)
        return None
    # fetch_channel works even before full guild cache is ready
    channel = bot.get_channel(cid)
    if channel is None:
        try:
            channel = await bot.fetch_channel(cid)
        except Exception:
            pass
    if channel is None:
        print(f"[Backup] Channel {cid} not accessible.", file=sys.stderr)
    return channel


async def _find_last_backup(channel):
    """Find the most recent backup message sent by this bot in the channel. Returns Message or None."""
    try:
        async for msg in channel.history(limit=30):
            if msg.author == bot.user and msg.attachments:
                for att in msg.attachments:
                    if att.filename.endswith(".json"):
                        return msg
    except Exception:
        pass
    return None


async def do_backup():
    """Export DB → upload JSON to backup channel, deleting the previous backup message first."""
    channel = await _get_backup_channel()
    if channel is None:
        return

    try:
        # Delete last backup message to keep channel tidy
        last = await _find_last_backup(channel)
        if last:
            try:
                await last.delete()
            except Exception:
                pass

        # Export & send
        data = await asyncio.to_thread(export_backup_data)
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        file = discord.File(io.BytesIO(json_str.encode("utf-8")), filename="gmpt_auto_backup.json")

        total = sum(len(v) for v in data.values())
        msg = await channel.send(
            content=f"Auto-backup — {total} records / {len(BACKUP_TABLES)} tables",
            file=file,
        )
        print(f"[Backup] Sent {total} records → channel {BACKUP_CHANNEL_ID} (msg {msg.id})")
    except Exception as e:
        print(f"[Backup] Failed: {e}", file=sys.stderr)


async def auto_backup_loop():
    """Background task: periodically push backup to Discord channel."""
    if not BACKUP_CHANNEL_ID:
        print("[Backup] BACKUP_CHANNEL_ID not set — auto-backup disabled.")
        return

    await asyncio.sleep(15)  # let bot fully start

    while True:
        await asyncio.sleep(BACKUP_INTERVAL)
        await do_backup()


# =============================================================================
# Auto-restore ← Discord channel
# =============================================================================
async def auto_restore():
    """On startup: download latest backup JSON from Discord channel and restore to SQLite."""
    if not BACKUP_CHANNEL_ID:
        print("[Restore] BACKUP_CHANNEL_ID not set — skipping auto-restore.")
        return

    await bot.wait_until_ready()

    channel = await _get_backup_channel()
    if channel is None:
        return

    try:
        last = await _find_last_backup(channel)
        if last is None:
            print("[Restore] No backup message found in channel, starting fresh.")
            return

        # Find JSON attachment
        attachment = None
        for att in last.attachments:
            if att.filename.endswith(".json"):
                attachment = att
                break
        if attachment is None:
            print("[Restore] No JSON attachment on backup message.")
            return

        content = await attachment.read()
        data = json.loads(content.decode("utf-8"))
    except Exception as e:
        print(f"[Restore] Failed to fetch backup: {e}", file=sys.stderr)
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
    # Restore data from Discord backup channel (if configured)
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

    # Start background backup loop (pushes to Discord channel)
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
