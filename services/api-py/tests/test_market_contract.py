from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import market
from app.core.security import verify_api_key
from app.infra import upstream_cache
from app.infra.cache import BoundedCache
from app.infra.singleflight import Singleflight


@pytest.mark.parametrize(
    "first", [RuntimeError("offline failure"), {}, {"data": None}, {"data": {"mover_list": None}}]
)
def test_failed_movers_are_not_cached_as_empty_success(monkeypatch, first):
    # Given: one failed upstream response followed by a genuine empty list.
    calls = []

    async def fetch(url, label):
        calls.append(url)
        if len(calls) == 1:
            if isinstance(first, Exception):
                raise first
            return first
        return {"data": {"mover_list": []}}

    monkeypatch.setattr(market, "get_provider", lambda: SimpleNamespace(fetch=fetch))
    monkeypatch.setattr(upstream_cache, "upstream_cache", BoundedCache())
    monkeypatch.setattr(upstream_cache, "upstream_flight", Singleflight())
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(market.router)
    with TestClient(app) as client:
        # When: retrying after the failure and requesting the recovered result again.
        failed = client.get("/v1/market/movers")
        recovered = client.get("/v1/market/movers")
        cached = client.get("/v1/market/movers")
    # Then: only explicit empty success is cached.
    assert failed.status_code == 502
    assert recovered.status_code == cached.status_code == 200
    assert recovered.json() == cached.json() == {"kind": "top_gainers", "movers": []}
    assert len(calls) == 2
