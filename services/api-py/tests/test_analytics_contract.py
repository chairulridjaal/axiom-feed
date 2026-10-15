import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import analytics
from app.core.security import verify_api_key
from app.infra.archive import SQLiteArchive


def test_retained_vwap_and_flow_report_coverage_without_session_completeness(tmp_path, monkeypatch):
    # Given: retained trades across dates with another symbol excluded.
    db = tmp_path / "ticks.db"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE trades (symbol TEXT, price TEXT, volume INTEGER, side TEXT, ts TEXT)"
        )
        con.executemany(
            "INSERT INTO trades VALUES (?, ?, ?, ?, ?)",
            [
                ("BBCA", "100", 10, "BUY", "2026-10-08T10:00:00+07:00"),
                ("BBCA", "200", 30, "SELL", "2026-10-09T10:00:00+07:00"),
                ("BBRI", "999", 100, "BUY", "2026-10-01T10:00:00+07:00"),
            ],
        )
    monkeypatch.setattr(analytics, "_archive", SQLiteArchive(db))
    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: None
    app.include_router(analytics.router)
    # When: requesting each public aggregate.
    with TestClient(app) as client:
        vwap = client.get("/v1/analytics/vwap/BBCA").json()
        flow = client.get("/v1/analytics/flow/BBCA").json()
        missing = client.get("/v1/analytics/vwap/MISSING")
    # Then: arithmetic remains exact and retained coverage is disclosed on both.
    assert vwap["vwap"] == flow["vwap"] == "175.00"
    assert vwap["trade_count"] == flow["trade_count"] == 2
    for result in (vwap, flow):
        assert result["coverage_start"] == "2026-10-08T10:00:00+07:00"
        assert result["coverage_end"] == "2026-10-09T10:00:00+07:00"
        assert result["scope"] == "retained_ticks"
        assert result["coverage_complete"] is False
    assert missing.status_code == 404


def test_retained_bounds_compare_instants_across_offsets(tmp_path):
    db = tmp_path / "ticks.db"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE trades (symbol TEXT, price TEXT, volume INTEGER, side TEXT, ts TEXT)"
        )
        con.executemany(
            "INSERT INTO trades VALUES (?, ?, ?, ?, ?)",
            [
                ("BBCA", "100", 10, "BUY", "2026-10-09T02:00:00+00:00"),
                ("BBCA", "200", 10, "SELL", "2026-10-09T08:00:00+07:00"),
            ],
        )
    result = SQLiteArchive(db).calculate_vwap("BBCA")
    assert result["coverage_start"] == "2026-10-09T08:00:00+07:00"
    assert result["coverage_end"] == "2026-10-09T02:00:00+00:00"
