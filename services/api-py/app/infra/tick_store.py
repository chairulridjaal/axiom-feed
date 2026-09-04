"""Embedded bounded time-series store for running trade ticks.

Provides offline tick tape replay when upstream WebSocket feeds are closed
(nights, weekends, holidays) or after system restarts.
Uses SQLite in Write-Ahead Logging (WAL) mode for sub-millisecond persistence
and zero external database dependencies.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.domain.models import Board, Side, Trade

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(os.getenv("TICKS_DB_PATH", "data/ticks.db"))
DEFAULT_MAX_RECORDS = int(os.getenv("TICKS_MAX_RECORDS", "50000"))
DEFAULT_BATCH_SIZE = int(os.getenv("TICKS_BATCH_SIZE", "50"))


class TickStore:
    """Bounded SQLite time-series store for running trade ticks."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        max_records: int = DEFAULT_MAX_RECORDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.max_records = max_records
        self._batch_size = batch_size
        self._pending: list[Trade] = []
        self._lock = threading.Lock()
        self._con: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._con = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10.0,
            )
            with self._con:
                self._con.execute("PRAGMA journal_mode = WAL;")
                self._con.execute("PRAGMA synchronous = NORMAL;")
                self._con.execute("PRAGMA busy_timeout = 5000;")
                self._con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trades (
                        seq INTEGER PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        price TEXT NOT NULL,
                        volume INTEGER NOT NULL,
                        side TEXT NOT NULL,
                        board TEXT NOT NULL,
                        ts TEXT NOT NULL,
                        change TEXT,
                        change_pct TEXT
                    )
                    """
                )
                self._con.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_trades_symbol_seq
                    ON trades (symbol, seq DESC)
                    """
                )
                self._con.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_trades_seq
                    ON trades (seq DESC)
                    """
                )
            logger.info(f"TickStore initialized at {self.db_path} (limit={self.max_records})")
        except Exception as e:
            logger.warning(f"Failed to initialize TickStore at {self.db_path}: {e}")
            self._con = None

    def _flush_locked(self) -> None:
        if self._con is None or not self._pending:
            return
        rows = [
            (
                t.seq,
                t.symbol.upper(),
                str(t.price),
                t.volume,
                t.side.value if hasattr(t.side, "value") else str(t.side),
                t.board.value if hasattr(t.board, "value") else str(t.board),
                t.ts.isoformat(),
                str(t.change) if t.change is not None else None,
                str(t.change_pct) if t.change_pct is not None else None,
            )
            for t in self._pending
        ]
        self._pending.clear()
        try:
            with self._con:
                self._con.executemany(
                    """
                    INSERT OR IGNORE INTO trades (
                        seq, symbol, price, volume, side, board, ts, change, change_pct
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        except Exception as e:
            logger.debug(f"TickStore flush failed: {e}")

    def insert_trade(self, trade: Trade) -> None:
        if self._con is None:
            return
        with self._lock:
            self._pending.append(trade)
            if len(self._pending) >= self._batch_size:
                self._flush_locked()

    def insert_batch(self, trades: list[Trade]) -> None:
        if self._con is None or not trades:
            return
        with self._lock:
            self._pending.extend(trades)
            if len(self._pending) >= self._batch_size:
                self._flush_locked()

    def get_trades(self, symbol: str | None = None, limit: int = 50) -> list[Trade]:
        if self._con is None:
            return []
        with self._lock:
            self._flush_locked()
            try:
                if symbol:
                    cur = self._con.execute(
                        """
                        SELECT symbol, price, volume, side, board, ts, seq, change, change_pct
                        FROM trades
                        WHERE symbol = ?
                        ORDER BY seq DESC
                        LIMIT ?
                        """,
                        (symbol.upper(), limit),
                    )
                else:
                    cur = self._con.execute(
                        """
                        SELECT symbol, price, volume, side, board, ts, seq, change, change_pct
                        FROM trades
                        ORDER BY seq DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )
                rows = cur.fetchall()
            except Exception as e:
                logger.debug(f"TickStore query failed: {e}")
                return []

        out: list[Trade] = []
        for r in rows:
            sym, price_s, vol, side_s, board_s, ts_s, seq, ch_s, ch_pct_s = r
            try:
                ts = datetime.fromisoformat(ts_s)
            except Exception:
                ts = datetime.now()

            side = Side(side_s) if side_s in Side._value2member_map_ else Side.UNKNOWN
            board = Board(board_s) if board_s in Board._value2member_map_ else Board.UNKNOWN

            out.append(
                Trade(
                    symbol=sym,
                    price=Decimal(price_s),
                    volume=int(vol),
                    side=side,
                    board=board,
                    ts=ts,
                    seq=int(seq),
                    change=Decimal(ch_s) if ch_s is not None else None,
                    change_pct=Decimal(ch_pct_s) if ch_pct_s is not None else None,
                )
            )
        return out

    def prune_old_records(self) -> int:
        """Prune records beyond max_records limit to bound disk usage."""
        if self._con is None or self.max_records <= 0:
            return 0
        with self._lock:
            self._flush_locked()
            try:
                with self._con:
                    cur = self._con.execute(
                        """
                        DELETE FROM trades
                        WHERE seq NOT IN (
                            SELECT seq FROM trades
                            ORDER BY seq DESC
                            LIMIT ?
                        )
                        """,
                        (self.max_records,),
                    )
                    return cur.rowcount
            except Exception as e:
                logger.debug(f"TickStore prune failed: {e}")
                return 0

    def count(self) -> int:
        if self._con is None:
            return 0
        with self._lock:
            self._flush_locked()
            try:
                cur = self._con.execute("SELECT COUNT(*) FROM trades")
                row = cur.fetchone()
                return int(row[0]) if row else 0
            except Exception:
                return 0

    def close(self) -> None:
        with self._lock:
            self._flush_locked()
            if self._con is not None:
                try:
                    self._con.close()
                except Exception:
                    pass
                self._con = None
