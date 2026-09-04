"""Interactive helper to log into Stockbit and capture Bearer + Refresh tokens into .env."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path

import httpx

BEARER_ENV = "STOCKBIT_BEARER_TOKEN"
REFRESH_ENV = "STOCKBIT_REFRESH_TOKEN"


def _find_env() -> Path:
    cands = [Path(".env"), Path("../.env"), Path("../../.env")]
    for c in cands:
        if c.exists():
            return c.resolve()
    return Path(".env").resolve()


def _update_env(env_path: Path, updates: dict[str, str]) -> None:
    content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = content.splitlines()
    found = set()
    new_lines = []
    for line in lines:
        matched = False
        for k, v in updates.items():
            if re.match(rf"^\s*{re.escape(k)}\s*=", line):
                new_lines.append(f'{k}="{v}"')
                found.add(k)
                matched = True
                break
        if not matched:
            new_lines.append(line)
    for k, v in updates.items():
        if k not in found:
            new_lines.append(f'{k}="{v}"')
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _find_browser() -> str | None:
    cands = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in cands:
        if Path(c).exists():
            return c
    return None


async def main():
    browser_exe = _find_browser()
    if not browser_exe:
        print("No supported Chromium browser found (Brave/Chrome/Edge).")
        return

    port = 9222
    user_data = Path("C:/Temp/stockbit-login-profile")
    user_data.mkdir(parents=True, exist_ok=True)

    print(f"Launching browser ({Path(browser_exe).name}) for Stockbit login...")
    args = [
        browser_exe,
        f"--user-data-dir={user_data}",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "https://stockbit.com/login",
    ]
    proc = subprocess.Popen(args)

    try:
        from websocket import create_connection
    except ImportError:
        print("Installing websocket-client...")
        subprocess.run(["uv", "pip", "install", "websocket-client"], check=True)
        from websocket import create_connection

    print("Waiting for browser debugger connection...")
    tabs = []
    for _ in range(30):
        await asyncio.sleep(1)
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"http://127.0.0.1:{port}/json/list", timeout=2)
                tabs = r.json()
                if tabs:
                    break
        except Exception:
            pass

    if not tabs:
        print("Could not connect to browser debugger.")
        proc.terminate()
        return

    page = [
        t
        for t in tabs
        if "stockbit.com" in (t.get("url", "") or "") and t.get("type") == "page"
    ]
    if not page:
        page = [t for t in tabs if t.get("type") == "page"]

    ws_url = page[0]["webSocketDebuggerUrl"]
    ws = create_connection(ws_url, timeout=30)
    ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))

    print("\nPlease log into Stockbit in the opened browser window.")
    print("Capturing session tokens...")

    access_token = None
    refresh_token = None
    deadline = time.time() + 300

    def _recv_until(ws, want_id: int, timeout: float = 15):
        """Wait for a CDP response id without hanging forever."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                m = json.loads(ws.recv())
            except Exception:
                continue
            if m.get("id") == want_id:
                return m
        return None

    while time.time() < deadline:
        try:
            m = json.loads(ws.recv())
        except Exception:
            # Idle periods raise recv timeouts — keep listening until deadline.
            continue

        method = m.get("method", "")
        if method == "Network.requestWillBeSent":
            req = m.get("params", {}).get("request", {})
            auth = req.get("headers", {}).get("Authorization", "")
            if auth.startswith("Bearer eyJ") and "exodus.stockbit.com" in req.get(
                "url", ""
            ):
                tok = auth.split(" ", 1)[1].strip()
                if not access_token:
                    access_token = tok
                    print("Found Bearer token!")

        elif method == "Network.responseReceived":
            res = m.get("params", {}).get("response", {})
            url = res.get("url", "")
            mime = res.get("mimeType", "")
            # Scan every JSON response body on any host for a credential mint.
            # The mint endpoint is not guaranteed to live on exodus or to carry
            # a keyword in its URL — host/keyword filters are how captures
            # silently miss while the Bearer (sent on request headers) is found.
            if "json" not in mime:
                continue
            req_id = m.get("params", {}).get("requestId")
            try:
                ws.send(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "Network.getResponseBody",
                            "params": {"requestId": req_id},
                        }
                    )
                )
                m2 = _recv_until(ws, 2)
                if not m2:
                    continue
                body = m2.get("result", {}).get("body", "")
                acc = re.search(r'"access"\s*:\s*\{\s*"token"\s*:\s*"([^"]+)"', body)
                ref = re.search(r'"refresh"\s*:\s*\{\s*"token"\s*:\s*"([^"]+)"', body)
                if acc:
                    access_token = acc.group(1)
                    print("Found Bearer token from login response!")
                if ref:
                    refresh_token = ref.group(1)
                    print("Found 7-day Refresh token!")
            except Exception:
                pass

        if access_token and refresh_token:
            break

    # Also capture all session cookies from browser
    try:
        ws.send(
            json.dumps(
                {
                    "id": 3,
                    "method": "Network.getCookies",
                    "params": {
                        "urls": ["https://stockbit.com", "https://exodus.stockbit.com"]
                    },
                }
            )
        )
        m3 = _recv_until(ws, 3)
        if m3:
            cookies_list = m3.get("result", {}).get("cookies", [])
            if cookies_list:
                # Canonical location: next to the .env being updated, so the
                # server finds one pair regardless of its working directory.
                try:
                    env_dir = _find_env().parent
                except Exception:
                    env_dir = Path(".")
                cookies_path = env_dir / "cookies.json"
                cookies_path.write_text(
                    json.dumps(cookies_list, indent=2), encoding="utf-8"
                )
                print(
                    f"Exported {len(cookies_list)} session cookies to {cookies_path.resolve()}!"
                )
    except Exception:
        pass

    ws.close()
    proc.terminate()

    if access_token:
        env_path = _find_env()
        updates = {BEARER_ENV: access_token}
        if refresh_token:
            updates[REFRESH_ENV] = refresh_token
        _update_env(env_path, updates)
        print(f"\nSuccessfully saved tokens to {env_path}!")
    else:
        print("\nCould not capture access token.")


if __name__ == "__main__":
    asyncio.run(main())
