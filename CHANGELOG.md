# Chronological Operational Log

Use this file to track engineering chronology, operational actions, and empirical verification over time. Keep entries short, factual, and operational. Most recent entries are listed first.

---

### 2026-09-05 WIB — followup-advisor-verdicts
- **Objective**: Close the four advisor follow-ups from the redis-only/SQLite/cache-aside refactor.
- **Context**: Verdicts accepted as given: (1) dashboard `tsc` gate was proven necessary by a real broken-commit incident (`35f2313` fixed 19 orphan braces); gate as full `vite build` since that's the shipped artifact. (2) TTL tuning deferred 1–2 weeks for real traffic; near-zero hit-rate in a tier means the key is never re-requested — drop caching for it, don't lengthen TTL. (3) No formal SQLite benchmark suite — log-only tripwire instead, build benches only if it fires. (4) Redis-only stands; no IPC fallback flag — Redis-HA belongs at infra level, not as bespoke app transport. Rollback safety: no persistent schema changed in this line (tick_store/SQLite untouched; Parquet removal deleted a read/export path, not data), so `git revert` is sufficient with no back-migration.
- **Changes**: CI gains `dashboard` job (`npm ci` + `tsc --noEmit` + `vite build`); `BoundedCache` tracks per-tier hits/misses surfaced in `/v1/health` `cache.upstream.tiers` (`hit_rate` per tier, `None` until first request); `SQLiteArchive.calculate_vwap` logs a warning past 500ms (`SQLite VWAP slow`); no benchmark suite, no IPC fallback.
- **Proof**: `pytest` 44/44, `ruff check` + `format --check` clean; dashboard `tsc --noEmit` clean + `vite build` succeeds locally.
- **State**: Operational.

---

### 2026-09-05 WIB — refactor-redis-only-ingest-sqlite-cache-aside
- **Objective**: Cut direct-IPC transport, replace DuckDB/Parquet with SQLite analytics, and put every upstream REST route behind one cache-aside layer.
- **Context**: Three ingest paths (embedded/redis/direct) with Rust always running both outputs; `DuckDBArchive` + Parquet export (~30MB dep) had no downstream consumer; only candles had cache/singleflight while ~35 upstream routes hit Stockbit unguarded; provider stacked a second semaphore over the transport gate.
- **Changes**: `ingest-rs` Redis-Streams-only (direct-IPC server + dead `publisher_task`/`subscribe()`/`decompress()` cut, XADD branches collapsed, `http`/`url`/`bytes` dropped); new `infra/upstream_cache.py` (`cached_json` + singleflight) wired into all 38 upstream REST routes with existing tiers + new `seasonality:86400`, `trades:running:10s` keys on `default:60s` pending hit-rate data; `archive.py` → `SQLiteArchive` one-query VWAP/flow; `TickStore` periodic prune (`TICKS_PRUNE_INTERVAL=300`) + WAL checkpoint on close; provider semaphore removed (transport is the single gate); `pytz`→`zoneinfo` (+`tzdata`); dashboard `apiFetch` replaces candidate fan-out, dead components/deps/proxies cut; `.env.example` stale vars removed.
- **Proof**: `pytest` 44/44, `cargo test` 7/7, `ruff check` + `format --check` + `cargo fmt --check` + `clippy -D warnings` green; live `bench/verify_live_upstream.py` 25/25 PASS; cache smoke 37/37 repeat-call hits; regex-vs-HTMLParser bench 5.5x confirms regex-first order.
- **State**: Operational.

---

