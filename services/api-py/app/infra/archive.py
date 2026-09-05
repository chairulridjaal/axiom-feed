"""SQLite-backed VWAP/flow analytics over the tick store.

Replaces the DuckDB + Parquet engine: one aggregate SQL query against the
existing trades table. Parquet export had no downstream consumer.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(os.getenv("TICKS_DB_PATH", "data/ticks.db"))

_VWAP_SQL = """
    SELECT
        COUNT(*),
        COALESCE(SUM(volume), 0),
        COALESCE(SUM(CAST(price AS REAL) * volume), 0.0),
        COALESCE(MIN(CAST(price AS REAL)), 0.0),
        COALESCE(MAX(CAST(price AS REAL)), 0.0),
        COALESCE(SUM(CASE WHEN side = 'BUY' THEN volume ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN side = 'SELL' THEN volume ELSE 0 END), 0)
    FROM trades
    WHERE symbol = ?
"""


def _vwap_row_to_stats(sym: str, row: tuple) -> dict[str, Any] | None:
    trade_count, tot_vol, tot_val, min_p, max_p, buy_vol, sell_vol = row
    if not trade_count:
        return None
    tot_vol = int(tot_vol)
    vwap = (float(tot_val) / tot_vol) if tot_vol else 0.0
    return {
        "symbol": sym,
        "trade_count": int(trade_count),
        "total_volume": tot_vol,
        "total_value": f"{float(tot_val):.2f}",
        "vwap": f"{vwap:.2f}",
        "min_price": f"{float(min_p):.2f}",
        "max_price": f"{float(max_p):.2f}",
        "buy_volume": int(buy_vol),
        "sell_volume": int(sell_vol),
        "net_volume": int(buy_vol - sell_vol),
    }


class SQLiteArchive:
    """VWAP/flow analytics over TickStore's SQLite table (no DuckDB)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection | None:
        if not self.db_path.exists():
            return None
        try:
            # ponytail: short-lived read connection per query, pooled conn if profiling says so
            return sqlite3.connect(str(self.db_path), timeout=5.0)
        except Exception as e:
            logger.debug(f"SQLite analytics connect failed: {e}")
            return None

    def calculate_vwap(self, symbol: str) -> dict[str, Any] | None:
        """Volume Weighted Average Price + execution stats via one SUM query."""
        sym = symbol.upper()
        con = self._connect()
        if con is None:
            return None
        try:
            start = time.monotonic()
            with self._lock:
                row = con.execute(_VWAP_SQL, (sym,)).fetchone()
            elapsed_ms = (time.monotonic() - start) * 1000.0
            # ponytail: log-only tripwire, no benchmark suite until this fires in prod
            if elapsed_ms > 500:
                logger.warning(f"SQLite VWAP slow: {sym} took {elapsed_ms:.0f}ms")
            if not row or not row[0]:
                return None
            return _vwap_row_to_stats(sym, row)
        except Exception as e:
            logger.debug(f"SQLite VWAP query failed: {e}")
            return None
        finally:
            try:
                con.close()
            except Exception:
                pass

    def get_flow_stats(self, symbol: str) -> dict[str, Any] | None:
        """Buyer/seller flow imbalance derived from the VWAP aggregate."""
        stats = self.calculate_vwap(symbol)
        if not stats:
            return None
        tot_vol = stats["total_volume"]
        buy_vol = stats["buy_volume"]
        sell_vol = stats["sell_volume"]
        buy_ratio = round((buy_vol / tot_vol) * 100.0, 2) if tot_vol > 0 else 50.0
        sell_ratio = round((sell_vol / tot_vol) * 100.0, 2) if tot_vol > 0 else 50.0
        return {
            "symbol": stats["symbol"],
            "trade_count": stats["trade_count"],
            "total_volume": tot_vol,
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "buy_volume_pct": buy_ratio,
            "sell_volume_pct": sell_ratio,
            "flow_imbalance": round(buy_ratio - sell_ratio, 2),
            "vwap": stats["vwap"],
        }


# Back-compat alias (DuckDBArchive → SQLiteArchive; Parquet export removed).
DuckDBArchive = SQLiteArchive
