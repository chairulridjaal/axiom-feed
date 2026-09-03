from fastapi import APIRouter, Depends, Query

from app.core.security import verify_api_key

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Trades"])


@router.get("/v1/trades")
async def trades(
    symbols: str = Query("", description="comma-separated"), limit: int = Query(50, ge=1, le=500)
):
    from app.providers.stockbit.provider import get_provider

    prov = get_provider()
    live = prov.live_feed()
    if hasattr(live, "snapshot_trades"):
        try:
            if symbols:
                wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
                pool = live.snapshot_trades(limit=1000)
                all_trades = [t for t in pool if t.symbol in wanted]
            else:
                all_trades = live.snapshot_trades(limit=limit)
            out = [
                {
                    "symbol": t.symbol,
                    "price": str(t.price),
                    "volume": t.volume,
                    "side": t.side.value if hasattr(t.side, "value") else str(t.side),
                    "ts": t.ts.isoformat(),
                    "seq": t.seq,
                }
                for t in all_trades[:limit]
            ]
            return {"symbols": symbols, "limit": limit, "trades": out}
        except Exception:
            pass
    return {"symbols": symbols, "limit": limit, "trades": []}


@router.get("/v1/trades/{symbol}")
async def trades_by_symbol(symbol: str, limit: int = Query(50, ge=1, le=500)):
    from app.providers.stockbit.provider import get_provider

    prov = get_provider()
    live = prov.live_feed()
    if hasattr(live, "snapshot_trades"):
        try:
            data = live.snapshot_trades(symbol=symbol.upper(), limit=limit)
            out = [
                {
                    "symbol": t.symbol,
                    "price": str(t.price),
                    "volume": t.volume,
                    "side": t.side.value if hasattr(t.side, "value") else str(t.side),
                    "ts": t.ts.isoformat(),
                    "seq": t.seq,
                }
                for t in data
            ]
            return {"symbol": symbol.upper(), "limit": limit, "trades": out}
        except Exception:
            pass
    return {"symbol": symbol.upper(), "limit": limit, "trades": []}


@router.get("/v1/trades/running/snapshot")
async def running_trades_snapshot(
    limit: int = Query(80, ge=1, le=200, description="Number of execution ticks"),
    sort: str = Query("DESC", description="Sort order"),
    order_by: str = Query("RUNNING_TRADE_ORDER_BY_TIME", description="Order by criterion"),
):
    """Retrieve upstream snapshot of recent market-wide trade executions."""
    from app.providers.stockbit.provider import get_provider

    prov = get_provider()
    try:
        data = await prov.running_trade_snapshot(sort=sort, limit=limit, order_by=order_by)
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {"running_trades": raw_data}
    except Exception as e:
        return {"running_trades": None, "error": str(e)}
