from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import candles
from app.core.security import verify_api_key
from app.domain.models import Candle
from app.infra.cache import BoundedCache
from app.providers.stockbit.provider import StockbitProvider


def bar(day: int = 0) -> Candle:
    return Candle(
        datetime(2026, 10, 1, tzinfo=UTC) + timedelta(days=day),
        Decimal(100),
        Decimal(110),
        Decimal(90),
        Decimal(105),
        10,
        Decimal(1050),
    )


def route_client(monkeypatch, produce):
    monkeypatch.setattr(candles, "get_provider", lambda: SimpleNamespace(candles=produce))
    monkeypatch.setattr(candles, "router", candles.APIRouter())
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(candles.init_candles(BoundedCache()))
    return TestClient(app)


@pytest.mark.parametrize(("resolution", "days"), [("daily", 3661), ("minute", 32)])
def test_excessive_candle_span_fails_before_provider(monkeypatch, resolution, days):
    calls = []

    async def produce(*args) -> AsyncIterator[Candle]:
        calls.append(args)
        yield bar()

    with route_client(monkeypatch, produce) as client:
        response = client.get(
            "/v1/candles/BBCA",
            params={
                "from": "2020-01-01",
                "to": (date(2020, 1, 1) + timedelta(days=days)).isoformat(),
                "resolution": resolution,
            },
        )
    assert response.status_code == 422
    assert calls == []


def test_candle_failure_never_returns_partial_success(monkeypatch):
    async def produce(*args) -> AsyncIterator[Candle]:
        yield bar()
        raise httpx.ReadError("offline failure")

    with route_client(monkeypatch, produce) as client:
        response = client.get("/v1/candles/BBCA", params={"from": "2026-10-01", "to": "2026-10-02"})
    assert response.status_code == 502
    assert "105" not in response.text


def test_candle_row_limit_stops_and_closes_producer(monkeypatch):
    closed = []
    emitted = []

    async def produce(*args) -> AsyncIterator[Candle]:
        try:
            for day in range(4):
                emitted.append(day)
                yield bar(day)
        finally:
            closed.append(True)

    monkeypatch.setattr(candles, "MAX_CANDLES", 2, raising=False)
    with route_client(monkeypatch, produce) as client:
        response = client.get("/v1/candles/BBCA", params={"from": "2026-10-01", "to": "2026-10-04"})
    assert response.status_code == 413
    assert emitted == [0, 1, 2]
    assert closed == [True]


def test_candle_exact_byte_limit_and_cache_parity(monkeypatch):
    import orjson

    c = bar()
    wire = (
        orjson.dumps(
            {
                "ts": c.ts.isoformat(),
                "open": "100",
                "high": "110",
                "low": "90",
                "close": "105",
                "volume": 10,
                "value": "1050",
                "freq": None,
            }
        )
        + b"\n"
    )
    calls = []

    async def produce(*args) -> AsyncIterator[Candle]:
        calls.append(args)
        yield c

    monkeypatch.setattr(candles, "MAX_CANDLE_BYTES", len(wire), raising=False)
    with route_client(monkeypatch, produce) as client:
        params = {"from": "2026-10-02", "to": "2026-10-01"}
        first = client.get("/v1/candles/BBCA", params=params)
        cached = client.get("/v1/candles/BBCA", params=params)
        monkeypatch.setattr(candles, "MAX_CANDLE_BYTES", len(wire) - 1, raising=False)
        over = client.get("/v1/candles/BBRI", params=params)
    assert first.status_code == cached.status_code == 200
    assert first.content == cached.content == wire
    assert cached.headers["X-Cache"] == "HIT"
    assert over.status_code == 413
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_empty_primary_never_fabricates_ohlc():
    async def stream(*args, **kwargs):
        if False:
            yield {}

    async def fallback(*args, **kwargs):
        return {"data": {"prices": [{"formatted_date": "2026-10-01", "value": "105"}]}}

    provider = StockbitProvider.__new__(StockbitProvider)
    provider.transport = SimpleNamespace(stream_json_array=stream, get_json=fallback)
    result = [
        c async for c in provider.candles("BBCA", date(2026, 10, 1), date(2026, 10, 2), "daily")
    ]
    assert result == []


