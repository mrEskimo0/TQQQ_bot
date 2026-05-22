"""
SQLite-backed state: position and trade history.
"""
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Position:
    shares: int
    avg_cost: float        # average cost per share
    total_invested: float  # running total dollars put in
    last_updated: str


@dataclass
class Trade:
    timestamp: str
    action: str   # 'BUY' or 'SELL'
    shares: int
    price: float
    total_value: float
    sma_200: float
    notes: str = ""


class StateDB:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS position (
                    id            INTEGER PRIMARY KEY CHECK (id = 1),
                    shares        INTEGER NOT NULL DEFAULT 0,
                    avg_cost      REAL    NOT NULL DEFAULT 0.0,
                    total_invested REAL   NOT NULL DEFAULT 0.0,
                    last_updated  TEXT    NOT NULL DEFAULT ''
                );

                INSERT OR IGNORE INTO position (id, shares, avg_cost, total_invested, last_updated)
                VALUES (1, 0, 0.0, 0.0, '');

                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    action      TEXT    NOT NULL,
                    shares      INTEGER NOT NULL,
                    price       REAL    NOT NULL,
                    total_value REAL    NOT NULL,
                    sma_200     REAL    NOT NULL,
                    notes       TEXT    NOT NULL DEFAULT ''
                );

            """)

    # ── Position ─────────────────────────────────────────────────────────────

    def get_position(self) -> Position:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM position WHERE id = 1").fetchone()
        return Position(
            shares=row["shares"],
            avg_cost=row["avg_cost"],
            total_invested=row["total_invested"],
            last_updated=row["last_updated"],
        )

    def set_position(self, shares: int, avg_cost: float, total_invested: float):
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """UPDATE position
                   SET shares = ?, avg_cost = ?, total_invested = ?, last_updated = ?
                   WHERE id = 1""",
                (shares, avg_cost, total_invested, now),
            )

    # ── Trades ────────────────────────────────────────────────────────────────

    def record_trade(self, trade: Trade):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO trades (timestamp, action, shares, price, total_value, sma_200, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade.timestamp,
                    trade.action,
                    trade.shares,
                    trade.price,
                    trade.total_value,
                    trade.sma_200,
                    trade.notes,
                ),
            )

    def get_trades(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


