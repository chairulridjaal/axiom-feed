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
            if isinstance(cached, (bytes, bytearray)):

                async def _from_bytes():
                    yield bytes(cached)

                return StreamingResponse(
                    _from_bytes(), media_type="application/x-ndjson", headers={"X-Cache": "HIT"}
                )
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

        async def _produce() -> bytes:
            chunks: list[bytes] = []
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
                    chunks.append(orjson.dumps(d) + b"\n")
            except Exception as e:
                err_msg = str(e)
                logger.error(f"candles stream failed {symbol} {frm}->{to} {resolution}: {err_msg}")
                chunks.append(orjson.dumps({"error": err_msg}) + b"\n")
                return b"".join(chunks)

            if collected and len(collected) <= MAX_CACHE_CANDLES:
                try:
                    raw_bytes = orjson.dumps(collected)
                    if len(raw_bytes) <= MAX_CACHE_BYTES:
                        cache.set(cache_key, b"".join(chunks), size=len(raw_bytes))
                except Exception:
                    pass
            return b"".join(chunks)

        try:
            body: bytes = await sf.do(cache_key, _produce)
            skipped_cache = len(body) > MAX_CACHE_BYTES
        except Exception as e:
            err_msg = str(e)
            logger.error(f"candles produce failed {symbol} {frm}->{to} {resolution}: {err_msg}")

            async def _from_error():
                yield orjson.dumps({"error": err_msg}) + b"\n"

            return StreamingResponse(
                _from_error(), media_type="application/x-ndjson", headers={"X-Cache": "MISS"}
            )

        async def _stream_replay():
            yield body

        return StreamingResponse(
            _stream_replay(),
            media_type="application/x-ndjson",
            headers={"X-Cache": "MISS" if not skipped_cache else "SKIP"},
        )

    return router
