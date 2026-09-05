import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import verify_api_key
from app.infra.archive import SQLiteArchive

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Analytics"])
_archive = SQLiteArchive()


@router.get("/v1/analytics/vwap/{symbol}")
async def get_vwap(symbol: str):
    """VWAP, trade count, and price range from stored ticks (SQLite aggregate)."""
    res = await asyncio.to_thread(_archive.calculate_vwap, symbol)
    if not res:
        raise HTTPException(
            status_code=404, detail=f"No execution ticks found for {symbol.upper()}"
        )
    return res


@router.get("/v1/analytics/flow/{symbol}")
async def get_flow(symbol: str):
    """Buyer-initiated vs seller-initiated volume imbalance ratio."""
    res = await asyncio.to_thread(_archive.get_flow_stats, symbol)
    if not res:
        raise HTTPException(
            status_code=404, detail=f"No execution ticks found for {symbol.upper()}"
        )
    return res
