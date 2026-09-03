#![allow(dead_code, clippy::needless_range_loop)]
//! decode — provider specifics isolated here.

use flate2::read::{DeflateDecoder, ZlibDecoder};
use prost::Message;
use serde_json::Value;
use std::io::Read;

include!(concat!(env!("OUT_DIR"), "/stockbit.datafeed.v1.rs"));

pub fn decompress(bytes: &[u8]) -> Vec<u8> {
    if bytes.is_empty() {
        return Vec::new();
    }
    if let Ok(v) = try_deflate(bytes) {
        if !v.is_empty() && v.len() > 8 {
            return v;
        }
    }
    let mut with_suffix = Vec::with_capacity(bytes.len() + 4);
    with_suffix.extend_from_slice(bytes);
    with_suffix.extend_from_slice(b"\x00\x00\xff\xff");
    if let Ok(v) = try_deflate(&with_suffix) {
        if !v.is_empty() && v.len() > 8 {
            return v;
        }
    }
    if let Ok(v) = try_zlib(bytes) {
        if !v.is_empty() && v.len() > 8 {
            return v;
        }
    }
    bytes.to_vec()
}

fn try_zlib(d: &[u8]) -> Result<Vec<u8>, std::io::Error> {
    let mut dec = ZlibDecoder::new(d);
    let mut out = Vec::with_capacity(d.len() * 3);
    dec.read_to_end(&mut out)?;
    Ok(out)
}

fn try_deflate(d: &[u8]) -> Result<Vec<u8>, std::io::Error> {
    let mut dec = DeflateDecoder::new(d);
    let mut out = Vec::with_capacity(d.len() * 3);
    dec.read_to_end(&mut out)?;
    Ok(out)
}

#[derive(Debug, Clone)]
pub struct NormalizedEvent {
    pub kind: String,
    pub symbol: String,
    pub payload: Value,
}

fn parse_pipe(body: &str) -> (Vec<Value>, Vec<Value>) {
    let mut bids = Vec::new();
    let mut asks = Vec::new();
    if !body.contains('|') {
        return (bids, asks);
    }
    let parts: Vec<&str> = body.split('|').collect();
    if parts.len() < 4 {
        return (bids, asks);
    }
    let mut bid_idx: Option<usize> = None;
    let mut offer_idx: Option<usize> = None;
    for (i, p) in parts.iter().enumerate() {
        let u = p.trim().to_ascii_uppercase();
        if u == "BID" {
            bid_idx = Some(i);
        } else if u == "OFFER" || u == "ASK" {
            offer_idx = Some(i);
        }
    }
    if bid_idx.is_none() && offer_idx.is_none() {
        return (bids, asks);
    }
    let parse_segment = |start: usize, end: usize, out: &mut Vec<Value>| {
        for s in &parts[start..end] {
            let s = s.trim();
            if s.is_empty() {
                continue;
            }
            let f: Vec<&str> = s.split(';').collect();
            if f.len() < 2 {
                continue;
            }
            if let (Ok(price), Ok(lot)) = (f[0].parse::<f64>(), f[1].parse::<f64>()) {
                out.push(serde_json::json!({"price": price, "lot": lot as i64}));
            }
        }
    };
    if let Some(bi) = bid_idx {
        let end = offer_idx.unwrap_or(parts.len());
        parse_segment(bi + 1, end, &mut bids);
    }
    if let Some(oi) = offer_idx {
        parse_segment(oi + 1, parts.len(), &mut asks);
    }
    (bids, asks)
}

pub fn decode(bytes: &[u8]) -> Option<Vec<NormalizedEvent>> {
    use websocket_wrap_message_channel::MessageChannel;
    let data = decompress(bytes);
    if data.is_empty() {
        return None;
    }
    let msg = WebsocketWrapMessageChannel::decode(data.as_slice()).ok()?;
    let which = msg.message_channel?;
    let mut out = Vec::new();
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
            for t in b.batch {
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
                    }),
                });
            }
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
            let bids: Vec<Value> = ob
                .bid
                .iter()
                .map(|b| serde_json::json!({"price": b.price, "lot": b.lot}))
                .collect();
            let offers: Vec<Value> = ob
                .offer
                .iter()
                .map(|o| serde_json::json!({"price": o.price, "lot": o.lot}))
                .collect();
            out.push(NormalizedEvent {
                kind: "book".into(),
                symbol: ob.stock_symbol.clone(),
                payload: serde_json::json!({
                    "stock": ob.stock_symbol,
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
