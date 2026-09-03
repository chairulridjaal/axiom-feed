"""Insider & Major Shareholder Intelligence router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Insider & Shareholders"])


@router.get("/v1/insider/movements")
async def get_insider_movements(
    date_start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    date_end: str = Query(..., description="End date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Pagination page"),
    limit: int = Query(20, ge=1, le=100, description="Records per page"),
    action_type: str = Query(
        "ACTION_TYPE_UNSPECIFIED", description="Transaction filter action type"
    ),
    source_type: str = Query("SOURCE_TYPE_UNSPECIFIED", description="Filing source filter"),
) -> dict[str, Any]:
    """Retrieve daily substantial shareholder (>= 5%) buy/sell transactions filed across IDX."""
    p = get_provider()
    try:
        data = await p.insider_majorholders(
            date_start=date_start,
            date_end=date_end,
            page=page,
            limit=limit,
            action_type=action_type,
            source_type=source_type,
        )
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {
            "date_start": date_start,
            "date_end": date_end,
            "page": page,
            "limit": limit,
            "data": raw_data,
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch insider movements: {e}")


@router.get("/v1/companies/{symbol}/shareholders")
async def get_shareholding_composition(symbol: str) -> dict[str, Any]:
    """Retrieve structured shareholder composition (controller, institutional, public, management)."""
    p = get_provider()
    try:
        data = await p.shareholding_composition(symbol)
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {
            "symbol": symbol.upper(),
            "composition": raw_data,
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch shareholding composition for {symbol}: {e}")


@router.get("/v1/companies/{symbol}/shareholders/trend")
async def get_shareholders_trend(
    symbol: str,
    value_year: int = Query(12, description="Months of historical breakdown (e.g. 12, 24, 36)"),
) -> dict[str, Any]:
    """Retrieve multi-year monthly/quarterly shareholder progression and changes."""
    p = get_provider()
    try:
        data = await p.shareholders_chart(symbol, value_year=value_year)
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {
            "symbol": symbol.upper(),
            "value_year": value_year,
            "trend": raw_data,
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch shareholders trend for {symbol}: {e}")
