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
from database import get_db, get_db_ctx, init_db, _merge_databases
from init_new_cogs import init_all_new_tables
from utils.logger import log_error
from config import TOKEN, TOKENS, BOT_ROLE, BACKUP_CHANNEL_ID, BACKUP_INTERVAL, BACKUP_TABLES, GUILD_ID

# Text XP cooldown: user_id -> last_xp_time
_msg_xp_cooldowns: dict[str, float] = {}

# Image mode toggle (set in on_ready based on font availability)
IMAGE_MODE = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
# Suppress noisy discord library logs
logging.getLogger("discord").setLevel(logging.WARNING)

# Single-instance mode: require TOKEN
if BOT_ROLE and not TOKEN and not any(TOKENS.values()):
    logger.critical("请在 .env 文件中设置 DISCORD_TOKEN 或 TOKEN_* 环境变量")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ── BOT_ROLE: 从 config 导入（兼容环境变量 BOT_ROLE 或 TOKENS 字典） ──

# Common cogs loaded by ALL bots regardless of role
COMMON_COGS = [
    "cogs.admin_backup",
    "cogs.daily",
    "cogs.actions",
    "cogs.voice_tracker",
    "cogs.stats",
    "cogs.dashboard",
]

MMORPG_COGS = {
    "cogs.boss",
    "cogs.mmorpg_shop",
    "cogs.mmorpg_skills",
    "cogs.mmorpg_pvp",
}
COMMUNITY_COGS = {
    "cogs.pets",
    "cogs.clans",
    "cogs.polls",
    "cogs.meme",
    "cogs.predict",
    "cogs.guess_champion",
    "cogs.social",
}
ARENA_COGS = {
    "cogs.tournament",
    "cogs.lol",
    "cogs.queue",
    "cogs.help",
}
FULL_ONLY_COGS = {
    "cogs.economy",
    "cogs.economy_jobs",
    "cogs.shop",
    "cogs.announce",
    "cogs.leaderboard",
    "cogs.auction",
    "cogs.gambling",
    "cogs.casino_games",
    "cogs.poker",
    "cogs.games",
    "cogs.casino",
    "cogs.trivia",
    "cogs.mini_games",
    "cogs.wheel",
    "cogs.duel",
}

# Build ALL_COGS — union of all cog sets
ALL_COGS = list(set(COMMON_COGS) | MMORPG_COGS | COMMUNITY_COGS | ARENA_COGS | FULL_ONLY_COGS)

ROLE_COGS = {
    "full": ALL_COGS,
    "mmorpg": list(MMORPG_COGS),
    "community": list(COMMUNITY_COGS),
    "arena": list(ARENA_COGS),
}

# COGS resolution
if BOT_ROLE == "full":
    COGS = ALL_COGS
elif BOT_ROLE in ROLE_COGS:
    COGS = COMMON_COGS + ROLE_COGS[BOT_ROLE]
else:
    logger.warning(f"Unknown BOT_ROLE={BOT_ROLE!r}, falling back to 'full'")
    COGS = ALL_COGS

logger.info(f"BOT_ROLE={BOT_ROLE} → loading {len(COGS)} cogs: {[c.split('.')[-1] for c in COGS]}")


# =============================================================================
# GMPTBot class — 支持多实例同容器运行，共享 data.db
# =============================================================================
def get_cogs_for_role(role: str) -> list[str]:
    """根据角色返回要加载的 Cog 列表，与模块级 COGS 逻辑一致。"""
    role = role.strip().lower()
    if role == "full":
        return ALL_COGS
    if role in ROLE_COGS:
        return COMMON_COGS + ROLE_COGS[role]
    logger.warning(f"Unknown role={role!r}, falling back to 'full'")
    return ALL_COGS


