import sqlite3
import time
import logging
from contextlib import contextmanager
from config import DATABASE

logger = logging.getLogger(__name__)

# WAL mode enabled at module load — ensures all connections inherit it
_WAL_INITIALIZED = False


def _ensure_wal():
    """Enable WAL journal mode once per process. Safe to call multiple times."""
    global _WAL_INITIALIZED
    if _WAL_INITIALIZED:
        return
    try:
        conn = sqlite3.connect(DATABASE, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.close()
        _WAL_INITIALIZED = True
    except Exception as e:
        logger.warning(f"WAL initialization failed: {e}")


def get_db(max_retries=3):
    """Return a SQLite connection with WAL mode, busy timeout, and retry on locked.

    - timeout=30: wait up to 30s for the database lock
    - PRAGMA journal_mode=WAL: allows concurrent readers + one writer
    - PRAGMA busy_timeout=5000: 5s busy handler
    - Retries on sqlite3.OperationalError 'database is locked' up to max_retries
    """
    _ensure_wal()

    last_error = None
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(DATABASE, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            return conn
        except sqlite3.OperationalError as e:
            last_error = e
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(0.2 * (attempt + 1))  # exponential backoff: 0.2s, 0.4s, 0.6s
                continue
            raise

    raise last_error


@contextmanager
def db_context():
    """上下文管理器：自动 commit / rollback / close。"""
    conn = get_db()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

@contextmanager
def get_db_ctx():
    """上下文管理器：自动 close，适合不需要事务包裹的简单读/写模式。

    用法：
        with get_db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(...)
            conn.commit()  # 可选
    """
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


def _create_core_tables(cursor):
    """Create core user & tournament tables."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id   TEXT PRIMARY KEY,
            username     TEXT,
            score        INTEGER DEFAULT 500,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tournaments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            max_teams    INTEGER NOT NULL,
            team_size    INTEGER NOT NULL,
            status       TEXT DEFAULT 'open',
            created_by   TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS registrations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id   INTEGER NOT NULL,
            discord_id      TEXT NOT NULL,
            team_id         INTEGER,
            registered_at   TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
            UNIQUE(tournament_id, discord_id)
        );

        CREATE TABLE IF NOT EXISTS teams (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id   INTEGER NOT NULL,
            name            TEXT NOT NULL,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
        );

        CREATE TABLE IF NOT EXISTS results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id   INTEGER NOT NULL,
            team_id         INTEGER NOT NULL,
            rank            INTEGER NOT NULL,
            score_awarded   INTEGER NOT NULL,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
        );
    """)


def _create_economy_tables(cursor):
    """Create economy / shop / achievements tables."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS daily_checkin (
            discord_id  TEXT PRIMARY KEY,
            last_date   TEXT NOT NULL,
            streak      INTEGER DEFAULT 0,
            total_days  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id  TEXT NOT NULL,
            amount      INTEGER NOT NULL,
            reason      TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS game_limits (
            user_id     INTEGER,
            date        TEXT,
            game_type   TEXT,
            play_count  INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date, game_type)
        );

        CREATE TABLE IF NOT EXISTS achievements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT NOT NULL,
            reward      INTEGER DEFAULT 0,
            hidden      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS user_achievements (
            user_id     TEXT NOT NULL,
            achievement_id INTEGER NOT NULL,
            unlocked_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, achievement_id)
        );

        CREATE TABLE IF NOT EXISTS shop_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT NOT NULL,
            price       INTEGER NOT NULL,
            item_type   TEXT NOT NULL,
            category    TEXT DEFAULT '其他'
        );

        CREATE TABLE IF NOT EXISTS user_inventory (
            user_id     TEXT NOT NULL,
            item_id     INTEGER NOT NULL,
            quantity    INTEGER DEFAULT 1,
            UNIQUE(user_id, item_id)
        );

        CREATE TABLE IF NOT EXISTS user_flags (
            discord_id TEXT PRIMARY KEY,
            queue_skip INTEGER DEFAULT 0,
            mode_pick TEXT
        );

        CREATE TABLE IF NOT EXISTS active_effects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,
            effect_type TEXT NOT NULL,
            used_at     TEXT DEFAULT (datetime('now')),
            consumed    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS bets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id    INTEGER NOT NULL,
            discord_id  TEXT NOT NULL,
            amount      INTEGER NOT NULL,
            team        TEXT NOT NULL,
            placed_at   TEXT DEFAULT (datetime('now')),
            settled     INTEGER DEFAULT 0,
            won         INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS active_bets (
            match_id    INTEGER NOT NULL,
            discord_id  TEXT NOT NULL,
            team_id     INTEGER NOT NULL,
            amount      INTEGER NOT NULL,
            placed_at   TEXT DEFAULT (datetime('now')),
            UNIQUE(match_id, discord_id)
        );

        CREATE TABLE IF NOT EXISTS job_cooldowns (
            user_id     TEXT NOT NULL,
            job_type    TEXT NOT NULL,
            last_used   REAL NOT NULL,
            PRIMARY KEY (user_id, job_type)
        );
    """)


