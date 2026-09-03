"""Equity News, Regulatory Filings & Ticker News Stream router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["News & Filings"])


@router.get("/v1/news/{symbol}")
async def get_symbol_news(
    symbol: str,
    category: str = Query("STREAM_CATEGORY_ALL", description="News stream category filter"),
    last_stream_id: int = Query(0, description="Cursor for pagination"),
    limit: int = Query(20, ge=1, le=50, description="Number of news items to return"),
) -> dict[str, Any]:
    """Retrieve breaking news, corporate announcements, and regulatory disclosures for a specific equity ticker."""
    p = get_provider()
    try:
        data = await p.stream_symbol(
            symbol=symbol,
            category=category,
            last_stream_id=last_stream_id,
            limit=limit,
        )
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {
            "symbol": symbol.upper(),
            "category": category,
            "data": raw_data,
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch news for {symbol}: {e}")
