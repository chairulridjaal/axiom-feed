from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Quotes"])


@router.get("/v1/quotes/subscriptions")
async def quote_subscriptions():
    prov = get_provider()
    return {"subscribed": list(prov.live_feed().snapshot_quotes().keys())}


@router.get("/v1/quotes")
async def quotes(symbols: str = Query("", description="comma-separated")):
    prov = get_provider()
    snap = prov.live_feed().snapshot_quotes()
    if symbols:
        wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
        out = {}
        for sym in wanted:
            q = snap.get(sym)
            if not q:
                try:
                    data = await prov.emitten_info(sym)
                    if data and isinstance(data, dict) and "data" in data:
                        d = data["data"]
                        price = (
                            d.get("price") or d.get("last_price") or d.get("previous_price") or 0
                        )
                        out[sym] = {"last": str(price), "ts": d.get("date", "")}
                    else:
                        out[sym] = None
                except Exception:
                    out[sym] = None
            else:
                out[sym] = {"last": str(q.last), "ts": q.ts.isoformat()}
    else:
        out = {k: {"last": str(v.last), "ts": v.ts.isoformat()} for k, v in snap.items()}
    return {"symbols": symbols, "quotes": out}


@router.get("/v1/quotes/{symbol}")
async def quote(symbol: str):
    sym = symbol.upper()
    prov = get_provider()
    q = prov.live_feed().snapshot_quotes().get(sym)
    if not q:
        try:
            data = await prov.emitten_info(sym)
            if data and isinstance(data, dict) and "data" in data:
                d = data["data"]
                price = d.get("price") or d.get("last_price") or d.get("previous_price") or 0
                avg = d.get("average")
                return {
                    "symbol": sym,
                    "quote": {
                        "last": str(price),
                        "open": str(d.get("open_price", "")),
                        "high": str(d.get("high", "")),
                        "low": str(d.get("low", "")),
                        "prev_close": str(d.get("previous_price", "")),
                        "change": str(d.get("change", "")),
                        "avg": str(avg) if avg else None,
                        "ts": str(d.get("date", "")),
                    },
                }
        except Exception:
            pass
        return {"symbol": sym, "quote": None}
    return {
        "symbol": sym,
        "quote": {
            "last": str(q.last),
            "open": str(q.open) if q.open else None,
            "high": str(q.high) if q.high else None,
            "low": str(q.low) if q.low else None,
            "prev_close": str(q.prev_close) if q.prev_close else None,
            "avg": str(q.avg) if q.avg else None,
            "ts": q.ts.isoformat(),
        },
    }


@router.post("/v1/quotes/subscribe")
async def quote_subscribe(payload: dict = Body(...)):
    symbols = payload.get("symbols", [])
    prov = get_provider()
    try:
        prov.live_feed().subscribe(set(s.upper() for s in symbols), {"quotes"})
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"subscribed": symbols}


@router.post("/v1/subscriptions/ensure")
async def ensure(payload: Any = Body(...)):
    symbols: list[str] = []
    if isinstance(payload, dict):
        symbols = payload.get("symbols", [])
    elif isinstance(payload, list):
        symbols = payload
    if not isinstance(symbols, list):
        raise HTTPException(422, "expect {symbols: [...]} or [...]")
    prov = get_provider()
    prov.live_feed().subscribe(set(s.upper() for s in symbols), {"quotes", "books"})
    return {"ensured": symbols}
