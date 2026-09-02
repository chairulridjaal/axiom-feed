import os

# Ensure auth disabled for tests before importing app
os.environ["API_KEY"] = ""
from fastapi.testclient import TestClient  # noqa: E402

# Ensure imported security sees empty key
import app.core.security as sec
from app.main import app  # noqa: E402
from app.providers.stockbit.auth import decode_jwt_claims, jwt_exp  # noqa: E402

sec.API_KEY = ""

client = TestClient(app)


def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] in ("ok", "healthy")
    assert "hub" in j


def test_ready():
    r = client.get("/v1/ready")
    assert r.status_code == 200
    assert "ready" in r.json()


def test_docs():
    r = client.get("/docs")
    assert r.status_code == 200


def test_candles_normalized():
    r = client.get(
        "/v1/candles/BBCA",
        params={"from": "2026-08-26", "to": "2026-08-01", "resolution": "daily"},
    )
    assert r.status_code == 200


def test_wildcard_rejected_for_quotes():
    from app.providers.stockbit.provider import get_provider

    p = get_provider()
    try:
        p.live_feed().subscribe({"*"}, {"quotes"})
        assert False, "should have rejected wildcard for quotes"
    except ValueError as e:
        assert "*" in str(e)


def test_jwt_decode_exp():
    import base64
    import json

    def make_jwt(exp):
        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
        payload = (
            base64.urlsafe_b64encode(json.dumps({"exp": exp, "iat": exp - 86400}).encode())
            .decode()
            .rstrip("=")
        )
        sig = "sig"
        return f"{header}.{payload}.{sig}"

    fresh = make_jwt(1788421941)
    expired = make_jwt(1774487418)
    assert jwt_exp(fresh) == 1788421941
    assert jwt_exp(expired) == 1774487418
    claims = decode_jwt_claims(fresh)
    assert claims is not None
    assert claims["exp"] - claims["iat"] == 86400


def test_candles_cache_tiered():
    from app.infra.cache import BoundedCache

    c = BoundedCache(max_keys=2, max_bytes=1000)
    c.set("candles:daily:BBCA:2026-01-01:2026-01-02", [{"a": 1}], size=100)
    s = c.stats()
    assert s["keys"] == 1


def test_hub_drop_oldest():
    import asyncio

    from app.infra.bus import Hub

    async def _test():
        h = Hub(max_clients=2, queue_size=2)
        q = await h.register("c1")
        assert q is not None
        await h.publish({"a": 1})
        await h.publish({"a": 2})
        await h.publish({"a": 3})
        assert h.messages_dropped >= 1
        await h.unregister("c1")

    asyncio.run(_test())


def test_mapping_pipe():
    from app.providers.stockbit.mapping import parse_legacy_orderbook_pipe

    body = "#O|BBCA|BID|7500;10;75000|7499;5;37495|OFFER|7501;8;60008|"
    bids, asks = parse_legacy_orderbook_pipe(body, "BBCA")
    assert len(bids) == 2
    assert len(asks) == 1
    assert str(bids[0].price) == "7500"
    bids2, asks2 = parse_legacy_orderbook_pipe("#O|BBCA|BID|7500;10|", "BBCA")
    assert len(bids2) == 1 and len(asks2) == 0
    bids3, asks3 = parse_legacy_orderbook_pipe("", "BBCA")
    assert bids3 == [] and asks3 == []


def test_mapping_candle_and_range():
    from datetime import date

    from app.providers.stockbit.mapping import (
        build_daily_params,
        build_intraday_params,
        map_candle_dict,
        normalize_range,
    )

    a = date(2026, 8, 1)
    b = date(2026, 8, 26)
    assert normalize_range(b, a) == (a, b)
    d = build_daily_params(a, b)
    assert d["from"] == "2026-08-26" and d["to"] == "2026-08-01" and d["limit"] == "0"
    intr = build_intraday_params(a, b)
    assert intr["from"] > intr["to"]
    c = map_candle_dict(
        {
            "timestamp": 1722470400,
            "open": "100",
            "high": "110",
            "low": "90",
            "close": "105",
            "volume": 1000,
        }
    )
    assert c is not None and str(c.open) == "100"


def test_cache_tier_ttl_and_eviction():
    from app.infra.cache import BoundedCache, ttl_for

    assert ttl_for("candles:daily:BBCA") == 86400
    assert ttl_for("candles:minute:BBCA") == 60
    assert ttl_for("unknown:key") == 60
    c = BoundedCache(max_keys=2, max_bytes=200)
    c.set("k1", "v1", size=100)
    c.set("k2", "v2", size=100)
    c.set("k3", "v3", size=100)
    assert c.stats()["evictions"] >= 1
    assert c.stats()["keys"] == 2


def test_rate_limiter_does_not_hold_lock_on_sleep():
    import asyncio
    import time

    from app.providers.stockbit.transport import RateLimiter

    async def _test():
        rl = RateLimiter(rps=1)
        start = time.monotonic()
        await rl.acquire()
        await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.9
        assert elapsed < 2.0

    asyncio.run(_test())


def test_security_dynamic_api_key():
    import os

    import app.core.security as sec

    os.environ["API_KEY"] = "secret123"
    sec.API_KEY = "secret123"
    assert sec.verify_ws_token("secret123") is True
    assert sec.verify_ws_token("wrong") is False
    os.environ["API_KEY"] = ""
    sec.API_KEY = ""
    assert sec.verify_ws_token(None) is True


def test_trades_endpoint_empty_ok():
    r = client.get("/v1/trades", params={"symbols": "BBCA", "limit": 2})
    assert r.status_code == 200
    assert "trades" in r.json()
    r2 = client.get("/v1/trades/BBCA", params={"limit": 2})
    assert r2.status_code == 200


def test_sectors_subsectors_handles_empty():
    r = client.get("/v1/sectors")
    assert r.status_code == 200
    assert "sectors" in r.json()
