# axiom-feed — Comprehensive API Endpoints Specification

Complete reference documentation for all endpoints provided by `axiom-feed`.

---

## 1. Authentication & Global Conventions

- **Base URL**: `http://localhost:8000` (default)
- **API Version Prefix**: `/v1`
- **Timezone**: All timestamps are formatted in ISO 8601 with Asia/Jakarta (WIB, `UTC+07:00`).
- **Monetary & Decimal Precision**: Prices, valuations, changes, and ratios are serialized as JSON strings or raw decimal numbers to prevent floating-point rounding errors in algorithmic and quant execution pipelines.
- **Authentication**:
  - Unauthenticated in local development mode (`API_KEY=""`).
  - Production deployments with `API_KEY` require the `X-API-Key: <token>` header for REST calls and `?token=<token>` query parameter for WebSocket connections.

---

## 2. Health & System Telemetry

---

### `GET /v1/health`
Monitors real-time service health, uptime, upstream Stockbit WebSocket connection status, JWT Bearer token validity, and memory usage.

#### Parameters
*None*

#### Example Request
```bash
curl -s http://localhost:8000/v1/health | jq .
```

#### Example Response (`200 OK`)
```json
{
  "status": "healthy",
  "uptime_seconds": 1845.21,
  "websocket_connected": true,
  "entitlement_active": true,
  "hub": {
    "clients": 1,
    "max_clients": 500,
    "queue_size": 100,
    "messages_dropped": 0,
    "published": 248910
  },
  "cache": {
    "keys": 18,
    "bytes": 15820400,
    "max_keys": 100,
    "max_bytes": 52428800,
    "hits": 1420,
    "misses": 34,
    "evictions": 0
  },
  "ingest": "embedded",
  "auth": {
    "bearer_set": true,
    "is_expired": false,
    "ttl_seconds": 84210,
    "user_id": "579640"
  }
}
```

---

### `GET /v1/ready`
Kubernetes and container readiness probe to verify system components.

#### Example Request
```bash
curl -s http://localhost:8000/v1/ready | jq .
```

#### Example Response (`200 OK`)
```json
{
  "ready": true,
  "ws_ok": true,
  "redis_ok": true,
  "auth": {
    "bearer_set": true,
    "exp": 1788421941,
    "is_expired": false
  }
}
```

---

## 3. Quotes & Price Action

---

### `GET /v1/quotes/{symbol}`
Returns real-time price quotation for an equity ticker or market index (`IHSG`). Falls back to Stockbit company master if live cache is unpopulated.

#### Parameters
| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | Stock ticker (e.g. `BBCA`, `TLKM`) or `IHSG` |

#### Example Request
```bash
curl -s http://localhost:8000/v1/quotes/BBCA | jq .
```

#### Example Response (`200 OK`)
```json
{
  "symbol": "BBCA",
  "quote": {
    "last": "6675",
    "open": "6450",
    "high": "6725",
    "low": "6600",
    "prev_close": "6600",
    "change": "+75.00",
    "change_pct": "+1.14%",
    "volume": 108537400,
    "value": "723116960000",
    "freq": 25753,
    "avg": "6661.28",
    "ts": "2026-09-02T16:15:00+07:00",
    "is_index": false
  }
}
```

---

### `GET /v1/quotes?symbols={s1,s2,...}`
Batch query to fetch quotes for multiple tickers in a single HTTP request.

