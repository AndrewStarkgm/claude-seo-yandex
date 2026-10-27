#!/usr/bin/env python3
"""
Yandex.Webmaster API v4 client for Claude SEO.

Usage:
    python yandex_webmaster.py hosts [--json]
    python yandex_webmaster.py summary https://example.ru [--json]
    python yandex_webmaster.py diagnostics https://example.ru [--all] [--json]
    python yandex_webmaster.py queries https://example.ru [--days 28] [--limit 50] [--json]
    python yandex_webmaster.py indexing https://example.ru [--days 90] [--json]
    python yandex_webmaster.py sitemaps https://example.ru [--json]
    python yandex_webmaster.py important https://example.ru [--json]
    python yandex_webmaster.py recrawl https://example.ru --urls-file urls.txt [--dry-run] [--json]
    python yandex_webmaster.py quota https://example.ru [--json]
    python yandex_webmaster.py audit https://example.ru [--json]      # summary + diagnostics + top queries

Host may be given as a URL (https://example.ru) or a Webmaster host_id (https:example.ru:443).
"""

import argparse
import datetime as dt
import json
import os
import sys
from urllib.parse import quote, urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
from yandex_auth import api_request, host_id_from_url, load_config  # noqa: E402

BASE = "https://api.webmaster.yandex.net/v4"

# Diagnostic codes with their meaning for a human-readable report.
PROBLEM_NOTES = {
    "THREATS": "Угрозы безопасности (вирусы, вредоносный код)",
    "DISALLOWED_IN_ROBOTS": "Главная или сайт закрыт в robots.txt",
    "DNS_ERROR": "Ошибка DNS",
    "CONNECT_FAILED": "Сайт недоступен для робота",
    "MAIN_PAGE_ERROR": "Главная отдаёт ошибку",
    "URL_ALERT_5XX": "Много ответов 5xx",
    "SLOW_AVG_RESPONSE_TIME": "Медленный ответ сервера",
    "NO_REGIONS": "Регион сайта не задан (Вебмастер → Информация о сайте → Региональность)",
    "NOT_IN_SPRAV": "Нет связанной организации в Яндекс.Бизнесе",
    "TOO_MANY_DOMAINS_ON_SEARCH": "Много поддоменов в поиске - Яндекс может склеить или понизить",
    "DUPLICATE_PAGES": "Дубли страниц",
    "DUPLICATE_CONTENT_ATTRS": "Одинаковые title/description",
    "NO_METRIKA_COUNTER_BINDING": "Счётчик Метрики не привязан",
    "NO_METRIKA_COUNTER_CRAWL_ENABLED": "В Метрике не разрешён обход по счётчику",
    "MAIN_MIRROR_IS_NOT_HTTPS": "Главное зеркало не на HTTPS",
    "ERRORS_IN_SITEMAPS": "Ошибки в sitemap",
    "NO_SITEMAPS": "Sitemap не найден",
    "SOFT_404": "Страницы-заглушки с кодом 200 вместо 404",
    "INSIGNIFICANT_CGI_PARAMETER": "Незначащие GET-параметры (нужен Clean-param)",
}
SEVERITY_ORDER = {"FATAL": 0, "CRITICAL": 1, "POSSIBLE_PROBLEM": 2, "RECOMMENDATION": 3}


def _token() -> str:
    token = load_config().get("oauth_token")
    if not token:
        print("Error: no Yandex OAuth token. Run /seo yandex setup.", file=sys.stderr)
        sys.exit(1)
    return token


_user_id_cache = None


def user_id(token: str) -> int:
    global _user_id_cache
    if _user_id_cache is None:
        r = api_request("GET", f"{BASE}/user", token)
        if not r["ok"]:
            print(f"Error: Webmaster /user failed: {r['error']}", file=sys.stderr)
            sys.exit(1)
        _user_id_cache = r["data"]["user_id"]
    return _user_id_cache


def _host_path(token: str, host: str) -> str:
    return f"{BASE}/user/{user_id(token)}/hosts/{quote(host_id_from_url(host), safe='')}"


def _dates(days: int):
    end = dt.date.today() - dt.timedelta(days=1)
    return (end - dt.timedelta(days=days - 1)).isoformat(), end.isoformat()