def _create_lol_tables(cursor):
    """Create LoL / MMR / Riot connection tables."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS player_riot (
            discord_id    TEXT PRIMARY KEY,
            summoner_name TEXT NOT NULL,
            tag_line      TEXT NOT NULL,
            region        TEXT NOT NULL DEFAULT 'kr',
            created_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS votes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id   INTEGER NOT NULL,
            discord_id      TEXT NOT NULL,
            vote_team       TEXT NOT NULL,
            voted_at        TEXT DEFAULT (datetime('now')),
            UNIQUE(tournament_id, discord_id)
        );

        CREATE TABLE IF NOT EXISTS tournament_players (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id   INTEGER NOT NULL,
            discord_id      TEXT NOT NULL,
            wins            INTEGER DEFAULT 0,
            losses          INTEGER DEFAULT 0,
            draws           INTEGER DEFAULT 0,
            points          INTEGER DEFAULT 0,
            seed            INTEGER,
            tier            TEXT,
            UNIQUE(tournament_id, discord_id)
        );

        CREATE TABLE IF NOT EXISTS tournament_matches (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id   INTEGER NOT NULL,
            round           INTEGER NOT NULL,
            match_index     INTEGER NOT NULL,
            player_a_id     TEXT NOT NULL,
            player_b_id     TEXT,
            score_a         INTEGER DEFAULT 0,
            score_b         INTEGER DEFAULT 0,
            winner_id       TEXT,
            status          TEXT DEFAULT 'pending',
            reported_by     TEXT,
            reported_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS mmr (
            discord_id  TEXT PRIMARY KEY,
            mmr         INTEGER DEFAULT 1000,
            wins        INTEGER DEFAULT 0,
            losses      INTEGER DEFAULT 0,
            streak      INTEGER DEFAULT 0,
            rank        TEXT DEFAULT 'Iron'
        );

        CREATE TABLE IF NOT EXISTS mmr_board (
            guild_id    TEXT PRIMARY KEY,
            message_id  TEXT NOT NULL,
            channel_id  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS match_view_state (
            message_id        TEXT PRIMARY KEY,
            match_id          INTEGER NOT NULL,
            channel_id        INTEGER NOT NULL,
            player_list_msg_id TEXT
        );
    """)


def _create_draft_tables(cursor):
    """Create captain draft tables."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS draft_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id   INTEGER,
            status          TEXT DEFAULT 'setup',
            snake_round     INTEGER DEFAULT 0,
            pick_index      INTEGER DEFAULT 0,
            created_by      TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS draft_captains (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id        INTEGER NOT NULL,
            captain_id      TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            pick_order      INTEGER NOT NULL,
            tier_score      INTEGER DEFAULT 0,
            UNIQUE(draft_id, captain_id)
        );

        CREATE TABLE IF NOT EXISTS draft_picks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id        INTEGER NOT NULL,
            captain_id      TEXT NOT NULL,
            player_id       TEXT NOT NULL,
            pick_number     INTEGER NOT NULL,
            UNIQUE(draft_id, player_id)
        );
    """)


