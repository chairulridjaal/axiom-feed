import asyncio

import pytest

from app.infra.singleflight import Singleflight
from app.providers.stockbit.provider import StockbitProvider


@pytest.mark.asyncio
async def test_singleflight_concurrent_deduplication():
    sf = Singleflight()
    call_count = 0

    async def slow_work():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return {"data": 42}

    tasks = [sf.do("k1", slow_work) for _ in range(20)]
    results = await asyncio.gather(*tasks)

    assert call_count == 1
    assert len(results) == 20
    assert all(r == {"data": 42} for r in results)
    assert sf.in_flight_count() == 0


@pytest.mark.asyncio
async def test_singleflight_independent_keys():
    sf = Singleflight()
    counts = {"k1": 0, "k2": 0}

    async def work(key):
        counts[key] += 1
        await asyncio.sleep(0.02)
        return key

    tasks = [sf.do("k1", lambda: work("k1")), sf.do("k2", lambda: work("k2"))]
    res = await asyncio.gather(*tasks)

    assert res == ["k1", "k2"]
    assert counts["k1"] == 1
    assert counts["k2"] == 1
    assert sf.in_flight_count() == 0


@pytest.mark.asyncio
async def test_singleflight_exception_propagation_and_cleanup():
    sf = Singleflight()
    attempts = 0

    async def failing_work():
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.02)
        raise ValueError("upstream boom")

    tasks = [sf.do("fail_key", failing_work) for _ in range(5)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert attempts == 1
    assert len(results) == 5
    assert all(isinstance(r, ValueError) and str(r) == "upstream boom" for r in results)
    assert sf.in_flight_count() == 0


@pytest.mark.asyncio
async def test_singleflight_subsequent_calls_after_completion():
    sf = Singleflight()
    call_count = 0

    async def work():
        nonlocal call_count
        call_count += 1
        return call_count

    r1 = await sf.do("k", work)
    r2 = await sf.do("k", work)

    assert r1 == 1
    assert r2 == 2
    assert call_count == 2
    assert sf.in_flight_count() == 0


@pytest.mark.asyncio
async def test_provider_methods_delegation():
    p = StockbitProvider()
    assert hasattr(p, "emitten_info")
    assert hasattr(p, "emitten_profile")
    assert hasattr(p, "emitten_subsidiaries")
    assert hasattr(p, "trade_book")
    assert hasattr(p, "chart_daily")
    assert hasattr(p, "price_performance")
    assert hasattr(p, "financial_report")
    assert hasattr(p, "calendars")
    assert hasattr(p, "company_actions")
