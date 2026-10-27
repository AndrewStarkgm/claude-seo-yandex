#!/usr/bin/env python3
"""
Yandex.Metrika Reporting API client for Claude SEO - organic search traffic.

Usage:
    python yandex_metrika.py counters [--json]
    python yandex_metrika.py organic   [--counter N] [--days 28] [--json]   # by search engine, week over week
    python yandex_metrika.py landings  [--counter N] [--days 28] [--engine yandex|google] [--limit 30] [--json]
    python yandex_metrika.py cities    [--counter N] [--days 28] [--engine yandex] [--json]
    python yandex_metrika.py hosts     [--counter N] [--days 28] [--json]     # organic by start domain (subdomains)
    python yandex_metrika.py phrases   [--counter N] [--days 28] [--json]     # search phrases (mostly "not set" - Yandex hides them)

Counter id: --counter, or metrika_counter_id in ~/.config/claude-seo/yandex-api.json.
"""

import argparse
import datetime as dt
import json
import os
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
from yandex_auth import api_request, load_config  # noqa: E402

API = "https://api-metrika.yandex.net/stat/v1/data"
ORGANIC = "ym:s:lastTrafficSource=='organic'"


def _period(days: int, shift: int = 0):
    end = dt.date.today() - dt.timedelta(days=1 + shift)
    return (end - dt.timedelta(days=days - 1)).isoformat(), end.isoformat()


def _report(token, counter, d1, d2, metrics, dimensions="", filters=ORGANIC, limit=100, sort=None):
    params = {"ids": counter, "metrics": metrics, "date1": d1, "date2": d2, "limit": limit,
              "accuracy": "full", "filters": filters}
    if dimensions:
        params["dimensions"] = dimensions
    if sort:
        params["sort"] = sort
    r = api_request("GET", API, token, params=params)
    if not r["ok"]:
        return r
    names = metrics.split(",")
    rows = []
    for row in r["data"].get("data", []):
        rec = {"dims": [d.get("name") if d.get("name") is not None else "(not set)"
                        for d in row.get("dimensions", [])]}
        rec.update({n.split(":")[-1]: v for n, v in zip(names, row.get("metrics", []))})
        rows.append(rec)
    totals = dict(zip([n.split(":")[-1] for n in names], r["data"].get("totals", [])))
    return {"ok": True, "data": {"period": [d1, d2], "rows": rows, "totals": totals,
                                 "sampled": r["data"].get("sampled")}}


def _engine_filter(engine):
    return ORGANIC + (f" AND ym:s:lastSearchEngineRoot=='{engine}'" if engine else "")


METRICS = "ym:s:visits,ym:s:bounceRate,ym:s:pageDepth,ym:s:avgVisitDurationSeconds"


def cmd_counters(token, counter, args):
    r = api_request("GET", "https://api-metrika.yandex.net/management/v1/counters", token, params={"per_page": 200})
    if r["ok"]:
        r["data"] = [{"id": c["id"], "name": c.get("name"), "site": c.get("site2", {}).get("site") or c.get("site")}
                     for c in r["data"].get("counters", [])]
    return r


def cmd_organic(token, counter, args):
    cur = _report(token, counter, *_period(args.days), METRICS, "ym:s:lastSearchEngineRoot")
    prev = _report(token, counter, *_period(args.days, args.days), METRICS, "ym:s:lastSearchEngineRoot")
    if not cur["ok"]:
        return cur
    pv = {r["dims"][0]: r["visits"] for r in (prev["data"]["rows"] if prev["ok"] else [])}
    for r in cur["data"]["rows"]:
        before = pv.get(r["dims"][0])
        r["visits_prev"] = before
        r["change_pct"] = round((r["visits"] - before) / before * 100, 1) if before else None
    cur["data"]["previous_period"] = prev["data"]["period"] if prev["ok"] else None
    return cur


def cmd_landings(token, counter, args):
    return _report(token, counter, *_period(args.days), METRICS, "ym:s:startURLPathFull",
                   _engine_filter(args.engine), args.limit, "-ym:s:visits")


def cmd_cities(token, counter, args):
    return _report(token, counter, *_period(args.days), "ym:s:visits", "ym:s:regionCity",
                   _engine_filter(args.engine), args.limit, "-ym:s:visits")


def cmd_hosts(token, counter, args):
    return _report(token, counter, *_period(args.days), "ym:s:visits",
                   "ym:s:startURLDomain,ym:s:lastSearchEngineRoot", ORGANIC, args.limit, "-ym:s:visits")


def cmd_phrases(token, counter, args):
    return _report(token, counter, *_period(args.days), "ym:s:visits", "ym:s:lastSearchPhrase",
                   _engine_filter(args.engine), args.limit, "-ym:s:visits")


COMMANDS = {"counters": cmd_counters, "organic": cmd_organic, "landings": cmd_landings,
            "cities": cmd_cities, "hosts": cmd_hosts, "phrases": cmd_phrases}


def main() -> int:
    p = argparse.ArgumentParser(description="Yandex.Metrika organic traffic for Claude SEO")
    p.add_argument("command", choices=sorted(COMMANDS))
    p.add_argument("--counter")
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--engine", choices=["yandex", "google", "bing", "mail_ru"])
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cfg = load_config()
    token = cfg.get("oauth_token")
    if not token:
        print("Error: no Yandex OAuth token. Run /seo yandex setup.", file=sys.stderr)
        return 1
    counter = args.counter or cfg.get("metrika_counter_id")
    if args.command != "counters" and not counter:
        p.error("counter id required (--counter or metrika_counter_id in yandex-api.json)")
    r = COMMANDS[args.command](token, counter, args)
    if not r["ok"]:
        print(f"Error ({r.get('status')}): {r['error']}", file=sys.stderr)
        return 1
    print(json.dumps(r["data"], ensure_ascii=False, indent=2 if args.json else 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