def _create_voice_giveaway_tables(cursor):
    """Create voice tracking and giveaway tables."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS voice_sessions (
            discord_id    TEXT NOT NULL,
            join_time     TEXT NOT NULL,
            total_seconds INTEGER DEFAULT 0,
            PRIMARY KEY (discord_id, join_time)
        );

        CREATE TABLE IF NOT EXISTS match_vc_config (
            guild_id       TEXT NOT NULL,
            team_a_vc_id   TEXT,
            team_b_vc_id   TEXT,
            lobby_vc_id    TEXT,
            notification_channel_id TEXT DEFAULT '1453208983358935121',
            enabled        INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id)
        );

        CREATE TABLE IF NOT EXISTS voice_tracker (
            user_id         TEXT PRIMARY KEY,
            total_seconds   INTEGER DEFAULT 0,
            login_days      INTEGER DEFAULT 0,
            total_joins     INTEGER DEFAULT 0,
            last_join_date  TEXT,
            last_join_time  TEXT
        );

        CREATE TABLE IF NOT EXISTS giveaway_tickets (
            discord_id TEXT PRIMARY KEY,
            tickets INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS giveaway_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER NOT NULL,
            discord_id TEXT NOT NULL,
            tickets_used INTEGER DEFAULT 1,
            entered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (giveaway_id) REFERENCES giveaways(id)
        );

        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            prize TEXT,
            created_by TEXT,
            drawn INTEGER DEFAULT 0,
            winner_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            draw_at TIMESTAMP
        );
    """)


def _create_season_queue_tables(cursor):
    """Create season / queue / scheduled events / match tables."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS seasons (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            start_date  TEXT NOT NULL,
            end_date    TEXT,
            active      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS season_standings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id   INTEGER NOT NULL,
            discord_id  TEXT NOT NULL,
            mmr         INTEGER NOT NULL,
            wins        INTEGER DEFAULT 0,
            losses      INTEGER DEFAULT 0,
            rank        TEXT DEFAULT 'Unranked',
            UNIQUE(season_id, discord_id)
        );

        CREATE TABLE IF NOT EXISTS weekly_challenges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start  TEXT NOT NULL,
            title       TEXT NOT NULL,
            description TEXT NOT NULL,
            reward      INTEGER NOT NULL,
            target      INTEGER NOT NULL,
            task_type   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_challenges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id  TEXT NOT NULL,
            challenge_id INTEGER NOT NULL,
            progress    INTEGER DEFAULT 0,
            completed   INTEGER DEFAULT 0,
            UNIQUE(discord_id, challenge_id)
        );

        CREATE TABLE IF NOT EXISTS matches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            created_by  TEXT NOT NULL,
            channel_id  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS match_signups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id    INTEGER NOT NULL,
            discord_id  TEXT NOT NULL,
            team        TEXT DEFAULT NULL,
            UNIQUE(match_id, discord_id)
        );

        CREATE TABLE IF NOT EXISTS daily_rewards (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id      TEXT NOT NULL,
            date            TEXT NOT NULL,
            voice_minutes   INTEGER DEFAULT 0,
            claimed         INTEGER DEFAULT 0,
            claimed_at      TEXT,
            reward_amount   INTEGER DEFAULT 0,
            UNIQUE(discord_id, date)
        );

        CREATE TABLE IF NOT EXISTS daily_config (
            key             TEXT PRIMARY KEY,
            value           TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS queue (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id      TEXT NOT NULL,
            match_type      TEXT DEFAULT 'normal',
            role            TEXT DEFAULT 'any',
            status          TEXT DEFAULT 'waiting',
            joined_at       TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS match_events (
            event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id   INTEGER,
            timestamp       TEXT DEFAULT (datetime('now')),
            event_type      TEXT NOT NULL,
            actor_id        TEXT,
            target_id       TEXT,
            team_id         INTEGER,
            data            TEXT
        );

        CREATE TABLE IF NOT EXISTS scheduled_events (
            event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name      TEXT NOT NULL,
            cron_expr       TEXT NOT NULL,
            template_id     INTEGER,
            channel_id      TEXT,
            created_by      TEXT,
            enabled         INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS match_templates (
            template_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            template_name   TEXT UNIQUE,
            max_teams       INTEGER DEFAULT 2,
            team_size       INTEGER DEFAULT 5,
            rules           TEXT
        );

        CREATE TABLE IF NOT EXISTS season_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id       INTEGER,
            discord_id      TEXT,
            mmr_before      INTEGER,
            mmr_after       INTEGER,
            rank_before     TEXT,
            rank_after      TEXT,
            games_played    INTEGER DEFAULT 0,
            archived_at     TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (season_id) REFERENCES seasons(id)
        );

        CREATE TABLE IF NOT EXISTS lol_vote_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            message_id TEXT,
            vote_date TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            winner_mode TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS lol_vote_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER REFERENCES lol_vote_sessions(id),
            discord_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            voted_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS dashboard_panel (
            guild_id    TEXT PRIMARY KEY,
            message_id  TEXT NOT NULL,
            channel_id  TEXT NOT NULL
        );
    """)