### 2026-09-05 WIB — fix-auth-single-use-rotation
- **Objective**: Make silent refresh survive Stockbit's single-use refresh-token rotation across processes and login-script runs.
- **Context**: Stored refresh token 401'd despite 7-day JWT validity — bearer iat lagged refresh iat by 14 min, proving the stored token was already spent server-side (rotation retires on every use). Gaps: no adopt-before-spend, `_find_env_file` fallback pointed at `services/.env` (parents[4], should be parents[5]), transport retried with stale client headers when no lifespan callback wired.
- **Changes**: `refresh_tokens_via_stockbit` re-reads `.env` under lock and adopts newer file tokens before spending; fixed env fallback to repo root; `get_json`/`post_json` call `update_bearer` directly after on-demand refresh. Tests: 2 new cases (adopt-newer, hot-swap) in `tests/test_auth_rotation.py`.
- **Proof**: `pytest` 44/44, `ruff check` + `format --check` clean. Live proof 2026-09-05: fresh 7-day refresh token (168h) rotated twice in a row — new 24h bearer verified upstream (`user_id 579640`), rotated pair persisted to `.env`, second rotation with the new refresh token also minted a fresh bearer. Chain rotation works. (Redis publish warnings benign — no local Redis.)

---

### 2026-09-05 WIB — feat-upstream-route-expansion
- **Objective**: Expand upstream route coverage with 10 verified market-data endpoints, and fix silently-dropped filter params on existing broker endpoints.
- **Context**: `broker_summary`/`brokers_top`/`top-stocks`/`broker_activity` routers advertised filter params but the provider hardcoded NET/REGULER/ALL (axiom-mcp hard-rejects non-defaults because of this); `trade_book` sent legacy `GROUP_BY_PRICE` while upstream requires numeric `group_by`; `broker_distribution` always sent `date`+`period` together so explicit ranges were silently ignored.
- **Changes**: 10 new provider methods + 10 REST routes (market session, order queue, intraday price/brokers, index members, peer multiples, corpaction status/day, earnings recap, underwriter performance). Fixes: numeric `group_by="1"`, `period`-vs-`from`/`to` exclusivity on summary + distribution, full filter pass-through on all broker routes. `/earnings` vocabulary settled live (`sort_column` + `order` required, `filter` rejected). Docs: `docs/ENDPOINTS.md` §§23–25, README surface table. Tests: 5 new mocked cases in `tests/test_discovered_endpoints.py`.
- **Proof**: `pytest` 44/44, `ruff check` + `format --check` clean; live `scripts/verify_new_endpoints.py` 15/15 OK after fresh login 2026-09-05.
- **State**: Operational.

### 2026-09-04 22:40 WIB — perf-event-loop-offload-duckdb-attach-batch-fanout
- **Objective**: Eliminate event-loop stalls from SQLite/DuckDB and cut fan-out cost under 500-client load.
- **Context**: `TickStore.executemany` flushes ran synchronously on ingest callers (p50 216 µs, p95 319 µs per 50-row flush); `DuckDBArchive` paid `duckdb.connect(":memory:")` (~16 ms) per VWAP/flow/archive call plus full `sqlite_scan` re-parse (~92 ms on 2k rows); analytics routes ran synchronously so one VWAP stalled all 100 fan-out clients for ~90 ms; `Hub.publish` looped N×C for trade batches.
- **Changes**: `TickStore` now drains via a dedicated daemon writer thread (`TICKS_FLUSH_INTERVAL="0.2"`, separate `_lock`/`_db_lock`, blocking `flush()` on reads, join on `close()`); `DuckDBArchive` reuses one connection with read-only SQLite `ATTACH` under `RLock` and bound parameters (no f-string symbols); analytics routes run via `asyncio.to_thread`; `Hub.publish_batch()` added (single client pass, bulk newest-window eviction) and embedded `running_trade_batch` uses it; Rust `direct_ipc_server_task` coalesces ≤64 events per TCP write with 2 ms max flush delay. New env `TICKS_FLUSH_INTERVAL` documented in `.env.example`, `README.md`, `docs/ARCHITECTURE.md`.
- **Proof**: `cargo test` 9/9, `pytest` 37/37, `ruff check`/`format --check`/`pyright`/`cargo fmt --check`/`clippy -D warnings` green; `verify_contract.py` 18/18 PASS; `verify_all_endpoints.py` 36/36 PASS; `verify_live_upstream.py` 25/25 PASS. Warm VWAP (2k rows) 92.5 ms → 15.9 ms; batch fan-out per-event 500-client 201.7 µs → 156.0 µs (thr 5.0k → 6.4k ev/s); insert storm 2000 trades 4.8 ms wall with loop free; comprehensive_bench 500-client p50 272.9 µs → 157.1 µs, p99 501.3 µs → 214.2 µs, drops exact 75,000.
- **State**: Operational.