#### Parameters
| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `symbols` | Query | `string` | **Yes** | Comma-separated list of symbols (e.g. `BBCA,TLKM,BBRI`) |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/quotes?symbols=BBCA,TLKM" | jq .
```

#### Example Response (`200 OK`)
```json
{
  "symbols": "BBCA,TLKM",
  "quotes": {
    "BBCA": { "last": "6675", "ts": "02 Sep 2026" },
    "TLKM": { "last": "2590", "ts": "02 Sep 2026" }
  }
}
```

---

### `GET /v1/quotes/subscriptions`
Returns the active subscription list of explicit symbols registered for live price updates.

#### Example Request
```bash
curl -s http://localhost:8000/v1/quotes/subscriptions | jq .
```

#### Example Response (`200 OK`)
```json
{
  "subscribed": ["BBCA", "TLKM", "IHSG", "BBRI", "BMRI"]
}
```

---

### `POST /v1/subscriptions/ensure`
Dynamically registers additional symbols for streaming price and orderbook feeds without restarting the backend service.

#### Request Body (`application/json`)
```json
{
  "symbols": ["ASII", "GOTO"]
}
```

#### Example Response (`200 OK`)
```json
{
  "status": "ok",
  "subscribed": ["BBCA", "TLKM", "IHSG", "BBRI", "BMRI", "ASII", "GOTO"]
}
```

---

## 4. Order Book & Depth Ladders

---

### `GET /v1/books/{symbol}`
Returns the Level 2 top 5–10 bid/ask depth ladder. Outside market hours, automatically retrieves the end-of-day order book snapshot.

#### Parameters
| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | Stock ticker (e.g. `BBCA`) |

#### Example Request
```bash
curl -s http://localhost:8000/v1/books/BBCA | jq .
```

#### Example Response (`200 OK`)
```json
{
  "symbol": "BBCA",
  "book": {
    "bids": [
      { "price": "6725", "lots": 47 },
      { "price": "6700", "lots": 137940 },
      { "price": "6675", "lots": 197305 },
      { "price": "6650", "lots": 288004 },
      { "price": "6625", "lots": 31127 }
    ],
    "asks": [
      { "price": "6700", "lots": 15679 },
      { "price": "6675", "lots": 186794 },
      { "price": "6650", "lots": 116341 },
      { "price": "6625", "lots": 101223 },
      { "price": "6600", "lots": 10914 }
    ],
    "ts": "2026-09-02"
  }
}
```

---

### `GET /v1/books/snapshot/{symbol}`
Returns the full REST trade-book snapshot from Stockbit with lot distribution across Pre-opening, Continuous Trading, and Post-trading sessions.

#### Parameters
| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | Stock ticker (e.g. `BBCA`) |

#### Example Request
```bash
curl -s http://localhost:8000/v1/books/snapshot/BBCA | jq .
```

---

## 5. Live Trades & Execution Tape

---

### `GET /v1/trades?symbols={symbols}&limit={limit}`
Retrieves the most recent running trade ticks from the circular buffer populated by the WebSocket feed.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbols` | Query | `string` | No | `""` | Comma-separated symbols filter (or omit for all symbols) |
| `limit` | Query | `integer` | No | `50` | Number of trade ticks to return (max `1000`) |

#### Market Hours Note
In Stockbit's architecture, running trades (`RunningTrade` / `RunningTradeBatch`) **only stream during active trading sessions (Mon–Fri 09:00–16:15 WIB)**. When the market is closed, this endpoint returns `{"trades": []}`.

#### Example Request
```bash
curl -s "http://localhost:8000/v1/trades?symbols=BBCA&limit=5" | jq .
```

#### Example Response (`200 OK`)
```json
{
  "symbols": "BBCA",
  "limit": 5,
  "trades": [
    {
      "symbol": "BBCA",
      "price": "6675",
      "volume": 500,
      "side": "BUY",
      "board": "RG",
      "ts": "2026-09-02T16:14:58.204+07:00",
      "seq": 48201,
      "change": "+75.00",
      "change_pct": "+1.14"
    }
  ]
}
```

---

## 6. Historical Candlesticks (OHLCV)

---

### `GET /v1/candles/{symbol}`
Streams continuous historical candlestick bars line-by-line using NDJSON (`application/x-ndjson`). Automatically handles date normalization and window slicing (365 days for daily, 90 days for minute bars) without buffering multi-megabyte payloads in RAM.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker (e.g. `BBCA`) |
| `from` | Query | `string` | **Yes** | — | Start date (`YYYY-MM-DD`, e.g. `2025-09-02`) |
| `to` | Query | `string` | **Yes** | — | End date (`YYYY-MM-DD`, e.g. `2026-09-02`) |
| `resolution` | Query | `string` | No | `daily` | Candlestick period: `daily` or `minute` |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/candles/BBCA?from=2025-09-02&to=2026-09-02&resolution=daily" | head -n 3
```

#### Example Response (`200 OK` — `application/x-ndjson`)
```ndjson
{"ts":"2026-09-02T00:00:00+07:00","open":"6675","high":"6725","low":"6600","close":"6675","volume":108537400,"value":"723116960000","freq":25753}
{"ts":"2026-09-01T00:00:00+07:00","open":"6450","high":"6600","low":"6425","close":"6600","volume":117969900,"value":"773769317500","freq":34039}
{"ts":"2026-08-31T00:00:00+07:00","open":"6450","high":"6525","low":"6400","close":"6475","volume":230904500,"value":"1493528017500","freq":18637}
```

---

## 7. Charts & Price Performance

---

### `GET /v1/charts/tradebook`
Returns intraday volume and lot breakdown across price levels and trading intervals.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Query | `string` | **Yes** | — | Stock ticker (e.g. `BBCA`) |
| `interval` | Query | `string` | No | `1m` | Time bucket: `1m`, `5m`, `15m`, `1h` |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/charts/tradebook?symbol=BBCA&interval=1m" | jq .
```

