"""
GMPT Bot — Global Jackpot system
Global jackpot pool for slot machines. 
5% of each bet goes into the pool. 0.5% chance to win the entire pool.
"""
import random
import time
from database import get_db_ctx
import logging

logger = logging.getLogger(__name__)

JACKPOT_CONTRIBUTION = 0.05     # 5% of bet
JACKPOT_WIN_CHANCE = 0.005      # 0.5%


def _ensure_tables():
    """Create jackpot table if not exists."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jackpot (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                pool INTEGER NOT NULL DEFAULT 0,
                total_contributions INTEGER NOT NULL DEFAULT 0,
                total_payouts INTEGER NOT NULL DEFAULT 0,
                last_winner TEXT,
                last_won_at REAL,
                updated_at REAL
            )
        """)
        cur.execute("""
            INSERT OR IGNORE INTO jackpot (id, pool, total_contributions, total_payouts, updated_at)
            VALUES (1, 0, 0, 0, ?)
        """, (time.time(),))
        conn.commit()


_ensure_tables()


def get_jackpot() -> int:
    """Get current jackpot pool amount."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT pool FROM jackpot WHERE id = 1")
        row = cur.fetchone()
        return row["pool"] if row else 0


def get_jackpot_stats() -> dict:
    """Get full jackpot stats."""
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM jackpot WHERE id = 1")
        row = cur.fetchone()
        if not row:
            return {"pool": 0, "total_contributions": 0, "total_payouts": 0, "last_winner": None}
        return {
            "pool": row["pool"],
            "total_contributions": row["total_contributions"],
            "total_payouts": row["total_payouts"],
            "last_winner": row["last_winner"],
            "last_won_at": row["last_won_at"],
        }


def contribute_to_jackpot(bet: int) -> int:
    """Contribute 5% of bet to jackpot. Returns contribution amount."""
    contribution = max(1, int(bet * JACKPOT_CONTRIBUTION))
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE jackpot SET pool = pool + ?, total_contributions = total_contributions + ?, updated_at = ? WHERE id = 1",
            (contribution, contribution, time.time()),
        )
        conn.commit()
    return contribution


def try_win_jackpot(uid: str, username: str) -> tuple[bool, int, int]:
    """
    Attempt to win the jackpot (0.5% chance).
    Returns (won: bool, win_amount: int, pool_before: int).
    """
    pool_before = get_jackpot()
    if pool_before <= 0:
        return False, 0, 0

    roll = random.random()
    if roll >= JACKPOT_WIN_CHANCE:
        return False, 0, pool_before

    # Winner!
    with get_db_ctx() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE jackpot SET pool = 0, total_payouts = total_payouts + ?, last_winner = ?, last_won_at = ?, updated_at = ? WHERE id = 1",
            (pool_before, username, time.time(), time.time()),
        )
        conn.commit()

    return True, pool_before, pool_before
