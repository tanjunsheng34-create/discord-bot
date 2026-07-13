import sqlite3
from config import DATABASE


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

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
            item_type   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_inventory (
            user_id     TEXT NOT NULL,
            item_id     INTEGER NOT NULL,
            quantity    INTEGER DEFAULT 1,
            UNIQUE(user_id, item_id)
        );
    """)

    conn.commit()
    conn.close()