---

### `GET /v1/charts/{symbol}/daily`
Stockbit daily chart series with timeframe windowing.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker (e.g. `BBCA`) |
| `timeframe` | Query | `string` | No | `1w` | Allowed: `today`, `1w`, `1m`, `3m`, `ytd`, `1y`, `3y`, `5y` |
| `is_include_previous_historical` | Query | `boolean` | No | `true` | Include previous historical close marker |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/charts/BBCA/daily?timeframe=1w&is_include_previous_historical=true" | jq .
```

---

### `GET /v1/charts/{symbol}/performance`
Multi-timeframe price return performance summary (1D, 1W, 1M, 3M, 6M, YTD, 1Y, 3Y, 5Y, 10Y).

#### Parameters
| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | Stock ticker (e.g. `BBCA`) |

#### Example Request
```bash
curl -s http://localhost:8000/v1/charts/BBCA/performance | jq .
```

#### Example Response (`200 OK`)
```json
{
  "symbol": "BBCA",
  "performance": {
    "prices": [
      { "timeframe": "1D", "percentage": { "raw": 1.136, "formatted": "(+1.14%)" }, "high": { "raw": 6725 }, "low": { "raw": 6600 } },
      { "timeframe": "1W", "percentage": { "raw": 5.118, "formatted": "(+5.12%)" }, "high": { "raw": 6675 }, "low": { "raw": 6325 } },
      { "timeframe": "1Y", "percentage": { "raw": -16.56, "formatted": "(-16.56%)" }, "high": { "raw": 8750 }, "low": { "raw": 4820 } },
      { "timeframe": "5Y", "percentage": { "raw": 1.675, "formatted": "(+1.68%)" }, "high": { "raw": 10950 }, "low": { "raw": 4820 } }
    ]
  }
}
```

---

## 8. Fundamental Valuation, Financials & Company Profile

---

### `GET /v1/fundamentals/{symbol}`
Extracts comprehensive 10-year valuation metrics, profitability factors, solvency indicators, dividend metrics, and financial statement line items.

#### Parameters
| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | Stock ticker (e.g. `BBCA`) |

#### Example Request
```bash
curl -s http://localhost:8000/v1/fundamentals/BBCA | jq .
```

---

### `GET /v1/fundamentals/{symbol}/financials`
Retrieves standardized corporate financial statements (Income Statement, Balance Sheet, Cash Flow) across standard and growth timeframes.

#### Parameters
| Name | In | Type | Required | Default | Allowed Values & Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker (e.g. `AALI`, `BBCA`) |
| `data_type` | Query | `integer` | No | `1` | `1`: Standard statements |
| `report_type` | Query | `integer` | No | `1` | `1`: Income Statement<br>`2`: Balance Sheet<br>`3`: Cash Flow |
| `statement_type` | Query | `integer` | No | `1` | `1`: Quarterly<br>`2`: Annually<br>`3`: TTM (Trailing Twelve Months)<br>`4`: Interim YTD<br>`5`: Q1, `6`: Q2, `7`: Q3, `8`: Q4<br>`9`: QoQ Growth<br>`10`: Quarter YoY Growth<br>`11`: YTD YoY Growth<br>`12`: Annual YoY Growth<br>`13`: 3 Year CAGR |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/fundamentals/BBCA/financials?data_type=1&report_type=1&statement_type=1" | jq .
```

---

### `GET /v1/companies/{symbol}`
Returns company listing status, base currency, and index memberships.

#### Example Request
```bash
curl -s http://localhost:8000/v1/companies/BBCA | jq .
```

---

### `GET /v1/companies/{symbol}/profile`
Returns official corporate metadata including headquarters address, investor relations email, telephone, website URL, and IPO listing date.

#### Example Request
```bash
curl -s http://localhost:8000/v1/companies/BBCA/profile | jq .
```

---

