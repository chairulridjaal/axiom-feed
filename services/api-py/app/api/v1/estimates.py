"""Analyst Estimates & Ratings router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Estimates & Ratings"])


@router.get("/v1/estimates/{symbol}/consensus")
async def get_analyst_consensus(symbol: str) -> dict[str, Any]:
    """Retrieve multi-year forward analyst consensus estimates (Revenue, Operating Profit, Net Profit, EPS)."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.analyst_consensus(symbol)
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {
                "symbol": symbol.upper(),
                "consensus": raw_data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch analyst consensus for {symbol}: {e}")

    return await cached_json(f"default:estimates:{symbol.upper()}:consensus", _produce)


@router.get("/v1/estimates/{symbol}/ratings")
async def get_analyst_ratings(symbol: str) -> dict[str, Any]:
    """Retrieve analyst target prices (low, high, consensus) and Buy/Hold/Sell breakdown."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.analyst_ratings(symbol)
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {
                "symbol": symbol.upper(),
                "ratings": raw_data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch analyst ratings for {symbol}: {e}")

    return await cached_json(f"default:estimates:{symbol.upper()}:ratings", _produce)


@router.get("/v1/estimates/{symbol}/research")
async def get_company_research(symbol: str) -> dict[str, Any]:
    """Retrieve official analyst equity research coverage and reports for a symbol."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.company_research(symbol)
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {
                "symbol": symbol.upper(),
                "research": raw_data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch equity research for {symbol}: {e}")

    return await cached_json(f"default:estimates:{symbol.upper()}:research", _produce)
