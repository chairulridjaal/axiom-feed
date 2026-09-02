#![allow(dead_code, clippy::all)]
//! hub — fanout to api-py via Redis Streams, plus local broadcast.

use std::sync::Arc;
use tokio::sync::broadcast;
use tracing::{info, warn};

#[derive(Clone)]
pub struct Hub {
    tx: broadcast::Sender<String>,
}

impl Hub {
    pub fn new() -> Arc<Self> {
        let (tx, _) = broadcast::channel(1024);
        Arc::new(Self { tx })
    }
    pub fn sender(&self) -> broadcast::Sender<String> {
        self.tx.clone()
    }
    pub fn publish(&self, json: String) {
        let _ = self.tx.send(json);
    }
}

pub async fn redis_publisher_task(hub: Arc<Hub>, redis_url: String) {
    let mut rx = hub.sender().subscribe();
    let client = match redis::Client::open(redis_url.clone()) {
        Ok(c) => c,
        Err(e) => {
            warn!("redis client open failed {} — running in-memory only", e);
            return;
        }
    };
    let mut con = match client.get_multiplexed_async_connection().await {
        Ok(c) => c,
        Err(e) => {
            warn!("redis get connection failed at startup: {} — retrying", e);
            tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
            return Box::pin(redis_publisher_task(hub, redis_url)).await;
        }
    };
    loop {
        match rx.recv().await {
            Ok(msg) => {
                let res: Result<String, _> = redis::cmd("XADD")
                    .arg("axiom.events")
                    .arg("MAXLEN")
                    .arg("~")
                    .arg("1000")
                    .arg("*")
                    .arg("payload")
                    .arg(&msg)
                    .query_async(&mut con)
                    .await;
                if let Err(e) = res {
                    warn!("XADD failed: {} — reconnecting redis", e);
                    tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
                    match client.get_multiplexed_async_connection().await {
                        Ok(c) => con = c,
                        Err(e2) => {
                            warn!("redis reconnect failed: {}", e2);
                            tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
                        }
                    }
                }
            }
            Err(broadcast::error::RecvError::Lagged(n)) => {
                warn!("hub lagged {} messages — drop-oldest active", n);
            }
            Err(broadcast::error::RecvError::Closed) => break,
        }
    }
}

pub async fn publisher_task(_hub: Arc<Hub>) {
    info!("in-memory hub publisher idle (use redis_publisher_task for Streams)");
    std::future::pending::<()>().await;
}
