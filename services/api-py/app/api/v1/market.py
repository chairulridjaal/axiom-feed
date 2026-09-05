from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Market"])


@router.get("/v1/market/movers")
async def movers(kind: str = Query("top_gainers")):
    from app.infra.upstream_cache import cached_json

    cache_key = f"movers:{kind}"

    async def _produce():
        return await _fetch_movers(kind)

    return await cached_json(cache_key, _produce)


async def _fetch_movers(kind: str):
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
    from app.infra.upstream_cache import cached_json

    cache_key = f"calendars:{type}"

    async def _produce():
        p = get_provider()
        try:
            data = await p.calendars(type)
            return {"type": type, "data": data.get("data") if isinstance(data, dict) else data}
        except Exception:
            return {"type": type, "data": None}

    return await cached_json(cache_key, _produce)


@router.get("/v1/calendars/companies/{symbol}/actions")
async def company_actions(symbol: str, limit: int = Query(30)):
    from app.infra.upstream_cache import cached_json

    cache_key = f"calendars:{symbol.upper()}:actions:{limit}"

    async def _produce():
        p = get_provider()
        try:
            data = await p.company_actions(symbol, limit=limit)
            return {
                "symbol": symbol.upper(),
                "actions": data.get("data") if isinstance(data, dict) else data,
            }
        except Exception:
            return {"symbol": symbol.upper(), "actions": None}

    return await cached_json(cache_key, _produce)


@router.get("/v1/seasonality/{symbol}")
async def seasonality(symbol: str, year: int = Query(2026), back_year: int = Query(5)):
    from app.infra.upstream_cache import cached_json

    cache_key = f"seasonality:{symbol.upper()}:{year}:{back_year}"

    async def _produce():
        p = get_provider()
        try:
            data = await p.seasonality(symbol, year, back_year)
            return {"symbol": symbol.upper(), "year": year, "back_year": back_year, "data": data}
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch seasonality for {symbol}: {e}")

    return await cached_json(cache_key, _produce)


@router.get("/v1/market/session")
async def market_session():
    """Authoritative IDX session state (pre-open/session 1/break/session 2/closed).

    Returns `data.detail.{regular,fca}` with state names, session windows and
    end-of-day flags — use this instead of wall-clock heuristics to decide
    whether empty movers/order queues are normal.
    """
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.market_session()
            return {"session": data.get("data") if isinstance(data, dict) else data}
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch market session: {e}")

    # Live-ish state: default 60s tier, no dedicated key.
    return await cached_json("default:market:session", _produce)


