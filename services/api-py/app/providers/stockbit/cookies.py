from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from .jwt import COOKIES_STALE_MSG, AuthenticationError


def _get_auth_mode() -> str:
    return os.getenv("AUTH_MODE", "cookies")


def _get_cookies_path() -> Path:
    return Path(os.getenv("STOCKBIT_COOKIES_PATH", "./cookies.json"))


def load_cookies_array(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        path = _get_cookies_path()
    if not path.exists():
        raise AuthenticationError(
            f"Cookies file not found: {path}. " + COOKIES_STALE_MSG.format(path=path)
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise AuthenticationError(f"Invalid JSON in cookies file {path}: {e}")
    if not isinstance(data, list):
        raise AuthenticationError(
            f"Cookies file must be JSON array, got {type(data).__name__}: {path}"
        )
    return data


def _cookies_to_httpx_jar(cookies: list[dict[str, Any]]) -> httpx.Cookies:
    jar = httpx.Cookies()
    for c in cookies:
        try:
            jar.set(
                name=c.get("name", ""),
                value=c.get("value", ""),
                domain=c.get("domain", ".stockbit.com"),
                path=c.get("path", "/"),
            )
        except Exception:
            continue
    return jar
