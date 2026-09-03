//! bench_suite — High-precision empirical benchmark for ingest-rs.
//! Measures Deflate decompression, Prost decoding, and Hub broadcast latency
//! under 1,000, 5,000, and 10,000 events/sec.

use flate2::write::DeflateEncoder;
use flate2::Compression;
use prost::Message;
use std::io::Write;
use std::time::{Duration, Instant};
use tokio::sync::broadcast;

// Include generated protobuf definitions
include!(concat!(env!("OUT_DIR"), "/stockbit.datafeed.v1.rs"));

// Re-implement or import decode functions
fn compress_raw_deflate(data: &[u8]) -> Vec<u8> {
    let mut encoder = DeflateEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(data).unwrap();
    encoder.finish().unwrap()
}

fn compress_zlib(data: &[u8]) -> Vec<u8> {
    use flate2::write::ZlibEncoder;
    let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(data).unwrap();
    encoder.finish().unwrap()
}

fn try_zlib(d: &[u8]) -> Result<Vec<u8>, std::io::Error> {
    use flate2::read::ZlibDecoder;
    use std::io::Read;
    let mut dec = ZlibDecoder::new(d);
    let mut out = Vec::with_capacity(d.len().saturating_mul(2).max(256));
    dec.read_to_end(&mut out)?;
    Ok(out)
}

fn try_deflate(d: &[u8]) -> Result<Vec<u8>, std::io::Error> {
    use flate2::read::DeflateDecoder;
    use std::io::Read;
    let mut dec = DeflateDecoder::new(d);
    let mut out = Vec::with_capacity(d.len().saturating_mul(2).max(256));
    dec.read_to_end(&mut out)?;
    Ok(out)
}

pub fn decompress_baseline(bytes: &[u8]) -> Vec<u8> {
    if bytes.is_empty() {
        return Vec::new();
    }
    let is_zlib = bytes.len() >= 2 && bytes[0] == 0x78;
    if is_zlib {
        if let Ok(v) = try_zlib(bytes) {
            if !v.is_empty() && v.len() > 8 {
                return v;
            }
        }
        if let Ok(v) = try_deflate(bytes) {
            if !v.is_empty() && v.len() > 8 {
                return v;
            }
        }
    } else {
        if let Ok(v) = try_deflate(bytes) {
            if !v.is_empty() && v.len() > 8 {
                return v;
            }
        }
        let data: Vec<u8> = [bytes, b"\x00\x00\xff\xff" as &[u8]].concat();
        if let Ok(v) = try_deflate(&data) {
            if !v.is_empty() && v.len() > 8 {
                return v;
            }
        }
        if let Ok(v) = try_zlib(bytes) {
            if !v.is_empty() && v.len() > 8 {
                return v;
            }
        }
    }
    bytes.to_vec()
}

