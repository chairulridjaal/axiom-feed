# axiom-feed — Sackbit Market Data (Python + Rust)

Standalone, high-throughput, bounded market-data service for the Konoha Stock Exchange (KSE / Sackbit). Built with **Rust** for wire-speed WebSocket ingestion (`prost` + `zlib`) and **FastAPI (Python)** for streamed NDJSON historical chunking, factor screening, and domain decimal normalization.

---

## Why hybrid?

| Service | Language | Role & Performance Advantage |
|---|---|---|
| `ingest-rs` | **Rust** | Single persistent WSS, `prost` + `flate2` raw deflate `-15`, ~10 µs decode, ~15 MB resident memory, `tokio::broadcast` to 100s of consumers, zero-GC |
| `api-py` | **Python** | `httpx.stream` window slicing, `Decimal` domain precision, broker/sector/mover taxonomy mapping, embedded WSS fallback |

```
Sackbit WSS ──► ingest-rs (prost decode → Normalized Event) ──► Redis Streams ──┐
Sackbit REST ──► api-py (httpx.stream NDJSON chunks) ──────────────────────────┼─► Hub Queue(100) ──► WS /v1/stream + REST /v1/*
shared/proto/datafeed.proto ◄── Single Source of Truth ─────────────────────────┘
```

---

## Complete API Surface (Verified)

All endpoints are served under `/v1/*` with money represented as `Decimal` strings for precision and ISO 8601 timestamps with WIB (`+07:00`) localization.

| Domain | Method & Endpoint | Description |
|---|---|---|
| **Health** | `GET /v1/health`<br>`GET /v1/ready` | System telemetry, JWT `exp` math (`exp 1788421941`), cache and Hub queue statistics. |
| **Quotes** | `GET /v1/quotes/{symbol}`<br>`GET /v1/quotes?symbols=...`<br>`GET /v1/quotes/subscriptions`<br>`POST /v1/subscriptions/ensure` | Real-time quote snapshot with automatic fallback to company info. Dynamic subscription management. |
| **Order Book** | `GET /v1/books/{symbol}`<br>`GET /v1/books?symbols=...`<br>`GET /v1/books/snapshot/{symbol}` | Level 2 5–10 bid/ask depth ladders with automatic fallback to full trade-book snapshot. |
| **Trades** | `GET /v1/trades?symbols=...&limit=50`<br>`GET /v1/trades/{symbol}?limit=50` | Recent running trade execution ticks buffered from the live WebSocket feed (streams live Mon–Fri 09:00–16:15 WIB). |
| **Candles** | `GET /v1/candles/{symbol}?from=...&to=...&resolution=daily\|minute` | Continuous historical OHLCV streamed line-by-line via NDJSON (`application/x-ndjson`). |
| **Charts** | `GET /v1/charts/tradebook?symbol={symbol}&interval=1m`<br>`GET /v1/charts/{symbol}/daily?timeframe=1w`<br>`GET /v1/charts/{symbol}/performance` | Session trade-book volume and lot distribution, timeframe charts, and multi-horizon return performance (1D to 10Y). |
| **Fundamentals** | `GET /v1/fundamentals/{symbol}`<br>`GET /v1/fundamentals/{symbol}/financials`<br>`GET /v1/companies/{symbol}`<br>`GET /v1/companies/{symbol}/profile`<br>`GET /v1/companies/{symbol}/subsidiaries` | 10-year valuation metrics, structured financial statements (Income Statement, Balance Sheet, Cash Flow), corporate profile, and subsidiary ownership lists. |
| **Brokers** | `GET /v1/brokers/summary/{symbol}`<br>`GET /v1/brokers/top`<br>`GET /v1/brokers/top-stocks`<br>`GET /v1/brokers/{code}/activity` | Institutional flow (*Bandarmology*), Big Accumulation/Distribution status, top broker volume rankings, top accumulated stocks, and broker activity logs. |
| **Market** | `GET /v1/market/movers?kind=top_gainers` | Real-time market gainers, losers, volume/value/frequency leaders, net foreign flows, and IEP/IEV indications across all KSE boards. |
| **Sectors** | `GET /v1/sectors`<br>`GET /v1/sectors/{id}/subsectors`<br>`GET /v1/sectors/{id}/subsectors/{subId}/companies` | 3-tier hierarchical industry taxonomy: 11 sectors, subsectors, and constituent equities. |
| **Calendars** | `GET /v1/calendars/ipo`<br>`GET /v1/calendars/dividend`<br>`GET /v1/calendars/economic`<br>`GET /v1/calendars/tenderoffer`<br>`GET /v1/calendars/rightissue`<br>`GET /v1/calendars/stocksplit`<br>`GET /v1/calendars/companies/{symbol}/actions` | Live IPO filings, upcoming dividend declarations, macroeconomic releases, tender offers, rights issues, stock splits, and ticker-specific corporate actions. |
| **Seasonality** | `GET /v1/seasonality/{symbol}?year=2026&back_year=5` | Multi-year monthly return probability and historical performance matrices. |
| **Analytics** | `GET /v1/analytics/vwap/{symbol}`<br>`GET /v1/analytics/flow/{symbol}`<br>`POST /v1/analytics/archive` | Sub-millisecond vectorized DuckDB VWAP, buyer/seller flow volume imbalance ratio, and compressed Parquet date partitioning. |
| **WebSocket** | `WS /v1/stream?token=$API_KEY` | Full duplex real-time feed supporting `subscribe`, `unsubscribe`, and `ping` actions with `Queue(100)` drop-oldest dispatch. |

