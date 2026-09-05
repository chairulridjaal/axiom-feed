"""Shared upstream cache + singleflight for REST routers.

One BoundedCache + one Singleflight shared across domains; each router uses
its tier key prefix (infra/cache.py TIER_TTL) so TTLs stay per-domain without
per-router cache instances.
"""

from __future__ import annotations

import logging
from typing import Any

import orjson

from app.infra.cache import BoundedCache
from app.infra.singleflight import Singleflight

logger = logging.getLogger(__name__)

upstream_cache = BoundedCache()
upstream_flight = Singleflight()


async def cached_json(cache_key: str, produce) -> Any:
    """Return cached value or run produce() once per key under singleflight."""
    hit = upstream_cache.get(cache_key)
    if hit is not None:
        return hit
    value = await upstream_flight.do(cache_key, produce)
    try:
        size = len(orjson.dumps(value, default=str))
        if size <= 5_000_000:
            upstream_cache.set(cache_key, value, size=size)
    except Exception:
        pass
    return value
