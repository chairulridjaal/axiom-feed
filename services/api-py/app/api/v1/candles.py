"""Bounded complete NDJSON responses; cache only successful candle series."""

from __future__ import annotations

import logging
from contextlib import aclosing
from datetime import date

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.core.security import verify_api_key
from app.domain.models import Resolution
from app.infra.cache import BoundedCache
from app.infra.candle_limits import (
    MAX_CANDLE_BYTES,
    MAX_CANDLE_LINE_BYTES,
    MAX_CANDLES,
    MAX_DAILY_DAYS,
    MAX_MINUTE_DAYS,
    CandleBudgetExceeded,
)
from app.infra.singleflight import Singleflight
from app.providers.stockbit.provider import get_provider

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Candles"])
_candles_flight: Singleflight[bytes] = Singleflight()


def init_candles(cache: BoundedCache, flight: Singleflight[bytes] | None = None):
    sf = flight or _candles_flight

    @router.get("/v1/candles/{symbol}")
    async def candles(
        symbol: str,
        frm: date = Query(..., alias="from"),
        to: date = Query(..., alias="to"),
        resolution: Resolution = Query("daily"),
    ) -> Response:
        start, end = sorted((frm, to))
        max_days = MAX_DAILY_DAYS if resolution == "daily" else MAX_MINUTE_DAYS
        if (end - start).days > max_days:
            raise HTTPException(422, f"Candle range exceeds {max_days} days for {resolution}")
        cache_key = f"candles:{resolution}:{symbol.upper()}:{start.isoformat()}:{end.isoformat()}"
        hit = cache.get(cache_key)
        if isinstance(hit, bytes):
            return Response(hit, media_type="application/x-ndjson", headers={"X-Cache": "HIT"})

        async def produce() -> bytes:
            buf = bytearray()
            count = 0
            provider = get_provider()
            async with aclosing(provider.candles(symbol, start, end, resolution)) as stream:
                async for c in stream:
                    count += 1
                    if count > MAX_CANDLES:
                        raise CandleBudgetExceeded("rows", MAX_CANDLES)
                    line = (
                        orjson.dumps(
                            {
                                "ts": c.ts.isoformat(),
                                "open": str(c.open),
                                "high": str(c.high),
                                "low": str(c.low),
                                "close": str(c.close),
                                "volume": c.volume,
                                "value": str(c.value) if c.value is not None else None,
                                "freq": c.freq,
                            }
                        )
                        + b"\n"
                    )
                    if len(line) > MAX_CANDLE_LINE_BYTES:
                        raise CandleBudgetExceeded("line bytes", MAX_CANDLE_LINE_BYTES)
                    if len(buf) + len(line) > MAX_CANDLE_BYTES:
                        raise CandleBudgetExceeded("serialized bytes", MAX_CANDLE_BYTES)
                    buf.extend(line)
            payload = bytes(buf)
            if count:
                cache.set(cache_key, payload, size=len(payload))
            return payload

        try:
            body = await sf.do(cache_key, produce)
        except CandleBudgetExceeded as exc:
            raise HTTPException(413, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(504, "Candle request deadline exceeded") from exc
        except Exception as exc:  # HTTP boundary: HTTP boundary
            logger.warning("Candle provider unavailable for %s", symbol)
            raise HTTPException(502, "Candle data unavailable") from exc
        return Response(body, media_type="application/x-ndjson", headers={"X-Cache": "MISS"})

    return router
