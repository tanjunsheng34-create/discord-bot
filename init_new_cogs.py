"""
GMPT Bot — 新模块数据库初始化 / New Cog Database Initializer
在 main.py 的 on_ready 中调用 init_all_new_tables() 创建所有新模块所需的表。
Bilingual (中文 / English)
"""
import logging
from database import get_db_ctx

logger = logging.getLogger(__name__)


def init_all_new_tables():
    """Initialize all database tables required by new cogs.

    Called from main.py on_ready(). Safe to call multiple times
    (all CREATE TABLE statements use IF NOT EXISTS).
    """
    logger.info("[InitNewCogs] Creating tables for new cogs...")

    with get_db_ctx() as conn:
        cur = conn.cursor()

        # ── economy_jobs.py ──
        # (No new tables needed — uses existing economy tables)

        # ── gambling.py: Lottery ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lottery_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                purchased_at TEXT DEFAULT (datetime('now')),
                drawn INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lottery_draws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_amount INTEGER NOT NULL DEFAULT 0,
                total_tickets INTEGER NOT NULL DEFAULT 0,
                winner_id TEXT,
                drawn_at TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)

        # ── marketplace.py ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS marketplace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                price INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                listed_at TEXT DEFAULT (datetime('now')),
                active INTEGER DEFAULT 1
            )
        """)

        # ── pets.py ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                pet_name TEXT NOT NULL,
                pet_type TEXT NOT NULL,
                happiness INTEGER DEFAULT 50,
                adopted_at TEXT DEFAULT (datetime('now')),
                last_fed TEXT,
                last_played TEXT
            )
        """)

        # ── clans.py ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                owner_id TEXT NOT NULL,
                total_contrib INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clan_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                personal_contrib INTEGER DEFAULT 0,
                joined_at TEXT DEFAULT (datetime('now')),
                UNIQUE(clan_id, user_id)
            )
        """)

        # ── social.py: Marriage & Reputation ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS marriages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposer_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                married_at TEXT,
                divorced_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reputation (
                user_id TEXT PRIMARY KEY,
                rep_count INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rep_cooldowns (
                giver_id TEXT NOT NULL,
                date TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (giver_id, date)
            )
        """)

        # ── games.py: Truth or Dare custom questions ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tod_custom_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_type TEXT NOT NULL,
                content TEXT NOT NULL,
                author_id TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.commit()

    logger.info("[InitNewCogs] All new tables created successfully.")

    # Summary
    tables = [
        "lottery_tickets", "lottery_draws",
        "marketplace",
        "pets",
        "clans", "clan_members",
        "marriages", "reputation", "rep_cooldowns",
        "tod_custom_questions",
    ]
    logger.info(f"[InitNewCogs] Tables: {', '.join(tables)}")
    return True
