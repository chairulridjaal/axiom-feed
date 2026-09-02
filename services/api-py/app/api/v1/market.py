from fastapi import APIRouter, Depends, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Market"])


@router.get("/v1/market/movers")
async def movers(kind: str = Query("top_gainers")):
    p = get_provider()
    mapping = {
        "top_gainers": "MOVER_TYPE_TOP_GAINER",
        "top_losers": "MOVER_TYPE_TOP_LOSER",
        "top_volume": "MOVER_TYPE_TOP_VOLUME",
        "top_value": "MOVER_TYPE_TOP_VALUE",
        "top_frequency": "MOVER_TYPE_TOP_FREQUENCY",
        "net_foreign_buy": "MOVER_TYPE_NET_FOREIGN_BUY",
        "net_foreign_sell": "MOVER_TYPE_NET_FOREIGN_SELL",
        "iep_top_gainers": "MOVER_TYPE_IEVAL_TOP_GAINER",
        "iev_top_gainers": "MOVER_TYPE_IEVAL_TOP_GAINER",
        "ieval_top_gainer": "MOVER_TYPE_IEVAL_TOP_GAINER",
    }
    mover_type = mapping.get(
        kind, kind.upper() if kind.startswith("MOVER_TYPE_") else "MOVER_TYPE_TOP_GAINER"
    )
    boards = (
        "filter_stocks=FILTER_STOCKS_TYPE_MAIN_BOARD"
        "&filter_stocks=FILTER_STOCKS_TYPE_DEVELOPMENT_BOARD"
        "&filter_stocks=FILTER_STOCKS_TYPE_ACCELERATION_BOARD"
        "&filter_stocks=FILTER_STOCKS_TYPE_NEW_ECONOMY_BOARD"
    )
    url = f"https://exodus.stockbit.com/order-trade/market-mover?mover_type={mover_type}&{boards}"
    try:
        data = await p.fetch(url, label=f"movers({kind})")
        mover_list = data.get("data", {}).get("mover_list", []) if isinstance(data, dict) else []
        res = []
        for it in mover_list:
            stock = it.get("stock_detail", {}).get("code", "")
            price = it.get("price", 0)
            ch = it.get("change", {}).get("value", 0)
            ch_pct = it.get("change", {}).get("percentage", 0)
            res.append(
                {
                    "symbol": stock,
                    "name": it.get("stock_detail", {}).get("name", ""),
                    "last": str(price),
                    "change": str(ch),
                    "change_pct": f"{ch_pct:.2f}%"
                    if isinstance(ch_pct, (int, float))
                    else str(ch_pct),
                    "volume": it.get("volume", 0),
                    "value": it.get("value", 0),
                    "frequency": it.get("frequency", 0),
                }
            )
        return {"kind": kind, "movers": res}
    except Exception:
        return {"kind": kind, "movers": []}


@router.get("/v1/calendars/{type}")
async def calendars(type: str):
    p = get_provider()
    try:
        data = await p.calendars(type)
        return {"type": type, "data": data.get("data") if isinstance(data, dict) else data}
    except Exception:
        return {"type": type, "data": None}


@router.get("/v1/calendars/companies/{symbol}/actions")
async def company_actions(symbol: str, limit: int = Query(30)):
    p = get_provider()
    try:
        data = await p.company_actions(symbol, limit=limit)
        return {
            "symbol": symbol.upper(),
            "actions": data.get("data") if isinstance(data, dict) else data,
        }
    except Exception:
        return {"symbol": symbol.upper(), "actions": None}


@router.get("/v1/seasonality/{symbol}")
async def seasonality(symbol: str, year: int = Query(2026), back_year: int = Query(5)):
    p = get_provider()
    data = await p.seasonality(symbol, year, back_year)
    return {"symbol": symbol.upper(), "year": year, "back_year": back_year, "data": data}
