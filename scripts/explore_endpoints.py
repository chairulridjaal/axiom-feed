"""Interactive API Explorer and Upstream Network Recorder for Stockbit/Exodus.

Captures all upstream network requests/responses from Stockbit via Chrome DevTools Protocol (CDP),
filters out noise, extracts JSON payloads & headers, persists deduplicated records to
docs/DISCOVERED_ENDPOINTS.jsonl, and provides diff/analysis against docs/ENDPOINTS.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from websockets.asyncio.client import ClientConnection, connect

# Paths
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = WORKSPACE_ROOT / "docs"
DISCOVERED_FILE = DOCS_DIR / "DISCOVERED_ENDPOINTS.jsonl"
ENDPOINTS_MD = DOCS_DIR / "ENDPOINTS.md"
DEFAULT_USER_DATA = Path("C:/Temp/stockbit-login-profile")

# Target Domains
TARGET_HOSTS = [
    "exodus.stockbit.com",
    "api.stockbit.com",
    "securities.stockbit.com",
    "trading.stockbit.com",
    "wss-jkt.trading.stockbit.com",
    "graphql.stockbit.com",
]

# Noise regex
NOISE_EXT_RE = re.compile(
    r"\.(?:js|jsx|ts|tsx|css|scss|sass|less|png|jpg|jpeg|gif|svg|ico|webp|woff|woff2|ttf|eot|otf|map|mp4|webm|mp3|ogg|wav)(?:\?.*)?$",
    re.IGNORECASE,
)
NOISE_SUBSTRINGS = [
    "clevertap",
    "tiktok",
    "analytics",
    "crisp.chat",
    "sentry.io",
    "hotjar",
    "datadog",
    "amplitude",
    "segment.io",
    "segment.com",
    "branch.io",
    "mixpanel",
    "clarity.ms",
    "intercom",
    "googletagmanager",
    "google-analytics",
    "facebook.com",
    "doubleclick",
    "/_next/static/",
    "/_next/image",
    "statsig",
    "recaptcha",
    "hcaptcha",
    "cloudflareinsights",
]


def find_browser_executable(preferred: str | None = None) -> str | None:
    """Find installed Chromium browser (Brave, Chrome, Edge)."""
    if preferred and Path(preferred).exists():
        return preferred

    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"
        ),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for cand in candidates:
        if Path(cand).exists():
            return cand
    return None


def is_target_url(url: str) -> bool:
    """Check if URL matches target domain and is not noise."""
    if not url or url.startswith("data:") or url.startswith("blob:"):
        return False

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    # Must be a stockbit domain
    if not (hostname == "stockbit.com" or hostname.endswith(".stockbit.com")):
        return False

    # Noise match by extension
    if NOISE_EXT_RE.search(parsed.path):
        return False

    # Noise match by tracker / asset substrings
    url_lower = url.lower()
    for noise in NOISE_SUBSTRINGS:
        if noise in url_lower:
            return False

    # For main web domain stockbit.com: only capture API routes
    if hostname == "stockbit.com":
        if not (parsed.path.startswith("/api") or parsed.path.startswith("/_api")):
            return False

    return True


def categorize_path(path: str, query: str = "") -> str:
    """Assign a logical domain category to an endpoint."""
    text = f"{path}?{query}".lower()

    if any(
        k in text
        for k in [
            "keystats",
            "findata",
            "financial",
            "ratio",
            "balance-sheet",
            "income-statement",
            "cash-flow",
            "statement",
        ]
    ):
        return "Financials & Valuation"
    if any(
        k in text
        for k in [
            "shareholder",
            "insider",
            "ownership",
            "holder",
            "director",
            "commissioner",
            "foreign",
            "domestic",
            "institution",
        ]
    ):
        return "Ownership & Insider Flow"
    if any(
        k in text
        for k in ["screener", "filter", "preset", "factor", "ranking", "scanner"]
    ):
        return "Screener & Factor Models"
    if any(
        k in text
        for k in [
            "consensus",
            "target-price",
            "estimate",
            "analyst",
            "rating",
            "forecast",
        ]
    ):
        return "Consensus & Estimates"
    if any(
        k in text
        for k in [
            "order-trade",
            "trade-book",
            "orderbook",
            "depth",
            "tick",
            "running-trade",
            "marketdetectors",
            "broker",
        ]
    ):
        return "Real-Time Execution & Depth"
    if any(
        k in text
        for k in [
            "news",
            "corpaction",
            "filing",
            "announcement",
            "disclosure",
            "prospectus",
            "calendar",
        ]
    ):
        return "News & Filings"
    if any(k in text for k in ["chart", "price-feed", "candles", "seasonality"]):
        return "Charts & Price Action"
    if any(
        k in text for k in ["emitten", "sector", "company", "profile", "subsidiary"]
    ):
        return "Company & Master Data"
    return "Other / Utilities"


class NetworkRecorder:
    def __init__(self, port: int = 9222, output_file: Path = DISCOVERED_FILE):
        self.port = port
        self.output_file = output_file
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        self._msg_id = 0
        self._pending_requests: dict[str, dict] = {}  # req_id -> dict
        self._cmd_futures: dict[int, asyncio.Future] = {}
        self._attached_sessions: set[str] = set()

        self._seen_exact_calls: set[str] = set()  # "METHOD URL"
        self._seen_paths: set[str] = set()  # "METHOD path"
        self._seen_templates: set[str] = set()  # "METHOD template"

        self.captured_count = 0
        self.bearer_token: str | None = None
        self._load_existing_records()

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _load_existing_records(self):
        """Pre-populate seen sets if DISCOVERED_ENDPOINTS.jsonl exists."""
        if not self.output_file.exists():
            return
        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        m = record.get("method", "GET")
                        u = record.get("url", "")
                        p = record.get("path", "")
                        self._seen_exact_calls.add(f"{m} {u}")
                        self._seen_paths.add(f"{m} {p}")
                    except Exception:
                        pass
        except Exception:
            pass

    async def get_browser_ws_url(self) -> str | None:
        """Fetch the browser debugger WebSocket URL from DevTools port."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"http://127.0.0.1:{self.port}/json/version", timeout=3.0
                )
                if r.status_code == 200:
                    data = r.json()
                    return data.get("webSocketDebuggerUrl")
        except Exception:
            pass
        return None

    def _normalize_path(self, path: str) -> str:
        """Normalize specific tickers or IDs into route templates."""
        # Replace 4-letter uppercase IDX tickers (e.g. BBCA, TLKM)
        p = re.sub(r"/(?:[A-Z]{4})(?=/|$)", "/{symbol}", path)
        # Replace integer IDs
        p = re.sub(r"/\d+(?=/|$)", "/{id}", p)
        # Replace 2-letter broker codes if preceded by broker/activity
        p = re.sub(r"(broker|activity)/[A-Z]{2}(?=/|$)", r"\1/{code}", p)
        return p

    def record_and_alert(self, record: dict):
        """Append deduplicated record to file and print terminal alert."""
        method = record.get("method", "GET")
        url = record.get("url", "")
        path = record.get("path", "")
        status = record.get("status_code", 200)

        exact_key = f"{method} {url}"
        path_key = f"{method} {path}"
        template_key = f"{method} {self._normalize_path(path)}"

        # Deduplication check: if exact call already logged with valid status, skip writing duplicate
        is_exact_new = exact_key not in self._seen_exact_calls
        self._seen_exact_calls.add(exact_key)

        is_path_new = path_key not in self._seen_paths
        self._seen_paths.add(path_key)

        is_template_new = template_key not in self._seen_templates
        self._seen_templates.add(template_key)

        if is_exact_new:
            self.captured_count += 1
            # Append to JSONL
            try:
                with open(self.output_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"[ERROR] Failed writing record: {e}", file=sys.stderr)

        # Quiet real-time notification on unique path
        if is_path_new or is_template_new:
            # Format query string preview if present
            parsed = urlparse(url)
            query_preview = f"?{parsed.query}" if parsed.query else ""
            status_str = f"Status: {status}" if status else "Pending"
            domain = parsed.hostname or "exodus.stockbit.com"
            print(
                f"[NEW] {method} {domain}{path}{query_preview} ({status_str})",
                flush=True,
            )

    async def handle_loading_finished(
        self, ws: ClientConnection, session_id: str | None, req_id: str
    ):
        """Fetch response body via CDP and persist full payload."""
        req_meta = self._pending_requests.pop(req_id, None)
        if not req_meta:
            return

        cmd_id = self._next_id()
        fut = asyncio.get_running_loop().create_future()
        self._cmd_futures[cmd_id] = fut

        cmd_payload: dict = {
            "id": cmd_id,
            "method": "Network.getResponseBody",
            "params": {"requestId": req_id},
        }
        if session_id:
            cmd_payload["sessionId"] = session_id

        try:
            await ws.send(json.dumps(cmd_payload))
            resp_msg = await asyncio.wait_for(fut, timeout=6.0)
        except Exception:
            resp_msg = None
        finally:
            self._cmd_futures.pop(cmd_id, None)

        body_raw = None
        is_json = False
        body_json = None
        resp_keys = []

        if resp_msg and "result" in resp_msg:
            body_raw = resp_msg["result"].get("body", "")
            if resp_msg["result"].get("base64Encoded", False) and body_raw:
                try:
                    import base64

                    body_raw = base64.b64decode(body_raw).decode(
                        "utf-8", errors="replace"
                    )
                except Exception:
                    pass
            if body_raw:
                try:
                    body_json = json.loads(body_raw)
                    is_json = True
                    if isinstance(body_json, dict):
                        resp_keys = list(body_json.keys())
                    elif (
                        isinstance(body_json, list)
                        and body_json
                        and isinstance(body_json[0], dict)
                    ):
                        resp_keys = [
                            f"[{len(body_json)} items] -> {list(body_json[0].keys())}"
                        ]
                except Exception:
                    is_json = False

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": req_meta.get("method", "GET"),
            "url": req_meta.get("url", ""),
            "domain": req_meta.get("domain", ""),
            "path": req_meta.get("path", ""),
            "query_params": req_meta.get("query_params", {}),
            "status_code": req_meta.get("status_code", 200),
            "headers": req_meta.get("headers", {}),
            "request_payload": req_meta.get("post_payload"),
            "response_headers": req_meta.get("response_headers", {}),
            "is_json": is_json,
            "response_keys": resp_keys,
            "response_data": body_json
            if is_json
            else (body_raw[:500] if body_raw else None),
            "category": req_meta.get("category", "Other"),
        }

        self.record_and_alert(record)

    async def attach_target(self, ws: ClientConnection, session_id: str):
        """Enable Network domain on newly attached target."""
        self._attached_sessions.add(session_id)
        cmd_id = self._next_id()
        await ws.send(
            json.dumps(
                {
                    "id": cmd_id,
                    "sessionId": session_id,
                    "method": "Network.enable",
                    "params": {"maxPostDataSize": 65536},
                }
            )
        )

    async def run_listener(self, ws_url: str):
        """Main CDP websocket event loop."""
        async with connect(ws_url, max_size=32 * 1024 * 1024) as ws:
            # 1. Enable Auto-Attach to all tabs/pages
            cmd_attach = self._next_id()
            await ws.send(
                json.dumps(
                    {
                        "id": cmd_attach,
                        "method": "Target.setAutoAttach",
                        "params": {
                            "autoAttach": True,
                            "waitForDebuggerOnStart": False,
                            "flatten": True,
                        },
                    }
                )
            )

            # 2. Discover existing targets
            cmd_disc = self._next_id()
            await ws.send(
                json.dumps(
                    {
                        "id": cmd_disc,
                        "method": "Target.setDiscoverTargets",
                        "params": {"discover": True},
                    }
                )
            )

            print(
                "[RECORDER] CDP Attached successfully. Actively monitoring Stockbit network traffic...\n",
                flush=True,
            )

            async for msg_str in ws:
                try:
                    msg = json.loads(msg_str)
                except Exception:
                    continue

                # Handle RPC Command Responses
                if "id" in msg:
                    cid = msg["id"]
                    if cid in self._cmd_futures:
                        fut = self._cmd_futures[cid]
                        if not fut.done():
                            fut.set_result(msg)
                    continue

                method = msg.get("method", "")
                params = msg.get("params", {})
                session_id = msg.get("sessionId")

                if method == "Target.attachedToTarget":
                    target_info = params.get("targetInfo", {})
                    ttype = target_info.get("type", "")
                    if ttype in ("page", "iframe", "service_worker", "worker"):
                        target_sess_id = params.get("sessionId")
                        if target_sess_id:
                            await self.attach_target(ws, target_sess_id)

                elif method == "Network.requestWillBeSent":
                    req = params.get("request", {})
                    url = req.get("url", "")
                    if not is_target_url(url):
                        continue

                    req_id = params.get("requestId")
                    req_method = req.get("method", "GET")
                    headers = req.get("headers", {})
                    parsed = urlparse(url)

                    # Extract post payload if present
                    post_data = req.get("postData")
                    post_payload = None
                    if post_data:
                        try:
                            post_payload = json.loads(post_data)
                        except Exception:
                            post_payload = post_data

                    # Extract Bearer token if present
                    auth = headers.get("Authorization") or headers.get("authorization")
                    if auth and auth.startswith("Bearer eyJ") and not self.bearer_token:
                        self.bearer_token = auth.split(" ", 1)[1].strip()
                        print(
                            f"[AUTH] Extracted active JWT Bearer Token! (prefix: {self.bearer_token[:18]}...)\n",
                            flush=True,
                        )

                    category = categorize_path(parsed.path, parsed.query)

                    self._pending_requests[req_id] = {
                        "req_id": req_id,
                        "session_id": session_id,
                        "url": url,
                        "domain": parsed.hostname or "",
                        "path": parsed.path,
                        "query_params": parse_qs(parsed.query),
                        "method": req_method,
                        "headers": headers,
                        "post_payload": post_payload,
                        "category": category,
                        "timestamp": params.get("timestamp", time.time()),
                    }

                elif method == "Network.responseReceived":
                    req_id = params.get("requestId")
                    if req_id in self._pending_requests:
                        resp = params.get("response", {})
                        self._pending_requests[req_id]["status_code"] = resp.get(
                            "status", 200
                        )
                        self._pending_requests[req_id]["response_headers"] = resp.get(
                            "headers", {}
                        )

                elif method == "Network.loadingFinished":
                    req_id = params.get("requestId")
                    if req_id in self._pending_requests:
                        asyncio.create_task(
                            self.handle_loading_finished(ws, session_id, req_id)
                        )

                elif method == "Network.loadingFailed":
                    req_id = params.get("requestId")
                    self._pending_requests.pop(req_id, None)

                elif method == "Network.webSocketCreated":
                    url = params.get("url", "")
                    if "stockbit.com" in url:
                        print(f"[NEW WSS] Channel Connected: {url}", flush=True)
                        parsed = urlparse(url)
                        record = {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "method": "WSS",
                            "url": url,
                            "domain": parsed.hostname or "",
                            "path": parsed.path,
                            "query_params": parse_qs(parsed.query),
                            "status_code": 101,
                            "category": "Real-Time Execution & Depth",
                            "is_json": False,
                            "response_keys": ["websocket_stream"],
                            "response_data": {
                                "type": "websocket_handshake",
                                "url": url,
                            },
                        }
                        self.record_and_alert(record)


