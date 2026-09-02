# Security Policy

## Reporting

Please report vulnerabilities via GitHub Security Advisories or email the maintainers. Do not open public issues for sensitive auth bypass / token exfiltration.

## Stockbit credentials

* `STOCKBIT_BEARER_TOKEN` is a 24h JWT. Rotate daily. Never commit `.env` or `cookies.json`.
* `API_KEY` (if set) gates REST via `X-API-Key`. WS uses `?token=` query — checked per-connection, not globally.
* The `.env.example` contains no real tokens. CI uses synthetic fixtures, never live Stockbit calls.

## Supported versions

`main` is the only supported branch pre-1.0.