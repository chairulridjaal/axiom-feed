from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import quotes
from app.core.security import verify_api_key
from app.domain.models import Quote


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, None),
        ({"previous_price": 7000}, None),
        ({"price": None}, None),
        ({"price": ""}, None),
        ({"price": 0, "last_price": 9000}, "0"),
        ({"price": None, "last_price": "6700"}, "6700"),
        ({"price": 6700}, "6700"),
    ],
)
def test_missing_last_is_not_previous_close_or_zero(monkeypatch, data, expected):
    # Given: a provider fallback and isolated HTTP routers.
    async def info(symbol):
        return {"data": {**data, "date": "2026-10-09"}}

    live = SimpleNamespace(snapshot_quotes=lambda: {})
    provider = SimpleNamespace(live_feed=lambda: live, emitten_info=info)
    monkeypatch.setattr(quotes, "get_provider", lambda: provider)
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(quotes.router)
    with TestClient(app) as client:
        # When: requesting the same fallback through single and batch APIs.
        single = client.get("/v1/quotes/BBCA").json()["quote"]
        batch = client.get("/v1/quotes", params={"symbols": "BBCA"}).json()["quotes"]["BBCA"]
    # Then: source semantics and missing data survive both surfaces.
    assert single["last"] == batch["last"] == expected
    assert single["prev_close"] == ("7000" if "previous_price" in data else None)
    assert single["source"] == batch["source"] == "company_info"
    assert single["ts"] == batch["ts"] == "2026-10-09"


def test_live_quote_preserves_observed_zero(monkeypatch):
    # Given: explicit zero observations in the live snapshot.
    q = Quote(
        "BBCA",
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        0,
        Decimal(0),
        0,
        Decimal(0),
        datetime(2026, 10, 9, tzinfo=UTC),
    )
    live = SimpleNamespace(snapshot_quotes=lambda: {"BBCA": q})
    monkeypatch.setattr(quotes, "get_provider", lambda: SimpleNamespace(live_feed=lambda: live))
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(quotes.router)
    # When: reading the live quote.
    with TestClient(app) as client:
        result = client.get("/v1/quotes/BBCA").json()["quote"]
    # Then: optional observed zero fields are preserved.
    assert all(result[key] == "0" for key in ("last", "open", "high", "low", "prev_close", "avg"))


def test_quote_provider_failure_stays_unavailable(monkeypatch):
    async def info(symbol):
        raise RuntimeError("synthetic provider failure")

    live = SimpleNamespace(snapshot_quotes=lambda: {})
    monkeypatch.setattr(
        quotes, "get_provider", lambda: SimpleNamespace(live_feed=lambda: live, emitten_info=info)
    )
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(quotes.router)
    with TestClient(app) as client:
        assert client.get("/v1/quotes/BBCA").json()["quote"] is None


@pytest.mark.parametrize(
    "fields",
    [
        {"prev": 100},
        {"lastprice": None, "prev": 100},
        {"lastprice": "", "prev": 100},
        {"lastprice": "bad", "prev": 100},
        {"lastprice": "NaN", "prev": 100},
    ],
)
def test_live_mapper_missing_or_malformed_last_stays_missing(monkeypatch, fields):
    from app.providers.stockbit.mapping import map_liveprice_to_quote

    q = map_liveprice_to_quote({"stock_code": "BBCA", **fields})
    live = SimpleNamespace(snapshot_quotes=lambda: {"BBCA": q})
    monkeypatch.setattr(quotes, "get_provider", lambda: SimpleNamespace(live_feed=lambda: live))
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(quotes.router)
    with TestClient(app) as client:
        single = client.get("/v1/quotes/BBCA").json()["quote"]
        batch = client.get("/v1/quotes", params={"symbols": "BBCA"}).json()["quotes"]["BBCA"]
    assert single["last"] == batch["last"] is None
    assert single["ts"] == batch["ts"] is None
    assert single["prev_close"] == "100"
    assert single["status"] == batch["status"] == "missing_last"


@pytest.mark.parametrize("source_time", [None, "", "not-a-timestamp"])
def test_live_mapper_never_invents_timestamp_for_valid_price(source_time):
    from app.providers.stockbit.mapping import map_liveprice_to_quote

    q = map_liveprice_to_quote({"stock_code": "BBCA", "lastprice": 100, "date": source_time})
    result = quotes._live_quote(q)
    assert result["last"] == "100"
    assert result["ts"] is None


def test_live_mapper_preserves_actual_zero_and_source_timestamp():
    from app.providers.stockbit.mapping import map_liveprice_to_quote

    q = map_liveprice_to_quote(
        {
            "stock_code": "BBCA",
            "lastprice": 0,
            "prev": 100,
            "date": "2026-10-09T10:00:00+07:00",
            "open": 0,
            "volume": 0,
        }
    )
    result = quotes._live_quote(q)
    assert result["last"] == result["open"] == "0"
    assert result["ts"] == "2026-10-09T10:00:00+07:00"
    assert result["status"] == "observed"
    assert q.volume == 0


@pytest.mark.parametrize("price", [None, 0])
def test_embedded_quote_payload_preserves_missing_and_zero(price):
    from app.providers.stockbit.embedded_ingest import quote_payload
    from app.providers.stockbit.mapping import map_liveprice_to_quote

    # Given a mapped source quote without a source timestamp.
    q = map_liveprice_to_quote({"stock_code": "BBCA", "lastprice": price, "open": price})
    # When the embedded live stream serializes it.
    payload = quote_payload(q)
    # Then missing and explicit zero stay distinct at the websocket boundary.
    assert payload["price"] == price
    assert payload["open"] == price
    assert payload["time_str"] is None


def test_proto_default_price_is_not_an_observed_zero():
    from importlib import import_module

    from app.providers.stockbit.mapping import map_liveprice_to_quote

    # Given a proto3 message without price presence (zero has the same wire encoding).
    source = import_module("app.providers.stockbit.generated.datafeed_pb2").LivePrice(
        stock_code="BBCA", prev=100
    )
    # When the mapper receives it, then it cannot claim an observed zero.
    mapped = map_liveprice_to_quote(source)
    assert mapped.last is None
    assert mapped.ts is None
    assert mapped.prev_close == Decimal(100)