@router.get("/v1/market/order-queue/{symbol}")
async def order_queue(
    symbol: str,
    sort_by: str = Query(None),
    limit: int = Query(None, ge=1, le=500),
):
    """Resting order queue (unmatched pending buy/sell orders) for one symbol."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.order_queue(symbol, sort_by=sort_by, limit=limit)
            raw = data.get("data") if isinstance(data, dict) else data
            return {"symbol": symbol.upper(), "queue": raw}
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch order queue for {symbol}: {e}")

    return await cached_json(f"default:order-queue:{symbol.upper()}:{sort_by}:{limit}", _produce)


@router.get("/v1/market/intraday/{symbol}")
async def intraday_session(
    symbol: str,
    kind: str = Query(
        "price",
        description="'price' (minute OHLC tape) or 'brokers' (intraday broker flow timeline)",
    ),
):
    """Minute-resolution session tape + intraday broker flow for one symbol.

    `kind=price` returns 09:00→16:14 one-minute OHLC points; `kind=brokers`
    returns per-broker cumulative net value/volume series across the session.
    Unlike the live-only `/v1/trades` tape, this serves the full session
    even after market close.
    """
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.running_trade_chart(symbol)
            raw = data.get("data") if isinstance(data, dict) else {}
            if not isinstance(raw, dict):
                return {"symbol": symbol.upper(), "kind": kind, "data": raw}
            if kind == "brokers":
                return {
                    "symbol": symbol.upper(),
                    "kind": kind,
                    "brokers": raw.get("broker_chart_data"),
                }
            return {
                "symbol": symbol.upper(),
                "kind": "price",
                "from": raw.get("from"),
                "to": raw.get("to"),
                "last_updated": raw.get("data_last_updated"),
                "prices": raw.get("price_chart_data"),
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch intraday session for {symbol}: {e}")

    return await cached_json(f"default:intraday:{symbol.upper()}:{kind}", _produce)


@router.get("/v1/indexes/{index_code}/members")
async def index_members(index_code: str, limit: int = Query(50, ge=1, le=500)):
    """Constituent ticker list for an IDX index (LQ45, IDX30, KOMPAS100…).

    Rows carry last price/change/volume inline — one call replaces N
    per-symbol quote lookups when screening a basket.
    """
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.index_members(index_code, limit=limit)
            return {
                "index": index_code.upper(),
                "members": data.get("data") if isinstance(data, dict) else data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch index members for {index_code}: {e}")

    # Membership changes rarely; prices inline go stale — movers:60s tier fits.
    return await cached_json(f"movers:index:{index_code.upper()}:{limit}", _produce)


@router.get("/v1/calendars/day/{day}")
async def corpaction_day(day: str):
    """Market-wide corporate-action calendar for ONE date (YYYY-MM-DD).

    Returns per-kind buckets (dividend, rups, tender, pubex, ipo…).
    """
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.corpaction_day(day)
            return {"date": day, "buckets": data.get("data") if isinstance(data, dict) else data}
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch corporate calendar for {day}: {e}")

    return await cached_json(f"calendars:day:{day}", _produce)


@router.get("/v1/market/corpaction-status")
async def corpaction_status(
    symbols: str = Query(..., description="comma-separated tickers, e.g. BBCA,BBRI"),
):
    """UMA / special-notation (Notasi Khusus) status for 1..N tickers in one call."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.corpaction_status(symbols)
            return {"status": data.get("data") if isinstance(data, dict) else data}
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch corporate-action status: {e}")

    tickers = ",".join(sorted(s.strip().upper() for s in symbols.split(",") if s.strip()))
    return await cached_json(f"calendars:corpaction-status:{tickers}", _produce)


@router.get("/v1/fundamentals/{symbol}/peers")
async def peer_comparison(symbol: str):
    """Peer-relative multiples: subject ratios vs subsector industry aggregate.

    The relative-valuation denominator that absolute-band scoring cannot
    supply — pairs subject and industry readings side-by-side.
    """
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            ratios = await p.peer_ratios(symbol)
            industries = await p.peer_industries(symbol)
            return {
                "symbol": symbol.upper(),
                "ratios": ratios.get("data") if isinstance(ratios, dict) else ratios,
                "industries": industries.get("data")
                if isinstance(industries, dict)
                else industries,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch peer comparison for {symbol}: {e}")

    # No fundamentals tier exists; default 60s. Revisit if hit rates say otherwise.
    return await cached_json(f"default:peers:{symbol.upper()}", _produce)


@router.get("/v1/market/earnings")
async def earnings_recap(
    year: int = Query(None),
    quarter: int = Query(None, ge=1, le=4),
    page: int = Query(1, ge=1),
    search: str = Query(None),
    sort_column: int = Query(1, description="Upstream sort column (required by upstream)"),
    order: str = Query("desc", description="'asc' or 'desc' (required by upstream)"),
):
    """Market-wide earnings recap: consensus estimate vs actual, by quarter."""
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.earnings_recap(
                year=year,
                quarter=quarter,
                page=page,
                search=search,
                sort_column=sort_column,
                order=order,
            )
            return {"earnings": data.get("data") if isinstance(data, dict) else data}
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch earnings recap: {e}")

    return await cached_json(
        f"default:earnings:{year}:{quarter}:{page}:{search}:{sort_column}:{order}", _produce
    )


@router.get("/v1/underwriters/{code}/performance")
async def underwriter_performance(code: str, sort_by: str = Query(None)):
    """One IPO underwriter's track record (first-day returns, ARA streaks, funds raised).

    NOTE: the bare underwriter directory route is 404 upstream — only the
    per-code performance route exists, so the code is a required path segment.
    """
    from app.infra.upstream_cache import cached_json

    async def _produce():
        p = get_provider()
        try:
            data = await p.underwriter_performance(code, sort_by=sort_by)
            return {
                "underwriter": code.upper(),
                "performance": data.get("data") if isinstance(data, dict) else data,
            }
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch underwriter performance for {code}: {e}")

    return await cached_json(f"default:underwriter:{code.upper()}:{sort_by}", _produce)
