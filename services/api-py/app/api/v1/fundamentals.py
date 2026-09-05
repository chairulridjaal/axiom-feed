from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.financial_parser import parse_financial_statement_html
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Fundamentals"])


@router.get("/v1/fundamentals/{symbol}")
async def fundamentals(symbol: str):
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        ks = await p.key_stats(symbol)
        if not ks:
            raise HTTPException(404, f"No fundamentals for {symbol}")
        return {"symbol": symbol.upper(), "key_stats": ks.raw}

    return await cached_json(f"default:fundamentals:{symbol.upper()}", _produce)


@router.get("/v1/fundamentals/{symbol}/financials")
async def company_financials(
    symbol: str,
    data_type: int = Query(1, description="1 for standard statements"),
    report_type: int = Query(1, description="1: Income Statement, 2: Balance Sheet, 3: Cash Flow"),
    statement_type: int = Query(
        1,
        description="1: Quarterly, 2: Annually, 3: TTM, 4: Interim YTD, 5: Q1, 6: Q2, 7: Q3, 8: Q4, 9: QoQ Growth, 10: Quarter YoY Growth, 11: YTD YoY Growth, 12: Annual YoY Growth, 13: 3 Year CAGR",
    ),
):
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.financial_report(
                symbol,
                data_type=data_type,
                report_type=report_type,
                statement_type=statement_type,
            )
            raw_data = data.get("data") if isinstance(data, dict) else data
            html_report = raw_data.get("html_report", "") if isinstance(raw_data, dict) else ""
            structured = parse_financial_statement_html(html_report)

            return {
                "symbol": symbol.upper(),
                "report_type": report_type,
                "statement_type": statement_type,
                "unit": structured.get("unit", "In Million"),
                "currency": raw_data.get("default_currency", "IDR")
                if isinstance(raw_data, dict)
                else "IDR",
                "periods": structured.get("periods", []),
                "line_items": structured.get("line_items", []),
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch financials for {symbol}: {e}")

    return await cached_json(
        f"default:financials:{symbol.upper()}:{data_type}:{report_type}:{statement_type}",
        _produce,
    )


@router.get("/v1/companies/{symbol}")
async def company(symbol: str):
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.emitten_info(symbol)
            return {
                "symbol": symbol.upper(),
                "data": data.get("data") if isinstance(data, dict) else data,
            }
        except Exception:
            return {"symbol": symbol.upper(), "data": None, "error": "upstream failed"}

    return await cached_json(f"default:company:{symbol.upper()}", _produce)


@router.get("/v1/companies/{symbol}/profile")
async def company_profile(symbol: str):
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.emitten_profile(symbol)
            return {
                "symbol": symbol.upper(),
                "profile": data.get("data") if isinstance(data, dict) else data,
            }
        except Exception:
            return {"symbol": symbol.upper(), "profile": None, "error": "upstream failed"}

    return await cached_json(f"default:profile:{symbol.upper()}", _produce)


@router.get("/v1/companies/{symbol}/subsidiaries")
async def company_subsidiaries(symbol: str):
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.emitten_subsidiaries(symbol)
            return {
                "symbol": symbol.upper(),
                "subsidiaries": data.get("data", {}).get("subsidiaries", [])
                if isinstance(data, dict)
                else [],
            }
        except Exception:
            return {"symbol": symbol.upper(), "subsidiaries": [], "error": "upstream failed"}

    return await cached_json(f"default:subsidiaries:{symbol.upper()}", _produce)


@router.get("/v1/fundamentals/{symbol}/valuation")
async def company_valuation(
    symbol: str,
    eps_value: str | None = Query(None, description="Custom EPS value or leave empty for default"),
    growth_value: str | None = Query(
        None, description="Custom Growth % value or leave empty for default"
    ),
    multiple_value: str | None = Query(
        None, description="Custom P/E multiple or leave empty for default"
    ),
):
    """Calculate DCF / Graham model fair value target price, margin of safety, and consensus range."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.company_valuation(
                symbol=symbol,
                eps_value=eps_value,
                growth_value=growth_value,
                multiple_value=multiple_value,
            )
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {
                "symbol": symbol.upper(),
                "valuation": raw_data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to calculate valuation for {symbol}: {e}")

    # Custom inputs are part of the key — same helper, no special path.
    return await cached_json(
        f"default:valuation:{symbol.upper()}:{eps_value}:{growth_value}:{multiple_value}",
        _produce,
    )


@router.get("/v1/fundamentals/{symbol}/valuation/metrics")
async def company_valuation_metrics(symbol: str):
    """Retrieve current EPS, historical growth rates, and valuation multiples used as model inputs."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.valuation_metrics(symbol=symbol)
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {
                "symbol": symbol.upper(),
                "metrics": raw_data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch valuation metrics for {symbol}: {e}")

    return await cached_json(f"default:valuation-metrics:{symbol.upper()}", _produce)


@router.get("/v1/fundamentals/{symbol}/history")
async def fundamental_history(
    symbol: str,
    item_id: int = Query(
        2661, description="Metric item ID (default: 2661 for Price, or PE, PBV, ROE etc.)"
    ),
    timeframe: str = Query("1y", description="Timeframe horizon (e.g. 1y, 3y, 5y, 10y)"),
):
    """Retrieve multi-year daily time-series for fundamental ratios and valuation metrics."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.fundachart_data(item=item_id, companies=symbol, timeframe=timeframe)
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {
                "symbol": symbol.upper(),
                "item_id": item_id,
                "timeframe": timeframe,
                "series": raw_data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch fundamental history for {symbol}: {e}")

    return await cached_json(
        f"default:fundhistory:{symbol.upper()}:{item_id}:{timeframe}", _produce
    )