def cmd_hosts(token, args):
    r = api_request("GET", f"{BASE}/user/{user_id(token)}/hosts", token)
    if not r["ok"]:
        return r
    hosts = [{"host_id": h["host_id"], "url": h.get("unicode_host_url") or h.get("ascii_host_url"),
              "verified": h.get("verified"), "main_mirror": (h.get("main_mirror") or {}).get("unicode_host_url")
              if isinstance(h.get("main_mirror"), dict) else h.get("main_mirror")}
             for h in r["data"].get("hosts", [])]
    return {"ok": True, "data": {"hosts": hosts, "count": len(hosts)}}


def cmd_summary(token, args):
    r = api_request("GET", _host_path(token, args.host) + "/summary", token)
    if r["ok"]:
        d = r["data"]
        r["data"] = {"host": args.host, "iks_sqi": d.get("sqi"),
                     "searchable_pages": d.get("searchable_pages_count"),
                     "excluded_pages": d.get("excluded_pages_count"),
                     "site_problems": d.get("site_problems", {})}
    return r


def cmd_diagnostics(token, args):
    r = api_request("GET", _host_path(token, args.host) + "/diagnostics", token)
    if not r["ok"]:
        return r
    items = []
    for code, p in (r["data"].get("problems") or {}).items():
        if p.get("state") != "PRESENT" and not args.all:
            continue
        items.append({"code": code, "severity": p.get("severity"), "state": p.get("state"),
                      "updated": p.get("last_state_update"), "note": PROBLEM_NOTES.get(code, "")})
    items.sort(key=lambda x: (SEVERITY_ORDER.get(x["severity"], 9), x["code"]))
    return {"ok": True, "data": {"host": args.host, "problems": items,
                                 "present": sum(1 for i in items if i["state"] == "PRESENT")}}


def cmd_queries(token, args):
    d1, d2 = _dates(args.days)
    params = [("order_by", args.order_by), ("date_from", d1), ("date_to", d2), ("limit", min(args.limit, 500))]
    for ind in ("TOTAL_SHOWS", "TOTAL_CLICKS", "AVG_SHOW_POSITION", "AVG_CLICK_POSITION"):
        params.append(("query_indicator", ind))
    r = api_request("GET", _host_path(token, args.host) + "/search-queries/popular", token, params=params)
    if not r["ok"]:
        return r
    rows = []
    for q in r["data"].get("queries", []):
        ind = q.get("indicators", {})
        shows, clicks = ind.get("TOTAL_SHOWS") or 0, ind.get("TOTAL_CLICKS") or 0
        rows.append({"query": q.get("query_text"), "shows": shows, "clicks": clicks,
                     "ctr": round(clicks / shows * 100, 2) if shows else 0,
                     "avg_show_pos": ind.get("AVG_SHOW_POSITION"), "avg_click_pos": ind.get("AVG_CLICK_POSITION")})
    return {"ok": True, "data": {"host": args.host, "period": [d1, d2], "queries": rows,
                                 "total_shows": sum(x["shows"] for x in rows),
                                 "total_clicks": sum(x["clicks"] for x in rows)}}


def cmd_indexing(token, args):
    d1, d2 = _dates(args.days)
    params = {"date_from": d1 + "T00:00:00Z", "date_to": d2 + "T23:59:59Z"}
    base = _host_path(token, args.host)
    out = {"host": args.host, "period": [d1, d2]}
    r = api_request("GET", base + "/search-urls/in-search/history", token, params=params)
    if r["ok"]:
        hist = r["data"].get("history", [])
        out["in_search"] = {"first": hist[0] if hist else None, "last": hist[-1] if hist else None, "points": len(hist)}
    else:
        out["in_search_error"] = r["error"]
    r = api_request("GET", base + "/indexing/history", token, params=params)
    if r["ok"]:
        out["crawled_by_http_code"] = {k: sum(p.get("value", 0) for p in v)
                                       for k, v in (r["data"].get("indicators") or {}).items()}
    else:
        out["indexing_error"] = r["error"]
    return {"ok": True, "data": out}


