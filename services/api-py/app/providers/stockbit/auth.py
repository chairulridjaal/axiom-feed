"""Shim — re-exports from split modules for backward compat.

New code should import from:
  app.providers.stockbit.jwt      — decode_jwt_claims, jwt_exp, Credentials, AuthenticationError
  app.providers.stockbit.cookies  — load_cookies_array, _get_cookies_path
  app.providers.stockbit.manager  — AuthManager, fetch_credentials
This file keeps old import paths working (tests import from auth).
"""

from .cookies import AUTH_MODE, COOKIES_PATH, _get_auth_mode, _get_cookies_path, load_cookies_array
from .jwt import (
    COOKIES_STALE_MSG,
    JWT_EXPIRED_MSG,
    AuthenticationError,
    Credentials,
    UpstreamAuthError,
    decode_jwt_claims,
    jwt_exp,
    jwt_ttl_seconds,
)
from .manager import (
    BEARER_ENV,
    EXODUS,
    REFRESH_ENV,
    AuthManager,
    exchange_refresh_token,
    fetch_credentials,
    get_auth,
    init_auth,
)

__all__ = [
    "AUTH_MODE",
    "COOKIES_PATH",
    "COOKIES_STALE_MSG",
    "JWT_EXPIRED_MSG",
    "BEARER_ENV",
    "REFRESH_ENV",
    "EXODUS",
    "AuthenticationError",
    "UpstreamAuthError",
    "Credentials",
    "_get_auth_mode",
    "_get_cookies_path",
    "decode_jwt_claims",
    "jwt_exp",
    "jwt_ttl_seconds",
    "load_cookies_array",
    "exchange_refresh_token",
    "fetch_credentials",
    "AuthManager",
    "get_auth",
    "init_auth",
]
