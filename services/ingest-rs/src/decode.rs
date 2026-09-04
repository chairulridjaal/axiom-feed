#![allow(dead_code, clippy::needless_range_loop)]
//! decode — provider specifics isolated here.

use flate2::read::{DeflateDecoder, ZlibDecoder};
use prost::Message;
use serde_json::Value;
use std::cell::RefCell;
use std::collections::HashMap;
use std::io::Read;

include!(concat!(env!("OUT_DIR"), "/stockbit.datafeed.v1.rs"));

#[derive(Clone, Default)]
struct BookDepthState {
    bids: Vec<(i64, i64)>,
    offers: Vec<(i64, i64)>,
    count: u32,
}

thread_local! {
    static DECODE_SCRATCH: RefCell<Vec<u8>> = RefCell::new(Vec::with_capacity(16384));
    static DEPTH_TRACKER: RefCell<HashMap<String, BookDepthState>> = RefCell::new(HashMap::new());
}

/// Decompress bytes into a reusable buffer, avoiding allocations in steady state.
pub fn decompress_into(bytes: &[u8], out: &mut Vec<u8>) -> bool {
    out.clear();
    if bytes.is_empty() {
        return false;
    }
    // Header sniff: zlib streams start with 0x78 (deflate window bits).
    let is_zlib = bytes.len() >= 2 && bytes[0] == 0x78;
    if is_zlib {
        if try_zlib_into(bytes, out).is_ok() && out.len() > 8 {
            return true;
        }
        if try_deflate_into(bytes, out).is_ok() && out.len() > 8 {
            return true;
        }
    } else {
        if try_deflate_into(bytes, out).is_ok() && out.len() > 8 {
            return true;
        }
        // Legacy suffix variant only when primary fails (truncated stream).
        let mut with_suffix = Vec::with_capacity(bytes.len() + 4);
        with_suffix.extend_from_slice(bytes);
        with_suffix.extend_from_slice(b"\x00\x00\xff\xff");
        if try_deflate_into(&with_suffix, out).is_ok() && out.len() > 8 {
            return true;
        }
        if try_zlib_into(bytes, out).is_ok() && out.len() > 8 {
            return true;
        }
    }
    out.clear();
    out.extend_from_slice(bytes);
    true
}

pub fn decompress(bytes: &[u8]) -> Vec<u8> {
    if bytes.is_empty() {
        return Vec::new();
    }
    let mut out = Vec::with_capacity(bytes.len().saturating_mul(4).max(2048));
    decompress_into(bytes, &mut out);
    out
}

fn try_zlib_into(d: &[u8], out: &mut Vec<u8>) -> Result<(), std::io::Error> {
    out.clear();
    let mut dec = ZlibDecoder::new(d);
    dec.read_to_end(out)?;
    Ok(())
}

fn try_deflate_into(d: &[u8], out: &mut Vec<u8>) -> Result<(), std::io::Error> {
    out.clear();
    let mut dec = DeflateDecoder::new(d);
    dec.read_to_end(out)?;
    Ok(())
}

fn try_zlib(d: &[u8]) -> Result<Vec<u8>, std::io::Error> {
    let mut dec = ZlibDecoder::new(d);
    let mut out = Vec::with_capacity(d.len().saturating_mul(4).max(512));
    dec.read_to_end(&mut out)?;
    Ok(out)
}

fn try_deflate(d: &[u8]) -> Result<Vec<u8>, std::io::Error> {
    let mut dec = DeflateDecoder::new(d);
    let mut out = Vec::with_capacity(d.len().saturating_mul(4).max(512));
    dec.read_to_end(&mut out)?;
    Ok(out)
}

#[derive(Debug, Clone)]
pub struct NormalizedEvent {
    pub kind: String,
    pub symbol: String,
    pub payload: Value,
}

#[derive(serde::Serialize)]
struct EventEnvelope<'a> {
    kind: &'a str,
    symbol: &'a str,
    payload: &'a Value,
    ts: &'a str,
}

