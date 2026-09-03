from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from .cookies import _cookies_to_httpx_jar, _get_auth_mode, _get_cookies_path, load_cookies_array
from .jwt import (
    COOKIES_STALE_MSG,
    JWT_EXPIRED_MSG,
    AuthenticationError,
    Credentials,
    decode_jwt_claims,
    jwt_exp,
)

logger = logging.getLogger(__name__)

EXODUS = "https://exodus.stockbit.com"
BEARER_ENV = "STOCKBIT_BEARER_TOKEN"


def _headers(bearer: str) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Authorization": f"Bearer {bearer}",
    }


async def _fetch_with_cookies(client: httpx.AsyncClient, path: str, bearer: str) -> httpx.Response:
    url = f"{EXODUS}{path}"
    headers = _headers(bearer)
    resp = await client.get(url, headers=headers, timeout=15)
    return resp


async def fetch_credentials(bearer: str, cookies_path: Path | None = None) -> Credentials:
    if cookies_path is None:
        cookies_path = _get_cookies_path()
    cookies_arr = load_cookies_array(cookies_path)
    jar = _cookies_to_httpx_jar(cookies_arr)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(cookies=jar, limits=limits, follow_redirects=True) as client:
        resp = await _fetch_with_cookies(client, "/usergraph/socialinfo/user/me", bearer)
        if resp.status_code == 401:
            raise AuthenticationError(
                COOKIES_STALE_MSG.format(path=cookies_path) + " (user/me 401)"
            )
        resp.raise_for_status()
        data = resp.json()
        user_id = str(data.get("data", {}).get("user_id") or data.get("user_id") or "")
        if not user_id:
            raise AuthenticationError(f"user/me returned no user_id: {data}")
        resp2 = await _fetch_with_cookies(client, "/auth/websocket/key", bearer)
        if resp2.status_code == 401:
            raise AuthenticationError(COOKIES_STALE_MSG.format(path=cookies_path) + " (ws/key 401)")
        resp2.raise_for_status()
        data2 = resp2.json()
        ws_key = str(data2.get("data", {}).get("key") or data2.get("key") or "")
        if not ws_key:
            raise AuthenticationError(f"ws/key returned no key: {data2}")
        exp = jwt_exp(bearer)
        return Credentials(user_id=user_id, ws_key=ws_key, bearer_token=bearer, exp=exp)