---

### 2026-09-04 07:58 WIB — perf-api-parallel-windowing-ndjson-streaming (8a03624)
- **Objective**: Eliminate sequential multi-year historical candle query bottlenecks and reduce memory allocations during NDJSON streaming.
- **Context**: Daily historical queries spanning >365d sequentially iterated over annual slices, accumulating network latency ($O(N \times \text{RTT})$). `_produce()` in `candles.py` built an intermediate list of heap `bytes` objects, while `financial_parser.py` allocated intermediate substring lists using `re.findall`.
- **Changes**: Re-architected daily candle multi-year windowing in `StockbitProvider` to fetch slices concurrently using `asyncio.gather` bounded by `Semaphore(CONCURRENCY)`. Replaced chunk list allocation in `candles.py` with continuous in-place `bytearray`. Replaced `findall` with streaming `finditer` in `financial_parser.py`. Documented Section 22 in `docs/ENDPOINTS.md`.
- **Proof**: `pytest` passed 37/37 in 5.33s; `comprehensive_bench.py` daily candle MISS peak allocation dropped to 598.3 KB (down from 634.2 KB); Cache HIT dropped to 6.29 ms; live upstream BBCA daily candle streaming returned 200 OK.
- **State**: Operational.

---

### 2026-09-04 07:57 WIB — feat-analytics-duckdb-parquet-archival (37426b7)
- **Objective**: Introduce institutional columnar time-series storage and sub-millisecond vectorized analytics for trade executions without SQLite lock contention.
- **Context**: `TickStore` synchronous SQLite writes blocked the asyncio event loop under high-throughput tape bursts. Trades pruned beyond `TICKS_MAX_RECORDS` (50,000) were permanently lost, preventing multi-week quant backtesting and volume analytics.
- **Changes**: Integrated embedded `DuckDBArchive` in `app/infra/archive.py` with ZSTD-compressed Parquet date partitioning (`POST /v1/analytics/archive`). Mounted `app/api/v1/analytics.py` exposing `/v1/analytics/vwap/{symbol}` and `/v1/analytics/flow/{symbol}`. Added non-blocking write-behind batching (`TICKS_BATCH_SIZE="50"`) in `TickStore` with atomic pre-query flushes.
- **Proof**: `pytest` passed unit test `test_duckdb_parquet_archival_and_vwap` with exact volume weighting (VWAP 7512.50 on 400 lots, 75% buy volume). Live verification confirmed 200 OK for `/v1/analytics/vwap/BBCA`, `/v1/analytics/flow/BBCA`, and Parquet partition creation at `data/parquet/date=2026-09-04/trades.parquet`.
- **State**: Operational.

---

### 2026-09-04 07:57 WIB — feat-transport-direct-streaming-ipc (acc62db)
- **Objective**: Provide a direct, zero-Redis local IPC transport between `ingest-rs` and `api-py` for single-node development, testing, and edge deployments.
- **Context**: Running in `INGEST_MODE=redis` required an active Redis container or daemon, while `INGEST_MODE=embedded` bypassed Rust's 10 µs wire-speed parser to run a pure-Python WebSocket client.
- **Changes**: Implemented `direct_ipc_consumer_task` in `app/infra/bus.py` connecting via local streaming TCP socket (`DIRECT_IPC_PORT="8379"`). Added `INGEST_MODE=direct` handling in `app/main.py` and updated readiness probe logic in `app/api/v1/health.py`. Added pre-serialized `_json_text` caching and fast-path `q.full()` drop eviction in `Hub.publish`.
- **Proof**: `comprehensive_bench.py` measured 100-client fanout latency drop to 43.20 µs (down from 60.20 µs) and 500-client latency to 159.00 µs (down from 239.50 µs) while maintaining exact 75,000 drop accounting under 250-burst overload.
- **State**: Operational.

---

