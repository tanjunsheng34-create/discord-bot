import sqlite3
import time
from contextlib import contextmanager
from config import DATABASE

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
    except Exception:
        pass


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


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    # Ensure WAL + busy_timeout on the init connection as well
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")

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

        -- === 经济系统 ===

        CREATE TABLE IF NOT EXISTS daily_checkin (
            discord_id  TEXT PRIMARY KEY,
            last_date   TEXT NOT NULL,
            streak      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id  TEXT NOT NULL,
            amount      INTEGER NOT NULL,
            reason      TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now'))
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

        -- === 抽奖系统 ===

        CREATE TABLE IF NOT EXISTS giveaway_tickets (
            discord_id TEXT PRIMARY KEY,
            tickets INTEGER DEFAULT 0
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

        CREATE TABLE IF NOT EXISTS giveaway_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER,
            discord_id TEXT,
            tickets_used INTEGER DEFAULT 1,
            FOREIGN KEY (giveaway_id) REFERENCES giveaways(id)
        );

        -- === Discord 道具状态 ===

        CREATE TABLE IF NOT EXISTS user_flags (
            discord_id TEXT PRIMARY KEY,
            queue_skip INTEGER DEFAULT 0,
            mode_pick TEXT
        );
    """)

    # --- 新增锦标赛字段（Swiss/Elimination Tournament System）---
    for col, col_type in [
        ("format", "TEXT DEFAULT 'swiss'"),
        ("max_players", "INTEGER DEFAULT 32"),
        ("rounds", "INTEGER DEFAULT 3"),
        ("tier_restriction", "TEXT"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE tournaments ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # --- 新增 registrations.is_sub 字段（替补标记）---
    try:
        cursor.execute("ALTER TABLE registrations ADD COLUMN is_sub INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # --- 新增 users.mmr 字段（排位系统）---
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN mmr INTEGER DEFAULT 1000")
    except sqlite3.OperationalError:
        pass

    # --- 新增选路比赛字段 / Role-Pick Match Fields ---
    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN role_pick INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE registrations ADD COLUMN lane TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # --- 新增商店字段（stock/ends_at/discount_pct）---
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

    cursor.executescript("""
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

        -- === Captain Draft / 队长选秀 ===

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

        -- === Voice time tracking for daily reward ===
        CREATE TABLE IF NOT EXISTS voice_sessions (
            discord_id    TEXT NOT NULL,
            join_time     TEXT NOT NULL,
            total_seconds INTEGER DEFAULT 0,
            PRIMARY KEY (discord_id, join_time)
        );

        -- === Giveaway system ===
        CREATE TABLE IF NOT EXISTS giveaway (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id          TEXT NOT NULL,
            channel_id        TEXT NOT NULL,
            message_id        TEXT,
            prize             TEXT NOT NULL,
            duration_minutes  INTEGER NOT NULL,
            winner_count      INTEGER NOT NULL DEFAULT 1,
            created_by        TEXT NOT NULL,
            ends_at           TEXT,
            status            TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS giveaway_entries (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id   INTEGER NOT NULL,
            user_id       TEXT NOT NULL,
            UNIQUE(giveaway_id, user_id)
        );

        -- === Voice / online time tracker (stats) ===
        CREATE TABLE IF NOT EXISTS voice_tracker (
            user_id         TEXT PRIMARY KEY,
            total_seconds   INTEGER DEFAULT 0,
            login_days      INTEGER DEFAULT 0,
            total_joins     INTEGER DEFAULT 0,
            last_join_date  TEXT,
            last_join_time  TEXT
        );

        -- === MMR 排位系统 ===
        CREATE TABLE IF NOT EXISTS mmr (
            discord_id  TEXT PRIMARY KEY,
            mmr         INTEGER DEFAULT 1000,
            wins        INTEGER DEFAULT 0,
            losses      INTEGER DEFAULT 0,
            streak      INTEGER DEFAULT 0,
            rank        TEXT DEFAULT 'Iron'
        );

        -- === MMR 排行榜持久化 ===
        CREATE TABLE IF NOT EXISTS mmr_board (
            guild_id    TEXT PRIMARY KEY,
            message_id  TEXT NOT NULL,
            channel_id  TEXT NOT NULL
        );

        -- === MatchView 持久化状态（Bot 重启后恢复报名按钮）===
        CREATE TABLE IF NOT EXISTS match_view_state (
            message_id        TEXT PRIMARY KEY,
            match_id          INTEGER NOT NULL,
            channel_id        INTEGER NOT NULL,
            player_list_msg_id TEXT
        );

        -- === 道具激活效果 / Active Item Effects ===
        CREATE TABLE IF NOT EXISTS active_effects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,
            effect_type TEXT NOT NULL,
            used_at     TEXT DEFAULT (datetime('now')),
            consumed    INTEGER DEFAULT 0
        );

        -- === Dashboard 面板持久化（Bot 重启后自动刷新）===  [DEPRECATED: 零引用死表，待下个大版本删除]
        CREATE TABLE IF NOT EXISTS dashboard_panel (
            guild_id    TEXT PRIMARY KEY,
            message_id  TEXT NOT NULL,
            channel_id  TEXT NOT NULL
        );

        -- === Betting / 金币下注 ===
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

        -- === 赛季系统 / Season System ===
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

        -- === 每周挑战 / Weekly Challenges ===
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

        -- === 快速比赛 / Quick Match System ===
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
    """)

    # ── 性能索引 / Performance Indexes ──
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_registrations_discord_id ON registrations(discord_id)",
        "CREATE INDEX IF NOT EXISTS idx_registrations_tournament_team ON registrations(tournament_id, team_id)",
        "CREATE INDEX IF NOT EXISTS idx_giveaway_entries_giveaway ON giveaway_entries(giveaway_id)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_discord_id ON transactions(discord_id)",
        "CREATE INDEX IF NOT EXISTS idx_match_signups_match ON match_signups(match_id)",
    ]:
        try:
            cursor.execute(idx_sql)
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()
