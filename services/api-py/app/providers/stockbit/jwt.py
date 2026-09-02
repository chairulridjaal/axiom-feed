from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any


def _b64url_decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def decode_jwt_claims(token: str) -> dict[str, Any] | None:
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        payload = _b64url_decode(payload_b64)
        return json.loads(payload)
    except Exception:
        return None


def jwt_exp(token: str) -> int | None:
    claims = decode_jwt_claims(token)
    if not claims:
        return None
    exp = claims.get("exp")
    try:
        return int(exp) if exp is not None else None
    except Exception:
        return None


def jwt_ttl_seconds(token: str) -> int | None:
    exp = jwt_exp(token)
    if exp is None:
        return None
    return int(exp - time.time())


JWT_EXPIRED_MSG = (
    "Stockbit Bearer JWT expired (exp={exp} < now={now}). "
    "Copy fresh token: DevTools → exodus.stockbit.com → Headers → Authorization: Bearer <token> "
    "→ paste into STOCKBIT_BEARER_TOKEN in .env or refresh cookies.json and restart auto-refresh. "
    "Previous exp={exp} ({exp_iso}), now={now} ({now_iso})."
)

COOKIES_STALE_MSG = (
    "Stockbit cookies stale or expired (401). Re-export cookies.json: "
    "login at https://stockbit.com → DevTools → Application → Cookies "
    "→ copy all cookies as JSON array → save to {path}. "
    "Then refresh Bearer via DevTools → Network → exodus.stockbit.com → Authorization: Bearer."
)


@dataclass
class Credentials:
    user_id: str
    ws_key: str
    bearer_token: str
    exp: int | None = None

    @property
    def ttl(self) -> int | None:
        if self.exp is None:
            return None
        return int(self.exp - time.time())

    @property
    def is_expired(self) -> bool:
        if self.exp is None:
            return False
        return time.time() >= self.exp

    @property
    def warn_soon(self) -> bool:
        if self.exp is None:
            return False
        return (self.exp - time.time()) < 3600


class AuthenticationError(RuntimeError):
    pass