class AuthManager:
    def __init__(
        self,
        bearer_token: str | None = None,
        cookies_path: Path | str | None = None,
        on_refresh: Any | None = None,
        redis_url: str | None = None,
    ):
        self.bearer_token = (
            (bearer_token or os.getenv(BEARER_ENV, "")).strip().strip('"').strip("'")
        )
        self.cookies_path = Path(cookies_path) if cookies_path is not None else _get_cookies_path()
        self.on_refresh = on_refresh
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self._creds: Credentials | None = None
        self._mtime: float | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def creds(self) -> Credentials | None:
        return self._creds

    def _check_jwt(self) -> None:
        if not self.bearer_token:
            logger.warning("STOCKBIT_BEARER_TOKEN empty — set in .env")
            return
        claims = decode_jwt_claims(self.bearer_token)
        exp = jwt_exp(self.bearer_token)
        if exp is None:
            logger.warning("Bearer JWT has no exp claim — cannot monitor expiry")
            return
        ttl = exp - time.time()
        if claims and "iat" in claims:
            try:
                lifetime = int(exp) - int(claims["iat"])
                if abs(lifetime - 86400) > 3600:
                    logger.warning(
                        f"JWT lifetime {lifetime}s != 86400s — check token source (exp={exp}, iat={claims['iat']})"
                    )
            except Exception:
                pass
        if ttl < 0:
            logger.error(
                JWT_EXPIRED_MSG.format(
                    exp=exp,
                    now=int(time.time()),
                    exp_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp)),
                    now_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
            )
        elif ttl < 3600:
            logger.warning(
                f"Bearer JWT expires in {int(ttl)}s (T-1h window) — will auto-refresh via cookies"
            )
        else:
            logger.info(
                f"Bearer JWT ttl {int(ttl)}s ({int(ttl // 3600)}h) — exp {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(exp))}"
            )

    async def _publish_redis(self, creds: Credentials) -> None:
        if not self.redis_url:
            return
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(self.redis_url, decode_responses=True)
            payload = json.dumps(
                {
                    "user_id": creds.user_id,
                    "ws_key": creds.ws_key,
                    "bearer": creds.bearer_token,
                    "exp": creds.exp,
                }
            )
            await r.publish("axiom.auth.refresh", payload)
            await r.close()
            logger.info("Published auth refresh to Redis axiom.auth.refresh")
        except Exception as e:
            logger.warning(f"Redis publish auth refresh failed: {e}")

    async def refresh_once(self) -> Credentials:
        bearer = self.bearer_token
        exp = jwt_exp(bearer)
        if exp is not None and time.time() >= exp:
            raise AuthenticationError(
                JWT_EXPIRED_MSG.format(
                    exp=exp,
                    now=int(time.time()),
                    exp_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp)),
                    now_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
            )
        creds = await fetch_credentials(bearer, self.cookies_path)
        self._creds = creds
        self._mtime = self.cookies_path.stat().st_mtime if self.cookies_path.exists() else None
        self._check_jwt()
        if self.on_refresh:
            try:
                res = self.on_refresh(creds)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.warning(f"on_refresh callback failed: {e}")
        await self._publish_redis(creds)
        logger.info(
            f"Auth refreshed: user_id={creds.user_id} ws_key={creds.ws_key[:12]}... ttl={creds.ttl}s"
        )
        return creds

    async def start(self) -> None:
        self._check_jwt()
        try:
            if self.bearer_token and self.cookies_path.exists():
                await self.refresh_once()
            else:
                logger.warning(
                    f"Auth not refreshed at startup: bearer={'set' if self.bearer_token else 'empty'}, cookies_exists={self.cookies_path.exists()}"
                )
        except AuthenticationError as e:
            logger.warning(f"Initial auth refresh failed (will retry): {e}")
        except Exception as e:
            logger.warning(f"Initial auth refresh error: {e}")
        self._stop.clear()
        self._task = asyncio.create_task(self._watch_loop())
        logger.info(
            f"AuthManager watcher started (cookies={self.cookies_path}, mode={_get_auth_mode()})"
        )

    async def _watch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.sleep(30)
                if self.cookies_path.exists():
                    m = self.cookies_path.stat().st_mtime
                    if self._mtime is None or m > (self._mtime or 0) + 2.0:
                        logger.info(
                            f"cookies.json mtime changed ({self._mtime} -> {m}) — refreshing auth"
                        )
                        try:
                            await self.refresh_once()
                        except AuthenticationError as e:
                            logger.error(f"Auto-refresh after mtime change failed: {e}")
                        except Exception as e:
                            logger.error(f"Auto-refresh error: {e}")
                if self._creds and self._creds.warn_soon and not self._creds.is_expired:
                    logger.warning(f"JWT exp in {self._creds.ttl}s — attempting proactive refresh")
                    try:
                        await self.refresh_once()
                    except Exception as e:
                        logger.warning(f"Proactive refresh failed: {e}")
                cur = os.getenv(BEARER_ENV, "").strip().strip('"').strip("'")
                if cur and cur != self.bearer_token:
                    logger.info("STOCKBIT_BEARER_TOKEN changed — refreshing")
                    self.bearer_token = cur
                    try:
                        await self.refresh_once()
                    except Exception as e:
                        logger.error(f"Bearer change refresh failed: {e}")
                if self._creds and self._creds.is_expired:
                    logger.error(
                        f"Credentials expired (exp={self._creds.exp}) — manual Bearer refresh required"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Auth watcher loop error: {e}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("AuthManager stopped")

    def health(self) -> dict[str, Any]:
        exp = jwt_exp(self.bearer_token) if self.bearer_token else None
        ttl = int(exp - time.time()) if exp else None
        return {
            "bearer_set": bool(self.bearer_token),
            "exp": exp,
            "ttl_seconds": ttl,
            "warn_soon": (ttl is not None and ttl < 3600),
            "is_expired": (ttl is not None and ttl < 0),
            "cookies_path": str(self.cookies_path),
            "cookies_exists": self.cookies_path.exists(),
            "cookies_mtime": self._mtime,
            "user_id": self._creds.user_id if self._creds else None,
            "ws_key_set": bool(self._creds.ws_key) if self._creds else False,
            "auth_mode": _get_auth_mode(),
        }


_auth: AuthManager | None = None


def get_auth() -> AuthManager | None:
    return _auth


def init_auth(
    bearer_token: str | None = None,
    cookies_path: str | Path | None = None,
    on_refresh: Any | None = None,
) -> AuthManager:
    global _auth
    if _auth is None:
        _auth = AuthManager(
            bearer_token=bearer_token, cookies_path=cookies_path, on_refresh=on_refresh
        )
    else:
        if bearer_token is not None:
            _auth.bearer_token = bearer_token.strip().strip('"').strip("'")
        if cookies_path is not None:
            _auth.cookies_path = Path(cookies_path)
        if on_refresh is not None:
            _auth.on_refresh = on_refresh
    return _auth
