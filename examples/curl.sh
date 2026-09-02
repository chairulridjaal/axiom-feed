#!/usr/bin/env bash
set -e
BASE=${BASE:-http://localhost:8000}
API_KEY=${API_KEY:-}

echo "== health =="
curl -s "$BASE/v1/health" | jq .

echo "== ready =="
curl -s "$BASE/v1/ready" | jq .

echo "== daily candles (streamed NDJSON, from<=to normalized) =="
curl -s "$BASE/v1/candles/BBCA?from=2026-08-01&to=2026-08-26&resolution=daily" | head -n 5

echo "== minute candles (90d slice, bounded) =="
curl -s "$BASE/v1/candles/BBCA?from=2026-08-25&to=2026-08-26&resolution=minute" | head -n 5

echo "== quotes/books (live snapshot) =="
curl -s "$BASE/v1/quotes/BBCA" | jq . || true
curl -s "$BASE/v1/books/BBCA" | jq . || true

echo "== WS stream (5s demo, ?token= per-connection) =="
if command -v websocat >/dev/null 2>&1; then
  timeout 5 websocat -n "ws://localhost:8000/v1/stream?token=$API_KEY" <<< '{"action":"subscribe","symbols":["BBCA"],"kinds":["trades","quotes","books"]}' || true
else
  echo "websocat not installed — try: pip install websocat or use python example"
fi

echo "== try wildcard rejection (should 400) =="
curl -s -X POST "$BASE/v1/quotes/subscribe" -H "Content-Type: application/json" -d '{"symbols":["*"]}' | jq .