KNOWN_UPSTREAM_PATTERNS = [
    r"^/chartbit/.+/price/daily",
    r"^/chartbit/.+/price/intraday",
    r"^/charts/.+/daily",
    r"^/charts/.+/performance",
    r"^/emitten/.+/info",
    r"^/emitten/.+/profile",
    r"^/emitten-metadata/subsidiary/.+",
    r"^/order-trade/trade-book",
    r"^/company-price-feed/price-performance/.+",
    r"^/findata-view/company/financial",
    r"^/corpaction/.+",
    r"^/keystats/ratio/v1/.+",
    r"^/order-trade/market-mover",
    r"^/marketdetectors/.+",
    r"^/emitten/sectors",
    r"^/emitten/v3/sector/.+",
    r"^/order-trade/broker/top",
    r"^/order-trade/top-stock",
    r"^/findata-view/marketdetectors/activity/.+",
    r"^/seasonality/.+",
]


def is_known_endpoint(path: str) -> bool:
    """Check if the upstream path is already implemented in axiom-feed."""
    return any(re.search(pat, path, re.IGNORECASE) for pat in KNOWN_UPSTREAM_PATTERNS)


def analyze_discovered_records():
    """Read docs/DISCOVERED_ENDPOINTS.jsonl, diff against known endpoints, and print categorized report."""
    if not DISCOVERED_FILE.exists():
        print(f"[!] No discovered endpoints found at {DISCOVERED_FILE}")
        return

    records = []
    with open(DISCOVERED_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    print(
        "\n================================================================================"
    )
    print(f"       DISCOVERED ENDPOINTS TRIAGE REPORT ({len(records)} calls captured)")
    print(
        "================================================================================\n"
    )

    # Group by:
    # 1. Known vs Brand-New
    # 2. Domain Category
    known_endpoints: dict[str, dict] = {}
    new_endpoints: dict[str, dict] = {}

    for r in records:
        method = r.get("method", "GET")
        path = r.get("path", "")
        key = f"{method} {path}"
        cat = r.get("category", "Other / Utilities")

        entry = {
            "method": method,
            "path": path,
            "url": r.get("url", ""),
            "domain": r.get("domain", ""),
            "query_params": r.get("query_params", {}),
            "status": r.get("status_code", 200),
            "keys": r.get("response_keys", []),
            "sample_response": r.get("response_data"),
            "category": cat,
        }

        if is_known_endpoint(path):
            if key not in known_endpoints:
                known_endpoints[key] = {**entry, "count": 1}
            else:
                known_endpoints[key]["count"] += 1
        else:
            if key not in new_endpoints:
                new_endpoints[key] = {**entry, "count": 1}
            else:
                new_endpoints[key]["count"] += 1

    # Print Brand-New Gems first
    print(
        f"[NEW GEMS] BRAND-NEW / UNDOCUMENTED GEMS ({len(new_endpoints)} unique endpoints)"
    )
    print(f"{'-' * 80}")
    if not new_endpoints:
        print(
            "  (None discovered yet. Browse more features on Stockbit to discover new APIs!)\n"
        )
    else:
        # Group new by category
        new_by_cat: dict[str, list[dict]] = {}
        for item in new_endpoints.values():
            new_by_cat.setdefault(item["category"], []).append(item)

        for cat, items in sorted(new_by_cat.items()):
            print(f"\n  >> Category: {cat} ({len(items)} endpoints)")
            for item in items:
                q_keys = list(item["query_params"].keys())
                q_str = f" ?{q_keys}" if q_keys else ""
                keys_str = ", ".join(item["keys"][:6]) if item["keys"] else "no keys"
                print(
                    f"    * [{item['status']}] {item['method']} {item['domain']}{item['path']}{q_str}"
                )
                print(
                    f"      Response Schema Keys: [{keys_str}] (Hits: {item['count']})"
                )

    print(
        f"\n\n[KNOWN] KNOWN ENDPOINTS (Already implemented in axiom-feed: {len(known_endpoints)} endpoints)"
    )
    print(f"{'-' * 80}")
    for key, item in sorted(known_endpoints.items()):
        q_keys = list(item["query_params"].keys())
        q_str = f" ?{q_keys}" if q_keys else ""
        print(
            f"    + [{item['status']}] {item['method']} {item['domain']}{item['path']}{q_str} (Hits: {item['count']})"
        )

    print(
        "\n================================================================================"
    )
    print(f"  Total Calls Intercepted: {len(records)}")
    print(f"  Unique New Endpoints:    {len(new_endpoints)}")
    print(f"  Known Endpoints Active:  {len(known_endpoints)}")
    print(f"  Raw records saved to:   {DISCOVERED_FILE.resolve()}")
    print(
        "================================================================================\n"
    )


async def main():
    parser = argparse.ArgumentParser(
        description="Stockbit API Network Recorder & Explorer"
    )
    parser.add_argument(
        "--port", type=int, default=9222, help="Remote debugging port (default: 9222)"
    )
    parser.add_argument(
        "--user-data",
        type=str,
        default=str(DEFAULT_USER_DATA),
        help="Browser user-data-dir",
    )
    parser.add_argument(
        "--browser", type=str, default=None, help="Path to browser executable"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze existing captured records without recording",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Do not launch browser; connect to already running instance",
    )
    args = parser.parse_args()

    # Ensure stdout handles utf-8 on Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.analyze:
        analyze_discovered_records()
        return

    recorder = NetworkRecorder(port=args.port, output_file=DISCOVERED_FILE)

    # 1. Check if browser is already listening on debugging port
    ws_url = await recorder.get_browser_ws_url()

    browser_proc = None
    if not ws_url and not args.no_launch:
        exe = find_browser_executable(args.browser)
        if not exe:
            print(
                "[!] No supported Chromium browser found (Brave/Chrome/Edge).",
                file=sys.stderr,
            )
            print(
                "Please install Brave or Chrome, or start your browser with `--remote-debugging-port=9222`."
            )
            return

        user_data_path = Path(args.user_data)
        user_data_path.mkdir(parents=True, exist_ok=True)

        browser_name = Path(exe).name
        print(f"[*] Launching {browser_name} with remote debugging port {args.port}...")
        print(f"[*] Profile directory: {user_data_path}")

        cmd = [
            exe,
            f"--remote-debugging-port={args.port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={user_data_path}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://stockbit.com",
        ]
        browser_proc = subprocess.Popen(cmd)

        # Wait for debugger port
        for _ in range(30):
            await asyncio.sleep(1.0)
            ws_url = await recorder.get_browser_ws_url()
            if ws_url:
                break

    if not ws_url:
        print(f"[!] Could not connect to browser on port {args.port}.")
        print(
            f"Ensure the browser is running with `--remote-debugging-port={args.port}`."
        )
        if browser_proc:
            browser_proc.terminate()
        return

    print("==================================================================")
    print("  Stockbit Upstream API Network Recorder — LIVE                   ")
    print("==================================================================")
    print(f"  Browser DevTools URL: {ws_url}")
    print(f"  Target File:          {DISCOVERED_FILE.resolve()}")
    print("------------------------------------------------------------------")
    print("  READY! You can now freely navigate Stockbit in the browser window.")
    print("  Click any stocks, orderbooks, broker flows, screeners, reports,")
    print("  insider filings, community feeds, or settings.")
    print("------------------------------------------------------------------")
    print("  Press Ctrl+C at any time when you are done to generate the summary.")
    print("==================================================================\n")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _sig_handler():
        stop_event.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _sig_handler)
        except (NotImplementedError, AttributeError):
            pass

    listener_task = asyncio.create_task(recorder.run_listener(ws_url))

    def _on_listener_done(t):
        stop_event.set()

    listener_task.add_done_callback(_on_listener_done)

    try:
        await stop_event.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        if not listener_task.done():
            listener_task.cancel()
        print("\n\n[RECORDER] Recording session finished. Summary of captured data:")
        analyze_discovered_records()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