class GMPTBot(commands.Bot):
    """支持 role 属性的 Bot 子类，用于多实例部署。"""

    def __init__(self, role: str = "full"):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.bot_role = role
        self.IMAGE_MODE = True

    async def setup_hook(self) -> None:
        """Register global app command error handler."""
        @self.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction,
            error: discord.app_commands.AppCommandError,
        ):
            if interaction.command is not None and getattr(interaction.command, "_has_error_handler", False):
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

        # ── Sync slash commands ──
        # 只有 full 实例负责 sync，避免 4 实例合并后命令重复
        if self.bot_role == "full":
            guild_id = os.getenv("GUILD_ID")
            if guild_id:
                try:
                    guild = discord.Object(id=int(guild_id))
                    self.tree.copy_global_to(guild=guild)
                    synced = await self.tree.sync(guild=guild)
                    logger.info(f"[{self.bot_role}] Synced {len(synced)} commands to guild {guild_id}")
                except Exception as e:
                    logger.error(f"[{self.bot_role}] Guild sync failed for GUILD_ID={guild_id}: {e}")
            else:
                try:
                    synced = await self.tree.sync()
                    logger.info(f"[{self.bot_role}] Synced {len(synced)} global commands")
                except Exception as e:
                    logger.error(f"[{self.bot_role}] Global sync failed: {e}")
        else:
            logger.info(f"[{self.bot_role}] Skipped sync (only full role syncs)")

    async def on_ready(self):
        bot_role = self.bot_role
        if bot_role == "full":
            print("=" * 50)
            print("GMPT Bot v3.5 已启动 — 欢迎消息使用新版四板块")
            print("=" * 50)
        else:
            print(f"[on_ready] GMPT Bot ({bot_role}) 静默启动完成")

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

        if not font_ok:
            self.IMAGE_MODE = False
            print("🔴 字体缺失 → 所有图片功能使用纯文字模式")

        # DB init + VACUUM（仅第一个实例执行，避免重复 VACUUM）
        _once_db_init_lock: bool = getattr(GMPTBot, "_db_initialized", False)
        if not _once_db_init_lock:
            GMPTBot._db_initialized = True
            init_db()
            init_all_new_tables()
            try:
                with get_db_ctx() as conn:
                    conn.execute("PRAGMA optimize")
                    conn.execute("VACUUM")
                logger.info("Database VACUUM completed")
            except Exception as e:
                logger.warning(f"Database VACUUM failed (non-critical): {e}")
            # Auto-restore（也仅执行一次）
            await auto_restore()

        logger.info(f"Bot online: {self.user} (role={bot_role})")

        # ── Per-guild sync（仅 full 实例） ──
        if bot_role != "full":
            return
        total = 0
        for guild in self.guilds:
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
                logger.info(f"Synced {len(synced)} commands to {guild.name} ({guild.id})")
                total += len(synced)
            except Exception as e:
                logger.error(f"Guild sync error for {guild.name}: {e}")
        logger.info(f"Total synced: {total} commands across {len(self.guilds)} guilds")

        # 欢迎频道自检
        try:
            for guild in self.guilds:
                ch = guild.get_channel(1398991787523313675)
                if ch and ch.permissions_for(guild.me).send_messages:
                    print(f"[on_ready] 欢迎频道自检 OK: {guild.name} / {ch.name}")
                elif ch:
                    print(f"[on_ready] 欢迎频道无发消息权限: {guild.name} / {ch.name}")
                else:
                    print(f"[on_ready] 未找到频道 1398991787523313675: {guild.name}")
        except Exception as e:
            print(f"[on_ready] 欢迎频道自检异常: {e}")

    async def on_member_join(self, member: discord.Member):
        if self.bot_role != "full":
            return
        print(f"[on_member_join] 触发! member={member.name}, bot={member.bot}")
        if member.bot:
            return

        try:
            embed = discord.Embed(
                title="👋 Welcome to Gaming Planet! 🪐",
                description=f"{member.mention} 加入了我们！",
                color=0xA385FF,
                timestamp=datetime.datetime.now(),
            )
            embed.description += (
                "\n━━━━━━━━━━━━━━━━\n"
                "🚀 🔥 ✨ **What to expect here:**\n"
                "🎮 Active members • Weekly custom matches\n"
                "🏆 Monthly tournament & giveaways\n"
                "🎙️ Voice chat & live streams\n"
                "🌸 Friendly owner & admins\n"
                "━━━━━━━━━━━━━━━━\n\n"
                "📖 **快速上手 | Quick Start**\n"
                "💬 `/gmpt-help`\n"
                "🎮 `/gmpt-dashboard`\n\n"
            )

            # 查找 / 生成背景图
            try:
                path = os.path.join(os.path.dirname(__file__), "assets", "welcome_bg.png")
                if os.path.exists(path):
                    file = discord.File(path, filename="welcome_bg.png")
                    embed.set_image(url="attachment://welcome_bg.png")
                    # 发送到 WELCOME_CHANNEL_ID 1398991787523313675
                    ch = member.guild.get_channel(1398991787523313675)
                    if ch and ch.permissions_for(member.guild.me).send_messages:
                        await ch.send(content=member.mention, embed=embed, file=file)
                        print(f"[on_member_join] 发送完成 → 主频道 {ch.name}")
                        return
            except Exception:
                pass

            # fallback
            for ch in member.guild.text_channels:
                if ch.permissions_for(member.guild.me).send_messages:
                    await ch.send(content=member.mention, embed=embed)
                    print(f"[on_member_join] 发送完成 → fallback 频道 {ch.name}")
                    break
        except Exception as e:
            print(f"[on_member_join] 异常! {e}")
            logger.warning(f"Welcome message failed (non-critical): {e}")

    async def on_message(self, message):
        if message.author.bot:
            return
        uid = str(message.author.id)

        if self.bot_role == "full":
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
                    with get_db_ctx() as conn:
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
            except Exception as e:
                log_error("main", "on_message_xp", e)

    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        try:
            from cogs.economy import update_weekly_progress
            update_weekly_progress(str(user.id), "react")
        except Exception as e:
            log_error("main", "on_reaction_weekly", e)


