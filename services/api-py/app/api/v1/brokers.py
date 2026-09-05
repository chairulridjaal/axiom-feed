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
    period: str = Query(
        None,
        description="Native upstream aggregation window (e.g. BROKER_SUMMARY_PERIOD_YEAR_TO_DATE, BROKER_SUMMARY_PERIOD_LAST_7_DAYS). Mutually exclusive with from/to — when set, dates are omitted (upstream silently ignores dates when period is present).",
    ),
    transaction_type: str = Query("TRANSACTION_TYPE_NET"),
    market_board: str = Query("MARKET_BOARD_REGULER"),
    investor_type: str = Query("INVESTOR_TYPE_ALL"),
    limit: int = Query(100),
):
    from app.infra.upstream_cache import cached_json

    p = get_provider()
    sym = symbol.upper()
    cache_key = f"brokers:{sym}:{frm}:{to}:{period}:{transaction_type}:{market_board}:{investor_type}:{limit}"

    async def _produce():
        try:
            data = await p.broker_summary(
                symbol,
                frm=frm,
                to=to,
                period=period,
                transaction_type=transaction_type,
                market_board=market_board,
                investor_type=investor_type,
                limit=limit,
            )
            return {"symbol": sym, "data": data}
        except Exception as e:
            raise HTTPException(502, f"Broker summary failed: {e}")

    return await cached_json(cache_key, _produce)


@router.get("/v1/brokers/top")
async def brokers_top(
    frm: str = Query(None, alias="from"),
    to: str = Query(None, alias="to"),
    sort: str = Query("TB_SORT_BY_TOTAL_VALUE"),
    order: str = Query("ORDER_BY_DESC"),
    market_type: str = Query("MARKET_TYPE_ALL"),
):
    from app.infra.upstream_cache import cached_json

    p = get_provider()
    cache_key = f"brokers:top:{frm}:{to}:{sort}:{order}:{market_type}"

    async def _produce():
        try:
            data = await p.brokers_top(frm, to, sort=sort, order=order, market_type=market_type)
            return {"brokers": data}
        except Exception as e:
            raise HTTPException(502, f"Broker top failed: {e}")

    return await cached_json(cache_key, _produce)


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
    limit: int = Query(25, ge=1, le=100),
):
    from app.infra.upstream_cache import cached_json

    p = get_provider()
    s = start or frm or dt.datetime.now().strftime("%Y-%m-%d")
    e = end or to or s

    async def _produce():
        try:
            data = await p.brokers_top_stocks(
                s,
                e,
                investor_type=investor_type,
                market_type=market_type,
                value_type=value_type,
                page=page,
                limit=limit,
            )
            return {"stocks": data}
        except Exception as exc:
            raise HTTPException(502, f"Broker top-stocks failed: {exc}")

    return await cached_json(
        f"brokers:top-stocks:{s}:{e}:{investor_type}:{market_type}:{value_type}:{page}:{limit}",
        _produce,
    )


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
    from app.infra.upstream_cache import cached_json

    p = get_provider()

    async def _produce():
        try:
            data = await p.broker_activity(
                code,
                frm,
                to,
                limit=limit,
                page=page,
                transaction_type=transaction_type,
                market_board=market_board,
                investor_type=investor_type,
            )
            return {"broker": code.upper(), "activity": data}
        except Exception as e:
            raise HTTPException(502, f"Broker activity failed: {e}")

    return await cached_json(
        f"brokers:{code.upper()}:activity:{frm}:{to}:{limit}:{page}:{transaction_type}:{market_board}:{investor_type}",
        _produce,
    )


@router.get("/v1/brokers/{symbol}/distribution")
async def broker_distribution(
    symbol: str,
    date: str = Query(
        "", description="Legacy single date in YYYY-MM-DD (ignored when from/to given)"
    ),
    period: str = Query(
        None, description="Period preset, e.g. TB_PERIOD_LAST_1_DAY (ignored when from/to given)"
    ),
    frm: str = Query(
        None,
        alias="from",
        description="Range start YYYY-MM-DD (explicit range wins over period/date)",
    ),
    to: str = Query(None, alias="to", description="Range end YYYY-MM-DD"),
    investor_type: str = Query("INVESTOR_TYPE_ALL", description="Investor type"),
    market_board: str = Query(
        "MARKET_TYPE_REGULER",
        description="Market board (MARKET_TYPE_ prefix here, unlike MARKET_BOARD_ on /brokers/summary)",
    ),
    data_type: str = Query(
        "BROKER_DISTRIBUTION_DATA_TYPE_VALUE", description="Data type: VALUE or VOLUME"
    ),
):
    """Retrieve buyer-to-seller broker distribution matrix for a stock.

    `period` presets (e.g. TB_PERIOD_LAST_1_DAY) and explicit `from`/`to`
    dates are mutually exclusive upstream — when `from`/`to` are given,
    `period` and `date` are omitted so the dates are honored.
    """
    from app.infra.upstream_cache import cached_json

    p = get_provider()

    async def _produce():
        try:
            data = await p.broker_distribution(
                symbol=symbol,
                date=date,
                period=period,
                frm=frm,
                to=to,
                investor_type=investor_type,
                market_board=market_board,
                data_type=data_type,
            )
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {"symbol": symbol.upper(), "distribution": raw_data}
        except Exception as e:
            raise HTTPException(502, f"Broker distribution failed for {symbol}: {e}")

    return await cached_json(
        f"brokers:{symbol.upper()}:dist:{date}:{period}:{frm}:{to}:{investor_type}:{market_board}:{data_type}",
        _produce,
    )


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
    from app.infra.upstream_cache import cached_json

    p = get_provider()

    async def _produce():
        try:
            data = await p.foreign_domestic_flow(
                symbol=symbol, period=period, market_type=market_type
            )
            raw_data = data.get("data") if isinstance(data, dict) else data
            return {"symbol": symbol.upper(), "flow": raw_data}
        except Exception as e:
            raise HTTPException(502, f"Foreign-domestic flow failed for {symbol}: {e}")

    return await cached_json(f"brokers:{symbol.upper()}:flow:{period}:{market_type}", _produce)


@router.get("/v1/brokers/{code}/chart")
async def broker_activity_chart(
    code: str,
    period: str = Query("RT_PERIOD_LAST_1_DAY", description="Period"),
    investor_type: str = Query("INVESTOR_TYPE_ALL", description="Investor type"),
    market_board: str = Query("BOARD_TYPE_REGULAR", description="Board type"),
):
    """Retrieve intraday transaction time-series chart for a broker."""
    from app.infra.upstream_cache import cached_json

    p = get_provider()

    async def _produce():
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

    return await cached_json(
        f"brokers:{code.upper()}:chart:{period}:{investor_type}:{market_board}", _produce
    )


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
    from app.infra.upstream_cache import cached_json

    p = get_provider()

    async def _produce():
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
            raise HTTPException(
                502, f"Broker historical activity failed for {code} on {symbols}: {e}"
            )

    return await cached_json(
        f"brokers:{code.upper()}:{symbols.upper()}:hist:{period}:{interval}:{market_board}:{investor_type}:{page}:{limit}",
        _produce,
    )
