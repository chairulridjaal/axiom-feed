from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Charts"])


@router.get("/v1/charts/tradebook")
async def tradebook(symbol: str = Query(...), interval: str = Query("1m")):
    from app.infra.upstream_cache import cached_json

    async def _produce():
        prov = get_provider()
        try:
            data = await prov.trade_book(symbol, interval=interval, group_by="1")
        except Exception as e:
            raise HTTPException(502, str(e))
        return {"symbol": symbol.upper(), "interval": interval, "data": data}

    return await cached_json(f"default:tradebook:{symbol.upper()}:{interval}", _produce)


@router.get("/v1/charts/{symbol}/daily")
async def chart_daily(
    symbol: str,
    timeframe: str = Query("1w", description="today, 1w, 1m, 3m, ytd, 1y, 3y, 5y"),
    is_include_previous_historical: bool = Query(True),
):
    from app.infra.upstream_cache import cached_json

    async def _produce():
        prov = get_provider()
        try:
            data = await prov.chart_daily(
                symbol,
                timeframe=timeframe,
                is_include_previous_historical=is_include_previous_historical,
            )
            return {
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "data": data.get("data") if isinstance(data, dict) else data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch chart for {symbol}: {e}")

    return await cached_json(
        f"default:chart:{symbol.upper()}:{timeframe}:{is_include_previous_historical}", _produce
    )


@router.get("/v1/charts/{symbol}/performance")
async def price_performance(symbol: str):
    from app.infra.upstream_cache import cached_json

    async def _produce():
        prov = get_provider()
        try:
            data = await prov.price_performance(symbol)
            return {
                "symbol": symbol.upper(),
                "performance": data.get("data") if isinstance(data, dict) else data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch performance for {symbol}: {e}")

    return await cached_json(f"default:performance:{symbol.upper()}", _produce)