async def run_bot_instance(token: str, role: str):
    """启动单个 Bot 实例（多实例模式）。"""
    bot = GMPTBot(role=role)
    cogs = get_cogs_for_role(role)
    logger.info(f"[{role}] 加载 {len(cogs)} 个 cog: {[c.split('.')[-1] for c in cogs]}")
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            logger.info(f"[{role}] Loaded: {cog}")
        except Exception as e:
            logger.error(f"[{role}] FAILED to load {cog}: {e}", exc_info=True)
            print(f"[{role}] FAILED to load {cog}: {e}")
            continue
    await bot.start(token)


# =============================================================================
# Global app command error handler (module-level bot, 单实例模式)
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

    # ── Sync slash commands ──
    # 只有 full 实例负责 sync，避免多实例命令重复
    bot_role = os.getenv("BOT_ROLE", "full")
    if bot_role == "full":
        guild_id = GUILD_ID
        if guild_id:
            try:
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info(f"Synced {len(synced)} commands to guild {guild_id}")
            except Exception as e:
                logger.error(f"Guild sync failed for GUILD_ID={guild_id}: {e}")
        else:
            try:
                synced = await self.tree.sync()
                logger.info(f"Synced {len(synced)} global commands")
            except Exception as e:
                logger.error(f"Global sync failed: {e}")
    else:
        logger.info(f"Single-instance {bot_role} skipped sync (only full role syncs)")

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
        "aiohttp": "aiohttp",
        "PIL": "Pillow",
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

# 在 bot.run() 之前调用
ensure_deps()


