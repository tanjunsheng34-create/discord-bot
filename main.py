"""
Discord Bot — LOL 自定义比赛 5v5
"""
import os
import sys
import json
import io
import logging
import asyncio
import discord
from discord.ext import commands
from database import get_db, init_db
from config import TOKEN, BACKUP_CHANNEL_ID, BACKUP_INTERVAL, BACKUP_TABLES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

if TOKEN is None:
    logger.critical("请在 .env 文件中设置 DISCORD_TOKEN")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.announce",
    "cogs.economy",
    "cogs.tournament",
    "cogs.lol",
    "cogs.dashboard",
    "cogs.giveaway",
    "cogs.voice_tracker",
    "cogs.queue",
    "cogs.admin_backup",
    "cogs.match",
    "cogs.daily",
    "cogs.help",
    "cogs.music",
    "cogs.peiwans",
]


# =============================================================================
# Global app command error handler
# =============================================================================
async def setup_hook(self):
    """Register global on_app_command_error handler."""

    @self.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        # Already handled by local error handlers
        if interaction.command is not None and getattr(interaction.command, "_has_error_handler", False):
            # Pass to cog-level handler if exists
            if hasattr(error, "handled"):
                return
            raise error

        if isinstance(error, discord.app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"冷却中，请在 {error.retry_after:.0f} 秒后重试 / "
                f"On cooldown, retry after {error.retry_after:.0f}s",
                ephemeral=True,
            )
        elif isinstance(error, discord.app_commands.MissingPermissions):
            await interaction.response.send_message(
                "你没有使用此命令的权限 / You don't have permission.",
                ephemeral=True,
            )
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            await interaction.response.send_message(
                "机器人缺少必要权限 / Bot missing required permissions.",
                ephemeral=True,
            )
        else:
            logger.error(
                f"Unhandled command error in /{interaction.command.qualified_name if interaction.command else 'unknown'}: "
                f"{error}",
                exc_info=True,
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "命令执行时发生意外错误，请稍后再试 / An unexpected error occurred, please try again later.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "命令执行时发生意外错误，请稍后再试 / An unexpected error occurred, please try again later.",
                        ephemeral=True,
                    )
            except Exception:
                pass

bot.setup_hook = setup_hook.__get__(bot)


# =============================================================================
# Auto-install missing dependencies
# =============================================================================
import subprocess
import sys

def ensure_deps():
    """Auto-install missing Python and system dependencies.
    Returns the path to the ffmpeg binary directory.
    """
    pkgs = {
        "nacl": "PyNaCl",
        "croniter": "croniter",
        "yt_dlp": "yt-dlp",
    }
    for import_name, pip_name in pkgs.items():
        try:
            __import__(import_name)
        except ImportError:
            print(f"Installing missing dependency: {pip_name} ...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pip_name]
            )

    # --- PyNaCl / nacl import verification (debug discord voice warning) ---
    print("--- nacl import diagnostics ---")
    nacl_import_ok = True
    try:
        import nacl
        print(f"import nacl OK: {nacl.__file__}")
    except ImportError as e:
        nacl_import_ok = False
        print(f"import nacl FAILED: {e}")

    if nacl_import_ok:
        for submod in ("nacl.utils", "nacl.bindings"):
            try:
                __import__(submod)
                print(f"import {submod} OK")
            except ImportError as e:
                nacl_import_ok = False
                print(f"import {submod} FAILED: {e}")

    if not nacl_import_ok:
        print("nacl import failed — force-reinstalling PyNaCl ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--force-reinstall", "PyNaCl"]
        )
        try:
            import nacl
            import nacl.utils
            import nacl.bindings
            print("nacl reimport OK after force-reinstall")
        except ImportError as e:
            print(f"CRITICAL: nacl still fails after force-reinstall: {e}")
    else:
        print("All nacl imports verified OK")
    print("--- end nacl diagnostics ---")

    # Install davey (discord.py 2.7.1 voice dependency)
    try:
        import davey
        print("davey already installed.")
    except ImportError:
        print("Installing davey library...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "davey"]
            )
            import davey
            print("davey installed successfully.")
        except Exception as e:
            print(f"pip install davey failed: {e}")
            print("Trying GitHub install...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install",
                     "git+https://github.com/davey/davey.git"]
                )
                import davey
                print("davey installed from GitHub successfully.")
            except Exception as e2:
                print(f"GitHub install also failed: {e2}")
                print("davey unavailable — voice features may not work.")
                print("To fix: downgrade discord.py to 2.6.0 in requirements.txt")

    # Install imageio-ffmpeg (bundled FFmpeg binary, no root/apt required)
    try:
        import imageio_ffmpeg
    except ImportError:
        print("Installing imageio-ffmpeg ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "imageio-ffmpeg"]
        )
        import imageio_ffmpeg

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    print(f"imageio-ffmpeg 提供的 FFmpeg: {ffmpeg_exe}")
    return ffmpeg_exe

# 在 bot.run() 之前调用，保存路径到 bot.ffmpeg_path
bot.ffmpeg_path = ensure_deps()


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
        logger.error(f"Invalid BACKUP_CHANNEL_ID: {BACKUP_CHANNEL_ID}")
        return None
    # fetch_channel works even before full guild cache is ready
    channel = bot.get_channel(cid)
    if channel is None:
        try:
            channel = await bot.fetch_channel(cid)
        except Exception:
            pass
    if channel is None:
        logger.error(f"Channel {cid} not accessible.")
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
        logger.info(f"Backup sent: {total} records → channel {BACKUP_CHANNEL_ID} (msg {msg.id})")
    except Exception as e:
        logger.error(f"Backup failed: {e}")


