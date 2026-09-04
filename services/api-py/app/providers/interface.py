"""Provider boundary — the only seam Stockbit is allowed to cross."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any, Protocol

from app.domain.models import Book, Candle, KeyStats, Mover, Quote, Resolution, Symbol, Trade


class LiveFeed(Protocol):
    """Push feed — Stockbit WSS in prod, fake in tests."""

    async def subscribe(self, symbols: set[Symbol], kinds: set[str] = ...) -> None: ...
    async def unsubscribe(self, symbols: set[Symbol]) -> None: ...
    def events(self) -> AsyncIterator[Trade | Quote | Book]: ...
    def snapshot_quotes(self) -> dict[Symbol, Quote]: ...
    def snapshot_books(self) -> dict[Symbol, Book]: ...
    def snapshot_trades(self, symbol: Symbol | None = None, limit: int = 100) -> list[Trade]: ...


class MarketDataProvider(Protocol):
    def live_feed(self) -> LiveFeed: ...

    def candles(
        self, symbol: Symbol, frm: date, to: date, resolution: Resolution
    ) -> AsyncIterator[Candle]: ...
    async def key_stats(self, symbol: Symbol) -> KeyStats: ...
    async def movers(self, kind: str, boards: list[str] | None = None) -> list[Mover]: ...
    async def broker_summary(
        self,
        symbol: Symbol,
        frm: str | None = None,
        to: str | None = None,
        period: str | None = None,
        transaction_type: str = "TRANSACTION_TYPE_NET",
        market_board: str = "MARKET_BOARD_REGULER",
        investor_type: str = "INVESTOR_TYPE_ALL",
        limit: int = 100,
    ) -> Any: ...
    async def brokers_top(
        self,
        frm: str,
        to: str,
        sort: str = "TB_SORT_BY_TOTAL_VALUE",
        order: str = "ORDER_BY_DESC",
        market_type: str = "MARKET_TYPE_ALL",
    ) -> Any: ...
    async def brokers_top_stocks(
        self,
        frm: str,
        to: str,
        investor_type: str = "INVESTOR_TYPE_ALL",
        market_type: str = "MARKET_TYPE_REGULER",
        value_type: str = "VALUE_TYPE_NET",
        page: int = 1,
        limit: int = 25,
    ) -> Any: ...
    async def broker_activity(
        self,
        code: str,
        frm: str,
        to: str,
        limit: int = 50,
        page: int = 1,
        transaction_type: str = "TRANSACTION_TYPE_NET",
        market_board: str = "MARKET_BOARD_REGULER",
        investor_type: str = "INVESTOR_TYPE_ALL",
    ) -> Any: ...
    async def running_trade_chart(self, symbol: Symbol) -> Any: ...
    async def order_queue(
        self, symbol: Symbol, sort_by: str | None = None, limit: int | None = None
    ) -> Any: ...
    async def market_session(self) -> Any: ...
    async def index_members(self, index_code: str, limit: int = 50) -> Any: ...
    async def peer_ratios(self, symbol: Symbol) -> Any: ...
    async def peer_industries(self, symbol: Symbol) -> Any: ...
    async def corpaction_status(self, symbols: str | list[str]) -> Any: ...
    async def corpaction_day(self, day: str) -> Any: ...
    async def earnings_recap(
        self,
        year: int | None = None,
        quarter: int | None = None,
        page: int = 1,
        search: str | None = None,
    ) -> Any: ...
    async def underwriter_performance(
        self, underwriter_code: str, sort_by: str | None = None
    ) -> Any: ...
    async def sector_list(self) -> Any: ...
    async def subsectors(self, sid: str) -> Any: ...
    async def sector_companies(self, sid: str, sub_id: str) -> Any: ...
    async def seasonality(self, symbol: Symbol, year: int, back_year: int = 5) -> Any: ...
    async def fetch(
        self, url: str, params: dict[str, Any] | None = None, label: str = "fetch"
    ) -> Any: ...
