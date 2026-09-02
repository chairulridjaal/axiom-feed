"""Per-router X-API-Key — fixes be-web global Depends that made WS 500.

Be-web set dependencies=[Depends(verify_api_key)] on app (api.py:146),
which applied to WS handshake too (500 before verify_ws_token could run).

Axiom: REST routers carry Depends(verify_api_key) individually; WS checks ?token= manually.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_api_key() -> str:
    val = os.getenv("API_KEY", "").strip()
    # Handle possible inline comments: API_KEY="" # comment
    if "#" in val and not (val.startswith('"') and val.endswith('"')):
        val = val.split("#")[0].strip()
    val = val.strip("\"'")
    return val


API_KEY = _get_api_key()


async def verify_api_key(api_key: str | None = Security(_api_key_header)):
    expected = _get_api_key()
    if not expected:
        return
    if api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")


def verify_ws_token(token: str | None) -> bool:
    expected = _get_api_key()
    if not expected:
        return True
    return token == expected