async def auto_backup_loop():
    """Background task: periodically push backup to Discord channel."""
    if not BACKUP_CHANNEL_ID:
        logger.info("BACKUP_CHANNEL_ID not set — auto-backup disabled.")
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
        logger.info("BACKUP_CHANNEL_ID not set — skipping auto-restore.")
        return

    auto_restore_env = os.getenv("AUTO_RESTORE", "0").strip().lower()
    if auto_restore_env not in ("1", "true"):
        logger.info(f"AUTO_RESTORE={auto_restore_env!r} — auto-restore disabled (set to '1' to enable).")
        return

    await bot.wait_until_ready()

    channel = await _get_backup_channel()
    if channel is None:
        return

    try:
        last = await _find_last_backup(channel)
        if last is None:
            logger.info("No backup message found in channel, starting fresh.")
            return

        # Find JSON attachment
        attachment = None
        for att in last.attachments:
            if att.filename.endswith(".json"):
                attachment = att
                break
        if attachment is None:
            logger.info("No JSON attachment on backup message.")
            return

        content = await attachment.read()
        data = json.loads(content.decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to fetch backup: {e}")
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

        # giveaways (economy.py new system)
        if "giveaways" in data and data["giveaways"]:
            for g in data["giveaways"]:
                cur.execute(
                    "INSERT OR REPLACE INTO giveaways "
                    "(id, channel_id, prize, created_by, drawn, winner_id, created_at, draw_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (g.get("id"), g.get("channel_id"), g.get("prize"), g.get("created_by"),
                     g.get("drawn", 0), g.get("winner_id"), g.get("created_at"), g.get("draw_at")),
                )
            restored["giveaways"] = len(data["giveaways"])

        # giveaway_tickets
        if "giveaway_tickets" in data and data["giveaway_tickets"]:
            for t in data["giveaway_tickets"]:
                cur.execute(
                    "INSERT OR REPLACE INTO giveaway_tickets (discord_id, tickets) "
                    "VALUES (?, ?)",
                    (t.get("discord_id"), t.get("tickets", 0)),
                )
            restored["giveaway_tickets"] = len(data["giveaway_tickets"])

        # tournaments
        if "tournaments" in data and data["tournaments"]:
            for t in data["tournaments"]:
                cur.execute(
                    "INSERT OR REPLACE INTO tournaments "
                    "(id, name, max_teams, team_size, status, created_by, created_at, "
                    "format, max_players, rounds, tier_restriction, role_pick) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (t.get("id"), t.get("name"), t.get("max_teams"), t.get("team_size"),
                     t.get("status", "open"), t.get("created_by"), t.get("created_at"),
                     t.get("format", "swiss"), t.get("max_players", 32), t.get("rounds", 3),
                     t.get("tier_restriction"), t.get("role_pick", 0)),
                )
            restored["tournaments"] = len(data["tournaments"])

        # match_signups
        if "match_signups" in data and data["match_signups"]:
            for s in data["match_signups"]:
                cur.execute(
                    "INSERT OR REPLACE INTO match_signups (id, match_id, discord_id, team) "
                    "VALUES (?, ?, ?, ?)",
                    (s.get("id"), s.get("match_id"), s.get("discord_id"), s.get("team")),
                )
            restored["match_signups"] = len(data["match_signups"])

        # matches
        if "matches" in data and data["matches"]:
            for m in data["matches"]:
                cur.execute(
                    "INSERT OR REPLACE INTO matches "
                    "(id, name, status, created_by, channel_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (m.get("id"), m.get("name"), m.get("status", "pending"),
                     m.get("created_by"), m.get("channel_id"), m.get("created_at")),
                )
            restored["matches"] = len(data["matches"])

        conn.commit()

        summary = ", ".join(f"{k}: {v}" for k, v in restored.items())
        logger.info(f"Restore complete: {summary}")
    except Exception as e:
        logger.error(f"Restore failed: {e}", exc_info=True)
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
    logger.info(f"Bot online: {bot.user}")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logger.error(f"Sync error: {e}")


# =============================================================================
# 每周挑战进度监听 — messages / attachments / reactions
# =============================================================================
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    uid = str(message.author.id)

    try:
        from cogs.economy import update_weekly_progress
        update_weekly_progress(uid, "send_message")
        if message.attachments:
            update_weekly_progress(uid, "send_attachment", len(message.attachments))
    except Exception:
        pass


@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    try:
        from cogs.economy import update_weekly_progress
        update_weekly_progress(str(user.id), "react")
    except Exception:
        pass


# =============================================================================
# 保活 — 内置 HTTP 服务器，每 30 秒自检，防止容器休眠
# =============================================================================
async def health_server():
    """启动一个简单的 HTTP 服务器响应 /health 请求。"""
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
    logger.info(f"Health server running on port {port}")


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
    # Start background backup loop (pushes to Discord channel)
    asyncio.create_task(auto_backup_loop())

    # 启动保活服务
    asyncio.create_task(health_server())
    asyncio.create_task(health_check())

    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"Loaded: {cog}")
        except Exception as e:
            logger.error(f"FAILED to load {cog}: {e}", exc_info=True)
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