### `GET /v1/companies/{symbol}/subsidiaries`
Returns all corporate subsidiaries, percentage ownership, operational status, business classification, and total asset valuations.

#### Parameters
| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | Stock ticker (e.g. `BBCA`) |

#### Example Request
```bash
curl -s http://localhost:8000/v1/companies/BBCA/subsidiaries | jq .
```

#### Example Response (`200 OK`)
```json
{
  "symbol": "BBCA",
  "subsidiaries": [
    {
      "company_name": "PT Bank Digital BCA",
      "business_type": "Perbankan",
      "location": "Jakarta",
      "commercial_year": "1965",
      "total_assets": "20,818,005",
      "percentage": "100.00"
    },
    {
      "company_name": "PT Bank BCA Syariah",
      "business_type": "perbankan syariah",
      "location": "Jakarta",
      "commercial_year": "1992",
      "total_assets": "20,657,723",
      "percentage": "100.00"
    }
  ]
}
```

---

## 9. Broker Analysis & Bandarmology

---

### `GET /v1/brokers/summary/{symbol}`
Quantifies institutional flow (*Bandar Detector*), overall accumulation/distribution status (`Big Acc`, `Normal Acc`, `Neutral`, `Big Dist`), average price, and top institutional buyers and sellers.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker (e.g. `ASII`, `BBCA`) |
| `from` | Query | `string` | No | Today | Start date (`YYYY-MM-DD`) |
| `to` | Query | `string` | No | Today | End date (`YYYY-MM-DD`) |
| `transaction_type` | Query | `string` | No | `TRANSACTION_TYPE_NET` | `TRANSACTION_TYPE_NET`, `TRANSACTION_TYPE_GROSS` |
| `market_board` | Query | `string` | No | `MARKET_BOARD_REGULER` | `MARKET_BOARD_REGULER`, `MARKET_BOARD_ALL` |
| `investor_type` | Query | `string` | No | `INVESTOR_TYPE_ALL` | `INVESTOR_TYPE_ALL`, `INVESTOR_TYPE_FOREIGN`, `INVESTOR_TYPE_DOMESTIC` |
| `limit` | Query | `integer` | No | `25` | Maximum number of buyer/seller entries |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/brokers/summary/ASII?from=2026-01-01&to=2026-02-05&transaction_type=TRANSACTION_TYPE_NET&market_board=MARKET_BOARD_REGULER&investor_type=INVESTOR_TYPE_ALL&limit=25" | jq .
```

---

### `GET /v1/brokers/top`
Returns top broker volume rankings across the Indonesia Stock Exchange.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `from` | Query | `string` | No | Today | Start date (`YYYY-MM-DD`) |
| `to` | Query | `string` | No | Today | End date (`YYYY-MM-DD`) |
| `sort` | Query | `string` | No | `TB_SORT_BY_TOTAL_VALUE` | `TB_SORT_BY_TOTAL_VALUE`, `TB_SORT_BY_BUY_VALUE`, `TB_SORT_BY_SELL_VALUE`, `TB_SORT_BY_NET_VALUE` |
| `order` | Query | `string` | No | `ORDER_BY_DESC` | `ORDER_BY_DESC`, `ORDER_BY_ASC` |
| `market_type` | Query | `string` | No | `MARKET_TYPE_ALL` | `MARKET_TYPE_ALL`, `MARKET_TYPE_REGULER` |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/brokers/top?sort=TB_SORT_BY_TOTAL_VALUE&order=ORDER_BY_DESC&from=2026-02-01&to=2026-02-05&market_type=MARKET_TYPE_ALL" | jq .
```

---

