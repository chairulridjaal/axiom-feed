from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.transport import get_transport

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Charts"])


@router.get("/v1/charts/tradebook")
async def tradebook(symbol: str = Query(...), interval: str = Query("1m")):
    t = get_transport()
    try:
        data = await t.get_json(
            "https://exodus.stockbit.com/order-trade/trade-book",
            params={"symbol": symbol.upper(), "group_by": "GROUP_BY_PRICE", "interval": interval},
            label=f"chart {symbol} {interval}",
        )
    except Exception as e:
        raise HTTPException(502, str(e))
    return {"symbol": symbol.upper(), "interval": interval, "data": data}


@router.get("/v1/charts/{symbol}/daily")
async def chart_daily(
    symbol: str,
    timeframe: str = Query("1w", description="today, 1w, 1m, 3m, ytd, 1y, 3y, 5y"),
    is_include_previous_historical: bool = Query(True),
):
    t = get_transport()
    url = f"https://exodus.stockbit.com/charts/{symbol.upper()}/daily"
    params = {
        "timeframe": timeframe,
        "is_include_previous_historical": "true" if is_include_previous_historical else "false",
    }
    try:
        data = await t.get_json(url, params=params, label=f"chart_daily {symbol} {timeframe}")
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "data": data.get("data") if isinstance(data, dict) else data,
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch chart for {symbol}: {e}")


@router.get("/v1/charts/{symbol}/performance")
async def price_performance(symbol: str):
    t = get_transport()
    url = f"https://exodus.stockbit.com/company-price-feed/price-performance/{symbol.upper()}"
    try:
        data = await t.get_json(url, label=f"performance {symbol}")
        return {
            "symbol": symbol.upper(),
            "performance": data.get("data") if isinstance(data, dict) else data,
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch performance for {symbol}: {e}")