pub fn parse_pipe(body: &str) -> (Vec<serde_json::Value>, Vec<serde_json::Value>) {
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
        let t = p.trim();
        if t.eq_ignore_ascii_case("BID") {
            bid_idx = Some(i);
        } else if t.eq_ignore_ascii_case("OFFER") || t.eq_ignore_ascii_case("ASK") {
            offer_idx = Some(i);
        }
    }
    if bid_idx.is_none() && offer_idx.is_none() {
        return (bids, asks);
    }
    let parse_segment = |start: usize, end: usize, out: &mut Vec<serde_json::Value>| {
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

fn create_sample_trade_batch() -> Vec<u8> {
    let mut trades = Vec::new();
    for i in 0..10 {
        trades.push(RunningTrade {
            websocket_time: None,
            stock: "BBCA".to_string(),
            price: 7500.0 + (i as f64 * 25.0),
            volume: 100.0 + (i as f64 * 10.0),
            action: 1, // BUY
            is_global: false,
            time: Some(prost_types::Timestamp {
                seconds: 1700000000 + i,
                nanos: 0,
            }),
            change: Some(Change {
                value: 50.0,
                percentage: 0.67,
            }),
            trade_number: 100000 + i,
            market_board: 1, // RG
            value: 0.0,
        });
    }
    let wrap = WebsocketWrapMessageChannel {
        message_channel: Some(
            websocket_wrap_message_channel::MessageChannel::RunningTradeBatch(RunningTradeBatch {
                batch: trades,
            }),
        ),
    };
    let mut raw = Vec::new();
    wrap.encode(&mut raw).unwrap();
    compress_raw_deflate(&raw)
}

fn create_sample_liveprice() -> Vec<u8> {
    let lp = LivePrice {
        stock_code: "BBRI".to_string(),
        lastprice: 4850.0,
        volume: 5200000.0,
        high: 4900.0,
        low: 4800.0,
        open: 4830.0,
        frequency: 18450.0,
        frg_buy: 0.0,
        frg_sell: 0.0,
        average: 4860.0,
        date: "2026-09-02T14:30:00+07:00".to_string(),
        close: 4850.0,
        prev: 4820.0,
        value: 25272000000.0,
        change: None,
        order_verb: "".to_string(),
        quantity: 0,
        is_index: false,
        sequence_number: 0,
        order_book_id: 0,
        order_number: 0,
        match_number: 0,
        board_flag: 1,
        match_time: "2026-09-02T14:30:00+07:00".to_string(),
        lot_volume: 52000.0,
    };
    let wrap = WebsocketWrapMessageChannel {
        message_channel: Some(websocket_wrap_message_channel::MessageChannel::Liveprice(
            lp,
        )),
    };
    let mut raw = Vec::new();
    wrap.encode(&mut raw).unwrap();
    compress_raw_deflate(&raw)
}

fn create_sample_orderbook_body() -> Vec<u8> {
    let mut bids = Vec::new();
    let mut offers = Vec::new();
    for i in 0..10 {
        bids.push(Bid {
            price: 7500.0 - (i as f64 * 25.0),
            lot: 1000.0 + (i as f64 * 50.0),
        });
        offers.push(Offer {
            price: 7525.0 + (i as f64 * 25.0),
            lot: 800.0 + (i as f64 * 40.0),
        });
    }
    let ob = OrderBookBody {
        stock_symbol: "BBCA".to_string(),
        bid: bids,
        offer: offers,
        time: Some(prost_types::Timestamp {
            seconds: 1700000000,
            nanos: 0,
        }),
    };
    let wrap = WebsocketWrapMessageChannel {
        message_channel: Some(websocket_wrap_message_channel::MessageChannel::OrderbookBody(ob)),
    };
    let mut raw = Vec::new();
    wrap.encode(&mut raw).unwrap();
    compress_raw_deflate(&raw)
}

fn create_sample_orderbook_pipe() -> Vec<u8> {
    let body = "#O|BBCA|BID|7500;1000;7500000|7475;800;5980000|7450;1200;8940000|OFFER|7525;500;3762500|7550;900;6795000|";
    let ob = Orderbook {
        stock: "BBCA".to_string(),
        body: body.to_string(),
        sequence: 12345,
        depth: 5,
        time: "2026-09-02T14:30:00+07:00".to_string(),
        type_flag: 1,
        server_time: "2026-09-02T14:30:00+07:00".to_string(),
    };
    let wrap = WebsocketWrapMessageChannel {
        message_channel: Some(websocket_wrap_message_channel::MessageChannel::Orderbook(
            ob,
        )),
    };
    let mut raw = Vec::new();
    wrap.encode(&mut raw).unwrap();
    compress_raw_deflate(&raw)
}

fn percentile(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let idx = ((sorted.len() as f64 * p / 100.0).round() as usize).min(sorted.len() - 1);
    sorted[idx]
}

#[tokio::main]
async fn main() {
    println!("=== Ingest-RS Performance & Latency Benchmark Suite ===");

    // 1. Benchmark Individual Processing Stages
    println!("\n--- Stage 1: Micro-benchmarking Pipeline Steps (10,000 iterations) ---");
    let trade_batch_wire = create_sample_trade_batch();
    let liveprice_wire = create_sample_liveprice();
    let ob_body_wire = create_sample_orderbook_body();
    let ob_pipe_wire = create_sample_orderbook_pipe();

    // Measure Decompress
    let mut decompress_durations = Vec::with_capacity(10000);
    for _ in 0..10000 {
        let t0 = Instant::now();
        let _ = decompress_baseline(&trade_batch_wire);
        decompress_durations.push(t0.elapsed().as_secs_f64() * 1_000_000.0); // us
    }
    decompress_durations.sort_by(|a, b| a.partial_cmp(b).unwrap());

    // Measure Decompress on zlib-wrapped input (header sniff should route
    // straight to zlib; the old triple-try order burned two deflate attempts).
    let trade_batch_zlib = compress_zlib(&decompress_baseline(&trade_batch_wire));
    assert!(!trade_batch_zlib.is_empty() && trade_batch_zlib[0] == 0x78);
    let mut zlib_durations = Vec::with_capacity(10000);
    for _ in 0..10000 {
        let t0 = Instant::now();
        let out = decompress_baseline(&trade_batch_zlib);
        assert!(!out.is_empty());
        zlib_durations.push(t0.elapsed().as_secs_f64() * 1_000_000.0); // us
    }
    zlib_durations.sort_by(|a, b| a.partial_cmp(b).unwrap());

    // Measure Protobuf Decode
    let decompressed = decompress_baseline(&trade_batch_wire);
    let mut proto_durations = Vec::with_capacity(10000);
    for _ in 0..10000 {
        let t0 = Instant::now();
        let msg = WebsocketWrapMessageChannel::decode(decompressed.as_slice()).unwrap();
        let _ = msg.message_channel;
        proto_durations.push(t0.elapsed().as_secs_f64() * 1_000_000.0); // us
    }
    proto_durations.sort_by(|a, b| a.partial_cmp(b).unwrap());

    // Measure Pipe parsing
    let pipe_body =
        "#O|BBCA|BID|7500;1000;7500000|7475;800;5980000|OFFER|7525;500;3762500|7550;900;6795000|";
    let mut pipe_durations = Vec::with_capacity(10000);
    for _ in 0..10000 {
        let t0 = Instant::now();
        let _ = parse_pipe(pipe_body);
        pipe_durations.push(t0.elapsed().as_secs_f64() * 1_000_000.0);
    }
    pipe_durations.sort_by(|a, b| a.partial_cmp(b).unwrap());

    println!(
        "Decompress (raw deflate + zlib fallback try): p50={:.2}us, p95={:.2}us, p99={:.2}us, min={:.2}us, max={:.2}us",
        percentile(&decompress_durations, 50.0),
        percentile(&decompress_durations, 95.0),
        percentile(&decompress_durations, 99.0),
        decompress_durations[0],
        decompress_durations[decompress_durations.len() - 1]
    );

    println!(
        "Decompress (zlib-wrapped input):              p50={:.2}us, p95={:.2}us, p99={:.2}us, min={:.2}us, max={:.2}us",
        percentile(&zlib_durations, 50.0),
        percentile(&zlib_durations, 95.0),
        percentile(&zlib_durations, 99.0),
        zlib_durations[0],
        zlib_durations[zlib_durations.len() - 1]
    );

    println!(
        "Protobuf decode (prost):                      p50={:.2}us, p95={:.2}us, p99={:.2}us, min={:.2}us, max={:.2}us",
        percentile(&proto_durations, 50.0),
        percentile(&proto_durations, 95.0),
        percentile(&proto_durations, 99.0),
        proto_durations[0],
        proto_durations[proto_durations.len() - 1]
    );

    println!(
        "Pipe-format L2 parsing:                       p50={:.2}us, p95={:.2}us, p99={:.2}us, min={:.2}us, max={:.2}us",
        percentile(&pipe_durations, 50.0),
        percentile(&pipe_durations, 95.0),
        percentile(&pipe_durations, 99.0),
        pipe_durations[0],
        pipe_durations[pipe_durations.len() - 1]
    );

    // 2. End-to-End Pipeline Latency at 1k, 5k, 10k events/sec
    println!("\n--- Stage 2: End-to-End Ingestion Wire Latency (Deflate -> Prost -> Tokio Broadcast) ---");
    let rates = [1000, 5000, 10000];

    for &rate in &rates {
        let (tx, _) = broadcast::channel::<String>(1024);
        let mut rx = tx.subscribe();
        let total_events = rate * 2; // 2 seconds of traffic
        let interval = Duration::from_nanos(1_000_000_000 / rate as u64);

        let mut latencies_us = Vec::with_capacity(total_events);
        let mut inter_arrival_us = Vec::with_capacity(total_events);

        let tx_clone = tx.clone();
        let payload = trade_batch_wire.clone();

        let consumer = tokio::spawn(async move {
            let mut count = 0;
            while count < total_events {
                if let Ok(_msg) = rx.recv().await {
                    count += 1;
                }
            }
        });

        let mut last_send = Instant::now();
        let bench_start = Instant::now();

        for i in 0..total_events {
            let t0 = Instant::now();
            if i > 0 {
                inter_arrival_us.push(t0.duration_since(last_send).as_secs_f64() * 1_000_000.0);
            }
            last_send = t0;

            // Full pipeline execution as in decode.rs + hub.rs
            let decompressed = decompress_baseline(&payload);
            if let Ok(msg) = WebsocketWrapMessageChannel::decode(decompressed.as_slice()) {
                if let Some(websocket_wrap_message_channel::MessageChannel::RunningTradeBatch(b)) =
                    msg.message_channel
                {
                    for t in b.batch {
                        let p = serde_json::json!({
                            "kind": "trade",
                            "symbol": t.stock,
                            "payload": {
                                "stock": t.stock,
                                "price": t.price,
                                "volume": t.volume,
                                "action": t.action,
                                "board": t.market_board,
                                "trade_number": t.trade_number,
                            },
                            "ts": chrono::Utc::now().to_rfc3339(),
                        });
                        let _ = tx_clone.send(p.to_string());
                    }
                }
            }

            let elapsed_us = t0.elapsed().as_secs_f64() * 1_000_000.0;
            latencies_us.push(elapsed_us);

            // Rate pacing
            let target_time = bench_start + interval * (i as u32 + 1);
            let now = Instant::now();
            if target_time > now {
                tokio::time::sleep(target_time - now).await;
            }
        }

        let _ = consumer.await;

        latencies_us.sort_by(|a, b| a.partial_cmp(b).unwrap());
        inter_arrival_us.sort_by(|a, b| a.partial_cmp(b).unwrap());

        let throughput = total_events as f64 / bench_start.elapsed().as_secs_f64();

        println!(
            "Rate: {:5} ev/s | Throughput: {:7.1} ev/s | Pipeline Latency: p50={:5.2}us, p95={:5.2}us, p99={:5.2}us, max={:6.2}us | Jitter (stddev): {:.2}us",
            rate,
            throughput,
            percentile(&latencies_us, 50.0),
            percentile(&latencies_us, 95.0),
            percentile(&latencies_us, 99.0),
            latencies_us[latencies_us.len() - 1],
            percentile(&inter_arrival_us, 95.0) - percentile(&inter_arrival_us, 50.0)
        );
    }

    // 3. Per-Tag Latency & Jitter Profiling
    println!("\n--- Stage 3: Per-Tag Latency Profiling (RunningTradeBatch vs LivePrice vs Orderbook) ---");
    let tags: Vec<(&str, Vec<u8>)> = vec![
        ("RunningTradeBatch (Tag 8)", trade_batch_wire.clone()),
        ("LivePrice (Tag 9)", liveprice_wire.clone()),
        ("OrderBookBody (Tag 6)", ob_body_wire.clone()),
        ("Orderbook Pipe (Tag 10)", ob_pipe_wire.clone()),
    ];

    for (name, wire_bytes) in tags {
        let mut latencies = Vec::with_capacity(5000);
        for _ in 0..5000 {
            let t0 = Instant::now();
            let decomp = decompress_baseline(&wire_bytes);
            let msg = WebsocketWrapMessageChannel::decode(decomp.as_slice()).unwrap();
            let _json = match msg.message_channel.unwrap() {
                websocket_wrap_message_channel::MessageChannel::RunningTradeBatch(b) => {
                    serde_json::json!({"trades_count": b.batch.len()}).to_string()
                }
                websocket_wrap_message_channel::MessageChannel::Liveprice(lp) => {
                    serde_json::json!({"price": lp.lastprice, "volume": lp.volume}).to_string()
                }
                websocket_wrap_message_channel::MessageChannel::OrderbookBody(ob) => {
                    serde_json::json!({"bids": ob.bid.len(), "offers": ob.offer.len()}).to_string()
                }
                websocket_wrap_message_channel::MessageChannel::Orderbook(ob) => {
                    let (bids, asks) = parse_pipe(&ob.body);
                    serde_json::json!({"bids": bids, "offers": asks}).to_string()
                }
                _ => String::new(),
            };
            latencies.push(t0.elapsed().as_secs_f64() * 1_000_000.0);
        }
        latencies.sort_by(|a, b| a.partial_cmp(b).unwrap());
        println!(
            "{:25} -> p50={:5.2}us, p95={:5.2}us, p99={:5.2}us, min={:5.2}us, max={:6.2}us",
            name,
            percentile(&latencies, 50.0),
            percentile(&latencies, 95.0),
            percentile(&latencies, 99.0),
            latencies[0],
            latencies[latencies.len() - 1]
        );
    }

    // 4. Contract Precision Verification
    println!("\n--- Stage 4: Contract Precision & Floating-Point Drift Verification ---");
    let decomp = decompress_baseline(&trade_batch_wire);
    let msg = WebsocketWrapMessageChannel::decode(decomp.as_slice()).unwrap();
    if let Some(websocket_wrap_message_channel::MessageChannel::RunningTradeBatch(b)) =
        msg.message_channel
    {
        let t = &b.batch[0];
        println!("Protobuf raw price: {}", t.price);
        println!("Protobuf raw volume: {}", t.volume);
        println!("Protobuf raw change: {:?}", t.change);
        assert_eq!(t.price, 7500.0);
        assert_eq!(t.volume, 100.0);
        println!("Schema contract check: PASS (zero drift detected)");
    }

    println!("\n=== Ingest-RS Benchmark Complete ===");
}
