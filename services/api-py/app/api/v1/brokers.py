import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Brokers"])


@router.get("/v1/brokers/summary/{symbol}")
async def broker_summary(
    symbol: str,
    frm: str = Query(None, alias="from"),
    to: str = Query(None, alias="to"),
    transaction_type: str = Query("TRANSACTION_TYPE_NET"),
    market_board: str = Query("MARKET_BOARD_REGULER"),
    investor_type: str = Query("INVESTOR_TYPE_ALL"),
    limit: int = Query(100),
):
    p = get_provider()
    frm = frm or dt.datetime.now().strftime("%Y-%m-%d")
    to = to or frm
    try:
        data = await p.broker_summary(symbol, frm=frm, to=to)
        return {"symbol": symbol.upper(), "data": data}
    except Exception as e:
        raise HTTPException(502, f"Broker summary failed: {e}")


@router.get("/v1/brokers/top")
async def brokers_top(
    frm: str = Query(None, alias="from"),
    to: str = Query(None, alias="to"),
    sort: str = Query("TB_SORT_BY_TOTAL_VALUE"),
    order: str = Query("ORDER_BY_DESC"),
    market_type: str = Query("MARKET_TYPE_ALL"),
):
    p = get_provider()
    frm = frm or dt.datetime.now().strftime("%Y-%m-%d")
    to = to or frm
    try:
        data = await p.brokers_top(frm, to)
        return {"brokers": data}
    except Exception as e:
        raise HTTPException(502, f"Broker top failed: {e}")


@router.get("/v1/brokers/top-stocks")
async def brokers_top_stocks(
    start: str = Query(None),
    end: str = Query(None),
    frm: str = Query(None, alias="from"),
    to: str = Query(None, alias="to"),
    investor_type: str = Query("INVESTOR_TYPE_ALL"),
    market_type: str = Query("MARKET_TYPE_REGULER"),
    value_type: str = Query("VALUE_TYPE_NET"),
    page: int = Query(1),
):
    p = get_provider()
    s = start or frm or dt.datetime.now().strftime("%Y-%m-%d")
    e = end or to or s
    try:
        data = await p.brokers_top_stocks(s, e)
        return {"stocks": data}
    except Exception as e:
        raise HTTPException(502, f"Broker top-stocks failed: {e}")


@router.get("/v1/brokers/{code}/activity")
async def broker_activity(
    code: str,
    frm: str = Query(None, alias="from"),
    to: str = Query(None, alias="to"),
    limit: int = Query(50),
    page: int = Query(1),
    transaction_type: str = Query("TRANSACTION_TYPE_NET"),
    market_board: str = Query("MARKET_BOARD_REGULER"),
    investor_type: str = Query("INVESTOR_TYPE_ALL"),
):
    p = get_provider()
    frm = frm or dt.datetime.now().strftime("%Y-%m-%d")
    to = to or frm
    try:
        data = await p.broker_activity(code, frm, to)
        return {"broker": code.upper(), "activity": data}
    except Exception as e:
        raise HTTPException(502, f"Broker activity failed: {e}")
