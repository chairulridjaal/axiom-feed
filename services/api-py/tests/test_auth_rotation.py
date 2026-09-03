import base64
import json
import time
from unittest.mock import AsyncMock

import pytest

from app.providers.stockbit.auth import (
    Credentials,
    UpstreamAuthError,
    exchange_refresh_token,
    init_auth,
)
from app.providers.stockbit.manager import _read_env_tokens, _update_env_file


def _make_jwt(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": exp, "iat": exp - 86400}).encode())
        .decode()
        .rstrip("=")
    )
    sig = "sig"
    return f"{header}.{payload}.{sig}"


def test_credentials_refresh_properties():
    now = int(time.time())
    access = _make_jwt(now + 3600 * 12)
    refresh = _make_jwt(now + 86400 * 5)
    c = Credentials(
        user_id="123",
        ws_key="key",
        bearer_token=access,
        refresh_token=refresh,
        exp=now + 3600 * 12,
        refresh_exp=now + 86400 * 5,
    )
    assert c.is_expired is False
    assert c.is_refresh_expired is False
    assert c.ttl is not None and c.ttl > 0
    assert c.refresh_ttl is not None and c.refresh_ttl > 86400 * 4
    assert c.warn_soon is False
    assert c.warn_soon_refresh is False


def test_update_and_read_env_file(tmp_path):
    env_file = tmp_path / ".env"
    initial_content = (
        '# Some config\nAPI_HOST=127.0.0.1\nSTOCKBIT_BEARER_TOKEN="old_bearer"\nOTHER_VAR=xyz\n'
    )
    env_file.write_text(initial_content, encoding="utf-8")

    _update_env_file(
        env_file,
        {"STOCKBIT_BEARER_TOKEN": "new_bearer", "STOCKBIT_REFRESH_TOKEN": "new_refresh"},
    )

    b, r = _read_env_tokens(env_file)
    assert b == "new_bearer"
    assert r == "new_refresh"

    content = env_file.read_text(encoding="utf-8")
    assert "API_HOST=127.0.0.1" in content
    assert "OTHER_VAR=xyz" in content


@pytest.mark.asyncio
async def test_exchange_refresh_token_success():
    fake_resp = {
        "data": {
            "access": {"token": "access_token_abc"},
            "refresh": {"token": "refresh_token_xyz"},
        }
    }

    mock_client = AsyncMock()
    mock_post_resp = AsyncMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json = lambda: fake_resp
    mock_post_resp.raise_for_status = lambda: None
    mock_client.post.return_value = mock_post_resp

    access, refresh = await exchange_refresh_token("valid_refresh_token", client=mock_client)
    assert access == "access_token_abc"
    assert refresh == "refresh_token_xyz"


@pytest.mark.asyncio
async def test_exchange_refresh_token_401():
    mock_client = AsyncMock()
    mock_post_resp = AsyncMock()
    mock_post_resp.status_code = 401
    mock_post_resp.text = "Unauthorized"
    mock_post_resp.raise_for_status = lambda: None
    mock_client.post.return_value = mock_post_resp

    with pytest.raises(UpstreamAuthError):
        await exchange_refresh_token("invalid_refresh_token", client=mock_client)


def test_auth_manager_health_with_refresh(tmp_path):
    now = int(time.time())
    access = _make_jwt(now + 7200)
    refresh = _make_jwt(now + 86400 * 7)
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text("[]", encoding="utf-8")

    mgr = init_auth(
        bearer_token=access,
        refresh_token=refresh,
        cookies_path=cookies_file,
    )
    h = mgr.health()
    assert h["bearer_set"] is True
    assert h["refresh_token_set"] is True
    assert h["refresh_ttl_seconds"] is not None and h["refresh_ttl_seconds"] > 86400 * 6