def _create_predict_tables(cursor):
    """Create predict / match prediction tables."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS predict_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_a TEXT,
            team_b TEXT,
            match_time TEXT,
            cutoff_time TEXT,
            status TEXT DEFAULT 'open',
            winner TEXT,
            creator_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','+8 hours'))
        );
        CREATE TABLE IF NOT EXISTS predict_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            predict_id INTEGER,
            user_id TEXT,
            team TEXT,
            amount INTEGER,
            created_at TEXT DEFAULT (datetime('now','+8 hours'))
        );
    """)


def _create_peiwans_tables(cursor):
    """Create companion system tables."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS peiwans_profiles (
            user_id INTEGER PRIMARY KEY,
            game TEXT,
            rank TEXT,
            price INTEGER,
            intro TEXT,
            status TEXT DEFAULT 'offline',
            total_orders INTEGER DEFAULT 0,
            avg_rating REAL DEFAULT 0,
            total_earnings INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS peiwans_orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            peiwans_id INTEGER,
            game TEXT,
            price INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS peiwans_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            reviewer_id INTEGER,
            peiwans_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS peiwans_earnings (
            earning_id INTEGER PRIMARY KEY AUTOINCREMENT,
            peiwans_id INTEGER,
            order_id INTEGER,
            amount INTEGER,
            created_at TEXT
        );
    """)


