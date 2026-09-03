from __future__ import annotations

import asyncio
import json
import logging
import os
import re
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
    UpstreamAuthError,
    decode_jwt_claims,
    jwt_exp,
)

logger = logging.getLogger(__name__)

EXODUS = "https://exodus.stockbit.com"
BEARER_ENV = "STOCKBIT_BEARER_TOKEN"
REFRESH_ENV = "STOCKBIT_REFRESH_TOKEN"


def _headers(bearer: str) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Authorization": f"Bearer {bearer}",
    }


def _find_env_file(configured: Path | str | None = None) -> Path | None:
    if configured:
        p = Path(configured)
        if p.exists():
            return p
    cands = [
        Path(".env"),
        Path("../../.env"),
        Path(__file__).resolve().parents[4] / ".env",
    ]
    for c in cands:
        if c.exists():
            return c
    return None


def _update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    if not env_path.exists():
        return
    try:
        content = env_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        found_keys: set[str] = set()
        new_lines: list[str] = []

        for line in lines:
            replaced = False
            for k, v in updates.items():
                if re.match(rf"^\s*{re.escape(k)}\s*=", line):
                    new_lines.append(f'{k}="{v}"')
                    found_keys.add(k)
                    replaced = True
                    break
            if not replaced:
                new_lines.append(line)

        for k, v in updates.items():
            if k not in found_keys:
                new_lines.append(f'{k}="{v}"')

        new_content = "\n".join(new_lines) + "\n"
        env_path.write_text(new_content, encoding="utf-8")
        logger.info(f"Updated {list(updates.keys())} in {env_path}")
    except Exception as e:
        logger.warning(f"Failed to update env file {env_path}: {e}")


def _read_env_tokens(env_path: Path) -> tuple[str, str]:
    bearer = ""
    refresh = ""
    if not env_path.exists():
        return bearer, refresh
    try:
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith(f"{BEARER_ENV}="):
                bearer = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith(f"{REFRESH_ENV}="):
                refresh = line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"Error reading env tokens from {env_path}: {e}")
    return bearer, refresh


async def exchange_refresh_token(
    refresh_token: str, client: httpx.AsyncClient | None = None
) -> tuple[str, str]:
    url = f"{EXODUS}/login/refresh"
    headers = _headers(refresh_token)

    async def _post(c: httpx.AsyncClient) -> httpx.Response:
        return await c.post(url, headers=headers, timeout=20)

    if client is not None:
        resp = await _post(client)
    else:
        limits = httpx.Limits(max_connections=5, max_keepalive_connections=2)
        async with httpx.AsyncClient(limits=limits, follow_redirects=True) as c:
            resp = await _post(c)

    if resp.status_code == 401:
        raise UpstreamAuthError(
            f"Stockbit refresh token rejected (401 Unauthorized). Manual re-login required. Detail: {resp.text[:120]}"
        )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    new_access = data.get("access", {}).get("token") or ""
    new_refresh = data.get("refresh", {}).get("token") or ""

    if not new_access:
        raise AuthenticationError(f"login/refresh returned no access token: {resp.text[:150]}")
    return new_access, (new_refresh or refresh_token)


async def _fetch_with_cookies(client: httpx.AsyncClient, path: str, bearer: str) -> httpx.Response:
    url = f"{EXODUS}{path}"
    headers = _headers(bearer)
    resp = await client.get(url, headers=headers, timeout=15)
    return resp