@pytest.mark.asyncio
async def test_failed_daily_window_is_not_silently_omitted():
    async def stream(*args, **kwargs):
        raise httpx.ReadError("offline window failure")
        yield {}

    provider = StockbitProvider.__new__(StockbitProvider)
    provider.transport = SimpleNamespace(stream_json_array=stream)
    with pytest.raises(httpx.ReadError):
        async for _ in provider.candles("BBCA", date(2020, 1, 1), date(2022, 1, 1), "daily"):
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        {"timestamp": 1790816400, "close": "105", "volume": 10},
        {"timestamp": "invalid", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 10},
    ],
)
async def test_incomplete_candle_source_never_creates_ohlc_or_timestamp(raw):
    from app.infra.candle_limits import CandleDataError

    async def stream(*args, **kwargs):
        yield raw

    provider = StockbitProvider.__new__(StockbitProvider)
    provider.transport = SimpleNamespace(stream_json_array=stream)
    with pytest.raises(CandleDataError):
        async for _ in provider.candles("BBCA", date(2026, 10, 1), date(2026, 10, 2), "daily"):
            pass


def test_candle_line_budget_rejects_before_publication(monkeypatch):
    async def produce(*args):
        yield bar()

    monkeypatch.setattr(candles, "MAX_CANDLE_LINE_BYTES", 20)
    with route_client(monkeypatch, produce) as client:
        response = client.get("/v1/candles/BBCA", params={"from": "2026-10-01", "to": "2026-10-02"})
    assert response.status_code == 413


def test_candle_deadline_closes_stream_without_partial_success(monkeypatch):
    import anyio

    from app.infra.singleflight import Singleflight

    closed = []

    async def produce(*args):
        try:
            yield bar()
            await anyio.sleep_forever()
        finally:
            closed.append(True)

    monkeypatch.setattr(candles, "_candles_flight", Singleflight(timeout_seconds=0.01))
    with route_client(monkeypatch, produce) as client:
        response = client.get("/v1/candles/BBCA", params={"from": "2026-10-01", "to": "2026-10-02"})
    assert response.status_code == 504
    assert closed == [True]


@pytest.mark.asyncio
async def test_provider_counts_duplicate_scanned_rows(monkeypatch):
    from app.infra.candle_limits import CandleBudgetExceeded
    from app.providers.stockbit import provider as provider_module

    seen = []

    async def stream(*args, **kwargs):
        for i in range(4):
            seen.append(i)
            yield {
                "timestamp": 1790816400,
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "volume": 10,
            }

    monkeypatch.setattr(provider_module, "MAX_SCANNED_CANDLES", 2)
    provider = StockbitProvider.__new__(StockbitProvider)
    provider.transport = SimpleNamespace(stream_json_array=stream)
    with pytest.raises(CandleBudgetExceeded):
        async for _ in provider.candles("BBCA", date(2026, 10, 1), date(2026, 10, 2), "daily"):
            pass
    assert seen == [0, 1, 2]


@pytest.mark.asyncio
async def test_provider_rejects_outside_requested_dates():
    from app.infra.candle_limits import CandleDataError

    async def stream(*args, **kwargs):
        yield {
            "timestamp": "2026-10-20",
            "open": 100,
            "high": 110,
            "low": 90,
            "close": 105,
            "volume": 10,
        }

    provider = StockbitProvider.__new__(StockbitProvider)
    provider.transport = SimpleNamespace(stream_json_array=stream)
    with pytest.raises(CandleDataError):
        async for _ in provider.candles("BBCA", date(2026, 10, 1), date(2026, 10, 2), "daily"):
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize("resolution", ["daily", "minute"])
@pytest.mark.parametrize(
    ("stamp", "accepted"),
    [
        ("2026-09-30T17:00:00Z", True),
        ("2026-10-02T16:59:59Z", True),
        ("2026-09-30T16:59:59Z", False),
        ("2026-10-02T17:00:00Z", False),
    ],
)
async def test_provider_scope_uses_jakarta_dates(resolution, stamp, accepted):
    from app.infra.candle_limits import CandleDataError

    # Given a source row straddling a Jakarta date boundary.
    async def stream(*args, **kwargs):
        yield {"timestamp": stamp, "open": 100, "high": 110, "low": 90, "close": 105, "volume": 10}

    provider = StockbitProvider.__new__(StockbitProvider)
    provider.transport = SimpleNamespace(stream_json_array=stream)
    # When retrieving the requested local dates, then only their instants are accepted.
    if accepted:
        rows = [
            c
            async for c in provider.candles(
                "BBCA", date(2026, 10, 1), date(2026, 10, 2), resolution
            )
        ]
        assert len(rows) == 1
    else:
        with pytest.raises(CandleDataError):
            async for _ in provider.candles(
                "BBCA", date(2026, 10, 1), date(2026, 10, 2), resolution
            ):
                pass