impl NormalizedEvent {
    #[inline]
    pub fn to_json_string(&self, ts: &str) -> String {
        serde_json::to_string(&EventEnvelope {
            kind: &self.kind,
            symbol: &self.symbol,
            payload: &self.payload,
            ts,
        })
        .unwrap_or_default()
    }
}

pub fn parse_pipe(body: &str) -> (Vec<Value>, Vec<Value>) {
    let mut bids = Vec::new();
    let mut asks = Vec::new();
    if !body.contains('|') {
        return (bids, asks);
    }
    let mut mode = 0u8; // 0 = None, 1 = Bid, 2 = Offer/Ask
    for part in body.split('|') {
        let trimmed = part.trim();
        if trimmed.is_empty() {
            continue;
        }
        if trimmed.eq_ignore_ascii_case("BID") {
            mode = 1;
            continue;
        } else if trimmed.eq_ignore_ascii_case("OFFER") || trimmed.eq_ignore_ascii_case("ASK") {
            mode = 2;
            continue;
        }
        if mode == 0 {
            continue;
        }
        let mut fields = trimmed.split(';');
        if let (Some(price_str), Some(lot_str)) = (fields.next(), fields.next()) {
            if let (Ok(price), Ok(lot)) = (price_str.parse::<f64>(), lot_str.parse::<f64>()) {
                let entry = serde_json::json!({"price": price, "lot": lot as i64});
                if mode == 1 {
                    bids.push(entry);
                } else if mode == 2 {
                    asks.push(entry);
                }
            }
        }
    }
    (bids, asks)
}

