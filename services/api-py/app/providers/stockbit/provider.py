"""StockbitProvider — implements MarketDataProvider, the only Stockbit boundary.

Uses HttpxTransport (Limits 20, tenacity, 10 rps) + mapping + BoundedCache streaming.

Historical candles: window slicing 365d daily / 90d intraday (env-configurable),
httpx.stream per window, incremental orjson, per-window retry, Semaphore(4),
StreamingResponse yields Candle one-by-one — never 60MB response.json().
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.domain.models import Book, Candle, KeyStats, Mover, Quote, Resolution, Symbol, Trade

from .mapping import (
    build_daily_params,
    build_intraday_params,
    map_candle_dict,
    map_liveprice_to_quote,
    map_orderbook_body_to_book,
    map_running_trade_to_domain,
    normalize_range,
)
from .transport import get_transport, init_transport

logger = logging.getLogger(__name__)

try:
    import pytz

    _WIB_TZ = pytz.timezone("Asia/Jakarta")
except Exception:
    _WIB_TZ = None

EXODUS = "https://exodus.stockbit.com"

SLICE_DAILY = int(os.getenv("CANDLES_SLICE_DAILY_DAYS", "365"))
SLICE_INTRADAY = int(os.getenv("CANDLES_SLICE_INTRADAY_DAYS", "90"))
_raw_conc = int(os.getenv("CANDLES_CONCURRENCY", "4"))
CONCURRENCY = max(1, min(8, _raw_conc))


class LiveFeedState:
    """In-process live store (used when INGEST_MODE=embedded or tests)."""

    def __init__(self, max_symbols: int = 200):
        self.max_symbols = max_symbols
        self.quotes: dict[Symbol, Quote] = {}
        self.books: dict[Symbol, Book] = {}
        self.trades: dict[Symbol, list] = {}
        self._global_trades: list[Trade] = []

    def subscribe(self, symbols: set[Symbol], kinds: set[str] | None = None):
        kinds = kinds or {"quotes", "books", "trades"}
        if "*" in symbols and any(k in kinds for k in ("quotes", "books")):
            raise ValueError("'*' wildcard only for running_trade_batch (trades), not quotes/books")

    def snapshot_quotes(self):
        return dict(self.quotes)

    def snapshot_books(self):
        return dict(self.books)

    def snapshot_trades(self, symbol: Symbol | None = None, limit: int = 100):
        if symbol is not None:
            return list(self.trades.get(symbol.upper(), []))[:limit]
        return list(self._global_trades[:limit])

    def ingest_trade(self, trade: Trade):
        self.trades.setdefault(trade.symbol, []).insert(0, trade)
        self._global_trades.insert(0, trade)
        if len(self.trades[trade.symbol]) > 1000:
            self.trades[trade.symbol] = self.trades[trade.symbol][:1000]
        if len(self._global_trades) > 1000:
            self._global_trades = self._global_trades[:1000]

    def ingest_quote(self, quote: Quote):
        sym = quote.symbol.upper()
        if sym not in self.quotes and len(self.quotes) >= self.max_symbols:
            oldest = next(iter(self.quotes))
            del self.quotes[oldest]
        self.quotes[sym] = quote

    def ingest_book(self, book: Book):
        sym = book.symbol.upper()
        if sym not in self.books and len(self.books) >= self.max_symbols:
            oldest = next(iter(self.books))
            del self.books[oldest]
        self.books[sym] = book

    def ingest_hub_event(self, event: dict):
        try:
            kind = event.get("kind", "")
            if kind not in ("quote", "book", "trade"):
                return
            symbol = str(event.get("symbol", "")).upper()
            payload = event.get("payload", {}) or {}
            if not symbol or not isinstance(payload, dict):
                return
            if kind == "quote":
                if "price" not in payload and "stock" not in payload and not payload:
                    return
                q = map_liveprice_to_quote(
                    payload
                    if "stock" in payload or "price" in payload
                    else {"stock": symbol, **payload}
                )
                if q and q.symbol:
                    self.ingest_quote(q)
            elif kind == "book":
                bids_raw = payload.get("bids") or payload.get("bid") or []
                offers_raw = payload.get("offers") or payload.get("offer") or []
                if bids_raw or offers_raw:
                    from datetime import datetime

                    ts = datetime.now(_WIB_TZ) if _WIB_TZ else datetime.now()
                    book = map_orderbook_body_to_book(symbol, bids_raw, offers_raw, ts=ts)
                    self.ingest_book(book)
                elif "body" in payload:
                    from .mapping import map_legacy_orderbook_msg

                    class _Legacy:
                        stock = symbol
                        body = payload.get("body", "")
                        sequence = int(payload.get("sequence", 0) or 0)
                        time = payload.get("time", "")
                        server_time = payload.get("server_time", "")

                    b = map_legacy_orderbook_msg(_Legacy())
                    if b:
                        self.ingest_book(b)
            elif kind == "trade":
                if not payload:
                    return
                if "price" not in payload and "volume" not in payload:
                    return
                t = map_running_trade_to_domain(
                    payload if "stock" in payload else {"stock": symbol, **payload}
                )
                if t and t.symbol != "UNKNOWN":
                    self.ingest_trade(t)
        except Exception:
            pass


class StockbitProvider:
    def __init__(self, bearer_token: str | None = None):
        self.bearer = bearer_token or os.getenv("STOCKBIT_BEARER_TOKEN", "")
        try:
            self.transport = get_transport()
        except RuntimeError:
            self.transport = init_transport(bearer=self.bearer)
        self._live = LiveFeedState(max_symbols=int(os.getenv("LIVE_MAX_SYMBOLS", "200")))

    def live_feed(self) -> LiveFeedState:
        return self._live

    async def candles(
        self, symbol: Symbol, frm: date, to: date, resolution: Resolution
    ) -> AsyncIterator[Candle]:
        from datetime import datetime

        symbol = symbol.upper().strip()
        frm, to = normalize_range(frm, to)

        if resolution == "daily":
            # Primary: Stockbit chartbit daily
            url = f"{EXODUS}/chartbit/{symbol}/price/daily"
            params = build_daily_params(frm, to)
            found_any = False
            seen_ts: set[int] = set()
            try:
                async for d in self.transport.stream_json_array(url, params=params):
                    c = map_candle_dict(d)
                    if c:
                        found_any = True
                        key = int(c.ts.timestamp())
                        if key not in seen_ts:
                            seen_ts.add(key)
                            yield c
            except Exception:
                pass

            # Fallback: if chartbit daily returned empty, use exodus /charts/{symbol}/daily (always has real daily prices)
            if not found_any:
                try:
                    data = await self.transport.get_json(
                        f"{EXODUS}/charts/{symbol}/daily?timeframe=1Y",
                        label=f"charts fallback {symbol}",
                    )
                    prices = (
                        data.get("data", {}).get("prices", []) if isinstance(data, dict) else []
                    )
                    for item in prices:
                        dt_str = item.get("formatted_date", "")
                        val_str = str(item.get("value", "0")).replace(",", "").strip()
                        if dt_str and val_str and val_str != "0":
                            try:
                                d_obj = datetime.strptime(dt_str[:10], "%Y-%m-%d").date()
                                if frm <= d_obj <= to:
                                    p = Decimal(val_str)
                                    ts = datetime.combine(d_obj, datetime.min.time())
                                    if _WIB_TZ:
                                        ts = _WIB_TZ.localize(ts)
                                    c = Candle(
                                        ts=ts,
                                        open=p,
                                        high=p,
                                        low=p,
                                        close=p,
                                        volume=0,
                                        value=Decimal("0"),
                                    )
                                    yield c
                            except Exception:
                                continue
                except Exception as e:
                    logger.debug(f"daily chart fallback failed: {e}")
            return

        # Intraday/minute resolution
        slice_days = SLICE_INTRADAY
        windows: list[tuple[date, date]] = []
        cur = frm
        while cur <= to:
            nxt = min(cur + timedelta(days=slice_days - 1), to)
            windows.append((cur, nxt))
            cur = nxt + timedelta(days=1)

        seen_ts = set()
        for w_from, w_to in windows:
            url = f"{EXODUS}/chartbit/{symbol}/price/intraday"
            params = build_intraday_params(w_from, w_to)
            try:
                async for d in self.transport.stream_json_array(url, params=params):
                    c = map_candle_dict(d)
                    if not c:
                        continue
                    key = int(c.ts.timestamp())
                    if key in seen_ts:
                        continue
                    seen_ts.add(key)
                    yield c
            except Exception as e:
                logger.warning(f"candle window {w_from}->{w_to} {resolution} failed: {e}")
        return

    async def emitten_info(self, symbol: Symbol) -> dict[str, Any]:
        url = f"{EXODUS}/emitten/{symbol.upper()}/info"
        return await self.transport.get_json(url, label=f"emitten_info({symbol})")

    async def emitten_profile(self, symbol: Symbol) -> dict[str, Any]:
        url = f"{EXODUS}/emitten/{symbol.upper()}/profile"
        return await self.transport.get_json(url, label=f"emitten_profile({symbol})")

    async def emitten_subsidiaries(self, symbol: Symbol) -> dict[str, Any]:
        url = f"{EXODUS}/emitten-metadata/subsidiary/{symbol.upper()}"
        return await self.transport.get_json(url, label=f"subsidiary({symbol})")

    async def trade_book(
        self,
        symbol: Symbol,
        interval: str | None = None,
        group_by: str = "GROUP_BY_PRICE",
    ) -> dict[str, Any]:
        url = f"{EXODUS}/order-trade/trade-book"
        params: dict[str, Any] = {"symbol": symbol.upper(), "group_by": group_by}
        if interval is not None:
            params["interval"] = interval
        return await self.transport.get_json(url, params=params, label=f"trade_book({symbol})")

    async def chart_daily(
        self,
        symbol: Symbol,
        timeframe: str = "1w",
        is_include_previous_historical: bool = True,
    ) -> dict[str, Any]:
        url = f"{EXODUS}/charts/{symbol.upper()}/daily"
        params = {
            "timeframe": timeframe,
            "is_include_previous_historical": "true" if is_include_previous_historical else "false",
        }
        return await self.transport.get_json(
            url, params=params, label=f"chart_daily({symbol}/{timeframe})"
        )

    async def price_performance(self, symbol: Symbol) -> dict[str, Any]:
        url = f"{EXODUS}/company-price-feed/price-performance/{symbol.upper()}"
        return await self.transport.get_json(url, label=f"performance({symbol})")

    async def financial_report(
        self,
        symbol: Symbol,
        data_type: int = 1,
        report_type: int = 1,
        statement_type: int = 1,
    ) -> dict[str, Any]:
        url = f"{EXODUS}/findata-view/company/financial"
        params = {
            "symbol": symbol.upper(),
            "data_type": data_type,
            "report_type": report_type,
            "statement_type": statement_type,
        }
        return await self.transport.get_json(url, params=params, label=f"financials({symbol})")

    async def calendars(self, calendar_type: str) -> dict[str, Any]:
        mapping = {
            "ipo": "ipo",
            "dividend": "dividend",
            "tenderoffer": "tenderoffer",
            "tender": "tenderoffer",
            "rightissue": "rightissue",
            "rights": "rightissue",
            "stocksplit": "stocksplit",
            "splits": "stocksplit",
            "economic": "economic",
        }
        ep = mapping.get(calendar_type.lower(), calendar_type.lower())
        url = f"{EXODUS}/corpaction/{ep}"
        return await self.transport.get_json(url, label=f"calendar({calendar_type})")

    async def company_actions(self, symbol: Symbol, limit: int = 30) -> dict[str, Any]:
        url = f"{EXODUS}/corpaction/{symbol.upper()}"
        return await self.transport.get_json(
            url, params={"limit": limit}, label=f"corpaction({symbol})"
        )

    async def key_stats(self, symbol: Symbol) -> KeyStats | None:
        url = f"{EXODUS}/keystats/ratio/v1/{symbol.upper()}"
        try:
            data = await self.transport.get_json(
                url, params={"year_limit": 10}, label=f"keystats({symbol})"
            )
            if not data:
                return None
            return KeyStats(symbol=symbol.upper(), raw=data)
        except Exception as e:
            logger.warning(f"key_stats {symbol} failed: {e}")
            return None

    async def movers(
        self, kind: str = "top_gainers", boards: list[str] | None = None
    ) -> list[Mover]:
        mapping = {
            "top_gainers": "MOVER_TYPE_TOP_GAINER",
            "top_losers": "MOVER_TYPE_TOP_LOSER",
            "top_volume": "MOVER_TYPE_TOP_VOLUME",
            "top_value": "MOVER_TYPE_TOP_VALUE",
            "top_frequency": "MOVER_TYPE_TOP_FREQUENCY",
            "net_foreign_buy": "MOVER_TYPE_NET_FOREIGN_BUY",
            "net_foreign_sell": "MOVER_TYPE_NET_FOREIGN_SELL",
        }
        mover_type = mapping.get(kind, "MOVER_TYPE_TOP_GAINER")
        url = f"{EXODUS}/order-trade/market-mover?mover_type={mover_type}&filter_stocks=FILTER_STOCKS_TYPE_MAIN_BOARD"
        try:
            data = await self.transport.get_json(url, label=f"movers({kind})")
            items = data.get("data", {}).get("mover_list", []) if isinstance(data, dict) else []
            out: list[Mover] = []
            for it in items:
                try:
                    sym = str(it.get("stock_detail", {}).get("code", "")).upper()
                    if not sym:
                        continue
                    last = Decimal(str(it.get("price", 0)))
                    ch = Decimal(str(it.get("change", {}).get("value", 0)))
                    chp = Decimal(str(it.get("change", {}).get("percentage", 0)))
                    out.append(Mover(symbol=sym, last=last, change=ch, change_pct=chp))
                except Exception:
                    continue
            return out
        except Exception as e:
            logger.warning(f"movers failed: {e}")
            return []

    async def broker_summary(self, symbol: Symbol, frm: str | None = None, to: str | None = None):
        from datetime import datetime as dt

        frm = frm or dt.now().strftime("%Y-%m-%d")
        to = to or frm
        url = f"{EXODUS}/marketdetectors/{symbol.upper()}"
        params = {
            "from": frm,
            "to": to,
            "transaction_type": "TRANSACTION_TYPE_NET",
            "market_board": "MARKET_BOARD_REGULER",
            "investor_type": "INVESTOR_TYPE_ALL",
            "limit": 100,
        }
        return await self.transport.get_json(url, params=params, label=f"broker_summary({symbol})")

    async def sector_list(self):
        url = f"{EXODUS}/emitten/sectors"
        return await self.transport.get_json(url, label="sectors")

    async def subsectors(self, sid: str):
        url = f"{EXODUS}/emitten/sectors/{sid}/subsectors"
        return await self.transport.get_json(url, label=f"subsectors({sid})")

    async def sector_companies(self, sid: str, sub_id: str):
        url = f"{EXODUS}/emitten/v3/sector/{sid}/subsector/{sub_id}/company"
        return await self.transport.get_json(url, label=f"sector_companies({sid}/{sub_id})")

    async def brokers_top(self, frm: str, to: str):
        return await self.transport.get_json(
            f"{EXODUS}/order-trade/broker/top",
            params={
                "from": frm,
                "to": to,
                "sort": "TB_SORT_BY_TOTAL_VALUE",
                "order": "ORDER_BY_DESC",
                "market_type": "MARKET_TYPE_ALL",
            },
            label="broker_top",
        )

    async def brokers_top_stocks(self, frm: str, to: str):
        return await self.transport.get_json(
            f"{EXODUS}/order-trade/top-stock",
            params={
                "start": frm,
                "end": to,
                "investor_type": "INVESTOR_TYPE_ALL",
                "market_type": "MARKET_TYPE_REGULER",
                "value_type": "VALUE_TYPE_NET",
                "page": 1,
            },
            label="broker_top_stock",
        )

    async def broker_activity(self, code: str, frm: str, to: str):
        return await self.transport.get_json(
            f"{EXODUS}/findata-view/marketdetectors/activity/{code.upper()}/detail",
            params={
                "from": frm,
                "to": to,
                "limit": 50,
                "page": 1,
                "transaction_type": "TRANSACTION_TYPE_NET",
                "market_board": "MARKET_BOARD_REGULER",
                "investor_type": "INVESTOR_TYPE_ALL",
            },
            label=f"broker_activity({code})",
        )

    async def seasonality(self, symbol: Symbol, year: int, back_year: int = 5):
        url = f"{EXODUS}/seasonality/{symbol.upper()}"
        return await self.transport.get_json(
            url, params={"year": year, "back_year": back_year}, label=f"seasonality({symbol})"
        )

    async def fetch(self, url: str, params: dict[str, Any] | None = None, label: str = "fetch"):
        return await self.transport.get_json(url, params=params, label=label)


_provider: StockbitProvider | None = None


def get_provider() -> StockbitProvider:
    global _provider
    if _provider is None:
        _provider = StockbitProvider()
    return _provider


def init_provider(bearer: str | None = None) -> StockbitProvider:
    global _provider
    if _provider is None:
        _provider = StockbitProvider(bearer_token=bearer)
    return _provider
