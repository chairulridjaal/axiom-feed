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


@router.get("/v1/brokers/{symbol}/distribution")
async def broker_distribution(
    symbol: str,
    date: str = Query("", description="Date in YYYY-MM-DD (empty for latest)"),
    period: str = Query("TB_PERIOD_LAST_1_DAY", description="Period filter"),
    investor_type: str = Query("INVESTOR_TYPE_ALL", description="Investor type"),
    market_board: str = Query("MARKET_TYPE_REGULER", description="Market board"),
    data_type: str = Query(
        "BROKER_DISTRIBUTION_DATA_TYPE_VALUE", description="Data type: VALUE or VOLUME"
    ),
):
    """Retrieve buyer-to-seller broker distribution matrix for a stock."""
    p = get_provider()
    try:
        data = await p.broker_distribution(
            symbol=symbol,
            date=date,
            period=period,
            investor_type=investor_type,
            market_board=market_board,
            data_type=data_type,
        )
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {"symbol": symbol.upper(), "distribution": raw_data}
    except Exception as e:
        raise HTTPException(502, f"Broker distribution failed for {symbol}: {e}")


@router.get("/v1/flow/{symbol}/foreign-domestic")
async def foreign_domestic_flow(
    symbol: str,
    period: str = Query(
        "PERIOD_RANGE_1D",
        description="Flow period range (e.g. PERIOD_RANGE_1D, PERIOD_RANGE_1W, PERIOD_RANGE_1M)",
    ),
    market_type: str = Query("MARKET_TYPE_REGULAR", description="Market type"),
):
    """Retrieve Foreign Buy vs Foreign Sell vs Domestic institutional flow summary and time-series."""
    p = get_provider()
    try:
        data = await p.foreign_domestic_flow(symbol=symbol, period=period, market_type=market_type)
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {"symbol": symbol.upper(), "flow": raw_data}
    except Exception as e:
        raise HTTPException(502, f"Foreign-domestic flow failed for {symbol}: {e}")


@router.get("/v1/brokers/{code}/chart")
async def broker_activity_chart(
    code: str,
    period: str = Query("RT_PERIOD_LAST_1_DAY", description="Period"),
    investor_type: str = Query("INVESTOR_TYPE_ALL", description="Investor type"),
    market_board: str = Query("BOARD_TYPE_REGULAR", description="Board type"),
):
    """Retrieve intraday transaction time-series chart for a broker."""
    p = get_provider()
    try:
        data = await p.broker_activity_chart(
            broker_code=code,
            period=period,
            investor_type=investor_type,
            market_board=market_board,
        )
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {"broker": code.upper(), "chart": raw_data}
    except Exception as e:
        raise HTTPException(502, f"Broker activity chart failed for {code}: {e}")


@router.get("/v1/brokers/{code}/history")
async def broker_activity_historical(
    code: str,
    symbols: str = Query(..., description="Equity symbol (e.g. BBCA)"),
    period: str = Query("RT_PERIOD_LAST_1_YEAR", description="History period"),
    interval: str = Query("INTERVAL_DAILY", description="Time interval"),
    market_board: str = Query("BOARD_TYPE_REGULAR", description="Board type"),
    investor_type: str = Query("INVESTOR_TYPE_ALL", description="Investor type"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(25, ge=1, le=100, description="Records limit"),
):
    """Retrieve multi-horizon historical daily accumulation/distribution of a broker on a specific stock."""
    p = get_provider()
    try:
        data = await p.broker_activity_historical(
            broker_codes=code,
            symbols=symbols,
            period=period,
            interval=interval,
            market_board=market_board,
            investor_type=investor_type,
            page=page,
            limit=limit,
        )
        raw_data = data.get("data") if isinstance(data, dict) else data
        return {"broker": code.upper(), "symbol": symbols.upper(), "history": raw_data}
    except Exception as e:
        raise HTTPException(502, f"Broker historical activity failed for {code} on {symbols}: {e}")