### `GET /v1/brokers/top-stocks`
Returns rank of most accumulated and distributed stocks across institutional buyers.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `start` | Query | `string` | No | Today | Start date (`YYYY-MM-DD`) |
| `end` | Query | `string` | No | Today | End date (`YYYY-MM-DD`) |
| `investor_type` | Query | `string` | No | `INVESTOR_TYPE_ALL` | `INVESTOR_TYPE_ALL`, `INVESTOR_TYPE_FOREIGN`, `INVESTOR_TYPE_DOMESTIC` |
| `market_type` | Query | `string` | No | `MARKET_TYPE_REGULER` | `MARKET_TYPE_REGULER`, `MARKET_TYPE_ALL` |
| `value_type` | Query | `string` | No | `VALUE_TYPE_NET` | `VALUE_TYPE_NET`, `VALUE_TYPE_GROSS` |
| `page` | Query | `integer` | No | `1` | Page number |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/brokers/top-stocks?start=2026-02-05&end=2026-02-05&investor_type=INVESTOR_TYPE_ALL&market_type=MARKET_TYPE_REGULER&value_type=VALUE_TYPE_NET&page=1" | jq .
```

---

### `GET /v1/brokers/{code}/activity`
Returns the complete execution trade log for a specific broker code.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `code` | Path | `string` | **Yes** | — | 2-letter broker code (e.g. `XL`, `CC`, `AK`) |
| `from` | Query | `string` | No | Today | Start date (`YYYY-MM-DD`) |
| `to` | Query | `string` | No | Today | End date (`YYYY-MM-DD`) |
| `limit` | Query | `integer` | No | `50` | Maximum rows to return |
| `page` | Query | `integer` | No | `1` | Pagination offset |
| `transaction_type` | Query | `string` | No | `TRANSACTION_TYPE_NET` | `TRANSACTION_TYPE_NET`, `TRANSACTION_TYPE_GROSS` |
| `market_board` | Query | `string` | No | `MARKET_BOARD_REGULER` | `MARKET_BOARD_REGULER`, `MARKET_BOARD_ALL` |
| `investor_type` | Query | `string` | No | `INVESTOR_TYPE_ALL` | `INVESTOR_TYPE_ALL`, `INVESTOR_TYPE_FOREIGN`, `INVESTOR_TYPE_DOMESTIC` |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/brokers/XL/activity?limit=50&page=1&from=2026-02-05&to=2026-02-05&transaction_type=TRANSACTION_TYPE_NET&market_board=MARKET_BOARD_REGULER&investor_type=INVESTOR_TYPE_ALL" | jq .
```

---

## 10. Market Movers & Momentum Breadth

---

### `GET /v1/market/movers`
Returns real-time market leaderboard ranked by momentum, volatility, and volume across Main, Development, Acceleration, and New Economy boards.

#### Parameters
| Name | In | Type | Required | Default | Allowed Values |
|---|---|---|---|---|---|
| `kind` | Query | `string` | No | `top_gainers` | `top_gainers` (`MOVER_TYPE_TOP_GAINER`)<br>`top_losers` (`MOVER_TYPE_TOP_LOSER`)<br>`top_volume` (`MOVER_TYPE_TOP_VOLUME`)<br>`top_value` (`MOVER_TYPE_TOP_VALUE`)<br>`top_frequency` (`MOVER_TYPE_TOP_FREQUENCY`)<br>`net_foreign_buy` (`MOVER_TYPE_NET_FOREIGN_BUY`)<br>`net_foreign_sell` (`MOVER_TYPE_NET_FOREIGN_SELL`)<br>`iev_top_gainers` / `iep_top_gainers` (`MOVER_TYPE_IEVAL_TOP_GAINER`) |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/market/movers?kind=top_gainers" | jq .
```

#### Example Request (IEP / IEV Indication):
```bash
curl -s "http://localhost:8000/v1/market/movers?kind=iev_top_gainers" | jq .
```

---

## 11. IDX Sectors & Industry Taxonomy

---

### `GET /v1/sectors`
Returns all 11 official Indonesia Stock Exchange industry sectors.

#### Example Request
```bash
curl -s http://localhost:8000/v1/sectors | jq .
```

---

### `GET /v1/sectors/{id}/subsectors`
Returns the subsectors belonging to an industry sector.

#### Parameters
| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `id` | Path | `string` | **Yes** | Sector ID (e.g. `1` for Consumer Non-Cyclicals, `3` for Financials) |

#### Example Request
```bash
curl -s http://localhost:8000/v1/sectors/1/subsectors | jq .
```

---

### `GET /v1/sectors/{id}/subsectors/{subId}/companies`
Returns the constituent equities belonging to a specific subsector.

#### Parameters
| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `id` | Path | `string` | **Yes** | Sector ID (e.g. `1`) |
| `subId` | Path | `string` | **Yes** | Subsector ID (e.g. `15` for Makanan & Minuman) |

#### Example Request
```bash
curl -s http://localhost:8000/v1/sectors/1/subsectors/15/companies | jq .
```

---

## 12. Corporate Calendars (IPO, Dividends, Economic & Actions)

---

### `GET /v1/calendars/ipo`
Returns Initial Public Offering (IPO) filings, offering prices, underwriters, and listing schedules.

#### Example Request
```bash
curl -s http://localhost:8000/v1/calendars/ipo | jq .
```

---

### `GET /v1/calendars/dividend`
Returns upcoming and past dividend corporate action schedules across the entire IDX exchange (cum-date, ex-date, recording date, and payment date).

#### Example Request
```bash
curl -s http://localhost:8000/v1/calendars/dividend | jq .
```

---

### `GET /v1/calendars/economic`
Returns macroeconomic calendar releases (GDP, inflation, interest rate announcements).

#### Example Request
```bash
curl -s http://localhost:8000/v1/calendars/economic | jq .
```

---

### `GET /v1/calendars/tenderoffer`
Returns mandatory and voluntary tender offer corporate filings.

#### Example Request
```bash
curl -s http://localhost:8000/v1/calendars/tenderoffer | jq .
```

---

### `GET /v1/calendars/rightissue`
Returns rights issue (HMETD) corporate filings, rights ratios, and exercise prices.

#### Example Request
```bash
curl -s http://localhost:8000/v1/calendars/rightissue | jq .
```

---

### `GET /v1/calendars/stocksplit`
Returns stock split and reverse split ratios and execution dates.

#### Example Request
```bash
curl -s http://localhost:8000/v1/calendars/stocksplit | jq .
```

---

### `GET /v1/calendars/companies/{symbol}/actions`
Returns corporate action history (dividends, stock splits, bonus shares, rights issues) for a specific ticker.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker (e.g. `AALI`, `BBCA`) |
| `limit` | Query | `integer` | No | `30` | Maximum corporate actions |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/calendars/companies/AALI/actions?limit=30" | jq .
```

