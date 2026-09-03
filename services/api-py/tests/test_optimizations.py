import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.models import Board, Side, Trade
from app.infra.tick_store import TickStore
from app.providers.stockbit.financial_parser import parse_financial_statement_html


def test_tick_store_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_ticks.db"
        store = TickStore(db_path=db_path, max_records=5)

        # 1. Insert individual trades
        t1 = Trade(
            symbol="BBCA",
            price=Decimal("7500"),
            volume=100,
            side=Side.BUY,
            board=Board.RG,
            ts=datetime.now(),
            seq=101,
            change=Decimal("50"),
            change_pct=Decimal("0.67"),
        )
        t2 = Trade(
            symbol="TLKM",
            price=Decimal("2900"),
            volume=200,
            side=Side.SELL,
            board=Board.RG,
            ts=datetime.now(),
            seq=102,
        )
        store.insert_trade(t1)
        store.insert_trade(t2)

        assert store.count() == 2
        bbca_trades = store.get_trades(symbol="BBCA", limit=10)
        assert len(bbca_trades) == 1
        assert bbca_trades[0].symbol == "BBCA"
        assert bbca_trades[0].price == Decimal("7500")
        assert bbca_trades[0].seq == 101

        # 2. Batch insert
        batch = [
            Trade(
                symbol="BBRI",
                price=Decimal(str(4800 + i * 10)),
                volume=50 + i,
                side=Side.BUY,
                board=Board.RG,
                ts=datetime.now(),
                seq=200 + i,
            )
            for i in range(5)
        ]
        store.insert_batch(batch)
        assert store.count() == 7

        # 3. Global latest query
        all_trades = store.get_trades(limit=10)
        assert len(all_trades) == 7
        assert all_trades[0].seq == 204  # DESC ordering

        # 4. Prune records
        pruned = store.prune_old_records()
        assert pruned > 0
        assert store.count() == 5

        store.close()

        # 5. Reopen and verify persistence
        reopened = TickStore(db_path=db_path)
        try:
            assert reopened.count() == 5
        finally:
            reopened.close()


def test_fast_financial_statement_parser():
    sample_html = """
    <table class="financial-table">
      <tr>
        <th>In Million IDR</th>
        <th>Q1 2024</th>
        <th>Q2 2024</th>
        <th>Q3 2024</th>
      </tr>
      <tr>
        <td><span><b>Revenue</b></span></td>
        <td>10,000,000</td>
        <td>11,500,000</td>
        <td>12,000,000</td>
      </tr>
      <tr>
        <td>Cost of Revenue...</td>
        <td>-6,000,000</td>
        <td>-6,800,000</td>
        <td>-7,100,000</td>
      </tr>
      <tr>
        <td>Net Income</td>
        <td>2,500,000</td>
        <td>3,000,000</td>
        <td>3,200,000</td>
      </tr>
    </table>
    """
    res = parse_financial_statement_html(sample_html)
    assert res["unit"] == "In Million IDR"
    assert res["periods"] == ["Q1 2024", "Q2 2024", "Q3 2024"]
    assert len(res["line_items"]) == 3
    assert res["line_items"][0]["name"] == "Revenue"
    assert res["line_items"][0]["values"] == ["10,000,000", "11,500,000", "12,000,000"]
    assert res["line_items"][1]["name"] == "Cost of Revenue"

    # Empty and invalid cases
    assert parse_financial_statement_html("") == {"periods": [], "line_items": []}
    assert parse_financial_statement_html("<div>No tables here</div>") == {
        "periods": [],
        "line_items": [],
    }


@pytest.mark.asyncio
async def test_daily_candles_multi_year_window_slicing():
    from app.providers.stockbit.provider import StockbitProvider

    p = StockbitProvider()

    # Request spanning > 2 years (2024-01-01 to 2026-06-01)
    frm = date(2024, 1, 1)
    to = date(2026, 6, 1)
    # Mock transport.stream_json_array to count windows
    windows_called = []

    async def mock_stream(url, params=None, array_key="data"):
        p = params or {}
        windows_called.append((p.get("from"), p.get("to")))
        # Yield one sample candle per window
        yield {
            "timestamp": 1704067200 + len(windows_called) * 86400 * 30,
            "open": "7500",
            "high": "7550",
            "low": "7450",
            "close": "7520",
            "volume": 1000,
        }

    orig_stream = p.transport.stream_json_array
    p.transport.stream_json_array = mock_stream

    candles = []
    async for c in p.candles("BBCA", frm, to, resolution="daily"):
        candles.append(c)

    p.transport.stream_json_array = orig_stream

    # Should have sliced into at least 3 annual windows (365d chunks)
    assert len(windows_called) >= 3
    assert len(candles) == len(windows_called)
    for c in candles:
        assert c.open == Decimal("7500")
