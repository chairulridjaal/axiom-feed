#![allow(dead_code, deprecated, unused_mut)]
//! ingest-rs — single WSS task, prost decode, publish to Redis Streams.

use std::sync::Arc;
use std::time::Duration;

use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::protocol::Message;
use tracing::{error, info, warn};

mod decode;
mod feed;
mod hub;

use hub::Hub;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let ws_url = std::env::var("STOCKBIT_WS_URL")
        .unwrap_or_else(|_| "wss://wss-jkt.trading.stockbit.com/ws".to_string());
    let redis_url = std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://redis:6379".to_string());
    let bearer = std::env::var("STOCKBIT_BEARER_TOKEN").unwrap_or_default();
    let user_id = std::env::var("STOCKBIT_USER_ID").unwrap_or_default();
    let ws_key = std::env::var("STOCKBIT_WS_KEY").unwrap_or_default();

    info!(
        "ingest-rs starting — Stockbit WSS → Redis Streams (ws_url={})",
        ws_url
    );

    let hub = Hub::new();
    let hub_clone = hub.clone();
    tokio::spawn(hub::redis_publisher_task(hub_clone, redis_url.clone()));

    let redis_for_pub = redis_url.clone();
    tokio::spawn(async move {
        let mut backoff = Duration::from_secs(2);
        loop {
            match redis::Client::open(redis_for_pub.clone()) {
                Ok(client) => match client.get_async_connection().await {
                    Ok(con) => {
                        let mut pubsub = con.into_pubsub();
                        if pubsub.subscribe("axiom.auth.refresh").await.is_ok() {
                            info!("subscribed to axiom.auth.refresh for hot-swap");
                            backoff = Duration::from_secs(2);
                            let mut stream = pubsub.on_message();
                            while let Some(msg) = stream.next().await {
                                if let Ok(payload) = msg.get_payload::<String>() {
                                    info!(
                                        "auth refresh msg: {}",
                                        payload[..payload.len().min(120)].to_string()
                                    );
                                    if let Ok(v) =
                                        serde_json::from_str::<serde_json::Value>(&payload)
                                    {
                                        if let Some(b) = v.get("bearer").and_then(|x| x.as_str()) {
                                            std::env::set_var("STOCKBIT_BEARER_TOKEN", b);
                                        }
                                        if let Some(u) = v.get("user_id").and_then(|x| x.as_str()) {
                                            std::env::set_var("STOCKBIT_USER_ID", u);
                                        }
                                        if let Some(k) = v.get("ws_key").and_then(|x| x.as_str()) {
                                            std::env::set_var("STOCKBIT_WS_KEY", k);
                                        }
                                    }
                                }
                            }
                        } else {
                            warn!("pubsub subscribe failed — retry in {:?}", backoff);
                        }
                    }
                    Err(e) => warn!(
                        "redis pubsub connect failed: {} — retry in {:?}",
                        e, backoff
                    ),
                },
                Err(e) => warn!("redis client open failed: {} — retry in {:?}", e, backoff),
            }
            tokio::time::sleep(backoff).await;
            backoff = std::cmp::min(Duration::from_secs(60), backoff * 2);
        }
    });

    let initial_symbols = std::env::var("SUBSCRIBE_SYMBOLS")
        .unwrap_or_else(|_| "BBCA,TLKM,IHSG".to_string())
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>();

    if bearer.is_empty() || ws_key.is_empty() {
        warn!("STOCKBIT_BEARER_TOKEN or WS_KEY empty — will connect once credentials available via redis/env");
    }

    run_loop(ws_url, user_id, ws_key, bearer, initial_symbols, hub).await
}