### 2026-09-04 07:57 WIB — perf-ingest-rs-scratch-buffer-l2-diffing (236b4e7)
- **Objective**: Eliminate heap allocation tail latency spikes during flate2 decompression and reduce redundant Level 2 order book network egress.
- **Context**: Baseline micro-benchmarks revealed decompression p95/p99 tail latency spikes (59.5 µs to 83.8 µs, max 404 µs) due to per-frame vector reallocations inside `read_to_end`. Resending full 10x10 order book depth ladders on every tick caused high egress bandwidth.
- **Changes**: Introduced `thread_local!` `DECODE_SCRATCH` with `decompress_into` in `decode.rs`, maintaining vector capacity across incoming frames. Implemented direct borrowed struct serialization (`NormalizedEvent::to_json_string`) eliminating intermediate `serde_json::Value` AST maps. Added stateful `DEPTH_TRACKER` to omit unchanged book sides during partial updates while resyncing full snapshots every 20 ticks. Built `direct_ipc_server_task` in `hub.rs`.
- **Proof**: `cargo run --release --bin bench_suite` demonstrated raw deflate p95 latency drop of 81.7% (11.4 µs vs 62.2 µs baseline), max spike drop of 92.3% (102 µs vs 1,328 µs), and 10k ev/s pipeline throughput jump from 5,516 ev/s to 9,707 ev/s.
- **State**: Operational.

---

### 2026-09-04 00:50 WIB — feat-api-market-intelligence-expansion (20b799d)
- **Objective**: Expose complete institutional market data surface across analyst estimates, insider filings, guru screeners, and broadcast research notes.
- **Context**: Discovered upstream Stockbit endpoints for consensus estimates, corporate actions, regulatory insider movements (>=5%), and research morning briefings were unmapped in the API surface.
- **Changes**: Created dedicated routers: `estimates.py` (consensus, price ratings), `insider.py` (major holder filings, composition, token-authenticated trend charts), `screeners.py` (presets, template execution), `research.py` (broadcast morning notes from Room 338965, analyst reports), and `news.py` (ticker-level news streams). Implemented DCF/Graham valuation model in `fundamentals.py`. Added CDP discovery script `scripts/explore_endpoints.py`.
- **Proof**: Added `tests/test_discovered_endpoints.py` with 17 new tests; `bench/verify_all_endpoints.py` verified 36/36 endpoints passing 200 OK.
- **State**: Operational.

---

### 2026-09-04 00:49 WIB — perf-infra-embedded-tick-store-html-parser (468845b)
- **Objective**: Enable offline trade tape replay outside market hours and accelerate financial statement parsing.
- **Context**: Upstream Stockbit WebSocket only streams ticks during IDX trading hours (Mon–Fri 09:00–16:15 WIB), leaving in-memory buffers empty on restarts or weekends. Financial statement HTML table parsing via standard `HTMLParser` callbacks took ~4.14 ms per statement.
- **Changes**: Introduced embedded SQLite WAL time-series store (`app/infra/tick_store.py`) retaining up to 50k trade execution ticks with automatic startup pre-seeding into in-memory deques. Replaced `HTMLParser` with compiled regex tokenizer in `financial_parser.py` (10.2x speedup to 0.40 ms). Added saturating buffer pre-allocation to Rust pipe-format L2 parsing.
- **Proof**: `pytest` passed `tests/test_optimizations.py` lifecycle tests (insert, query, prune, reopen persistence); benchmark suite verified 10.2x HTML parser acceleration.
- **State**: Operational.

---

### 2026-09-03 20:47 WIB — feat-auth-7day-silent-rotation-env-reload (3d343c1)
- **Objective**: Automate 24-hour Bearer JWT rotation and prevent operational outages from expired credentials.
- **Context**: Stockbit Bearer tokens expire after 24 hours (`iat` to `exp` delta = 86,400s), breaking feeds unless manually refreshed. Refresh tokens last 7 days.
- **Changes**: Implemented `AuthManager` silent token rotation calling Stockbit `POST /login/refresh`. Added automatic `.env` file and `cookies.json` `st_mtime` hot-reloading with T-1h proactive refresh before expiration. Created interactive login helper `scripts/stockbit_login.py`. Added retry-on-401 handling to `HttpxTransport`.
- **Proof**: `tests/test_auth_rotation.py` passed 7/7 tests verifying token exchange, file writing, mtime debounce, and expired vs. healthy token math.
- **State**: Operational.

