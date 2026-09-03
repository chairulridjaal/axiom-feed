"""Stockbit → domain mapping. Only place that knows pipe quirks.

Covers:
  - Legacy #O pipe (be-web core/websocket_client.py _parse_legacy_orderbook  L497-593)
    Body: #O|SYM|BID|price;lots;value|...|OFFER|...   — partial updates allowed (BID-only/OFFER-only).
  - OrderBookBody protobuf pure (field 6) — direct mapping.
  - LivePrice → Quote (expanded fields F1-F17, see proto).
  - RunningTrade/RunningTradeBatch → Trade.
  - Candle historical: Stockbit daily expects YYYY-MM-DD, intraday expects swapped EOD/SOD unix seconds (be-web scrape.py _build_minute_params L1241-1258).
  - Date-swap: caller always passes from<=to; we normalize and swap internally for intraday.

Never leaks raw pipe/body outside this module.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytz

from app.domain.models import Board, Book, Candle, Level, Quote, Side, Trade

logger = logging.getLogger(__name__)
WIB_TZ = pytz.timezone("Asia/Jakarta")


# ── Orderbook pipe parser (legacy Orderbook.body field 10) ───────────────


def parse_legacy_orderbook_pipe(body: str, symbol: str) -> tuple[list[Level], list[Level]]:
    """Parse #O|SYM|BID|p;lot;val|...|OFFER|... → (bids, asks).

    Accepts partial (BID-only or OFFER-only). Returns (bids, asks).
    """
    bids: list[Level] = []
    asks: list[Level] = []
    if not body or "|" not in body:
        return bids, asks
    parts = body.split("|")
    if len(parts) < 4:
        return bids, asks
    bid_idx = None
    offer_idx = None
    for i, part in enumerate(parts):
        u = part.strip().upper()
        if u == "BID":
            bid_idx = i
        elif u in ("OFFER", "ASK"):
            offer_idx = i
    if bid_idx is None and offer_idx is None:
        logger.warning(f"pipe parse: no BID/OFFER in {body[:120]!r}")
        return bids, asks

    def _parse_segment(start: int, end: int, out: list[Level]) -> None:
        for j in range(start, end):
            s = parts[j].strip()
            if not s:
                continue
            fields = s.split(";")
            if len(fields) < 2:
                continue
            try:
                price = Decimal(fields[0])
                lots = int(float(fields[1]))  # lot may be "10.0"
                out.append(Level(price=price, lots=lots))
            except Exception as e:
                logger.debug(f"pipe bid parse skip {s!r}: {e}")
                continue

    if bid_idx is not None:
        end = offer_idx if offer_idx is not None else len(parts)
        _parse_segment(bid_idx + 1, end, bids)
    if offer_idx is not None:
        _parse_segment(offer_idx + 1, len(parts), asks)
    return bids, asks


def _extract_price_lot(item: Any) -> tuple[Any, Any]:
    if isinstance(item, dict):
        return item.get("price"), item.get("lot")
    return getattr(item, "price", None), getattr(item, "lot", None)


def map_orderbook_body_to_book(
    stock_symbol: str,
    bid: list[dict[str, Any]] | list[Any],
    offer: list[dict[str, Any]] | list[Any],
    ts: datetime | None = None,
    seq: int = 0,
) -> Book:
    bids = tuple(
        Level(
            price=Decimal(str(_extract_price_lot(b)[0] or 0)),
            lots=int(float(_extract_price_lot(b)[1] or 0)),
        )
        for b in bid
    )
    asks = tuple(
        Level(
            price=Decimal(str(_extract_price_lot(o)[0] or 0)),
            lots=int(float(_extract_price_lot(o)[1] or 0)),
        )
        for o in offer
    )
    if ts is None:
        ts = datetime.now(WIB_TZ)
    return Book(symbol=stock_symbol.upper(), bids=bids, asks=asks, ts=ts, seq=seq)


def map_legacy_orderbook_msg(ob_legacy: Any) -> Book | None:
    """Take protobuf Orderbook (field 10) with body string → Book."""
    try:
        stock = getattr(ob_legacy, "stock", "") or ""
        body = getattr(ob_legacy, "body", "") or ""
        seq = int(getattr(ob_legacy, "sequence", 0) or 0)
        time_str = getattr(ob_legacy, "time", "") or getattr(ob_legacy, "server_time", "")
        bids, asks = parse_legacy_orderbook_pipe(body, stock)
        # parse time
        ts: datetime
        if time_str:
            try:
                ts = datetime.fromisoformat(str(time_str).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = WIB_TZ.localize(ts)
            except Exception:
                ts = datetime.now(WIB_TZ)
        else:
            ts = datetime.now(WIB_TZ)
        return Book(symbol=stock.upper(), bids=tuple(bids), asks=tuple(asks), ts=ts, seq=seq)
    except Exception as e:
        logger.error(f"legacy orderbook map failed: {e}")
        return None


# ── LivePrice → Quote ────────────────────────────────────────────────────


def map_liveprice_to_quote(lp: Any) -> Quote:
    # lp may be dict (REST) or proto object. Proto layout follows the official
    # client (stock_code/lastprice/date/prev + Change message); dict callers
    # use legacy stock/price/time_str keys — both are accepted here.
    def _g(k, default=None):
        if isinstance(lp, dict):
            return lp.get(k, default)
        return getattr(lp, k, default)

    def _first(*keys, default=None):
        for k in keys:
            v = _g(k, None)
            if v is not None and v != "":
                return v
        return default

    stock = str(_first("stock_code", "stock", "stock_symbol", default="")).upper()
    price = Decimal(str(_first("lastprice", "price", default=0) or 0))
    volume = int(float(_g("volume", 0) or 0))
    high = _g("high")
    low = _g("low")
    prev_close = _first("prev", "prev_close", "prevClose")
    freq = _g("frequency")
    avg = _g("average")
    value = _g("value")
    open_p = _g("open")
    time_str = _first("date", "time_str", "time", "timestamp", default="")
    is_index = bool(_g("is_index", 0))

    ts: datetime
    if isinstance(time_str, str) and time_str:
        try:
            ts = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = WIB_TZ.localize(ts)
        except Exception:
            ts = datetime.now(WIB_TZ)
    elif isinstance(time_str, datetime):
        ts = time_str
        if ts.tzinfo is None:
            ts = WIB_TZ.localize(ts)
    else:
        ts = datetime.now(WIB_TZ)

    def _d(v):
        return Decimal(str(v)) if v is not None else None

    return Quote(
        symbol=stock,
        last=price,
        open=_d(open_p),
        high=_d(high),
        low=_d(low),
        prev_close=_d(prev_close),
        volume=volume if volume else None,
        value=_d(value),
        freq=int(float(freq)) if freq is not None else None,
        avg=_d(avg),
        ts=ts,
        is_index=is_index,
    )


# ── Trade batch → Trade ──────────────────────────────────────────────────

_TRADE_TYPE_MAP = {0: Side.UNKNOWN, 1: Side.BUY, 2: Side.SELL}
_BOARD_TYPE_MAP = {0: Board.UNKNOWN, 1: Board.RG, 2: Board.TN, 3: Board.NG}


def map_running_trade_to_domain(t: Any, seq: int = 0) -> Trade:
    def _g(k, default=None):
        if isinstance(t, dict):
            return t.get(k, default)
        return getattr(t, k, default)

    stock = str(_g("stock", "") or _g("stock_symbol", "")).upper() or "UNKNOWN"
    price = Decimal(str(_g("price", 0) or 0))
    volume = int(float(_g("volume", 0) or 0))
    action = _g("action", 0)
    board = _g("market_board", 0)
    # action may be string already
    if isinstance(action, str):
        side = Side(action.upper()) if action.upper() in (s.value for s in Side) else Side.UNKNOWN
    else:
        side = _TRADE_TYPE_MAP.get(int(action) if action is not None else 0, Side.UNKNOWN)
    if isinstance(board, str):
        board_v = (
            Board(board.upper()) if board.upper() in (b.value for b in Board) else Board.UNKNOWN
        )
    else:
        board_v = _BOARD_TYPE_MAP.get(int(board) if board is not None else 0, Board.UNKNOWN)

    # time
    time_v = _g("time", _g("timestamp", _g("websocket_time")))
    ts: datetime
    if isinstance(time_v, datetime):
        ts = time_v
        if ts.tzinfo is None:
            ts = pytz.UTC.localize(ts).astimezone(WIB_TZ)
    elif isinstance(time_v, str) and time_v:
        try:
            ts = datetime.fromisoformat(time_v.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = WIB_TZ.localize(ts)
        except Exception:
            ts = datetime.now(WIB_TZ)
    else:
        try:
            utc_dt = getattr(time_v, "ToDatetime", None)
            raw_val: object = utc_dt() if callable(utc_dt) else None
            utc_dt_val: datetime | None = raw_val if isinstance(raw_val, datetime) else None
            if isinstance(utc_dt_val, datetime):
                if utc_dt_val.tzinfo is None:
                    utc_dt_val = pytz.UTC.localize(utc_dt_val)
                ts = utc_dt_val.astimezone(WIB_TZ)
            else:
                ts = datetime.now(WIB_TZ)
        except Exception:
            ts = datetime.now(WIB_TZ)

    change = _g("change")
    change_v = None
    change_pct = None
    if isinstance(change, dict):
        change_v = Decimal(str(change.get("value", 0))) if change.get("value") is not None else None
        change_pct = (
            Decimal(str(change.get("percentage", 0)))
            if change.get("percentage") is not None
            else None
        )
    elif change is not None and hasattr(change, "value"):
        try:
            v = getattr(change, "value", None)
            p = getattr(change, "percentage", None)
            change_v = Decimal(str(v)) if v is not None else None
            change_pct = Decimal(str(p)) if p is not None else None
        except Exception:
            pass

    trade_number = int(_g("trade_number", _g("tradeNumber", seq)) or seq)
    return Trade(
        symbol=stock,
        price=price,
        volume=volume,
        side=side,
        board=board_v,
        ts=ts,
        seq=trade_number,
        change=change_v,
        change_pct=change_pct,
    )


# ── Candle mapping ───────────────────────────────────────────────────────


def map_candle_dict(d: dict[str, Any]) -> Candle | None:
    """Map Stockbit candle dict (various shapes) → Candle."""
    try:
        # common keys: timestamp/date/time, open/high/low/close, volume, value, frequency
        ts_raw = (
            d.get("timestamp") or d.get("time") or d.get("date") or d.get("datetime") or d.get("t")
        )
        ts: datetime
        if isinstance(ts_raw, (int, float)):
            # may be ms or s — heuristic: > 1e12 => ms
            v = int(ts_raw)
            if v > 10_000_000_000:
                v = v // 1000
            ts = datetime.fromtimestamp(v, tz=WIB_TZ)
        elif isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = WIB_TZ.localize(ts)
            except Exception:
                # try YYYY-MM-DD
                try:
                    ts = WIB_TZ.localize(datetime.strptime(ts_raw[:10], "%Y-%m-%d"))
                except Exception:
                    ts = datetime.now(WIB_TZ)
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
            if ts.tzinfo is None:
                ts = WIB_TZ.localize(ts)
        else:
            ts = datetime.now(WIB_TZ)

        def _dec(k, alt=None):
            v = d.get(k, alt)
            return Decimal(str(v)) if v is not None else Decimal("0")

        def _int(k, alt=None):
            v = d.get(k, alt)
            return int(float(v)) if v is not None else 0

        open_p = _dec("open", d.get("o"))
        high = _dec("high", d.get("h"))
        low = _dec("low", d.get("l"))
        close = _dec("close", d.get("c", d.get("price")))
        volume = _int("volume", d.get("v", d.get("lot")))
        value = _dec("value", d.get("value_traded", 0))
        freq = d.get("frequency", d.get("freq"))
        freq_i = int(float(freq)) if freq is not None else None
        return Candle(
            ts=ts,
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=volume,
            value=value,
            freq=freq_i,
        )
    except Exception as e:
        logger.debug(f"candle map skip {d}: {e}")
        return None


# ── Date helpers ─────────────────────────────────────────────────────────


def normalize_range(frm: date, to: date) -> tuple[date, date]:
    """Caller guarantees from<=to; swap if somehow inverted (lesson from be-web needing date-swap)."""
    if to < frm:
        return to, frm
    return frm, to


def build_daily_params(frm: date, to: date) -> dict[str, str]:
    """Stockbit daily expects swapped from/to: from = more recent date (b), to = older date (a)."""
    a, b = normalize_range(frm, to)
    return {"from": b.isoformat(), "to": a.isoformat(), "limit": "0"}


def build_intraday_params(frm: date, to: date) -> dict[str, int]:
    """Stockbit intraday expects swapped EOD/SOD unix seconds (be-web services/scrape.py _build_minute_params)."""
    a, b = normalize_range(frm, to)
    # from = more recent (b) EOD, to = older (a) SOD — swap as be-web did
    from_naive = datetime.strptime(b.isoformat(), "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    to_naive = datetime.strptime(a.isoformat(), "%Y-%m-%d").replace(hour=0, minute=0, second=0)
    from_ts = int(WIB_TZ.localize(from_naive).timestamp())
    to_ts = int(WIB_TZ.localize(to_naive).timestamp())
    return {"from": from_ts, "to": to_ts}