---

## 13. Seasonality Analysis

---

### `GET /v1/seasonality/{symbol}`
Returns multi-year monthly return probability matrix and seasonal performance patterns.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker (e.g. `AALI`, `BBCA`) |
| `year` | Query | `integer` | No | Current Year | Reference year (e.g. `2026`) |
| `back_year` | Query | `integer` | No | `5` | Historical lookback depth in years |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/seasonality/AALI?year=2026&back_year=5" | jq .
```

---

## 14. Real-time WebSocket Stream

---

### `WS /v1/stream?token={token}`
Full duplex WebSocket connection delivering sub-millisecond execution ticks, order book depth changes, and quote updates.

#### Handshake URL
```
ws://localhost:8000/v1/stream?token=$API_KEY
```

#### Protocol Frames

**1. Subscribe Action:**
```json
{
  "action": "subscribe",
  "symbols": ["BBCA", "TLKM"],
  "kinds": ["trades", "quotes", "books"]
}
```
*Rule: Wildcard `"*"` is supported for `trades` (`running_trade_batch`). Quotes and books require explicit symbols.*

**2. Unsubscribe Action:**
```json
{
  "action": "unsubscribe",
  "symbols": ["TLKM"]
}
```

**3. Ping / Keepalive Action:**
```json
{
  "action": "ping"
}
```

#### Incoming Event Payloads

- **Live Trade Event:**
```json
{
  "kind": "trade",
  "symbol": "BBCA",
  "payload": {
    "stock": "BBCA",
    "price": 6675.0,
    "volume": 500,
    "side": "BUY",
    "trade_number": 48201
  }
}
```

- **Live Quote Event:**
```json
{
  "kind": "quote",
  "symbol": "BBCA",
  "payload": {
    "stock": "BBCA",
    "price": 6675.0,
    "open": 6450.0,
    "high": 6725.0,
    "low": 6600.0
  }
}
```

---

## 15. Analyst Consensus, Estimates & Research

---

### `GET /v1/estimates/{symbol}/consensus`
Returns forward multi-horizon analyst estimates (Revenue, Operating Profit, Net Profit, EPS) spanning historical actuals and next 2-3 fiscal years.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker (e.g. `BBCA`, `AALI`) |

#### Example Request
```bash
curl -s http://localhost:8000/v1/estimates/AALI/consensus | jq .
```

#### Example Response (`200 OK`)
```json
{
  "symbol": "AALI",
  "consensus": [
    {
      "name": "Revenue",
      "items": [
        { "year": 2025, "is_estimate": false, "value": "28,655 B", "raw_value": 0 },
        { "year": 2026, "is_estimate": true, "value": "29,083 B", "raw_value": 0 },
        { "year": 2027, "is_estimate": true, "value": "29,678 B", "raw_value": 0 }
      ]
    },
    {
      "name": "EPS",
      "items": [
        { "year": 2025, "is_estimate": false, "value": "578.10", "raw_value": 0 },
        { "year": 2026, "is_estimate": true, "value": "612.40", "raw_value": 0 }
      ]
    }
  ]
}
```

---

### `GET /v1/estimates/{symbol}/ratings`
Returns analyst consensus target price ranges (High, Low, Average) and recommendation breakdown (Buy, Hold, Sell).

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker (e.g. `BBCA`, `AALI`) |

#### Example Response (`200 OK`)
```json
{
  "symbol": "AALI",
  "ratings": {
    "price_target": {
      "best_target": 8050,
      "best_low_target": 6440,
      "best_high_target": 11600,
      "current_price": 8575
    },
    "recommendation": "Buy",
    "total_buy": 4,
    "total_hold": 9,
    "total_sell": 0,
    "total_analyst": 13,
    "last_updated": "31 Aug 26"
  }
}
```

---

### `GET /v1/estimates/{symbol}/research`
Returns official equity research reports, notes, and coverage history.

---

## 16. Insider Trading & Major Shareholding Intelligence

---

### `GET /v1/insider/movements`
Monitors all mandatory filings by substantial shareholders (>= 5%) and company directors/commissioners across the Indonesia Stock Exchange.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `date_start` | Query | `string` | **Yes** | — | Start date (`YYYY-MM-DD`) |
| `date_end` | Query | `string` | **Yes** | — | End date (`YYYY-MM-DD`) |
| `page` | Query | `integer` | No | `1` | Pagination page |
| `limit` | Query | `integer` | No | `20` | Items per page (max: `100`) |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/insider/movements?date_start=2026-08-01&date_end=2026-09-01" | jq .
```