---

### 2026-09-03 14:36 WIB — feat-dashboard-live-terminal-ui (31f6cbe & 8651290)
- **Objective**: Upgrade React terminal dashboard to display live WebSocket streaming ticks, L2 order books, and institutional broker flows without mock data.
- **Context**: Web frontend lacked dynamic API-key entry, dropped depth updates on partial bids/offers, and filtered batch trades before slicing.
- **Changes**: Added persisted header API-key editor. Upgraded `OrderbookView` to support partial bid/ask depth merging over WebSocket. Upgraded `BrokersView` to query custom date ranges. Fixed `trades.py` batch filtering logic. Enabled book publishing in embedded ingest mode.
- **Proof**: Manual and automated end-to-end testing across all frontend views (`OrderbookView`, `StreamView`, `BrokersView`, `FundamentalsView`) against backend API.
- **State**: Operational.

---

### 2026-09-03 14:01 WIB — feat-proto-wire-sync-liveprice (446090a & a3df717)
- **Objective**: Synchronize protobuf schema against live wire capture and optimize core streaming concurrency.
- **Context**: Wire capture of BBCA/TLKM/GOTO/IHSG revealed undocumented trailing protobuf fields in `LivePrice` (23 board flag, 26 match time, 28 lot volume). Server rejected subscriptions with 401 when `access_token` was omitted.
- **Changes**: Updated `shared/proto/datafeed.proto` declaring tags 23, 26, 28 and reserving 24, 25, 27. Re-generated Python protobuf bindings. Implemented `Singleflight` deduplication in Python. Added header-sniff decompression in `decode.rs`. Added exact-once drop accounting in `Hub`.
- **Proof**: `cargo test` 9/9 pass; `pytest` 20/20 pass; wire contract verification 18/18 pass.
- **State**: Operational.

---

### 2026-09-03 00:37 WIB — perf-raw-deflate-redis-pipeline (1b1db81)
- **Objective**: Optimize raw deflate decompression, pipeline Redis stream commands, and implement true NDJSON chunk streaming.
- **Context**: Deflate streams required raw `-15` window bits rather than standard zlib wrappers. Redis `XADD` commands executed unbatched, bottlenecking ingestion.
- **Changes**: Tuned `flate2` decompression heuristics. Added pipelined `XADD` batches (up to 64 items) in `ingest-rs` `hub.rs`. Added `stream_json_array` state machine in `transport.py` for continuous NDJSON streaming.
- **Proof**: Created `services/ingest-rs/src/bin/bench_suite.rs` profiling deflate decompression at ~5 µs p50 and 10k ev/s throughput.
- **State**: Operational.

---

### 2026-09-02 21:58 WIB — perf-singleflight-stream-isolation (2389cc1 & ffe062e)
- **Objective**: Isolate provider boundaries, eliminate full-response JSON buffering, and enforce Ruff formatting.
- **Context**: Upstream responses were loaded as monolithic 60MB dictionaries into memory. Ruff formatting checks failed in CI.
- **Changes**: Isolated `providers/stockbit/` boundary from domain models. Introduced `Singleflight` request deduplication. Formatted codebase with Ruff.
- **Proof**: Python CI green; `test_regression.py` passed concurrent request deduplication.
- **State**: Operational.

---

### 2026-09-02 20:38 WIB — feat-initial-release-axiom-feed (ecc27d8)
- **Objective**: Initial release of standalone hybrid Rust + FastAPI market data gateway for the Indonesia Stock Exchange (IDX).
- **Context**: Initial commit establishing hybrid architecture, `prost` + Tokio ingest engine, domain decimal models, REST routers, React dashboard, Docker Compose orchestration, and canonical `shared/proto/datafeed.proto`.
- **Proof**: Initial baseline test suite and Docker build verified.
- **State**: Operational foundation established.
