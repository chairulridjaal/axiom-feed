"""Guru & Quantitative Screeners router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Screeners"])


@router.get("/v1/screeners/presets")
async def list_screener_presets() -> dict[str, Any]:
    """Retrieve directory of pre-configured Guru & quantitative screeners (Piotroski F-Score, Kenneth Fisher P/S, EV/EBITDA, etc.)."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.screener_presets()
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {
                "presets": raw_data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch screener presets: {e}")

    return await cached_json("default:screeners:presets", _produce)


@router.get("/v1/screeners/presets/{preset_id}")
async def run_screener_preset(
    preset_id: int,
    template_type: str = Query("TEMPLATE_TYPE_GURU", description="Screener template type"),
) -> dict[str, Any]:
    """Execute a Guru screener preset and return the list of passing tickers with calculated valuation/financial metrics."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.screener_template(template_id=preset_id, template_type=template_type)
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {
                "preset_id": preset_id,
                "template_type": template_type,
                "data": raw_data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to execute screener preset {preset_id}: {e}")

    return await cached_json(f"default:screener:{preset_id}:{template_type}", _produce)