def _run_migrations(cursor):
    """Apply schema migrations (ALTER TABLE ADD COLUMN)."""
    # tournament format / swiss fields
    for col, col_type in [
        ("format", "TEXT DEFAULT 'swiss'"),
        ("max_players", "INTEGER DEFAULT 32"),
        ("rounds", "INTEGER DEFAULT 3"),
        ("tier_restriction", "TEXT"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE tournaments ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    # registrations.is_sub
    try:
        cursor.execute("ALTER TABLE registrations ADD COLUMN is_sub INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # users.mmr / win_streak / xp / level
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN mmr INTEGER DEFAULT 1000")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN win_streak INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    # MMORPG: users combat stats
    for col, col_type in [
        ("hp", "INTEGER DEFAULT 100"),
        ("max_hp", "INTEGER DEFAULT 100"),
        ("mp", "INTEGER DEFAULT 50"),
        ("max_mp", "INTEGER DEFAULT 50"),
        ("attack", "INTEGER DEFAULT 10"),
        ("defense", "INTEGER DEFAULT 5"),
        ("job_level", "INTEGER DEFAULT 1"),
        ("job_xp", "INTEGER DEFAULT 0"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    # role_pick
    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN role_pick INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE registrations ADD COLUMN lane TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # BO series support
    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN bo_type TEXT DEFAULT 'BO1'")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN current_game INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN team_a_wins INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN team_b_wins INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN started_at TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # match_vc_config — notification_channel_id
    try:
        cursor.execute("ALTER TABLE match_vc_config ADD COLUMN notification_channel_id TEXT DEFAULT '1453208983358935121'")
    except sqlite3.OperationalError:
        pass

    # shop items fields
    try:
        cursor.execute("ALTER TABLE shop_items ADD COLUMN stock INTEGER DEFAULT -1")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE shop_items ADD COLUMN ends_at TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE shop_items ADD COLUMN discount_pct INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # daily_tasks table for daily task system
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            task_type INTEGER,
            progress INTEGER DEFAULT 0,
            target INTEGER,
            claimed INTEGER DEFAULT 0
        )
    """)

    # daily_checkin.total_days migration
    try:
        cursor.execute("ALTER TABLE daily_checkin ADD COLUMN total_days INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # user_inventory expanded schema (for MMORPG potion inventory)
    try:
        cursor.execute("ALTER TABLE user_inventory ADD COLUMN item_name TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE user_inventory ADD COLUMN item_type TEXT DEFAULT 'item'")
    except sqlite3.OperationalError:
        pass

    # mmorpg_class — user's MMORPG class selection
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN mmorpg_class TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # MMORPG stats columns (spd, crit, acc, eva) — fallback migration
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN spd INTEGER DEFAULT 5")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN crit_rate INTEGER DEFAULT 5")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN accuracy INTEGER DEFAULT 90")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN evasion INTEGER DEFAULT 3")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN boss_kills INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN pvp_wins INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN dungeon_clears INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass


def _seed_default_vc(cursor):
    """Seed default voice channel IDs for match auto-assign (INSERT OR IGNORE)."""
    # Default guild voice channel configuration
    # A队语音 / B队语音 / 大厅（结算完）
    cursor.execute(
        """
        INSERT OR IGNORE INTO match_vc_config
            (guild_id, team_a_vc_id, team_b_vc_id, lobby_vc_id, notification_channel_id, enabled)
        VALUES ('default', '1438050912814895186', '1437626921394372658', '1442412877301416006', '1453208983358935121', 1)
        """
    )


def _create_mmorpg_tables(cursor):
    """Create MMORPG system tables: skills, potions, buffs."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS player_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            level INTEGER DEFAULT 1,
            equipped INTEGER DEFAULT 0,
            UNIQUE(user_id, skill_id)
        );

        CREATE TABLE IF NOT EXISTS potions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            emoji TEXT DEFAULT '🧪',
            description TEXT,
            price INTEGER NOT NULL,
            effect_type TEXT NOT NULL,
            effect_value INTEGER NOT NULL,
            duration_minutes INTEGER DEFAULT 0,
            stock INTEGER DEFAULT -1,
            min_level INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS active_buffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            buff_type TEXT NOT NULL,
            value INTEGER NOT NULL,
            expires_at TEXT
        );
    """)


def _seed_potions(cursor):
    """Seed default potion templates (INSERT OR IGNORE)."""
    potions = [
        ("初级生命药水", "❤️", "恢复 30 HP", 50, "heal_hp", 30, 0, 1),
        ("中级生命药水", "❤️‍🔥", "恢复 80 HP", 150, "heal_hp", 80, 0, 5),
        ("高级生命药水", "💖", "恢复 200 HP", 400, "heal_hp", 200, 0, 10),
        ("初级魔力药水", "💙", "恢复 20 MP", 50, "heal_mp", 20, 0, 1),
        ("中级魔力药水", "💎", "恢复 60 MP", 150, "heal_mp", 60, 0, 5),
        ("力量药剂", "💪", "攻击力 +15，持续 30 分钟", 200, "buff_atk", 15, 30, 3),
        ("防御药剂", "🛡️", "防御力 +10，持续 30 分钟", 200, "buff_def", 10, 30, 3),
        ("复活药剂", "✨", "复活并在战斗外恢复全部 HP/MP", 1000, "revive", 1, 0, 15),
    ]
    for p in potions:
        cursor.execute(
            """INSERT OR IGNORE INTO potions
               (name, emoji, description, price, effect_type, effect_value, duration_minutes, min_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            p,
        )


def _create_performance_indexes(cursor):
    """Create performance indexes."""
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_registrations_discord_id ON registrations(discord_id)",
        "CREATE INDEX IF NOT EXISTS idx_registrations_tournament_team ON registrations(tournament_id, team_id)",
        "CREATE INDEX IF NOT EXISTS idx_daily_tasks_user_date ON daily_tasks(user_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_discord_id ON transactions(discord_id)",
        "CREATE INDEX IF NOT EXISTS idx_match_signups_match ON match_signups(match_id)",
        "CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status)",
    ]:
        try:
            cursor.execute(idx_sql)
        except sqlite3.OperationalError:
            pass


def init_db():
    """Initialize database schema — delegates to sub-functions by module."""
    conn = get_db()
    cursor = conn.cursor()
    # WAL mode already set by _ensure_wal() at module load — no need to repeat here
    cursor.execute("PRAGMA busy_timeout=5000")

    _create_core_tables(cursor)
    _create_economy_tables(cursor)
    _create_lol_tables(cursor)
    _create_draft_tables(cursor)
    _create_voice_giveaway_tables(cursor)
    _create_season_queue_tables(cursor)
    _create_peiwans_tables(cursor)
    _create_predict_tables(cursor)
    _create_mmorpg_tables(cursor)
    _run_migrations(cursor)
    _seed_default_vc(cursor)
    _seed_potions(cursor)
    _create_performance_indexes(cursor)

    conn.commit()
    conn.close()


# =============================================================================
# 数据库合并 — 多实例迁移：4 容器各自 data.db → 统一 data.db
# =============================================================================
def _merge_databases():
    """检测并合并多个旧 data*.db 文件到主 data.db。

    合并策略：
    - users 表：同一 user_id 的 score（balance）累加
    - user_inventory：同一 user_id + item_id 合并去重，quantity 累加
    - transactions / voice_tracker 等：全部合并
    - player_skills：同一 user_id + skill_id 保留最高 level
    - 合并完成后旧 DB 重命名为 .bak
    """
    import os as _os
    import glob as _glob
    import shutil as _shutil

    db_dir = _os.path.dirname(DATABASE) or "."
    main_db_path = DATABASE

    # 扫描 data*.db（排除主 data.db）
    candidates = [
        p for p in _glob.glob(_os.path.join(db_dir, "data*.db"))
        if _os.path.abspath(p) != _os.path.abspath(main_db_path)
    ]
    if not candidates:
        return  # 没有需要合并的副 DB

    logger.info(f"检测到 {len(candidates)} 个副数据库，开始合并...")

    # 要合并的表（按合并策略分类）
    sum_tables = {"users": ("discord_id", "score")}
    inventory_tables = {"user_inventory": ("user_id", "item_id", "quantity")}
    skill_tables = {"player_skills": ("user_id", "skill_id", "level", "equipped")}
    append_tables = [
        "transactions", "voice_tracker", "daily_checkin", "game_limits",
        "achievements", "user_achievements", "active_effects", "daily_tasks",
        "active_buffs", "tournaments", "registrations", "teams", "results",
        "matches", "match_signups", "bets", "active_bets", "job_cooldowns",
    ]

    with get_db_ctx() as main_conn:
        main_cur = main_conn.cursor()

        for side_db_path in candidates:
            logger.info(f"合并: {side_db_path}")
            try:
                side_conn = sqlite3.connect(side_db_path, timeout=30)
                side_conn.row_factory = sqlite3.Row
                side_cur = side_conn.cursor()

                # 1. 累加表（users → score 累加）
                for table, (key_col, val_col) in sum_tables.items():
                    try:
                        side_cur.execute(f"SELECT * FROM {table}")
                        for row in side_cur.fetchall():
                            row_dict = dict(row)
                            if key_col in row_dict and val_col in row_dict:
                                main_cur.execute(
                                    f"INSERT INTO {table} ({key_col}, {val_col}, username, created_at) "
                                    f"VALUES (?, ?, ?, ?) "
                                    f"ON CONFLICT({key_col}) DO UPDATE SET "
                                    f"{val_col} = {val_col} + excluded.{val_col}",
                                    (row_dict[key_col], row_dict.get(val_col, 0),
                                     row_dict.get("username", ""), row_dict.get("created_at", "")),
                                )
                    except sqlite3.OperationalError:
                        pass

                # 2. 仓库表（user_inventory → quantity 累加）
                for table, (uid_col, item_col, qty_col) in inventory_tables.items():
                    try:
                        side_cur.execute(f"SELECT * FROM {table}")
                        for row in side_cur.fetchall():
                            row_dict = dict(row)
                            if uid_col in row_dict and item_col in row_dict:
                                main_cur.execute(
                                    f"INSERT INTO {table} ({uid_col}, {item_col}, {qty_col}) "
                                    f"VALUES (?, ?, ?) "
                                    f"ON CONFLICT({uid_col}, {item_col}) DO UPDATE SET "
                                    f"{qty_col} = {qty_col} + excluded.{qty_col}",
                                    (row_dict[uid_col], row_dict[item_col], row_dict.get(qty_col, 1)),
                                )
                    except sqlite3.OperationalError:
                        pass

                # 3. 技能表（player_skills → 保留最高 level / equipped）
                for table, (uid_col, sid_col, lvl_col, eq_col) in skill_tables.items():
                    try:
                        side_cur.execute(f"SELECT * FROM {table}")
                        for row in side_cur.fetchall():
                            row_dict = dict(row)
                            if uid_col in row_dict and sid_col in row_dict:
                                main_cur.execute(
                                    f"INSERT INTO {table} ({uid_col}, {sid_col}, {lvl_col}, {eq_col}) "
                                    f"VALUES (?, ?, ?, ?) "
                                    f"ON CONFLICT({uid_col}, {sid_col}) DO UPDATE SET "
                                    f"{lvl_col} = MAX({lvl_col}, excluded.{lvl_col}), "
                                    f"{eq_col} = MAX({eq_col}, excluded.{eq_col})",
                                    (row_dict[uid_col], row_dict[sid_col],
                                     row_dict.get(lvl_col, 1), row_dict.get(eq_col, 0)),
                                )
                    except sqlite3.OperationalError:
                        pass

                # 4. 追加表（直接 INSERT OR IGNORE）
                for table in append_tables:
                    try:
                        # 获取表列名
                        side_cur.execute(f"SELECT * FROM {table} LIMIT 0")
                        cols = [d[0] for d in side_cur.description]
                        placeholders = ", ".join(["?"] * len(cols))
                        col_names = ", ".join(cols)

                        side_cur.execute(f"SELECT * FROM {table}")
                        for row in side_cur.fetchall():
                            vals = [row[c] for c in cols]
                            try:
                                main_cur.execute(
                                    f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})",
                                    vals,
                                )
                            except sqlite3.OperationalError:
                                pass
                    except sqlite3.OperationalError:
                        pass

                side_conn.close()
                main_conn.commit()

                # 重命名为 .bak
                bak_path = side_db_path + ".bak"
                _shutil.move(side_db_path, bak_path)
                logger.info(f"已备份: {_os.path.basename(side_db_path)} → {_os.path.basename(bak_path)}")

            except Exception as e:
                logger.warning(f"合并 {side_db_path} 失败: {e}")

    logger.info("数据库合并完成")
