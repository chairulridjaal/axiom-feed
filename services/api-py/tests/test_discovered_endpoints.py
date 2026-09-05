import os
from unittest.mock import AsyncMock

os.environ["API_KEY"] = ""
from fastapi.testclient import TestClient

import app.core.security as sec
from app.main import app
from app.providers.stockbit.provider import get_provider

sec.API_KEY = ""
client = TestClient(app)


def test_estimates_endpoints(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(
        p, "analyst_consensus", AsyncMock(return_value={"data": [{"name": "Revenue", "items": []}]})
    )
    monkeypatch.setattr(
        p,
        "analyst_ratings",
        AsyncMock(
            return_value={"data": {"recommendation": "Buy", "price_target": {"best_target": 10000}}}
        ),
    )
    monkeypatch.setattr(p, "company_research", AsyncMock(return_value={"data": {"reports": []}}))

    r1 = client.get("/v1/estimates/BBCA/consensus")
    assert r1.status_code == 200
    assert r1.json()["symbol"] == "BBCA"
    assert "consensus" in r1.json()

    r2 = client.get("/v1/estimates/BBCA/ratings")
    assert r2.status_code == 200
    assert r2.json()["symbol"] == "BBCA"
    assert "ratings" in r2.json()

    r3 = client.get("/v1/estimates/BBCA/research")
    assert r3.status_code == 200
    assert r3.json()["symbol"] == "BBCA"
    assert "research" in r3.json()


def test_insider_endpoints(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(
        p,
        "insider_majorholders",
        AsyncMock(return_value={"data": {"movement": [{"name": "TEST", "symbol": "BBCA"}]}}),
    )
    monkeypatch.setattr(
        p,
        "shareholding_composition",
        AsyncMock(return_value={"data": {"periods": [{"compositions": []}]}}),
    )
    monkeypatch.setattr(p, "shareholders_chart", AsyncMock(return_value={"data": {"chart": []}}))

    r1 = client.get(
        "/v1/insider/movements", params={"date_start": "2026-08-01", "date_end": "2026-09-01"}
    )
    assert r1.status_code == 200
    assert "movement" in r1.json()["data"]

    r2 = client.get("/v1/companies/BBCA/shareholders")
    assert r2.status_code == 200
    assert r2.json()["symbol"] == "BBCA"
    assert "composition" in r2.json()

    r3 = client.get("/v1/companies/BBCA/shareholders/trend")
    assert r3.status_code == 200
    assert r3.json()["symbol"] == "BBCA"
    assert "trend" in r3.json()


def test_research_endpoints(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(
        p,
        "broadcast_messages",
        AsyncMock(return_value={"data": {"messages": [{"id": 456, "body": "Morning note"}]}}),
    )
    monkeypatch.setattr(
        p, "user_stream", AsyncMock(return_value={"data": {"stream": [{"stream_id": 123}]}})
    )
    monkeypatch.setattr(
        p,
        "stream_post",
        AsyncMock(return_value={"data": {"stream_id": 789, "content": "report thesis"}}),
    )

    r1 = client.get("/v1/research/morning-notes")
    assert r1.status_code == 200
    assert "Stockbit Reports" in r1.json()["source"]
    assert "messages" in r1.json()["data"]

    r2 = client.get("/v1/research/reports", params={"account": "StockbitReports"})
    assert r2.status_code == 200
    assert r2.json()["account"] == "StockbitReports"
    assert "stream" in r2.json()["data"]

    r3 = client.get("/v1/research/reports/789")
    assert r3.status_code == 200
    assert r3.json()["post_id"] == 789
    assert "content" in r3.json()["report"]


def test_news_endpoints(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(
        p, "stream_symbol", AsyncMock(return_value={"data": {"stream": [{"title": "News 1"}]}})
    )

    r = client.get("/v1/news/BBCA")
    assert r.status_code == 200
    assert r.json()["symbol"] == "BBCA"
    assert "stream" in r.json()["data"]


def test_screeners_endpoints(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(
        p,
        "screener_presets",
        AsyncMock(return_value={"data": [{"id": 1, "name": "Guru Screener"}]}),
    )
    monkeypatch.setattr(
        p,
        "screener_template",
        AsyncMock(return_value={"data": {"calcs": [{"company": {"symbol": "DRMA"}}]}}),
    )

    r1 = client.get("/v1/screeners/presets")
    assert r1.status_code == 200
    assert "presets" in r1.json()

    r2 = client.get("/v1/screeners/presets/2")
    assert r2.status_code == 200
    assert r2.json()["preset_id"] == 2
    assert "calcs" in r2.json()["data"]


def test_valuation_and_history_endpoints(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(
        p,
        "company_valuation",
        AsyncMock(return_value={"data": {"target_price": "9500", "margin_safety": "40"}}),
    )
    monkeypatch.setattr(
        p, "valuation_metrics", AsyncMock(return_value={"data": {"eps": {"default_value": "470"}}})
    )
    monkeypatch.setattr(
        p,
        "fundachart_data",
        AsyncMock(return_value={"data": [{"ratios": [{"item_name": "Price"}]}]}),
    )

    r1 = client.get("/v1/fundamentals/BBCA/valuation")
    assert r1.status_code == 200
    assert r1.json()["symbol"] == "BBCA"
    assert r1.json()["valuation"]["target_price"] == "9500"

    r2 = client.get("/v1/fundamentals/BBCA/valuation/metrics")
    assert r2.status_code == 200
    assert r2.json()["symbol"] == "BBCA"
    assert "metrics" in r2.json()

    r3 = client.get("/v1/fundamentals/BBCA/history", params={"item_id": 2661, "timeframe": "1y"})
    assert r3.status_code == 200
    assert r3.json()["symbol"] == "BBCA"
    assert r3.json()["item_id"] == 2661
    assert "series" in r3.json()


def test_brokers_and_flow_endpoints(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(
        p,
        "broker_distribution",
        AsyncMock(return_value={"data": {"by_value": {"top_broker_buy": []}}}),
    )
    monkeypatch.setattr(
        p,
        "foreign_domestic_flow",
        AsyncMock(return_value={"data": {"summary": {"foreign_buy": {}}}}),
    )
    monkeypatch.setattr(
        p, "broker_activity_chart", AsyncMock(return_value={"data": {"chart_data": []}})
    )
    monkeypatch.setattr(
        p, "broker_activity_historical", AsyncMock(return_value={"data": {"records": []}})
    )

    r1 = client.get("/v1/brokers/BBCA/distribution")
    assert r1.status_code == 200
    assert r1.json()["symbol"] == "BBCA"
    assert "distribution" in r1.json()

    r2 = client.get("/v1/flow/BBCA/foreign-domestic")
    assert r2.status_code == 200
    assert r2.json()["symbol"] == "BBCA"
    assert "flow" in r2.json()

    r3 = client.get("/v1/brokers/XL/chart")
    assert r3.status_code == 200
    assert r3.json()["broker"] == "XL"
    assert "chart" in r3.json()

    r4 = client.get("/v1/brokers/XL/history", params={"symbols": "BBCA"})
    assert r4.status_code == 200
    assert r4.json()["broker"] == "XL"
    assert r4.json()["symbol"] == "BBCA"
    assert "history" in r4.json()


def test_trades_running_endpoint(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(
        p, "running_trade_snapshot", AsyncMock(return_value={"data": {"running_trade": []}})
    )

    r = client.get("/v1/trades/running/snapshot")
    assert r.status_code == 200
    assert "running_trades" in r.json()


def test_market_microstructure_endpoints(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(
        p, "market_session", AsyncMock(return_value={"data": {"detail": {"regular": {}}}})
    )
    monkeypatch.setattr(p, "order_queue", AsyncMock(return_value={"data": {"orders": []}}))
    monkeypatch.setattr(
        p,
        "running_trade_chart",
        AsyncMock(
            return_value={
                "data": {
                    "from": "2026-09-04",
                    "to": "2026-09-04",
                    "price_chart_data": [{"time": "09:00"}],
                    "broker_chart_data": [{"type": "TYPE_CHART_VALUE"}],
                }
            }
        ),
    )

    r1 = client.get("/v1/market/session")
    assert r1.status_code == 200
    assert "detail" in r1.json()["session"]

    r2 = client.get("/v1/market/order-queue/BBCA", params={"limit": 3})
    assert r2.status_code == 200
    assert r2.json()["symbol"] == "BBCA"
    assert "orders" in r2.json()["queue"]

    r3 = client.get("/v1/market/intraday/BBCA", params={"kind": "price"})
    assert r3.status_code == 200
    assert r3.json()["kind"] == "price"
    assert "prices" in r3.json()

    r4 = client.get("/v1/market/intraday/BBCA", params={"kind": "brokers"})
    assert r4.status_code == 200
    assert r4.json()["kind"] == "brokers"
    assert "brokers" in r4.json()


def test_index_corpaction_peer_endpoints(monkeypatch):
    p = get_provider()
    monkeypatch.setattr(p, "index_members", AsyncMock(return_value={"data": [{"symbol": "BBCA"}]}))
    monkeypatch.setattr(p, "corpaction_day", AsyncMock(return_value={"data": {"dividend": []}}))
    monkeypatch.setattr(
        p, "corpaction_status", AsyncMock(return_value={"data": [{"symbol": "BBCA"}]})
    )
    monkeypatch.setattr(p, "peer_ratios", AsyncMock(return_value={"data": {"symbol": "BBCA"}}))
    monkeypatch.setattr(p, "peer_industries", AsyncMock(return_value={"data": {"competitor": []}}))
    monkeypatch.setattr(p, "earnings_recap", AsyncMock(return_value={"data": []}))
    monkeypatch.setattr(
        p,
        "underwriter_performance",
        AsyncMock(return_value={"data": {"underwriter": {"code": "YP"}}}),
    )

    r1 = client.get("/v1/indexes/LQ45/members", params={"limit": 3})
    assert r1.status_code == 200
    assert r1.json()["index"] == "LQ45"
    assert r1.json()["members"][0]["symbol"] == "BBCA"

    r2 = client.get("/v1/calendars/day/2026-09-04")
    assert r2.status_code == 200
    assert "dividend" in r2.json()["buckets"]

    r3 = client.get("/v1/market/corpaction-status", params={"symbols": "BBCA,BBRI"})
    assert r3.status_code == 200
    assert r3.json()["status"][0]["symbol"] == "BBCA"

    r4 = client.get("/v1/fundamentals/BBCA/peers")
    assert r4.status_code == 200
    assert r4.json()["symbol"] == "BBCA"
    assert "ratios" in r4.json() and "industries" in r4.json()

    r5 = client.get("/v1/market/earnings", params={"year": 2026, "quarter": 1})
    assert r5.status_code == 200
    assert "earnings" in r5.json()

    r6 = client.get("/v1/underwriters/YP/performance")
    assert r6.status_code == 200
    assert r6.json()["underwriter"] == "YP"
    assert "performance" in r6.json()


def test_broker_summary_period_wins_over_dates(monkeypatch):
    """Upstream silently ignores from/to when period is present — period must win."""
    p = get_provider()
    captured = {}

    async def fake_get_json(url, params=None, label=""):
        captured.clear()
        captured.update(params or {})
        return {"data": {}}

    monkeypatch.setattr(p.transport, "get_json", fake_get_json)

    r = client.get(
        "/v1/brokers/summary/BBCA", params={"period": "BROKER_SUMMARY_PERIOD_LAST_7_DAYS"}
    )
    assert r.status_code == 200
    assert captured.get("period") == "BROKER_SUMMARY_PERIOD_LAST_7_DAYS"
    assert "from" not in captured and "to" not in captured

    r = client.get(
        "/v1/brokers/summary/BBCA",
        params={
            "from": "2026-09-01",
            "to": "2026-09-04",
            "transaction_type": "TRANSACTION_TYPE_GROSS",
            "limit": 5,
        },
    )
    assert r.status_code == 200
    assert captured.get("from") == "2026-09-01"
    assert captured.get("to") == "2026-09-04"
    assert captured.get("transaction_type") == "TRANSACTION_TYPE_GROSS"
    assert captured.get("limit") == 5
    assert "period" not in captured


def test_broker_top_and_activity_forward_filters(monkeypatch):
    p = get_provider()
    captured = {}

    async def fake_get_json(url, params=None, label=""):
        captured.clear()
        captured.update(params or {})
        captured["_url"] = url
        return {"data": {}}

    monkeypatch.setattr(p.transport, "get_json", fake_get_json)

    r = client.get("/v1/brokers/top", params={"sort": "TB_SORT_BY_BUY_VALUE"})
    assert r.status_code == 200
    assert captured.get("sort") == "TB_SORT_BY_BUY_VALUE"

    r = client.get("/v1/brokers/XL/activity", params={"limit": 10})
    assert r.status_code == 200
    assert captured.get("limit") == 10

    r = client.get("/v1/brokers/top-stocks", params={"value_type": "VALUE_TYPE_GROSS", "page": 2})
    assert r.status_code == 200
    assert captured.get("value_type") == "VALUE_TYPE_GROSS"
    assert captured.get("page") == 2

    r = client.get(
        "/v1/brokers/BBCA/distribution",
        params={"from": "2026-09-01", "to": "2026-09-04"},
    )
    assert r.status_code == 200
    assert captured.get("from") == "2026-09-01"
    assert "period" not in captured


async def test_trade_book_group_by_normalized(monkeypatch):
    """Legacy GROUP_BY_PRICE spelling must normalize to numeric '1' upstream."""
    from app.providers.stockbit.provider import StockbitProvider

    p = StockbitProvider()
    captured = {}

    async def fake_get_json(url, params=None, label=""):
        captured.clear()
        captured.update(params or {})
        return {"data": {}}

    monkeypatch.setattr(p.transport, "get_json", fake_get_json)

    await p.trade_book("BBCA", group_by="GROUP_BY_PRICE")
    assert captured.get("group_by") == "1"

    await p.trade_book("BBCA")
    assert captured.get("group_by") == "1"
