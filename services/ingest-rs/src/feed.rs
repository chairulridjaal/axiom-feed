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

    pub fn subscribe(&mut self, symbols: &[String], kinds: &[String]) -> Result<(), String> {
        let has_wildcard = symbols.iter().any(|x| x == "*");
        let wants_quotes = kinds
            .iter()
            .any(|k| k == "quotes" || k == "liveprice" || k == "books" || k == "orderbook");
        if has_wildcard && wants_quotes {
            return Err("'*' only for running_trade_batch (trades), not quotes/books — use explicit symbols".into());
        }
        for sym in symbols {
            let u = sym.to_uppercase();
            if u == "*" {
                continue;
            }
            if kinds.iter().any(|k| k == "quotes" || k == "liveprice") {
                self.liveprice.insert(u.clone());
            }
            if kinds.iter().any(|k| k == "books" || k == "orderbook") {
                self.orderbook.insert(u.clone());
            }
            if kinds.iter().any(|k| k == "trades") {}
        }
        const MAX: usize = 200;
        if self.liveprice.len() > MAX || self.orderbook.len() > MAX {
            tracing::warn!(
                "FeedState exceeds {} symbols (liveprice={}, orderbook={})",
                MAX,
                self.liveprice.len(),
                self.orderbook.len()
            );
        }
        Ok(())
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
    fn test_wildcard_reject_quotes() {
        let mut s = FeedState::new(vec!["BBCA".into()]);
        assert!(s.subscribe(&["*".into()], &["quotes".into()]).is_err());
        assert!(s.subscribe(&["*".into()], &["books".into()]).is_err());
        assert!(s.subscribe(&["*".into()], &["liveprice".into()]).is_err());
    }

    #[test]
    fn test_wildcard_allowed_trades() {
        let mut s = FeedState::new(vec![]);
        assert!(s.subscribe(&["*".into()], &["trades".into()]).is_ok());
    }

    #[test]
    fn test_subscribe_and_build() {
        let mut s = FeedState::new(vec!["BBCA".into()]);
        s.subscribe(&["TLKM".into()], &["quotes".into(), "books".into()])
            .unwrap();
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