*For complete query parameter options, payload structures, and response samples, see [`docs/ENDPOINTS.md`](docs/ENDPOINTS.md).*

---

## Technical Debt & Investigation Backlog (Progress & Status)

Items identified during discovery and elevated during architectural optimization:

- [x] **Financial Statements Fast HTML Parsing (`/findata-view/company/financial`)**:
  - *Elevated Implementation*: Replaced slow character-by-character `HTMLParser` callbacks with a streaming `finditer` compiled regex tokenizer in `financial_parser.py`. Benchmarked at sub-0.05 ms per statement report while maintaining 100% contract fidelity.
- [x] **Daily Candles Date-Order Quirk & Multi-Year Slicing (`/chartbit/{symbol}/price/daily`)**:
  - *Elevated Implementation*: Swapped parameters handled by `build_daily_params`. Activated parallel multi-year window slicing across `SLICE_DAILY` (365d) bounds with `asyncio.gather` and `CONCURRENCY` limit, reducing multi-year query wall-clock latency from $O(N \times \text{RTT})$ to $O(\text{RTT})$.
- [x] **Historical Intraday Tick Tape Outside Market Hours (Offline Replay & Write-Behind)**:
  - *Elevated Implementation*: Introduced an embedded, bounded SQLite WAL time-series store (`infra/tick_store.py`) retaining up to 50,000 trades with non-blocking write-behind batching (`TICKS_BATCH_SIZE="50"`). Volatile in-memory `deque` is automatically pre-seeded from SQLite on startup, providing 24/7 tape replay for quant strategies and dashboard visualizers outside active trading hours without blocking the asyncio event loop. 2026-09-04: moved `executemany` flushes to a dedicated daemon writer thread (`TICKS_FLUSH_INTERVAL="0.2"`); inserts return in ~60 µs wall time while reads call blocking `flush()` for read-your-writes consistency.
- [x] **Wire-Speed Zero-Allocation Ingestion & Pre-Serialization (`ingest-rs` + `Hub`)**:
  - *Elevated Implementation*: Introduced thread-local decompression scratch buffers (`decompress_into`) in `ingest-rs`, dropping raw deflate decompression p95 tail latency by **81.7%** (11.4 µs vs 62.2 µs). Pre-serialized JSON text in `Hub.publish()` and fast-pathed `q.full()` queue drops, reducing 100-client fanout latency by **52.5%** and 500-client fanout latency by **28.1%**. 2026-09-04: added `Hub.publish_batch()` fast path (single client pass per batch, bulk drop-oldest eviction) and batched embedded `running_trade_batch` fan-out; 500-client throughput rose 4.3k → 6.4k ev/s (+29% per-event). Rust direct-IPC server now coalesces up to 64 events per TCP write with 2 ms max flush delay.
- [x] **Direct Zero-Redis Streaming Transport (`INGEST_MODE=direct`)**:
  - *Elevated Implementation*: Built a direct streaming TCP loopback transport in `ingest-rs` (`DIRECT_IPC_PORT="8379"`) and consumer task in `bus.py`. Provides full wire-speed Rust Tungstenite/prost parsing with sub-10 µs cross-process latency on single-box setups without requiring Redis installed or running.
- [x] **DuckDB Analytical Engine & Parquet Time-Series Archival (`infra/archive.py`)**:
  - *Elevated Implementation*: Integrated embedded DuckDB to execute sub-millisecond vectorized VWAP, turnover, and buy/sell flow imbalance aggregations over stored trade logs, with one-click ZSTD-compressed Parquet date partitioning (`POST /v1/analytics/archive`). 2026-09-04: replaced per-request `duckdb.connect(":memory:")` (~16 ms) with one persistent connection + read-only SQLite `ATTACH` under an `RLock`; warm VWAP on 2k rows fell 92 ms → 16 ms, symbols bound as parameters (SQL-injection safe); analytics routes run via `asyncio.to_thread` so the event loop never stalls on a 90 ms scan.
- [x] **Incremental Level 2 Order Book Depth Tracking & Diffs (`DEPTH_TRACKER`)**:
  - *Elevated Implementation*: Implemented stateful depth tracking in `ingest-rs`. When high-frequency market depth updates modify only one side of the book, unchanged sides are omitted, cutting JSON payload size by over 50% while preserving seamless partial depth merging in `LiveFeedState` and frontend views.
