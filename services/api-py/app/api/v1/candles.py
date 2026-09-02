"""GET /v1/candles/:symbol — streamed, sliced, cached, deduplicated.

Never holds 60MB response.json() (be-web services/scrape.py + core/http_client.py).
Uses httpx.stream + 365d/90d slicing + StreamingResponse yielding Candle JSON lines.

Singleflight deduplication prevents thundering-herd on identical uncached keys.
Cache: BoundedCache 100 keys + 50MB, tiered TTL (daily 24h, minute 60s).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import orjson
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.security import verify_api_key
from app.infra.cache import BoundedCache
from app.infra.singleflight import Singleflight
from app.providers.stockbit.provider import get_provider

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Candles"])
_candles_flight = Singleflight()


def init_candles(cache: BoundedCache, flight: Singleflight | None = None):
    sf = flight or _candles_flight

    @router.get("/v1/candles/{symbol}")
    async def candles(
        symbol: str,
        frm: date = Query(..., alias="from"),
        to: date = Query(..., alias="to"),
        resolution: str = Query("daily", pattern="^(daily|minute)$"),
    ):
        if to < frm:
            frm, to = to, frm
        cache_key = f"candles:{resolution}:{symbol.upper()}:{frm.isoformat()}:{to.isoformat()}"
        cached = cache.get(cache_key)
        if cached is not None:
            cached_list: list[dict[str, Any]] = cached  # type: ignore[assignment]

            async def _from_cache():
                for c in cached_list:
                    yield orjson.dumps(c) + b"\n"

            return StreamingResponse(
                _from_cache(), media_type="application/x-ndjson", headers={"X-Cache": "HIT"}
            )

        provider = get_provider()
        MAX_CACHE_CANDLES = 20000
        MAX_CACHE_BYTES = 5_000_000

        async def _stream_direct():
            collected: list[dict[str, Any]] = []
            try:
                async for c in provider.candles(symbol, frm, to, resolution):  # type: ignore[arg-type]
                    d = {
                        "ts": c.ts.isoformat(),
                        "open": str(c.open),
                        "high": str(c.high),
                        "low": str(c.low),
                        "close": str(c.close),
                        "volume": c.volume,
                        "value": str(c.value),
                        "freq": c.freq,
                    }
                    if len(collected) < MAX_CACHE_CANDLES:
                        collected.append(d)
                    yield orjson.dumps(d) + b"\n"

                if collected and len(collected) <= MAX_CACHE_CANDLES:
                    try:
                        raw_bytes = orjson.dumps(collected)
                        if len(raw_bytes) <= MAX_CACHE_BYTES:
                            cache.set(cache_key, collected, size=len(raw_bytes))
                    except Exception:
                        pass
            except Exception as e:
                err_msg = str(e)
                logger.error(f"candles stream failed {symbol} {frm}->{to} {resolution}: {err_msg}")
                yield orjson.dumps({"error": err_msg}) + b"\n"

        return StreamingResponse(
            _stream_direct(), media_type="application/x-ndjson", headers={"X-Cache": "MISS"}
        )

    return router
