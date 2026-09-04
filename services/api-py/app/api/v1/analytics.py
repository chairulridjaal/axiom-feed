from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.infra.archive import DuckDBArchive

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Analytics"])
_archive = DuckDBArchive()


@router.get("/v1/analytics/vwap/{symbol}")
async def get_vwap(symbol: str):
    """Retrieve fast columnar VWAP, trade count, and price range from stored ticks."""
    res = _archive.calculate_vwap(symbol)
    if not res:
        raise HTTPException(
            status_code=404, detail=f"No execution ticks found for {symbol.upper()}"
        )
    return res


@router.get("/v1/analytics/flow/{symbol}")
async def get_flow(symbol: str):
    """Calculate buyer-initiated vs seller-initiated volume imbalance ratio."""
    res = _archive.get_flow_stats(symbol)
    if not res:
        raise HTTPException(
            status_code=404, detail=f"No execution ticks found for {symbol.upper()}"
        )
    return res


@router.post("/v1/analytics/archive")
async def trigger_archive(
    symbol: str | None = Query(None, description="Optional symbol to archive"),
    date: str | None = Query(None, description="Optional YYYY-MM-DD date"),
):
    """Flush and archive stored execution ticks into compressed Parquet partitions."""
    res = _archive.archive_ticks_to_parquet(symbol=symbol, date_str=date)
    return res