async def fetch_credentials(
    bearer: str,
    cookies_path: Path | None = None,
    refresh_token: str | None = None,
) -> Credentials:
    if cookies_path is None:
        cookies_path = _get_cookies_path()
    cookies_arr = load_cookies_array(cookies_path)
    jar = _cookies_to_httpx_jar(cookies_arr)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(cookies=jar, limits=limits, follow_redirects=True) as client:
        resp = await _fetch_with_cookies(client, "/usergraph/socialinfo/user/me", bearer)
        if resp.status_code == 401:
            raise UpstreamAuthError(COOKIES_STALE_MSG.format(path=cookies_path) + " (user/me 401)")
        resp.raise_for_status()
        data = resp.json()
        user_id = str(data.get("data", {}).get("user_id") or data.get("user_id") or "")
        if not user_id:
            raise AuthenticationError(f"user/me returned no user_id: {data}")
        resp2 = await _fetch_with_cookies(client, "/auth/websocket/key", bearer)
        if resp2.status_code == 401:
            raise UpstreamAuthError(COOKIES_STALE_MSG.format(path=cookies_path) + " (ws/key 401)")
        resp2.raise_for_status()
        data2 = resp2.json()
        ws_key = str(data2.get("data", {}).get("key") or data2.get("key") or "")
        if not ws_key:
            raise AuthenticationError(f"ws/key returned no key: {data2}")
        exp = jwt_exp(bearer)
        ref_exp = jwt_exp(refresh_token) if refresh_token else None
        return Credentials(
            user_id=user_id,
            ws_key=ws_key,
            bearer_token=bearer,
            refresh_token=refresh_token,
            exp=exp,
            refresh_exp=ref_exp,
        )


