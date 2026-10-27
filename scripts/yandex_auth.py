#!/usr/bin/env python3
"""
Yandex API credentials and shared HTTP client for Claude SEO.

One OAuth token covers Yandex.Webmaster, Yandex.Metrika and (when access is
approved) the Wordstat API. The token is never printed or written to reports.

Config file: ~/.config/claude-seo/yandex-api.json
    {
      "oauth_token": "<YANDEX_OAUTH_TOKEN>",
      "wordstat_token": "<optional, defaults to oauth_token>",
      "metrika_counter_id": 12345678,
      "default_host": "https://example.ru"
    }

Environment fallbacks: YANDEX_OAUTH_TOKEN, YANDEX_WORDSTAT_TOKEN,
YANDEX_METRIKA_COUNTER, YANDEX_DEFAULT_HOST.

Usage:
    python yandex_auth.py --check [--json]
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Optional
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

CONFIG_PATH = os.path.expanduser("~/.config/claude-seo/yandex-api.json")
USER_AGENT = "ClaudeSEO-Yandex/1.0"
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.35  # Webmaster API allows ~10 rps; stay well below

_last_request = 0.0


def load_config() -> dict:
    """Load config file, then fill gaps from environment variables."""
    config = {
        "oauth_token": None,
        "wordstat_token": None,
        "metrika_counter_id": None,
        "default_host": None,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config.update({k: v for k, v in json.load(f).items() if v})
        except (OSError, json.JSONDecodeError) as e:
            print(f"Warning: Could not read {CONFIG_PATH}: {e}", file=sys.stderr)
    config["oauth_token"] = config["oauth_token"] or os.environ.get("YANDEX_OAUTH_TOKEN")
    config["wordstat_token"] = (config["wordstat_token"] or os.environ.get("YANDEX_WORDSTAT_TOKEN")
                                or config["oauth_token"])
    config["metrika_counter_id"] = config["metrika_counter_id"] or os.environ.get("YANDEX_METRIKA_COUNTER")
    config["default_host"] = config["default_host"] or os.environ.get("YANDEX_DEFAULT_HOST")
    return config


def redact(text: object) -> str:
    """Strip anything that looks like an OAuth token from error text."""
    s = str(text)
    s = re.sub(r"(OAuth|Bearer)\s+[A-Za-z0-9_\-\.]+", r"\1 <redacted>", s)
    return re.sub(r"y[0-3]_[A-Za-z0-9_\-]{20,}", "<redacted>", s)


def _throttle():
    global _last_request
    wait = REQUEST_DELAY - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def api_request(method: str, url: str, token: str, *, scheme: str = "OAuth",
                params: Optional[object] = None, body: Optional[dict] = None) -> dict:
    """
    Call a Yandex API. Returns {"ok": True, "data": ...} or {"ok": False, "error": ..., "status": ...}.
    Retries once on 429/5xx. Token never appears in the result.
    """
    headers = {"Authorization": f"{scheme} {token}", "User-Agent": USER_AGENT,
               "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    for attempt in range(2):
        _throttle()
        try:
            resp = requests.request(method, url, headers=headers, params=params,
                                    data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
                                    timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            if attempt == 0:
                time.sleep(2)
                continue
            return {"ok": False, "error": redact(e), "status": None}
        if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
            time.sleep(3)
            continue
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {"raw": resp.text[:500]}
        if resp.status_code >= 400:
            msg = data.get("error_message") or data.get("message") or data.get("error_code") or resp.text[:300]
            return {"ok": False, "error": redact(msg), "status": resp.status_code}
        return {"ok": True, "data": data, "status": resp.status_code}
    return {"ok": False, "error": "unreachable", "status": None}


def host_id_from_url(url: str) -> str:
    """https://example.ru/ -> https:example.ru:443 (Webmaster API host_id format)."""
    if re.match(r"^https?:[^/]+:\d+$", url):
        return url
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError(f"Not a site URL: {url}")
    port = p.port or (443 if p.scheme == "https" else 80)
    return f"{p.scheme}:{p.hostname.lower()}:{port}"


def check(config: dict) -> dict:
    """Probe each API with the configured token. Never returns the token."""
    out = {"config_path": CONFIG_PATH, "config_file_exists": os.path.exists(CONFIG_PATH),
           "webmaster": "no_token", "metrika": "no_token", "wordstat": "no_token",
           "metrika_counter_id": config.get("metrika_counter_id"), "default_host": config.get("default_host")}
    token = config.get("oauth_token")
    if token:
        r = api_request("GET", "https://api.webmaster.yandex.net/v4/user", token)
        out["webmaster"] = "ok" if r["ok"] else f"error {r['status']}: {r['error']}"
        if r["ok"]:
            out["webmaster_user_id"] = r["data"].get("user_id")
        r = api_request("GET", "https://api-metrika.yandex.net/management/v1/counters", token,
                        params={"per_page": 1})
        out["metrika"] = "ok" if r["ok"] else f"error {r['status']}: {r['error']}"
    wtoken = config.get("wordstat_token")
    if wtoken:
        r = api_request("POST", "https://api.wordstat.yandex.net/v1/userInfo", wtoken, scheme="Bearer", body={})
        out["wordstat"] = "ok" if r["ok"] else f"error {r['status']}: {r['error']}"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Yandex API credentials for Claude SEO")
    parser.add_argument("--check", action="store_true", help="Probe Webmaster, Metrika and Wordstat")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if not config.get("oauth_token") and not config.get("wordstat_token"):
        result = {"configured": False,
                  "hint": f"Create {CONFIG_PATH} with oauth_token, or set YANDEX_OAUTH_TOKEN. See /seo yandex setup."}
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result["hint"])
        return 1
    result = check(config) if args.check else {"configured": True}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for k, v in result.items():
            print(f"{k:22s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
