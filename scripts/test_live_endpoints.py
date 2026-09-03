"""Live End-to-End Test Suite against Upstream Stockbit/Exodus APIs."""

import asyncio
import os
import sys
from pathlib import Path

# Add services/api-py to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "api-py"))

# Ensure utf-8 output
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import httpx  # noqa: E402
from app.main import app  # noqa: E402
from app.providers.stockbit.provider import init_provider  # noqa: E402
from app.providers.stockbit.transport import init_transport  # noqa: E402
from httpx import ASGITransport  # noqa: E402


async def main():
    bearer = os.getenv("STOCKBIT_BEARER_TOKEN", "").strip().strip('"').strip("'")
    if not bearer:
        print("[!] No STOCKBIT_BEARER_TOKEN found in .env!")
        return

    print(f"[*] Initializing live provider with Bearer token ({bearer[:20]}...)...")
    init_transport(bearer=bearer)
    init_provider(bearer=bearer)

    # Disable API key check for local client
    os.environ["API_KEY"] = ""
    import app.core.security as sec

    sec.API_KEY = ""

    endpoints_to_test = [
        # (Category, URL, Params)
        ("Estimates Consensus", "/v1/estimates/BBCA/consensus", None),
        ("Estimates Ratings", "/v1/estimates/BBCA/ratings", None),
        ("Estimates Research", "/v1/estimates/BBCA/research", None),
        (
            "Insider Movements",
            "/v1/insider/movements",
            {"date_start": "2026-08-01", "date_end": "2026-09-01", "limit": 5},
        ),
        ("Shareholders Breakdown", "/v1/companies/BBCA/shareholders", None),
        (
            "Shareholders Trend",
            "/v1/companies/BBCA/shareholders/trend",
            {"value_year": 12},
        ),
        ("Research Morning Notes", "/v1/research/morning-notes", {"limit": 5}),
        (
            "Research Reports",
            "/v1/research/reports",
            {"account": "StockbitReports", "limit": 5},
        ),
        ("Company News", "/v1/news/BBCA", {"limit": 5}),
        ("Screener Presets", "/v1/screeners/presets", None),
        ("Screener Run (Guru)", "/v1/screeners/presets/2", None),
        ("Valuation Engine", "/v1/fundamentals/BBCA/valuation", None),
        ("Valuation Metrics", "/v1/fundamentals/BBCA/valuation/metrics", None),
        (
            "Fundachart History",
            "/v1/fundamentals/BBCA/history",
            {"item_id": 2661, "timeframe": "1y"},
        ),
        (
            "Broker Distribution",
            "/v1/brokers/BBCA/distribution",
            {"period": "TB_PERIOD_LAST_1_DAY"},
        ),
        (
            "Foreign/Domestic Flow",
            "/v1/flow/BBCA/foreign-domestic",
            {"period": "PERIOD_RANGE_1D"},
        ),
        (
            "Broker Activity Chart",
            "/v1/brokers/XL/chart",
            {"period": "RT_PERIOD_LAST_1_DAY"},
        ),
        (
            "Broker Historical Flow",
            "/v1/brokers/XL/history",
            {"symbols": "BBCA", "period": "RT_PERIOD_LAST_1_YEAR"},
        ),
        ("Running Trades Snapshot", "/v1/trades/running/snapshot", {"limit": 10}),
    ]

    print(
        "\n================================================================================"
    )
    print(
        "                     LIVE UPSTREAM API VERIFICATION SUITE                       "
    )
    print(
        "================================================================================\n"
    )

    passed = 0
    failed = 0

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for name, path, params in endpoints_to_test:
            try:
                r = await client.get(path, params=params, timeout=20.0)
                if r.status_code == 200:
                    data = r.json()
                    preview = ""
                    if "consensus" in data and isinstance(data["consensus"], list):
                        items = [it.get("name") for it in data["consensus"][:3]]
                        preview = f"Metrics: {items}"
                    elif "ratings" in data and isinstance(data["ratings"], dict):
                        pt = data["ratings"].get("price_target", {})
                        preview = f"Rec: {data['ratings'].get('recommendation')}, Target: {pt.get('best_target')}"
                    elif (
                        "data" in data
                        and isinstance(data["data"], dict)
                        and "movement" in data["data"]
                    ):
                        mvs = len(data["data"]["movement"])
                        preview = f"Found {mvs} insider transactions"
                    elif "composition" in data:
                        periods = data["composition"].get("periods", [])
                        preview = f"Periods: {len(periods)}, Top: {periods[0]['compositions'][0]['label'] if periods and periods[0].get('compositions') else 'N/A'}"
                    elif "source" in data and "data" in data:
                        msgs = (
                            len(data["data"].get("messages", []))
                            if isinstance(data["data"], dict)
                            else 0
                        )
                        preview = f"Broadcast messages: {msgs}"
                    elif "valuation" in data and isinstance(data["valuation"], dict):
                        val = data["valuation"]
                        preview = f"Target: {val.get('target_price')}, Margin Safety: {val.get('margin_safety')}%"
                    elif "distribution" in data and isinstance(
                        data["distribution"], dict
                    ):
                        date_info = data["distribution"].get("date_info")
                        preview = f"Date: {date_info}, Has By-Value: {'by_value' in data['distribution']}"
                    elif "flow" in data and isinstance(data["flow"], dict):
                        summary = data["flow"].get("summary", {})
                        net_f = (
                            summary.get("net_foreign", {})
                            .get("value", {})
                            .get("formatted")
                        )
                        preview = f"Net Foreign: {net_f}"
                    elif "series" in data and isinstance(data["series"], list):
                        points = (
                            len(
                                data["series"][0]
                                .get("ratios", [{}])[0]
                                .get("chart_data", [])
                            )
                            if data["series"]
                            else 0
                        )
                        preview = f"Time-series points: {points}"
                    elif "presets" in data:
                        preview = f"Presets count: {len(data['presets'])}"

                    print(f"  [PASS] 200 OK  | {name:<25} | {preview}")
                    passed += 1
                else:
                    print(
                        f"  [FAIL] {r.status_code}   | {name:<25} | Path: {path} - Response: {r.text[:120]}"
                    )
                    failed += 1
            except Exception as e:
                print(f"  [ERR ] ERROR   | {name:<25} | Exception: {e}")
                failed += 1

    print(
        "\n--------------------------------------------------------------------------------"
    )
    print(
        f"  Results: {passed} PASSED, {failed} FAILED across {len(endpoints_to_test)} live upstream tests."
    )
    print(
        "================================================================================\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
