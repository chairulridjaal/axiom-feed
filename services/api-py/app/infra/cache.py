"""One cache — byte-budget + TTL + LRU + tiered TTL.

Replaces 7 duplicated *Cache classes in be-web (services/*, each with own TTL/size).

Tiered TTL:
  daily candles  → 24h (86400s) — fundamental stable
  intraday/min   → 60s
  quotes/books   → 30s
  movers         → 60s
  fallback       → 60s

Byte budget: 100 keys + 50MB (env-tunable CANDLES_CACHE_KEYS/BYTES).
Dedup: LRU eviction by count or byte size.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

# tier map — new decision: explicit per-domain ttl, not single 60s
TIER_TTL = {
    "candles:daily": 86400,
    "candles:minute": 60,
    "candles:intraday": 60,
    "quotes": 30,
    "books": 30,
    "trades": 10,
    "movers": 60,
    "brokers": 300,
    "sectors": 1800,
    "calendars": 3600,
    "default": 60,
}


_TTL_ORDERED = sorted(TIER_TTL.items(), key=lambda kv: -len(kv[0]))


def ttl_for(key: str) -> float:
    for prefix, ttl in _TTL_ORDERED:
        if prefix == "default":
            continue
        if key.startswith(prefix):
            return float(ttl)
    return float(TIER_TTL["default"])


@dataclass
class Entry:
    value: object
    expires_at: float
    size: int


class BoundedCache:
    def __init__(
        self,
        max_keys: int | None = None,
        max_bytes: int | None = None,
        ttl_s: float | None = None,
    ):
        self.max_keys = int(max_keys or os.getenv("CANDLES_CACHE_KEYS", "100"))
        self.max_bytes = int(max_bytes or os.getenv("CANDLES_CACHE_BYTES", "50000000"))
        # base ttl_s kept for compat; if not given, use default tier
        self.ttl_s = float(ttl_s or TIER_TTL["default"])
        self._store: OrderedDict[str, Entry] = OrderedDict()
        self._bytes = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            e = self._store.get(key)
            if not e or time.monotonic() > e.expires_at:
                if e:
                    self._bytes -= e.size
                    del self._store[key]
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return e.value

    def set(self, key: str, value: object, size: int, ttl_s: float | None = None):
        if size > self.max_bytes:
            return
        with self._lock:
            chosen_ttl = ttl_s if ttl_s is not None else ttl_for(key)
            if key in self._store:
                self._bytes -= self._store[key].size
                del self._store[key]
            evicted = 0
            while (
                len(self._store) >= self.max_keys or self._bytes + size > self.max_bytes
            ) and self._store and evicted < 16:
                _, old = self._store.popitem(last=False)
                self._bytes -= old.size
                self.evictions += 1
                evicted += 1
            if len(self._store) >= self.max_keys or self._bytes + size > self.max_bytes:
                return
            self._store[key] = Entry(value, time.monotonic() + chosen_ttl, size)
            self._bytes += size

    def stats(self):
        return {
            "keys": len(self._store),
            "bytes": self._bytes,
            "max_keys": self.max_keys,
            "max_bytes": self.max_bytes,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
        }

    def clear(self):
        with self._lock:
            self._store.clear()
            self._bytes = 0
