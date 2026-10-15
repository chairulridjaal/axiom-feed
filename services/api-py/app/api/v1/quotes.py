import logging
from decimal import Decimal
from typing import Any, NotRequired, TypedDict

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator

from app.core.security import verify_api_key
from app.domain.models import Quote
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Quotes"])
logger = logging.getLogger(__name__)


class CompanyQuote(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    price: Decimal | None = None
    last_price: Decimal | None = None
    open_price: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    previous_price: Decimal | None = None
    change: Decimal | None = None
    average: Decimal | None = None
    date: str | None = None

    @field_validator(
        "price",
        "last_price",
        "open_price",
        "high",
        "low",
        "previous_price",
        "change",
        "average",
        mode="before",
    )
    @classmethod
    def empty_is_missing(
        cls, value: Decimal | int | float | str | None
    ) -> Decimal | int | float | str | None:
        if value == "":
            return None
        return value


class QuoteWire(TypedDict):
    last: str | None
    open: str | None
    high: str | None
    low: str | None
    prev_close: str | None
    avg: str | None
    ts: str | None
    source: str
    status: str
    change: NotRequired[str | None]


def _number(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _live_quote(q: Quote) -> QuoteWire:
    return {
        "last": _number(q.last),
        "open": _number(q.open),
        "high": _number(q.high),
        "low": _number(q.low),
        "prev_close": _number(q.prev_close),
        "avg": _number(q.avg),
        "ts": q.ts.isoformat() if q.ts is not None else None,
        "source": "live_feed",
        "status": "observed" if q.last is not None else "missing_last",
    }


async def _company_quote(symbol: str) -> QuoteWire | None:
    # HTTP boundary: unavailable or invalid provider data remains unavailable.
    try:
        raw = await get_provider().emitten_info(symbol)
        if not isinstance(raw, dict) or not isinstance(raw.get("data"), dict):
            return None
        d = CompanyQuote.model_validate(raw["data"])
        price = d.price if d.price is not None else d.last_price
        result: QuoteWire = {
            "last": _number(price),
            "open": _number(d.open_price),
            "high": _number(d.high),
            "low": _number(d.low),
            "prev_close": _number(d.previous_price),
            "avg": _number(d.average),
            "ts": d.date,
            "source": "company_info",
            "status": "observed" if price is not None else "missing_last",
        }
        result["change"] = _number(d.change)
        return result
    except Exception:  # HTTP boundary: provider boundary, optional quote response
        logger.warning("Company quote unavailable for %s", symbol)
        return None


@router.get("/v1/quotes/subscriptions")
async def quote_subscriptions():
    return {"subscribed": list(get_provider().live_feed().snapshot_quotes().keys())}


@router.get("/v1/quotes")
async def quotes(symbols: str = Query("", description="comma-separated")):
    snap = get_provider().live_feed().snapshot_quotes()
    if symbols:
        wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
        out: dict[str, QuoteWire | None] = {}
        for sym in wanted:
            q = snap.get(sym)
            out[sym] = _live_quote(q) if q is not None else await _company_quote(sym)
    else:
        out = {k: _live_quote(v) for k, v in snap.items()}
    return {"symbols": symbols, "quotes": out}


@router.get("/v1/quotes/{symbol}")
async def quote(symbol: str):
    sym = symbol.upper()
    q = get_provider().live_feed().snapshot_quotes().get(sym)
    return {"symbol": sym, "quote": _live_quote(q) if q is not None else await _company_quote(sym)}


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