def cmd_sitemaps(token, args):
    r = api_request("GET", _host_path(token, args.host) + "/sitemaps", token, params={"limit": 100})
    if r["ok"]:
        r["data"] = {"host": args.host, "sitemaps": [
            {"url": s.get("sitemap_url"), "urls": s.get("urls_count"), "errors": s.get("errors_count"),
             "last_access": s.get("last_access_date"), "type": s.get("sitemap_type")}
            for s in r["data"].get("sitemaps", [])]}
    return r


def cmd_important(token, args):
    r = api_request("GET", _host_path(token, args.host) + "/important-urls", token)
    if r["ok"]:
        r["data"] = {"host": args.host, "urls": [
            {"url": u.get("url"), "status": (u.get("indexing_status") or {}).get("status"),
             "http_code": (u.get("indexing_status") or {}).get("http_code"),
             "in_search": (u.get("search_status") or {}).get("searchable"),
             "excluded_reason": (u.get("search_status") or {}).get("excluded_url_status"),
             "title": (u.get("search_status") or {}).get("title")}
            for u in r["data"].get("urls", [])]}
    return r


def cmd_quota(token, args):
    return api_request("GET", _host_path(token, args.host) + "/recrawl/quota", token)


def cmd_recrawl(token, args):
    host = urlparse(args.host if "://" in args.host else "https://" + args.host).hostname
    with open(args.urls_file, encoding="utf-8") as f:
        urls = [u.strip() for u in f if u.strip() and not u.startswith("#")]
    foreign = [u for u in urls if urlparse(u).hostname != host]
    urls = [u for u in urls if urlparse(u).hostname == host]
    q = cmd_quota(token, args)
    remainder = (q.get("data") or {}).get("quota_remainder") if q["ok"] else None
    if remainder is not None:
        urls = urls[:remainder]
    if args.dry_run:
        return {"ok": True, "data": {"would_submit": len(urls), "quota_remainder": remainder,
                                     "skipped_foreign_host": len(foreign), "sample": urls[:5]}}
    done, failed = 0, []
    base = _host_path(token, args.host) + "/recrawl/queue"
    for u in urls:
        r = api_request("POST", base, token, body={"url": u})
        if r["ok"]:
            done += 1
        else:
            failed.append({"url": u, "error": r["error"]})
            if r["status"] in (403, 429):
                break
    return {"ok": True, "data": {"submitted": done, "failed": failed[:20], "failed_count": len(failed),
                                 "quota_before": remainder, "skipped_foreign_host": len(foreign)}}


def cmd_audit(token, args):
    args.all = False
    args.days, args.limit, args.order_by = 28, 20, "TOTAL_SHOWS"
    out = {}
    for name, fn in (("summary", cmd_summary), ("diagnostics", cmd_diagnostics), ("queries", cmd_queries)):
        r = fn(token, args)
        out[name] = r["data"] if r["ok"] else {"error": r["error"]}
    return {"ok": True, "data": out}


COMMANDS = {"hosts": cmd_hosts, "summary": cmd_summary, "diagnostics": cmd_diagnostics, "queries": cmd_queries,
            "indexing": cmd_indexing, "sitemaps": cmd_sitemaps, "important": cmd_important,
            "quota": cmd_quota, "recrawl": cmd_recrawl, "audit": cmd_audit}


def main() -> int:
    p = argparse.ArgumentParser(description="Yandex.Webmaster API v4 for Claude SEO")
    p.add_argument("command", choices=sorted(COMMANDS))
    p.add_argument("host", nargs="?", help="Site URL or host_id (not needed for 'hosts')")
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--order-by", default="TOTAL_SHOWS", choices=["TOTAL_SHOWS", "TOTAL_CLICKS"])
    p.add_argument("--all", action="store_true", help="diagnostics: include ABSENT/UNDEFINED")
    p.add_argument("--urls-file", help="recrawl: file with one URL per line")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.command != "hosts" and not args.host:
        args.host = load_config().get("default_host")
        if not args.host:
            p.error("host is required (or set default_host in yandex-api.json)")
    if args.command == "recrawl" and not args.urls_file:
        p.error("recrawl requires --urls-file")
    result = COMMANDS[args.command](_token(), args)
    if not result["ok"]:
        print(f"Error ({result.get('status')}): {result['error']}", file=sys.stderr)
        return 1
    print(json.dumps(result["data"], ensure_ascii=False, indent=2 if args.json else 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
