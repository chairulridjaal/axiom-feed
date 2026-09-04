"""StockbitProvider — implements MarketDataProvider, the only Stockbit boundary.

Uses HttpxTransport (Limits 20, tenacity, 10 rps) + mapping + BoundedCache streaming.

Historical candles: window slicing 365d daily / 90d intraday (env-configurable),
httpx.stream per window, incremental orjson, per-window retry, Semaphore(4),
StreamingResponse yields Candle one-by-one — never 60MB response.json().
"""

from __future__ import annotations

import logging
import os
from collections import deque
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.domain.models import Book, Candle, KeyStats, Mover, Quote, Resolution, Symbol, Trade
from app.infra.tick_store import TickStore

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

    def __init__(self, max_symbols: int = 200, tick_store: TickStore | None = None):
        self.max_symbols = max_symbols
        self.quotes: dict[Symbol, Quote] = {}
        self.books: dict[Symbol, Book] = {}
        self.trades: dict[Symbol, deque[Trade]] = {}
        self._global_trades: deque[Trade] = deque(maxlen=1000)
        self.tick_store = tick_store if tick_store is not None else TickStore()
        # Seed in-memory buffer with latest persistent trades for offline tape replay
        try:
            stored = self.tick_store.get_trades(limit=1000)
            for t in reversed(stored):
                sym_dq = self.trades.get(t.symbol)
                if sym_dq is None:
                    sym_dq = deque(maxlen=1000)
                    self.trades[t.symbol] = sym_dq
                sym_dq.appendleft(t)
                self._global_trades.appendleft(t)
        except Exception:
            pass

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
            trades_dq = self.trades.get(symbol.upper())
            res = list(trades_dq)[:limit] if trades_dq else []
            if not res:
                res = self.tick_store.get_trades(symbol=symbol.upper(), limit=limit)
            return res
        res = list(self._global_trades)[:limit]
        if not res:
            res = self.tick_store.get_trades(limit=limit)
        return res

    def ingest_trade(self, trade: Trade):
        sym_dq = self.trades.get(trade.symbol)
        if sym_dq is None:
            sym_dq = deque(maxlen=1000)
            self.trades[trade.symbol] = sym_dq
        sym_dq.appendleft(trade)
        self._global_trades.appendleft(trade)
        self.tick_store.insert_trade(trade)

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
            if kind == "trade_batch":
                payload = event.get("payload", {}) or {}
                trades = payload.get("trades") if isinstance(payload, dict) else None
                if not isinstance(trades, list):
                    return
                for t in trades:
                    if isinstance(t, dict):
                        self.ingest_hub_event(
                            {
                                "kind": "trade",
                                "symbol": t.get("stock") or event.get("symbol", ""),
                                "payload": t,
                            }
                        )
                return
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
                    prev = self.books.get(symbol)
                    if prev is not None:
                        if not bids_raw:
                            bids_raw = [
                                {"price": str(lv.price), "lot": lv.lots} for lv in prev.bids
                            ]
                        if not offers_raw:
                            offers_raw = [
                                {"price": str(lv.price), "lot": lv.lots} for lv in prev.asks
                            ]
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
            # Dynamic window slicing for multi-year ranges (>365d) to prevent upstream truncation
            found_any = False
            seen_ts: set[int] = set()

            if (to - frm).days > SLICE_DAILY:
                import asyncio

                windows: list[tuple[date, date]] = []
                cur = frm
                while cur <= to:
                    nxt = min(cur + timedelta(days=SLICE_DAILY - 1), to)
                    windows.append((cur, nxt))
                    cur = nxt + timedelta(days=1)

                sem = asyncio.Semaphore(CONCURRENCY)

                async def _fetch_daily_window(w_frm: date, w_to: date) -> list[Candle]:
                    url = f"{EXODUS}/chartbit/{symbol}/price/daily"
                    params = build_daily_params(w_frm, w_to)
                    out: list[Candle] = []
                    try:
                        async with sem:
                            async for d in self.transport.stream_json_array(url, params=params):
                                c = map_candle_dict(d)
                                if c:
                                    out.append(c)
                    except Exception as e:
                        logger.warning(f"daily candle window {w_frm}->{w_to} failed: {e}")
                    return out

                results = await asyncio.gather(*[_fetch_daily_window(a, b) for a, b in windows])
                for batch in results:
                    for c in batch:
                        key = int(c.ts.timestamp())
                        if key not in seen_ts:
                            seen_ts.add(key)
                            found_any = True
                            yield c
            else:
                # Fast-path: single window query
                url = f"{EXODUS}/chartbit/{symbol}/price/daily"
                params = build_daily_params(frm, to)
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
        import asyncio

        slice_days = SLICE_INTRADAY
        windows: list[tuple[date, date]] = []
        cur = frm
        while cur <= to:
            nxt = min(cur + timedelta(days=slice_days - 1), to)
            windows.append((cur, nxt))
            cur = nxt + timedelta(days=1)

        sem = asyncio.Semaphore(CONCURRENCY)

        async def _fetch_window(w_from: date, w_to: date) -> list[Candle]:
            url = f"{EXODUS}/chartbit/{symbol}/price/intraday"
            params = build_intraday_params(w_from, w_to)
            out: list[Candle] = []
            try:
                async with sem:
                    async for d in self.transport.stream_json_array(url, params=params):
                        c = map_candle_dict(d)
                        if c:
                            out.append(c)
            except Exception as e:
                logger.warning(f"candle window {w_from}->{w_to} {resolution} failed: {e}")
            return out

        results = await asyncio.gather(*[_fetch_window(a, b) for a, b in windows])
        seen_ts = set()
        for batch in results:
            for c in batch:
                key = int(c.ts.timestamp())
                if key in seen_ts:
                    continue
                seen_ts.add(key)
                yield c
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

    # ── Estimates & Analyst Ratings ─────────────────────────────────────
    async def analyst_consensus(self, symbol: Symbol) -> Any:
        url = f"{EXODUS}/analyst-ratings/{symbol.upper()}/consensus"
        return await self.transport.get_json(url, label=f"analyst_consensus({symbol})")

    async def analyst_ratings(self, symbol: Symbol) -> Any:
        url = f"{EXODUS}/analyst-ratings/{symbol.upper()}"
        return await self.transport.get_json(url, label=f"analyst_ratings({symbol})")

    async def company_research(self, symbol: Symbol) -> Any:
        url = f"{EXODUS}/research/company/{symbol.upper()}"
        return await self.transport.get_json(url, label=f"company_research({symbol})")

    # ── Insider & Shareholding ──────────────────────────────────────────
    async def insider_majorholders(
        self,
        date_start: str,
        date_end: str,
        page: int = 1,
        limit: int = 20,
        action_type: str = "ACTION_TYPE_UNSPECIFIED",
        source_type: str = "SOURCE_TYPE_UNSPECIFIED",
    ) -> Any:
        url = f"{EXODUS}/insider/company/majorholder"
        params = {
            "date_start": date_start,
            "date_end": date_end,
            "page": page,
            "limit": limit,
            "action_type": action_type,
            "source_type": source_type,
        }
        return await self.transport.get_json(url, params=params, label="insider_majorholders")

    async def shareholding_composition(self, symbol: Symbol) -> Any:
        url = f"{EXODUS}/insider/shareholding/composition/companies/{symbol.upper()}"
        return await self.transport.get_json(url, label=f"shareholding_composition({symbol})")

    async def get_shareholders_token(self) -> str | None:
        url = f"{EXODUS}/emitten-metadata/shareholders/token"
        try:
            res = await self.transport.post_json(url, json={})
            return res.get("data", {}).get("value")
        except Exception:
            return None

    async def shareholders_chart(self, symbol: Symbol, value_year: int = 12) -> Any:
        url = f"{EXODUS}/emitten-metadata/shareholders/{symbol.upper()}/chart"
        params = {"symbol": symbol.upper(), "value_year": value_year, "shareholder_type": "all"}
        tok = await self.get_shareholders_token()
        headers = {"Authorization": tok, "X-Platform": "web"} if tok else None
        return await self.transport.get_json(
            url, params=params, headers=headers, label=f"shareholders_chart({symbol})"
        )

    # ── Targeted Research & News Feeds ──────────────────────────────────
    async def user_stream(
        self,
        username: str = "StockbitReports",
        category: str = "STREAM_CATEGORY_MAIN_IDEAS",
        last_stream_id: int = 0,
        limit: int = 20,
    ) -> Any:
        url = f"{EXODUS}/stream/v3/user/{username}"
        payload = {"category": category, "last_stream_id": last_stream_id, "limit": limit}
        return await self.transport.post_json(url, json=payload, label=f"user_stream({username})")

    async def broadcast_messages(
        self,
        room_id: int = 338965,
        limit: int = 50,
        cursor_id: int | None = None,
        cursor_dir: str = "CURSOR_DIRECTION_BETWEEN",
    ) -> Any:
        url = f"{EXODUS}/chat/v2/broadcast/{room_id}/messages"
        params: dict[str, Any] = {"limit": limit, "cursor_dir": cursor_dir, "show_stream": "true"}
        if cursor_id is not None:
            params["cursor_id"] = cursor_id
        return await self.transport.get_json(
            url, params=params, label=f"broadcast_messages({room_id})"
        )

    async def stream_post(self, post_id: int) -> Any:
        url = f"{EXODUS}/stream/v3/post/{post_id}"
        return await self.transport.post_json(url, json={}, label=f"stream_post({post_id})")

    async def stream_symbol(
        self,
        symbol: Symbol,
        category: str = "STREAM_CATEGORY_ALL",
        last_stream_id: int = 0,
        limit: int = 20,
    ) -> Any:
        url = f"{EXODUS}/stream/v3/symbol/{symbol.upper()}"
        params = {"category": category, "last_stream_id": last_stream_id, "limit": limit}
        return await self.transport.get_json(url, params=params, label=f"stream_symbol({symbol})")

    async def social_websocket_key(self) -> Any:
        url = f"{EXODUS}/auth/websocket/key"
        return await self.transport.get_json(url, label="social_websocket_key")

    # ── Screeners & Factor Models ───────────────────────────────────────
    async def screener_presets(self) -> Any:
        url = f"{EXODUS}/screener/preset"
        return await self.transport.get_json(url, label="screener_presets")

    async def screener_template(
        self, template_id: int, template_type: str = "TEMPLATE_TYPE_GURU"
    ) -> Any:
        url = f"{EXODUS}/screener/templates/{template_id}"
        params = {"type": template_type}
        return await self.transport.get_json(
            url, params=params, label=f"screener_template({template_id})"
        )

    # ── Valuation ───────────────────────────────────────────────────────
    async def valuation_metrics(self, symbol: Symbol) -> Any:
        url = f"{EXODUS}/valuation/company/{symbol.upper()}/metrics"
        return await self.transport.get_json(url, label=f"valuation_metrics({symbol})")

    async def company_valuation(
        self,
        symbol: Symbol,
        eps_value: str | None = None,
        growth_value: str | None = None,
        multiple_value: str | None = None,
    ) -> Any:
        url = f"{EXODUS}/valuation/company/{symbol.upper()}"
        if eps_value is None or growth_value is None or multiple_value is None:
            metrics_resp = await self.valuation_metrics(symbol)
            m_data = metrics_resp.get("data", []) if isinstance(metrics_resp, dict) else []
            if isinstance(m_data, list) and len(m_data) >= 3:
                if eps_value is None:
                    eps_value = str(m_data[0].get("value", "0"))
                if growth_value is None:
                    growth_value = str(m_data[1].get("value", "0"))
                if multiple_value is None:
                    multiple_value = str(m_data[2].get("value", "15"))
            elif isinstance(m_data, dict):
                if eps_value is None:
                    eps_value = str(m_data.get("eps", {}).get("default_value", "0"))
                if growth_value is None:
                    growth_value = str(m_data.get("growth", {}).get("default_value", "0"))
                if multiple_value is None:
                    multiple_value = str(m_data.get("multiple", {}).get("default_value", "15"))
            else:
                eps_value = eps_value or "0"
                growth_value = growth_value or "0"
                multiple_value = multiple_value or "15"
        payload = {
            "eps_value": str(eps_value),
            "growth_value": str(growth_value),
            "multiple_value": str(multiple_value),
        }
        return await self.transport.post_json(
            url, json=payload, label=f"company_valuation({symbol})"
        )

    # ── Broker Matrix & Advanced Flow ───────────────────────────────────
    async def broker_distribution(
        self,
        symbol: Symbol,
        date: str = "",
        period: str = "TB_PERIOD_LAST_1_DAY",
        investor_type: str = "INVESTOR_TYPE_ALL",
        market_board: str = "MARKET_TYPE_REGULER",
        data_type: str = "BROKER_DISTRIBUTION_DATA_TYPE_VALUE",
    ) -> Any:
        url = f"{EXODUS}/order-trade/broker/distribution"
        params = {
            "symbol": symbol.upper(),
            "date": date,
            "period": period,
            "investor_type": investor_type,
            "market_board": market_board,
            "data_type": data_type,
        }
        return await self.transport.get_json(
            url, params=params, label=f"broker_distribution({symbol})"
        )

    async def foreign_domestic_flow(
        self,
        symbol: Symbol,
        period: str = "PERIOD_RANGE_1D",
        market_type: str = "MARKET_TYPE_REGULAR",
    ) -> Any:
        url = f"{EXODUS}/findata-view/foreign-domestic/v1/chart-data/{symbol.upper()}"
        params = {"period": period, "market_type": market_type}
        return await self.transport.get_json(
            url, params=params, label=f"foreign_domestic_flow({symbol})"
        )

    async def broker_activity_chart(
        self,
        broker_code: str,
        period: str = "RT_PERIOD_LAST_1_DAY",
        investor_type: str = "INVESTOR_TYPE_ALL",
        market_board: str = "BOARD_TYPE_REGULAR",
    ) -> Any:
        url = f"{EXODUS}/order-trade/broker/activity-chart"
        params = {
            "brokers_code": broker_code.upper(),
            "period": period,
            "investor_type": investor_type,
            "market_board": market_board,
        }
        return await self.transport.get_json(
            url, params=params, label=f"broker_activity_chart({broker_code})"
        )

    async def broker_activity_historical(
        self,
        broker_codes: str,
        symbols: str,
        period: str = "RT_PERIOD_LAST_1_YEAR",
        interval: str = "INTERVAL_DAILY",
        market_board: str = "BOARD_TYPE_REGULAR",
        investor_type: str = "INVESTOR_TYPE_ALL",
        page: int = 1,
        limit: int = 25,
    ) -> Any:
        url = f"{EXODUS}/order-trade/broker/activity/historical"
        params = {
            "broker_codes": broker_codes.upper(),
            "symbols": symbols.upper(),
            "period": period,
            "interval": interval,
            "market_board": market_board,
            "investor_type": investor_type,
            "pagination.page": page,
            "pagination.limit": limit,
        }
        return await self.transport.get_json(
            url, params=params, label=f"broker_activity_historical({broker_codes},{symbols})"
        )

    async def running_trade_snapshot(
        self, sort: str = "DESC", limit: int = 80, order_by: str = "RUNNING_TRADE_ORDER_BY_TIME"
    ) -> Any:
        url = f"{EXODUS}/order-trade/running-trade"
        params = {"sort": sort, "limit": limit, "order_by": order_by}
        return await self.transport.get_json(url, params=params, label="running_trade_snapshot")

    # ── Fundachart ──────────────────────────────────────────────────────
    async def fundachart_templates(self) -> Any:
        url = f"{EXODUS}/fundachart/templates"
        return await self.transport.get_json(url, label="fundachart_templates")

    async def fundachart_metrics(self, metric_name: str = "fundachart") -> Any:
        url = f"{EXODUS}/fundachart/metrics"
        return await self.transport.get_json(
            url, params={"metric_name": metric_name}, label="fundachart_metrics"
        )

    async def fundachart_data(self, item: int, companies: str, timeframe: str = "1y") -> Any:
        url = f"{EXODUS}/fundachart"
        params = {"item": item, "companies": companies.upper(), "timeframe": timeframe}
        return await self.transport.get_json(
            url, params=params, label=f"fundachart_data({companies},{item})"
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
