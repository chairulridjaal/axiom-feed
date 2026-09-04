from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import verify_api_key
from app.providers.stockbit.provider import get_provider

router = APIRouter(dependencies=[Depends(verify_api_key)], tags=["Books"])


@router.get("/v1/books/snapshot/{symbol}")
async def book_snapshot(symbol: str):
    prov = get_provider()
    try:
        data = await prov.trade_book(symbol, group_by="1")
    except Exception as e:
        raise HTTPException(502, f"upstream failed: {e}")
    return {"symbol": symbol.upper(), "snapshot": data}


@router.get("/v1/books")
async def books(symbols: str = Query("")):
    prov = get_provider()
    snap = prov.live_feed().snapshot_books()
    if symbols:
        wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
        out = {}
        for sym in wanted:
            b = snap.get(sym)
            if not b:
                try:
                    data = await prov.trade_book(sym, group_by="1")
                    book_list = (
                        data.get("data", {}).get("book", []) if isinstance(data, dict) else []
                    )
                    out[sym] = {
                        "bids": len([x for x in book_list if x.get("buy", {}).get("lot") != "-"]),
                        "asks": len([x for x in book_list if x.get("sell", {}).get("lot") != "-"]),
                    }
                except Exception:
                    out[sym] = None
            else:
                out[sym] = {"bids": len(b.bids), "asks": len(b.asks)}
    else:
        out = {k: {"bids": len(v.bids), "asks": len(v.asks)} for k, v in snap.items()}
    return {"symbols": symbols, "books": out}


@router.get("/v1/books/{symbol}")
async def book(symbol: str):
    sym = symbol.upper()
    prov = get_provider()
    b = prov.live_feed().snapshot_books().get(sym)
    if not b:
        try:
            data = await prov.trade_book(sym, group_by="1")
            if data and isinstance(data, dict) and "data" in data:
                raw_book = data["data"].get("book", [])
                bids = []
                asks = []
                for item in raw_book:
                    price_str = str(item.get("price", "0")).replace(",", "").strip()
                    try:
                        price = Decimal(price_str)
                    except Exception:
                        continue
                    buy_lot_str = str(item.get("buy", {}).get("lot", "-")).replace(",", "").strip()
                    if buy_lot_str not in ("-", ""):
                        try:
                            bids.append({"price": str(price), "lots": int(float(buy_lot_str))})
                        except Exception:
                            pass
                    sell_lot_str = (
                        str(item.get("sell", {}).get("lot", "-")).replace(",", "").strip()
                    )
                    if sell_lot_str not in ("-", ""):
                        try:
                            asks.append({"price": str(price), "lots": int(float(sell_lot_str))})
                        except Exception:
                            pass
                return {
                    "symbol": sym,
                    "book": {
                        "bids": bids,
                        "asks": asks,
                        "ts": data["data"].get("date", ""),
                    },
                }
        except Exception:
            pass
        return {"symbol": sym, "book": None}
    return {
        "symbol": sym,
        "book": {
            "bids": [{"price": str(l.price), "lots": l.lots} for l in b.bids],
            "asks": [{"price": str(l.price), "lots": l.lots} for l in b.asks],
            "ts": b.ts.isoformat(),
        },
    }
