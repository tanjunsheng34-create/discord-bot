"""
Discord Bot — LOL 自定义比赛 5v5
"""
import os
import sys
import json
import io
import time
import logging
import asyncio
import datetime
import sqlite3
import discord
from discord.ext import commands
from database import get_db, init_db
from utils.logger import log_error
from config import TOKEN, BACKUP_CHANNEL_ID, BACKUP_INTERVAL, BACKUP_TABLES

# Text XP cooldown: user_id -> last_xp_time
_msg_xp_cooldowns: dict[str, float] = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
# Suppress noisy discord library logs
logging.getLogger("discord").setLevel(logging.WARNING)

if TOKEN is None:
    logger.critical("请在 .env 文件中设置 DISCORD_TOKEN")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.actions",
    "cogs.announce",
    "cogs.economy",
    "cogs.tournament",
    "cogs.lol",
    "cogs.dashboard",
    "cogs.voice_tracker",
    "cogs.queue",
    "cogs.admin_backup",
    "cogs.daily",
    "cogs.help",
    "cogs.peiwans",
    "cogs.casino",
    "cogs.trivia",
    "cogs.guess_champion",
    "cogs.predict",
    "cogs.meme",
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
            except Exception as e:
                logger.warning(f"Failed to send error message: {e}")

bot.setup_hook = setup_hook.__get__(bot)


# =============================================================================
# Auto-install missing dependencies
# =============================================================================
import subprocess
import sys

