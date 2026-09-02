from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.financial_parser import parse_financial_statement_html
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Fundamentals"])


@router.get("/v1/fundamentals/{symbol}")
async def fundamentals(symbol: str):
    p = get_provider()
    ks = await p.key_stats(symbol)
    if not ks:
        raise HTTPException(404, f"No fundamentals for {symbol}")
    return {"symbol": symbol.upper(), "key_stats": ks.raw}


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


@router.get("/v1/companies/{symbol}")
async def company(symbol: str):
    p = get_provider()
    try:
        data = await p.emitten_info(symbol)
        return {
            "symbol": symbol.upper(),
            "data": data.get("data") if isinstance(data, dict) else data,
        }
    except Exception as e:
        return {"symbol": symbol.upper(), "data": None, "error": str(e)}


@router.get("/v1/companies/{symbol}/profile")
async def company_profile(symbol: str):
    p = get_provider()
    try:
        data = await p.emitten_profile(symbol)
        return {
            "symbol": symbol.upper(),
            "profile": data.get("data") if isinstance(data, dict) else data,
        }
    except Exception as e:
        return {"symbol": symbol.upper(), "profile": None, "error": str(e)}


@router.get("/v1/companies/{symbol}/subsidiaries")
async def company_subsidiaries(symbol: str):
    p = get_provider()
    try:
        data = await p.emitten_subsidiaries(symbol)
        return {
            "symbol": symbol.upper(),
            "subsidiaries": data.get("data", {}).get("subsidiaries", [])
            if isinstance(data, dict)
            else [],
        }
    except Exception as e:
        return {"symbol": symbol.upper(), "subsidiaries": [], "error": str(e)}