async fn run_loop(
    ws_url: String,
    mut user_id: String,
    mut ws_key: String,
    mut bearer: String,
    initial_symbols: Vec<String>,
    hub: Arc<Hub>,
) -> anyhow::Result<()> {
    let feed_state = feed::FeedState::new(initial_symbols);
    let mut backoff = Duration::from_secs(5);
    let max_backoff = Duration::from_secs(60);

    loop {
        if let Ok(b) = std::env::var("STOCKBIT_BEARER_TOKEN") {
            if !b.is_empty() {
                bearer = b;
            }
        }
        if let Ok(u) = std::env::var("STOCKBIT_USER_ID") {
            if !u.is_empty() {
                user_id = u;
            }
        }
        if let Ok(k) = std::env::var("STOCKBIT_WS_KEY") {
            if !k.is_empty() {
                ws_key = k;
            }
        }

        if bearer.is_empty() || ws_key.is_empty() || user_id.is_empty() {
            warn!(
                "missing credentials — retry in {:?} (set STOCKBIT_BEARER_TOKEN / run auth refresh)",
                backoff
            );
            tokio::time::sleep(backoff).await;
            backoff = std::cmp::min(max_backoff, backoff * 2);
            let jitter = rand::random::<f64>() * 0.3 + 0.85;
            backoff = Duration::from_secs_f64(backoff.as_secs_f64() * jitter);
            continue;
        }

        info!(
            "connecting to {} (user_id={} ws_key={}...)",
            ws_url,
            user_id,
            &ws_key[..ws_key.len().min(8)]
        );

        let request = tokio_tungstenite::tungstenite::handshake::client::Request::builder()
            .uri(ws_url.clone())
            .header("Origin", "https://stockbit.com")
            .header("Authorization", format!("Bearer {}", bearer))
            .header("User-Agent", "Mozilla/5.0")
            .body(())
            .unwrap();

        let connect_result = tokio_tungstenite::connect_async(request).await;
        let (mut ws_stream, _) = match connect_result {
            Ok(v) => {
                info!("WSS connected");
                backoff = Duration::from_secs(5);
                v
            }
            Err(e) => {
                error!("WSS connect failed: {} — backoff {:?}", e, backoff);
                tokio::time::sleep(backoff).await;
                backoff = std::cmp::min(max_backoff, backoff * 2);
                let jitter = rand::random::<f64>() * 0.3 + 0.85;
                backoff = Duration::from_secs_f64(backoff.as_secs_f64() * jitter);
                continue;
            }
        };

        let sub = feed_state.build_request(&user_id, &ws_key);
        if let Err(e) = ws_stream.send(Message::Binary(sub)).await {
            warn!("send sub failed: {}", e);
        } else {
            info!(
                "sent full subscription liveprice={} orderbook={}",
                feed_state.liveprice.len(),
                feed_state.orderbook.len()
            );
        }

        let mut ping_interval = tokio::time::interval(Duration::from_secs(25));
        ping_interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);

        loop {
            tokio::select! {
                _ = ping_interval.tick() => {
                    let ping = feed_state.build_ping();
                    if let Err(e) = ws_stream.send(Message::Binary(ping)).await {
                        warn!("ping send failed: {} — reconnecting", e);
                        break;
                    }
                }
                msg = ws_stream.next() => {
                    match msg {
                        Some(Ok(Message::Binary(bin))) => {
                            if let Some(events) = decode::decode(&bin) {
                                for ev in events {
                                    if ev.kind == "ping" { continue; }
                                    let payload = serde_json::json!({
                                        "kind": ev.kind,
                                        "symbol": ev.symbol,
                                        "payload": ev.payload,
                                        "ts": chrono::Utc::now().to_rfc3339(),
                                    });
                                    hub.publish(payload.to_string());
                                }
                            }
                        }
                        Some(Ok(Message::Close(frame))) => {
                            warn!("WSS closed: {:?}", frame);
                            break;
                        }
                        Some(Ok(Message::Ping(_))) => {}
                        Some(Ok(_)) => {}
                        Some(Err(e)) => {
                            warn!("WSS read error: {} — reconnecting", e);
                            break;
                        }
                        None => {
                            warn!("WSS stream ended — reconnecting");
                            break;
                        }
                    }
                }
            }
        }

        warn!("reconnect in {:?} (jittered)", backoff);
        tokio::time::sleep(backoff).await;
        backoff = std::cmp::min(max_backoff, backoff * 2);
        let jitter = rand::random::<f64>() * 0.3 + 0.85;
        backoff = Duration::from_secs_f64(backoff.as_secs_f64() * jitter);
    }
}