# =============================================================================
# Auto-backup → Discord channel
# =============================================================================
def export_backup_data():
    """Export all BACKUP_TABLES rows as a dict. Runs in thread — sync safe."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        data = {}
        for table in BACKUP_TABLES:
            try:
                cur.execute(f"SELECT * FROM {table}")
                rows = [dict(row) for row in cur.fetchall()]
                data[table] = rows
            except Exception:
                data[table] = []
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

    with get_db_ctx() as conn:
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

            conn.commit()

            summary = ", ".join(f"{k}: {v}" for k, v in restored.items())
            logger.info(f"Restore complete: {summary}")
        except Exception as e:
            logger.error(f"Restore failed: {e}", exc_info=True)


# =============================================================================
# Bot events
# =============================================================================
@bot.event
async def on_ready():
    bot_role = os.getenv("BOT_ROLE", "full")
    if bot_role == "full":
        print("=" * 50)
        print("GMPT Bot v3.5 已启动 - 欢迎消息使用新版四板块")
        print("=" * 50)
    else:
        print(f"[on_ready] GMPT Bot ({bot_role}) 静默启动完成")

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

    # 字体缺失 → 关闭图片模式，所有图片功能走纯文字
    global IMAGE_MODE
    if not font_ok:
        IMAGE_MODE = False
        print("🔴 字体缺失 → 所有图片功能使用纯文字模式")
    bot.IMAGE_MODE = IMAGE_MODE

    init_db()
    init_all_new_tables()
    # Periodic database maintenance
    try:
        with get_db_ctx() as conn:
            conn.execute("PRAGMA optimize")
            conn.execute("VACUUM")
        logger.info("Database VACUUM completed")
    except Exception as e:
        logger.warning(f"Database VACUUM failed (non-critical): {e}")
    # Restore data from Discord backup channel (if configured)
    await auto_restore()
    logger.info(f"Bot online: {bot.user}")
    # ── Per-guild sync：copy global commands → sync to each guild（仅 full 实例） ──
    bot_role = os.getenv("BOT_ROLE", "full")
    if bot_role != "full":
        logger.info(f"Single-instance {bot_role} skipped on_ready sync (only full role syncs)")
    else:
        total = 0
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            try:
                synced = await bot.tree.sync(guild=guild)
                logger.info(f"Synced {len(synced)} commands to {guild.name} ({guild.id})")
                total += len(synced)
            except Exception as e:
                logger.error(f"Guild sync error for {guild.name}: {e}")
        logger.info(f"Total synced: {total} commands across {len(bot.guilds)} guilds")

    # 启动自检：向欢迎频道发一条上线消息，验证频道存在 + 发消息权限
    try:
        for guild in bot.guilds:
            ch = guild.get_channel(1398991787523313675)
            if ch and ch.permissions_for(guild.me).send_messages:
                print(f"[on_ready] 欢迎频道自检 OK: {guild.name} / {ch.name}")
            elif ch:
                print(f"[on_ready] 欢迎频道无发消息权限: {guild.name} / {ch.name}")
            else:
                print(f"[on_ready] 未找到频道 1398991787523313675: {guild.name}")
    except Exception as e:
        print(f"[on_ready] 欢迎频道自检异常: {e}")


# =============================================================================
# 欢迎消息 — on_member_join（仅 BOT_ROLE=full 时触发）
# =============================================================================
@bot.event
async def on_member_join(member: discord.Member):
    if os.getenv("BOT_ROLE", "full") != "full":
        return
    print(f"[on_member_join] 触发! member={member.name}, bot={member.bot}")
    if member.bot:
        return

    try:
        embed = discord.Embed(
            title="👋 Welcome to Gaming Planet! 🪐",
            description=f"{member.mention} 加入了我们！",
            color=0xA385FF,
            timestamp=datetime.datetime.now(),
        )

        embed.description += (
            "\n━━━━━━━━━━━━━━━━\n"
            "🚀 🔥 ✨ **What to expect here:**\n"
            "🎮 Active members • Weekly custom matches\n"
            "🏆 Monthly tournament & giveaways\n"
            "🎙️ Voice chat & live streams\n"
            "🌸 Friendly owner & admins\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "📖 **快速上手 | Quick Start**\n"
            "💬 `/gmpt-help`\n"
            "🎮 `/gmpt-dashboard`\n\n"

            "📚 **教学 | Guides**\n"
            "🧠 `/gmpt-trivia`\n"
            "🕵️ `/gmpt-guess-champion`"
        )

        embed.set_image(url="attachment://welcome.png")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"G.M.P.T Gaming Planet | {member.guild.name}")

        file = discord.File("assets/welcome_bg.png", filename="welcome.png")

        welcome_channel = member.guild.get_channel(1398991787523313675)
        print(f"[on_member_join] welcome_channel={welcome_channel}")
        if welcome_channel:
            await welcome_channel.send(content=member.mention, embed=embed, file=file)
            print("[on_member_join] 发送完成 → welcome 频道")
        else:
            for channel in member.guild.text_channels:
                if channel.permissions_for(member.guild.me).send_messages:
                    await channel.send(content=member.mention, embed=embed, file=file)
                    print(f"[on_member_join] 发送完成 → fallback 频道 {channel.name}")
                    break
    except Exception as e:
        print(f"[on_member_join] 异常! {e}")
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
            with get_db_ctx() as conn:
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
    """启动所有 Bot 实例。

    单实例模式（BOT_ROLE 已设置）：使用模块级 bot，兼容旧部署。
    多实例模式（BOT_ROLE 未设置）：为 TOKENS 中每个有值的角色启动一个 GMPTBot。
    """
    # 保活服务 + 备份循环（全局只启动一次，使用模块级 bot）
    asyncio.create_task(health_server())
    asyncio.create_task(health_check())
    asyncio.create_task(auto_backup_loop())

    # ── 多实例模式 ──
    if not BOT_ROLE:
        logger.info("多实例模式启动中...")
        # 合并数据库（如果存在多个旧 data*.db 文件）
        _merge_databases()

        tasks = []
        for role, token in [
            ("full", TOKENS.get("full", "")),
            ("mmorpg", TOKENS.get("mmorpg", "")),
            ("community", TOKENS.get("community", "")),
            ("arena", TOKENS.get("arena", "")),
        ]:
            if token:
                logger.info(f"启动 {role} 实例...")
                tasks.append(run_bot_instance(token, role))

        if not tasks:
            logger.critical("没有配置任何 TOKEN_* 环境变量！")
            return

        await asyncio.gather(*tasks)
        return

    # ── 单实例模式（向后兼容） ──
    logger.info(f"单实例模式：BOT_ROLE={BOT_ROLE}")
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"Loaded: {cog}")
        except Exception as e:
            logger.error(f"FAILED to load {cog}: {e}", exc_info=True)
            print(f"FAILED to load {cog}: {e}")
            continue
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
