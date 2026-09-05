#![allow(dead_code)]
//! feed — subscription state machine.

use prost::Message;
use std::collections::HashSet;

include!(concat!(env!("OUT_DIR"), "/stockbit.datafeed.v1.rs"));

#[derive(Debug, Clone)]
pub struct FeedState {
    pub liveprice: HashSet<String>,
    pub orderbook: HashSet<String>,
}

impl FeedState {
    pub fn new(initial: Vec<String>) -> Self {
        let mut s = HashSet::new();
        for sym in initial {
            let u = sym.to_uppercase();
            if !u.is_empty() {
                s.insert(u);
            }
        }
        Self {
            liveprice: s.clone(),
            orderbook: s,
        }
    }

    pub fn build_request(&self, user_id: &str, ws_key: &str, access_token: &str) -> Vec<u8> {
        let mut req = WebsocketRequest {
            user_id: user_id.to_string(),
            key: ws_key.to_string(),
            access_token: access_token.to_string(),
            channel: Some(WebsocketChannel {
                running_trade_batch: vec!["*".to_string()],
                watchlist: vec!["*".to_string()],
                liveprice: self.liveprice.iter().cloned().collect(),
                order_book: self.orderbook.iter().cloned().collect(),
                running_trade: vec![],
                is_hotlist: false,
            }),
            ping: None,
        };
        debug_assert!(
            !self.liveprice.iter().any(|s| s == "*") && !self.orderbook.iter().any(|s| s == "*"),
            "wildcard only for trades/watchlist"
        );
        if let Some(ch) = req.channel.as_mut() {
            ch.liveprice.sort();
            ch.order_book.sort();
        }
        let mut buf = Vec::new();
        req.encode(&mut buf).unwrap();
        buf
    }

    pub fn build_ping(&self) -> Vec<u8> {
        use prost_types::Timestamp;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap();
        let ts = Timestamp {
            seconds: now.as_secs() as i64,
            nanos: now.subsec_nanos() as i32,
        };
        let req = WebsocketRequest {
            user_id: "".into(),
            key: "".into(),
            access_token: "".into(),
            channel: None,
            ping: Some(PingRequest {
                timestamp: Some(ts),
            }),
        };
        let mut buf = Vec::new();
        req.encode(&mut buf).unwrap();
        buf
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_request() {
        let s = FeedState::new(vec!["BBCA".into(), "TLKM".into()]);
        assert!(s.liveprice.contains("TLKM"));
        assert!(s.orderbook.contains("TLKM"));
        let buf = s.build_request("u1", "k1", "tok");
        assert!(!buf.is_empty());
    }

    #[test]
    fn test_build_ping() {
        let s = FeedState::new(vec![]);
        let buf = s.build_ping();
        assert!(!buf.is_empty());
    }
}
