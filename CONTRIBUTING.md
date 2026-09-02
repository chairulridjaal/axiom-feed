# Contributing to axiom-feed

Thank you for contributing! `axiom-feed` is designed to be **bounded, streamed, and provider-isolated**.

The golden rule is in `docs/ARCHITECTURE.md`: *Provider is contained, streams are streamed, bounds are explicit.*

---

## Quick Start

### 1. Environment Setup

```bash
cp .env.example .env
# Edit STOCKBIT_BEARER_TOKEN="eyJ..."  (DevTools → exodus.stockbit.com → Authorization: Bearer)
# Optional: set STOCKBIT_COOKIES_PATH=./cookies.json (JSON array export)
```

### 2. Development Commands

**Full Stack (Docker Compose):**
```bash
make up        # docker compose up --build
make down      # docker compose down -v
make logs      # docker compose logs -f --tail=200
```

**Python Backend (`api-py`):**
```bash
cd services/api-py
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

**Rust Ingest (`ingest-rs`):**
```bash
cd services/ingest-rs
cargo run --release
```

**Interactive Dashboard (`dashboard`):**
```bash
cd dashboard
npm install
npm run dev
# Open http://localhost:5174 in browser
```

---

## Project Structure

- `services/api-py/app/domain/` — Pure domain dataclasses (`Candle, Trade, Quote, Book, Level`). Never imports protobuf or exchange credentials.
- `services/api-py/app/providers/stockbit/` — The only place Stockbit-specific logic lives:
  - `auth.py`: Token monitoring and cookie-based key rotation.
  - `transport.py`: Reused `httpx.AsyncClient` with connection pooling, token bucket (10 rps), and retry logic.
  - `mapping.py`: Bidirectional wire decoding and date-swapping.
  - `provider.py`: Streamed chunked historical candle fetching.
- `services/api-py/app/infra/` — `BoundedCache` (50 MB LRU) and async message `Hub` (`Queue(100)` drop-oldest).
- `services/api-py/app/api/v1/` — Modular FastAPI routers with per-router security verification.
- `services/ingest-rs/src/` — Rust Tokio WebSocket ingestion service (`decode.rs`, `feed.rs`, `hub.rs`).
- `shared/proto/datafeed.proto` — Canonical wire protobuf schema.
- `dashboard/` — Interactive React + Vite market exploration interface.

---

## Core Engineering Rules

1. **Stream, Never Buffer Large Ranges**: Historical candles must use `httpx.stream` with date-slicing (365d daily, 90d minute) yielding line-by-line via NDJSON (`StreamingResponse`).
2. **Strict Bounds on Everything**: Bounded LRU cache (50 MB), bounded client message queues (`Queue(100)`), and maximum client limits (500 connections).
3. **Provider Isolation**: All exchange-specific data parsing stays in `app/providers/<name>/`. Domain models remain provider-agnostic.
4. **Zero Mock / Fake Data**: All dashboard views and endpoints must render authentic exchange data or clear loading/closed states.

---

## Code Quality & Test Verification

Before submitting a Pull Request, ensure all linters and tests pass:

```bash
# Python
cd services/api-py
uv run ruff check --fix .
uv run ruff format .
uv run pyright
uv run pytest -q

# Rust
cd services/ingest-rs
cargo fmt --check
cargo clippy -- -D warnings
cargo test

# Dashboard
cd dashboard
npm run build
```

---

## Pull Request Checklist

- [ ] All Python tests (`pytest`) and Rust tests (`cargo test`) pass.
- [ ] Linters (`ruff`, `pyright`, `cargo clippy`) report **0 errors**.
- [ ] Dashboard builds cleanly (`npm run build`).
- [ ] No secrets, Bearer tokens, or `.env` files are staged or committed.
- [ ] Documentation in `docs/ENDPOINTS.md` or `docs/ARCHITECTURE.md` is updated if endpoints or boundaries changed.