def ensure_deps():
    """Auto-install missing Python dependencies."""
    pkgs = {
        "nacl": "PyNaCl",
        "croniter": "croniter",
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

    # All dependencies installed

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
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            logger.warning(f"Failed to fetch backup channel {cid}: {e}")
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
        # Batched restore helpers
        def _restore_batch(table_name, sql, rows_builder):
            rows = [rows_builder(r) for r in data.get(table_name, [])]
            if rows:
                cur.executemany(sql, rows)
                restored[table_name] = len(rows)

        # users
        _restore_batch("users",
            "INSERT OR REPLACE INTO users (discord_id, username, score, created_at) VALUES (?, ?, ?, ?)",
            lambda u: (u.get("discord_id"), u.get("username", ""), u.get("score", 500), u.get("created_at", "")),
        )
        # voice_tracker
        _restore_batch("voice_tracker",
            "INSERT OR REPLACE INTO voice_tracker (user_id, total_seconds, login_days, total_joins, last_join_date, last_join_time) VALUES (?, ?, ?, ?, ?, ?)",
            lambda v: (v.get("user_id"), v.get("total_seconds", 0), v.get("login_days", 0), v.get("total_joins", 0), v.get("last_join_date"), v.get("last_join_time")),
        )
        # daily_checkin
        _restore_batch("daily_checkin",
            "INSERT OR REPLACE INTO daily_checkin (discord_id, last_date, streak) VALUES (?, ?, ?)",
            lambda c: (c.get("discord_id"), c.get("last_date", ""), c.get("streak", 0)),
        )
        # user_inventory
        _restore_batch("user_inventory",
            "INSERT OR REPLACE INTO user_inventory (user_id, item_id, quantity) VALUES (?, ?, ?)",
            lambda inv: (inv.get("user_id"), inv.get("item_id"), inv.get("quantity", 1)),
        )
        # giveaways (economy.py new system)
        _restore_batch("giveaways",
            "INSERT OR REPLACE INTO giveaways (id, channel_id, prize, created_by, drawn, winner_id, created_at, draw_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            lambda g: (g.get("id"), g.get("channel_id"), g.get("prize"), g.get("created_by"), g.get("drawn", 0), g.get("winner_id"), g.get("created_at"), g.get("draw_at")),
        )
        # giveaway_tickets
        _restore_batch("giveaway_tickets",
            "INSERT OR REPLACE INTO giveaway_tickets (discord_id, tickets) VALUES (?, ?)",
            lambda t: (t.get("discord_id"), t.get("tickets", 0)),
        )
        # tournaments
        _restore_batch("tournaments",
            "INSERT OR REPLACE INTO tournaments (id, name, max_teams, team_size, status, created_by, created_at, format, max_players, rounds, tier_restriction, role_pick) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            lambda t: (t.get("id"), t.get("name"), t.get("max_teams"), t.get("team_size"), t.get("status", "open"), t.get("created_by"), t.get("created_at"), t.get("format", "swiss"), t.get("max_players", 32), t.get("rounds", 3), t.get("tier_restriction"), t.get("role_pick", 0)),
        )
        # tournaments

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
    print("=" * 50)
    print("GMPT Bot v3.5 已启动 - 欢迎消息使用新版四板块")
    print("=" * 50)

    # ── 启动自检：图片生成依赖 ──
    dep_status = []
    try:
        from PIL import Image, ImageFont, ImageDraw
        dep_status.append("✅ Pillow OK")
    except Exception:
        dep_status.append("❌ Pillow 缺失 → Actions/Meme 将无法生成图片")
    try:
        import imageio
        dep_status.append("✅ imageio OK")
    except Exception:
        dep_status.append("❌ imageio 缺失 → Meme 将使用文字模式")
    font_ok = False
    for fp in [
        r"C:\Windows\Fonts\seguiemj.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
    ]:
        if os.path.exists(fp):
            font_ok = True
            break
    dep_status.append("✅ 字体 OK" if font_ok else "❌ 字体缺失 → 图片文字可能乱码")
    print(" | ".join(dep_status))

    init_db()
    # Periodic database maintenance
    try:
        conn = get_db()
        conn.execute("PRAGMA optimize")
        conn.execute("VACUUM")
        conn.close()
        logger.info("Database VACUUM completed")
    except Exception as e:
        logger.warning(f"Database VACUUM failed (non-critical): {e}")
    # Restore data from Discord backup channel (if configured)
    await auto_restore()
    logger.info(f"Bot online: {bot.user}")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logger.error(f"Sync error: {e}")


# =============================================================================
# 欢迎消息 — on_member_join
# =============================================================================
@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    try:
        file = discord.File("assets/welcome_bg.png", filename="welcome.png")

        embed = discord.Embed(
            title="👋 Welcome to Gaming Planet! 🪐",
            color=0x9B59B6,
            timestamp=datetime.datetime.now(),
        )

        embed.set_author(
            name=f"{member.name} 加入了我们！| just joined!",
            icon_url=member.display_avatar.url,
        )

        embed.description = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**🚀 🔥 ✨ What to expect here:**\n"
            "🎮 Active members • Weekly custom matches\n"
            "🏆 Monthly tournament & giveaways\n"
            "🎙️ Voice chat & live streams\n"
            "🌸 Friendly owner & admins\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📖 **快速上手 | Quick Start**\n"
            "💬 `/gmpt-help` — 查看所有功能 | See all features\n"
            "🎮 `/gmpt-dashboard` — 控制面板 | Control Panel\n\n"
            "👥 **找队友 | Find Teammates**\n"
            "🔍 `/gmpt-queue` — 寻找队伍 | Looking for group\n"
            "🤝 直接 @ 在线玩家组队 | Ping players to team up\n\n"
            "📚 **教学 | Guides**\n"
            "🧠 `/gmpt-trivia` — LOL 知识问答 | Quiz\n"
            "🕵️ `/gmpt-guess-champion` — 猜英雄 | Guess champion\n\n"
            "💜 **G.M.P.T Gaming Planet** — Have fun!"
        )

        embed.set_image(url="attachment://welcome.png")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(
            text="G.M.P.T Gaming Planet | Made with 💜",
            icon_url=member.guild.icon.url if member.guild.icon else None,
        )

        welcome_channel = discord.utils.get(member.guild.text_channels, name="welcome")
        if welcome_channel:
            await welcome_channel.send(content=member.mention, embed=embed, file=file)
        else:
            for channel in member.guild.text_channels:
                if channel.permissions_for(member.guild.me).send_messages:
                    await channel.send(content=member.mention, embed=embed, file=file)
                    break
    except Exception as e:
        logger.warning(f"Welcome message failed (non-critical): {e}")


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
    except Exception as e:
        log_error("main", "on_message_weekly", e)

    # ── Text XP: +2 per message, 60s cooldown ──
    try:
        now = time.time()
        last = _msg_xp_cooldowns.get(uid, 0)
        if now - last >= 60:
            _msg_xp_cooldowns[uid] = now
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (discord_id, username) VALUES (?, ?) ON CONFLICT(discord_id) DO NOTHING",
                (uid, message.author.name),
            )
            cur.execute("UPDATE users SET xp = xp + 2 WHERE discord_id = ?", (uid,))
            cur.execute("SELECT xp, level FROM users WHERE discord_id=?", (uid,))
            xp_row = cur.fetchone()
            if xp_row:
                current_xp = xp_row["xp"]
                current_level = xp_row["level"] or 1
                while current_xp >= int(current_level ** 1.5 * 100):
                    current_xp -= int(current_level ** 1.5 * 100)
                    current_level += 1
                if current_level != xp_row["level"]:
                    cur.execute("UPDATE users SET level = ?, xp = ? WHERE discord_id=?", (current_level, current_xp, uid))
            conn.commit()
            conn.close()
    except Exception as e:
        log_error("main", "on_message_xp", e)


@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    try:
        from cogs.economy import update_weekly_progress
        update_weekly_progress(str(user.id), "react")
    except Exception as e:
        log_error("main", "on_reaction_weekly", e)


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
            pass  # Health check is best-effort, expected to fail occasionally


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
            continue
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
