# axiom-feed — Architecture & Design Decisions

> Guiding Principle: **Provider is contained, streams are streamed, bounds are explicit.**

---

## 1. Architectural Decisions

| Evidence / Challenge | Architecture Decision |
|---|---|
| Stockbit WebSocket `WebsocketRequest` overwrites entire channel subscription; wildcard `"*"` is only valid for `running_trade_batch` | `LiveFeedState.subscribe()` is idempotent, resends full state, and enforces that `*` is only accepted for trades while rejecting `*` for quotes/books with an explicit 400 Bad Request. |
| Legacy `#O|SYM|BID|...|OFFER|...` pipe format (Tag 10) coexists with pure protobuf `OrderBookBody` (Tag 6) | `providers/stockbit/mapping.py` decodes both wire representations into a single domain `Book` model; raw pipe formats never escape the mapping layer. |
| Multi-year historical candle requests previously held 60+ MB uncompressed JSON in memory | Historical candles use `httpx.stream` + date window slicing (365 days for daily, 90 days for minute bars) yielding `Candle` objects one-by-one via `StreamingResponse` NDJSON (`application/x-ndjson`). |
| Multi-cache fragmentation and cache bloat | Single bounded LRU cache (`infra/cache.py`) with a hard byte budget (50 MB) and tiered TTLs (daily candles 24h, minute candles 60s, quotes/books 30s). |
| Thread-per-connection scaling bottlenecks | High-speed Rust service (`ingest-rs`) runs a single Tokio task with zero-copy decoding; Python embedded fallback uses `websockets` directly. |
| JWT Bearer Token expiration | `auth.py` watches `cookies.json` `mtime` and monitors token `exp` timestamp. Proactively warns at `T-1h` and auto-refreshes via `GET /usergraph/socialinfo/user/me → GET /auth/websocket/key`. |

---

## 2. Services Breakdown

### `ingest-rs` (Rust Tokio Service)
Responsible for wire-speed WebSocket ingestion:
```
Stockbit WSS ──► Tokio-Tungstenite ──► flate2 (raw deflate -15) ──► prost::Message::decode ──► tokio::broadcast / Redis Streams
```
- **`feed.rs`**: Manages credentials (`user_id`, `ws_key`, `bearer`), sends keepalive pings every 25s, handles exponential backoff reconnects (5s to 60s with jitter), and maintains full subscription state.
- **`decode.rs`**: Fast protobuf message dispatching across tags (`running_trade_batch`, `running_trade`, `liveprice`, `orderbook_body`, `orderbook`).
- **`hub.rs`**: Broadcasts events to local subscribers (`tokio::sync::broadcast`) or publishes to Redis Streams (`XADD MAXLEN ~1000`).
- Resident memory: **~15 MB**.

### `api-py` (Python FastAPI Service)
Responsible for API routing, historical chunking, factor analytics, and client WebSocket dispatching:
- **`domain/models.py`**: Pure, immutable domain dataclasses (`Candle`, `Trade`, `Quote`, `Book`, `Level`) using `Decimal` for currency precision. **Zero protobuf or exchange dependencies.**
- **`providers/stockbit/`**: Stockbit integration boundary:
  - `auth.py`: Token monitoring and cookie-based rotation.
  - `transport.py`: Reused `httpx.AsyncClient` with connection pooling (`Limits(20)`), token bucket rate limiting (10 rps), `Semaphore(4)` concurrency limit, and exponential retry on 429/5xx status codes.
  - `mapping.py`: Bidirectional wire-to-domain decoding and swapped date parameter handling (`build_daily_params`, `build_intraday_params`).
  - `provider.py`: Implements `MarketDataProvider` protocol.
- **`infra/`**:
  - `cache.py`: 50 MB bounded cache with tiered eviction.
  - `bus.py`: In-memory async message `Hub` with `Queue(100)` per-client drop-oldest buffers and 500 max client connection guardrail.
- **`api/v1/`**: Modular endpoints with per-router security verification.

---

## 3. Memory & Concurrency Bounds

- **Trades Queue**: Circular buffer of 1,000 trades per symbol and 1,000 global trades in RAM.
- **Quotes & Books**: 200 symbol LRU cache limit.
- **Hub Message Bus**: Bounded `Queue(100)` per client; drops oldest events on slow consumers with `messages_dropped` metric tracking; rejects connections beyond 500 clients with HTTP `429 Too Many Requests`.
- **Historical Cache**: Maximum 100 keys and 50 MB total memory budget.
- **Rate Limiting**: 10 requests per second token bucket on upstream requests to prevent exchange throttling.