#### Example Response (`200 OK`)
```json
{
  "date_start": "2026-08-01",
  "date_end": "2026-09-01",
  "page": 1,
  "limit": 20,
  "data": {
    "is_more": true,
    "movement": [
      {
        "name": "NICHOLAS SANTOSO",
        "symbol": "NICK",
        "date": "02 Sep 26",
        "previous": { "value": "284,200", "percentage": "0.04" },
        "current": { "value": "291,600", "percentage": "0.04" },
        "changes": { "value": "+7,400", "percentage": "+0.0012" }
      }
    ]
  }
}
```

---

### `GET /v1/companies/{symbol}/shareholders`
Returns structured ownership breakdown (Controller, Domestic Institution, Foreign Institution, Public, Management).

#### Example Request
```bash
curl -s http://localhost:8000/v1/companies/BBCA/shareholders | jq .
```

---

### `GET /v1/companies/{symbol}/shareholders/trend`
Multi-year monthly progression of shareholder counts and percentage changes.

---

## 17. Guru & Quantitative Screeners

---

### `GET /v1/screeners/presets`
Lists all available pre-built quantitative and Guru investment screeners (Piotroski F-Score, Kenneth Fisher P/S, EV/EBITDA, Graham Net-Net, etc.).

#### Example Response (`200 OK`)
```json
{
  "presets": [
    {
      "id": 11,
      "name": "Guru Screener",
      "childs": [
        {
          "id": 1,
          "name": "Value Screener",
          "childs": [
            { "id": 2, "name": "Kenneth Fisher Price To Sales", "type": "TEMPLATE_TYPE_GURU" },
            { "id": 3, "name": "Piotroski F-Score Price To Earnings", "type": "TEMPLATE_TYPE_GURU" }
          ]
        }
      ]
    }
  ]
}
```

---

### `GET /v1/screeners/presets/{preset_id}`
Executes a screener preset and returns matching tickers with exact calculated valuation/financial criteria.

#### Example Request
```bash
curl -s http://localhost:8000/v1/screeners/presets/2 | jq .
```

---

## 18. Valuation Engine (DCF & Graham Fair Value)

---

### `GET /v1/fundamentals/{symbol}/valuation`
Computes fair value target price, margin of safety (%), and consensus valuation benchmarks.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker |
| `eps_value` | Query | `string` | No | Auto | Custom EPS input (or defaults to TTM) |
| `growth_value` | Query | `string` | No | Auto | Custom growth rate % |
| `multiple_value` | Query | `string` | No | Auto | Custom P/E target multiple |