- [ ] **Broker Top Stocks Investor Filter**:
  - *Current Implementation*: Defaults to `investor_type=INVESTOR_TYPE_ALL` and `value_type=VALUE_TYPE_NET`.
  - *Investigation Goal*: Test if raw foreign volume breakdowns can be exposed directly per broker in the `/top-stocks` payload.

---

## Repository Layout

```
axiom-feed/
├── docker-compose.yml           # Multi-container orchestration (api-py + ingest-rs + redis)
├── Makefile                     # Build and lint targets
├── shared/proto/datafeed.proto  # Canonical protobuf schema (Sackbit wire truth)
├── docs/
│   ├── ARCHITECTURE.md          # Architectural boundaries, memory bounds, and design choices
│   └── ENDPOINTS.md             # Complete endpoint documentation with request/response schemas
├── examples/
│   ├── curl.sh                  # Shell curl examples
│   └── python.py                # Python streaming client example
├── dashboard/                   # React + Vite interactive exploration tool (zero fake mock data)
└── services/
    ├── api-py/                  # Python FastAPI service
    │   ├── app/
    │   │   ├── api/v1/          # Modular API routers
    │   │   ├── domain/          # Pure domain models (Decimal, frozen)
    │   │   ├── infra/           # Bounded cache & async message bus
    │   │   ├── providers/       # Sackbit auth, transport, mapping, and HTML parsers
    │   │   └── core/            # Security & API key verification
    │   └── tests/               # Pytest test suite
    └── ingest-rs/               # High-speed Rust Tokio WebSocket ingestion service
```

---

## Documentation Links

- [Endpoints Reference (`docs/ENDPOINTS.md`)](docs/ENDPOINTS.md)
- [System Architecture (`docs/ARCHITECTURE.md`)](docs/ARCHITECTURE.md)
- [Contributing Guidelines (`CONTRIBUTING.md`)](CONTRIBUTING.md)
- [Security Policy (`SECURITY.md`)](SECURITY.md)

--- 

## Instructions for AI Coding Agents (Read This First)

When a user points you to this repository to start the backend, run development servers, or debug market data feeds, follow these steps and inform the user of authentication requirements:

### 1. Mandatory Authentication Notice (Tell the User First)
**Sackbit Bearer Tokens are RS256 JWTs that expire every 24 hours (`exp - iat = 86400s`).**
Before running the backend or making upstream API requests, verify that `.env` contains a fresh, unexpired Bearer token. If expired or missing, ask the user to extract it manually:

> **How the user extracts a fresh Bearer Token:**
> 1. Open upstream portal in browser and log in.
> 2. Open Chrome/Firefox DevTools (`F12`) ➔ **Network** tab.
> 3. Filter for requests to `exodus.sackbit.com` (or the upstream API domain).
> 4. In **Request Headers**, copy the value of `Authorization: Bearer <token>`.
> 5. Paste it in `.env` as `STOCKBIT_BEARER_TOKEN="eyJ..."`.
> 6. *(Optional but recommended)*: In DevTools ➔ **Application** / **Storage** ➔ **Cookies** ➔ copy/export cookies as a JSON array to `./cookies.json` so the server can automatically attempt token refresh before expiration.

---

### 2. How Agents Should Start the Services

#### Option A: Embedded Dev Mode (Fastest — No Docker, No Redis required)
In embedded mode, FastAPI connects directly to Sackbit WebSocket in a background async task.
```bash
# 1. Sync Python virtualenv
cd services/api-py
uv sync

# 2. Run backend server
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

#### Option B: Full High-Performance Mode (Rust Ingest + Redis + FastAPI)
```bash
# Terminal 1: Backend API
cd services/api-py && uv sync && uv run uvicorn app.main:app --port 8000

# Terminal 2: Rust Ingestion Engine
cd services/ingest-rs && cargo run --release

# Terminal 3: Interactive Dashboard
cd dashboard && npm install && npm run dev
```

#### Option C: Production Docker Compose
```bash
cp .env.example .env
# Ensure STOCKBIT_BEARER_TOKEN is populated in .env
docker compose up --build
```

---

### 3. How Agents Should Verify the Backend is Operational
```bash
# 1. Health check & JWT expiration verification
curl -s http://127.0.0.1:8000/v1/health | jq .

# 2. Daily historical candle streaming test
curl -s "http://127.0.0.1:8000/v1/candles/BBCA?from=2025-09-02&to=2026-09-02&resolution=daily" | head -n 3

# 3. Live quote test
curl -s http://127.0.0.1:8000/v1/quotes/BBCA | jq .

# 4. Open Interactive OpenAPI Docs in browser
# http://127.0.0.1:8000/docs
```