pub fn decode(bytes: &[u8]) -> Option<Vec<NormalizedEvent>> {
    use websocket_wrap_message_channel::MessageChannel;
    if bytes.is_empty() {
        return None;
    }
    DECODE_SCRATCH.with(|cell| {
        let mut buf = cell.borrow_mut();
        if !decompress_into(bytes, &mut buf) || buf.is_empty() {
            return None;
        }
        let msg = WebsocketWrapMessageChannel::decode(buf.as_slice()).ok()?;
        let which = msg.message_channel?;
        let mut out = Vec::with_capacity(1);
        match which {
        MessageChannel::RunningTrade(t) => {
            out.push(NormalizedEvent {
                kind: "trade".into(),
                symbol: t.stock.clone(),
                payload: serde_json::json!({
                    "stock": t.stock,
                    "price": t.price,
                    "volume": t.volume,
                    "action": t.action,
                    "board": t.market_board,
                    "trade_number": t.trade_number,
                    "time": t.time.map(|x| x.seconds),
                    "change": t.change.map(|c| serde_json::json!({"value": c.value, "percentage": c.percentage})),
                }),
            });
        }
        MessageChannel::RunningTradeBatch(b) => {
            let trades: Vec<Value> = b
                .batch
                .into_iter()
                .map(|t| {
                    serde_json::json!({
                        "stock": t.stock,
                        "price": t.price,
                        "volume": t.volume,
                        "action": t.action,
                        "board": t.market_board,
                        "trade_number": t.trade_number,
                    })
                })
                .collect();
            let first_symbol = trades
                .first()
                .and_then(|t| t.get("stock").and_then(|s| s.as_str()))
                .unwrap_or("")
                .to_string();
            out.push(NormalizedEvent {
                kind: "trade_batch".into(),
                symbol: first_symbol,
                payload: serde_json::json!({"trades": trades}),
            });
        }
        MessageChannel::Liveprice(lp) => {
            out.push(NormalizedEvent {
                kind: "quote".into(),
                symbol: lp.stock_code.clone(),
                payload: serde_json::json!({
                    "stock_code": lp.stock_code,
                    "lastprice": lp.lastprice,
                    "volume": lp.volume,
                    "high": lp.high,
                    "low": lp.low,
                    "prev": lp.prev,
                    "frequency": lp.frequency,
                    "average": lp.average,
                    "date": lp.date,
                    "open": lp.open,
                    "value": lp.value,
                    "is_index": lp.is_index,
                }),
            });
        }
        MessageChannel::OrderbookBody(ob) => {
            let sym = ob.stock_symbol.clone();
            let raw_bids: Vec<(i64, i64)> = ob.bid.iter().map(|b| (b.price as i64, b.lot as i64)).collect();
            let raw_offers: Vec<(i64, i64)> = ob.offer.iter().map(|o| (o.price as i64, o.lot as i64)).collect();

            let (emit_bids, emit_offers) = DEPTH_TRACKER.with(|tracker| {
                let mut map = tracker.borrow_mut();
                if let Some(state) = map.get_mut(&sym) {
                    state.count += 1;
                    if state.count < 20 {
                        let bids_same = state.bids == raw_bids;
                        let offers_same = state.offers == raw_offers;
                        if bids_same && !offers_same {
                            state.offers = raw_offers;
                            return (false, true);
                        } else if offers_same && !bids_same {
                            state.bids = raw_bids;
                            return (true, false);
                        }
                    }
                    state.bids = raw_bids;
                    state.offers = raw_offers;
                    state.count = 0;
                    (true, true)
                } else {
                    map.insert(
                        sym.clone(),
                        BookDepthState {
                            bids: raw_bids,
                            offers: raw_offers,
                            count: 0,
                        },
                    );
                    (true, true)
                }
            });

            let bids: Vec<Value> = if emit_bids {
                ob.bid
                    .iter()
                    .map(|b| serde_json::json!({"price": b.price, "lot": b.lot}))
                    .collect()
            } else {
                Vec::new()
            };
            let offers: Vec<Value> = if emit_offers {
                ob.offer
                    .iter()
                    .map(|o| serde_json::json!({"price": o.price, "lot": o.lot}))
                    .collect()
            } else {
                Vec::new()
            };
            out.push(NormalizedEvent {
                kind: "book".into(),
                symbol: sym.clone(),
                payload: serde_json::json!({
                    "stock": sym,
                    "bids": bids,
                    "offers": offers,
                    "time": ob.time.map(|t| t.seconds),
                }),
            });
        }
        MessageChannel::Orderbook(ob) => {
            let (bids, asks) = parse_pipe(&ob.body);
            out.push(NormalizedEvent {
                kind: "book".into(),
                symbol: ob.stock.clone(),
                payload: serde_json::json!({
                    "stock": ob.stock,
                    "bids": bids,
                    "offers": asks,
                    "time": ob.time,
                    "server_time": ob.server_time,
                }),
            });
        }
        MessageChannel::Ping(_) => {
            out.push(NormalizedEvent {
                kind: "ping".into(),
                symbol: "".into(),
                payload: serde_json::json!({"type": "pong"}),
            });
        }
        MessageChannel::Error(e) => {
            out.push(NormalizedEvent {
                kind: "error".into(),
                symbol: "".into(),
                payload: serde_json::json!({"code": e.code, "message": e.message}),
            });
        }
    }
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_pipe_full() {
        let body = "#O|BBCA|BID|7500;10;75000|7499;5;37495|OFFER|7501;8;60008|";
        let (bids, asks) = parse_pipe(body);
        assert_eq!(bids.len(), 2);
        assert_eq!(asks.len(), 1);
        assert_eq!(bids[0]["price"], 7500.0);
    }

    #[test]
    fn test_parse_pipe_partial() {
        let (bids, asks) = parse_pipe("#O|BBCA|BID|7500;10|");
        assert_eq!(bids.len(), 1);
        assert_eq!(asks.len(), 0);
    }

    #[test]
    fn test_parse_pipe_empty() {
        let (bids, asks) = parse_pipe("");
        assert_eq!(bids.len(), 0);
        assert_eq!(asks.len(), 0);
    }

    #[test]
    fn test_decompress_empty() {
        let v = decompress(b"");
        assert_eq!(v, b"");
    }

    #[test]
    fn test_decode_empty_returns_none() {
        assert!(decode(b"").is_none());
        assert!(decode(b"not-proto").is_none());
    }
}