#### Example Response (`200 OK`)
```json
{
  "symbol": "BBCA",
  "valuation": {
    "current_price": "6,775.00",
    "target_price": "9,484.73",
    "margin_safety": "40",
    "consensus_low": "6,500.00",
    "consensus_medium": "8,142.84",
    "consensus_high": "10,100.00"
  }
}
```

---

### `GET /v1/fundamentals/{symbol}/valuation/metrics`
Returns current baseline valuation inputs (EPS, historical growth, default P/E).

---

### `GET /v1/fundamentals/{symbol}/history`
Returns multi-year historical daily time-series points for any fundamental ratio or valuation item (Price, PE, PBV, ROE, etc.).

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker |
| `item_id` | Query | `integer` | No | `2661` | Metric item ID (default `2661` for Price) |
| `timeframe` | Query | `string` | No | `1y` | Timeframe (`1y`, `3y`, `5y`, `10y`) |

#### Example Request
```bash
curl -s "http://localhost:8000/v1/fundamentals/BBCA/history?item_id=2661&timeframe=1y" | jq .
```

---

## 19. Advanced Institutional Flow & Broker Matrix

---

### `GET /v1/brokers/{symbol}/distribution`
Cross-checks buyer-to-seller broker matching matrix (who bought from whom).

#### Example Request
```bash
curl -s "http://localhost:8000/v1/brokers/BBCA/distribution" | jq .
```

---

### `GET /v1/flow/{symbol}/foreign-domestic`
Returns cumulative Foreign Buy vs Foreign Sell vs Domestic institutional flow.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker |
| `period` | Query | `string` | No | `PERIOD_RANGE_1D` | Range (`PERIOD_RANGE_1D`, `PERIOD_RANGE_1W`, `PERIOD_RANGE_1M`) |

---

### `GET /v1/brokers/{code}/chart`
Returns intraday transaction activity chart for a broker code.

---

### `GET /v1/brokers/{code}/history`
Tracks multi-horizon historical daily accumulation/distribution of a broker code on a specific stock.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `code` | Path | `string` | **Yes** | — | Broker code (e.g. `XL`, `YP`, `ZP`) |
| `symbols` | Query | `string` | **Yes** | — | Stock ticker (e.g. `BBCA`) |
| `period` | Query | `string` | No | `RT_PERIOD_LAST_1_YEAR` | Horizon |

---

### `GET /v1/trades/running/snapshot`
Returns an immediate REST snapshot of recent market-wide execution ticks.

---

## 20. Institutional Research & Morning Briefings

---

### `GET /v1/research/morning-notes`
Retrieves daily pre-market macro notes, sector updates, and analyst views directly from the official Stockbit Reports broadcast desk (Room `338965`).

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `limit` | Query | `integer` | No | `50` | Maximum messages to return |
| `cursor_id` | Query | `integer` | No | — | Message ID cursor for pagination |

#### Example Request
```bash
curl -s http://localhost:8000/v1/research/morning-notes | jq .
```

---

### `GET /v1/research/reports`
Retrieves institutional equity research reports, morning notes, and thesis writeups published by an analyst desk.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `account` | Query | `string` | No | `StockbitReports` | Analyst account handle |
| `last_stream_id` | Query | `integer` | No | `0` | Cursor for pagination |
| `limit` | Query | `integer` | No | `20` | Items per page (max: `50`) |

#### Example Request
```bash
curl -s http://localhost:8000/v1/research/reports?account=StockbitReports | jq .
```

---

### `GET /v1/research/reports/{post_id}`
Retrieves full research report detail including thesis breakdown, PDF report attachments, and financial models.

#### Example Request
```bash
curl -s http://localhost:8000/v1/research/reports/35455618 | jq .
```

---

## 21. Equity News & Regulatory Disclosures

---

### `GET /v1/news/{symbol}`
Retrieves live breaking news, corporate disclosures, and regulatory filings for an equity ticker.

#### Parameters
| Name | In | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `symbol` | Path | `string` | **Yes** | — | Stock ticker (e.g. `BBCA`, `TLKM`) |
| `category` | Query | `string` | No | `STREAM_CATEGORY_ALL` | Category filter |
| `last_stream_id` | Query | `integer` | No | `0` | Cursor for pagination |
| `limit` | Query | `integer` | No | `20` | Items per page |

#### Example Request
```bash
curl -s http://localhost:8000/v1/news/BBCA | jq .
```