class AuthManager:
    def __init__(
        self,
        bearer_token: str | None = None,
        refresh_token: str | None = None,
        cookies_path: Path | str | None = None,
        env_path: Path | str | None = None,
        on_refresh: Any | None = None,
        redis_url: str | None = None,
    ):
        self.bearer_token = (
            (bearer_token or os.getenv(BEARER_ENV, "")).strip().strip('"').strip("'")
        )
        self.refresh_token = (
            (refresh_token or os.getenv(REFRESH_ENV, "")).strip().strip('"').strip("'")
        )
        self.cookies_path = Path(cookies_path) if cookies_path is not None else _get_cookies_path()
        self.env_path = _find_env_file(env_path)
        self.on_refresh = on_refresh
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self._creds: Credentials | None = None
        self._mtime: float | None = None
        self._env_mtime: float | None = (
            self.env_path.stat().st_mtime if self.env_path and self.env_path.exists() else None
        )
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._refresh_lock = asyncio.Lock()

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
            logger.warning(f"Bearer JWT expires in {int(ttl)}s (T-1h window) — auto-refresh active")
        else:
            logger.info(
                f"Bearer JWT ttl {int(ttl)}s ({int(ttl // 3600)}h) — exp {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(exp))}"
            )
        if self.refresh_token:
            r_exp = jwt_exp(self.refresh_token)
            if r_exp:
                r_ttl = r_exp - time.time()
                logger.info(
                    f"Refresh token ttl {int(r_ttl)}s ({int(r_ttl // 86400)}d) — exp {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(r_exp))}"
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
                    "refresh": creds.refresh_token,
                    "exp": creds.exp,
                }
            )
            await r.publish("axiom.auth.refresh", payload)
            await r.close()
            logger.info("Published auth refresh to Redis axiom.auth.refresh")
        except Exception as e:
            logger.warning(f"Redis publish auth refresh failed: {e}")

    async def refresh_tokens_via_stockbit(self) -> Credentials:
        async with self._refresh_lock:
            if not self.refresh_token:
                raise AuthenticationError(
                    "No STOCKBIT_REFRESH_TOKEN configured — cannot auto-refresh."
                )
            logger.info("Attempting silent token refresh via Stockbit /login/refresh...")
            new_bearer, new_refresh = await exchange_refresh_token(self.refresh_token)
            self.bearer_token = new_bearer
            self.refresh_token = new_refresh
            os.environ[BEARER_ENV] = new_bearer
            os.environ[REFRESH_ENV] = new_refresh

            if self.env_path and self.env_path.exists():
                _update_env_file(
                    self.env_path,
                    {BEARER_ENV: new_bearer, REFRESH_ENV: new_refresh},
                )
                self._env_mtime = self.env_path.stat().st_mtime

            creds = await fetch_credentials(
                self.bearer_token, self.cookies_path, self.refresh_token
            )
            self._creds = creds
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
                f"Silent token refresh successful: user_id={creds.user_id} new_ttl={creds.ttl}s"
            )
            return creds

    async def refresh_once(self) -> Credentials:
        bearer = self.bearer_token
        exp = jwt_exp(bearer)
        if (exp is not None and time.time() >= exp) or not bearer:
            if self.refresh_token:
                try:
                    return await self.refresh_tokens_via_stockbit()
                except Exception as e:
                    logger.warning(f"Automatic refresh failed: {e}")
            raise AuthenticationError(
                JWT_EXPIRED_MSG.format(
                    exp=exp or 0,
                    now=int(time.time()),
                    exp_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp or 0)),
                    now_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
            )

        try:
            creds = await fetch_credentials(bearer, self.cookies_path, self.refresh_token)
        except UpstreamAuthError:
            if self.refresh_token:
                logger.info(
                    "Credentials rejected upstream — attempting recovery via refresh token..."
                )
                return await self.refresh_tokens_via_stockbit()
            raise

        self._creds = creds
        self._mtime = self.cookies_path.stat().st_mtime if self.cookies_path.exists() else None
        if self.env_path and self.env_path.exists():
            self._env_mtime = self.env_path.stat().st_mtime
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
            if (self.bearer_token or self.refresh_token) and (
                self.cookies_path.exists() or self.refresh_token
            ):
                await self.refresh_once()
            else:
                logger.warning(
                    f"Auth not refreshed at startup: bearer={'set' if self.bearer_token else 'empty'}, refresh={'set' if self.refresh_token else 'empty'}"
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
                        except Exception as e:
                            logger.error(f"Auto-refresh after cookie change failed: {e}")

                if self.env_path and self.env_path.exists():
                    em = self.env_path.stat().st_mtime
                    if self._env_mtime is not None and em > self._env_mtime + 2.0:
                        logger.info(
                            f".env file changed ({self._env_mtime} -> {em}) — reloading tokens"
                        )
                        self._env_mtime = em
                        new_b, new_r = _read_env_tokens(self.env_path)
                        changed = False
                        if new_b and new_b != self.bearer_token:
                            self.bearer_token = new_b
                            os.environ[BEARER_ENV] = new_b
                            changed = True
                        if new_r and new_r != self.refresh_token:
                            self.refresh_token = new_r
                            os.environ[REFRESH_ENV] = new_r
                            changed = True
                        if changed:
                            try:
                                await self.refresh_once()
                            except Exception as e:
                                logger.error(f"Auto-refresh after .env reload failed: {e}")

                if (
                    self._creds
                    and self._creds.warn_soon
                    and not self._creds.is_expired
                    and self.refresh_token
                ):
                    logger.info(
                        f"JWT exp in {self._creds.ttl}s — triggering proactive silent refresh"
                    )
                    try:
                        await self.refresh_tokens_via_stockbit()
                    except Exception as e:
                        logger.warning(f"Proactive refresh via refresh_token failed: {e}")

                if self._creds and self._creds.is_expired:
                    if self.refresh_token:
                        logger.info("Bearer expired — attempting recovery via refresh token")
                        try:
                            await self.refresh_tokens_via_stockbit()
                        except Exception as e:
                            logger.error(f"Recovery via refresh_token failed: {e}")
                    else:
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
        r_exp = jwt_exp(self.refresh_token) if self.refresh_token else None
        r_ttl = int(r_exp - time.time()) if r_exp else None
        return {
            "bearer_set": bool(self.bearer_token),
            "refresh_token_set": bool(self.refresh_token),
            "exp": exp,
            "ttl_seconds": ttl,
            "refresh_exp": r_exp,
            "refresh_ttl_seconds": r_ttl,
            "warn_soon": (ttl is not None and ttl < 3600),
            "is_expired": (ttl is not None and ttl < 0),
            "is_refresh_expired": (r_ttl is not None and r_ttl < 0),
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
    refresh_token: str | None = None,
    cookies_path: str | Path | None = None,
    env_path: str | Path | None = None,
    on_refresh: Any | None = None,
) -> AuthManager:
    global _auth
    if _auth is None:
        _auth = AuthManager(
            bearer_token=bearer_token,
            refresh_token=refresh_token,
            cookies_path=cookies_path,
            env_path=env_path,
            on_refresh=on_refresh,
        )
    else:
        if bearer_token is not None:
            _auth.bearer_token = bearer_token.strip().strip('"').strip("'")
        if refresh_token is not None:
            _auth.refresh_token = refresh_token.strip().strip('"').strip("'")
        if cookies_path is not None:
            _auth.cookies_path = Path(cookies_path)
        if env_path is not None:
            _auth.env_path = _find_env_file(env_path)
        if on_refresh is not None:
            _auth.on_refresh = on_refresh
    return _auth
