#!/usr/bin/env python3
"""
Yandex Wordstat API client for Claude SEO - search demand for keyword research.

Access to the Wordstat API is granted on request (Yandex support form); the token
is a regular Yandex OAuth token with Wordstat access, sent as "Bearer".

Usage:
    python yandex_wordstat.py top "бензопила" [--region 65] [--limit 50] [--json]
    python yandex_wordstat.py dynamics "бензопила" [--region 65] [--period monthly] [--json]
    python yandex_wordstat.py regions "бензопила" [--type cities] [--json]
    python yandex_wordstat.py batch phrases.txt [--region 65] [--json]   # total demand per phrase
    python yandex_wordstat.py region-id "Новосибирск"                    # lookup from built-in table

Wordstat operators work inside phrases: "!купить !бензопилу", "[купить бензопилу]", "бензопила -stihl".
"""

import argparse
import datetime as dt
import json
import os
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
from yandex_auth import api_request, load_config  # noqa: E402

API = "https://api.wordstat.yandex.net/v1"

# Yandex region ids (geobase) for the largest Russian cities. Full tree: /v1/getRegionsTree.
REGION_IDS = {
    "Россия": 225, "Москва": 213, "Москва и область": 1, "Санкт-Петербург": 2, "Новосибирск": 65,
    "Екатеринбург": 54, "Казань": 43, "Нижний Новгород": 47, "Челябинск": 56, "Красноярск": 62,
    "Самара": 51, "Уфа": 172, "Ростов-на-Дону": 39, "Омск": 66, "Краснодар": 35, "Воронеж": 193,
    "Пермь": 50, "Волгоград": 38, "Тюмень": 55, "Иркутск": 63, "Барнаул": 197, "Томск": 67,
    "Кемерово": 64, "Новокузнецк": 237, "Хабаровск": 76, "Владивосток": 75,
}


def _token():
    t = load_config().get("wordstat_token")
    if not t:
        print("Error: no Wordstat token. Run /seo yandex setup.", file=sys.stderr)
        sys.exit(1)
    return t


def _regions(arg):
    return [int(x) for x in str(arg).split(",")] if arg else None


def cmd_top(token, args):
    body = {"phrase": args.phrase, "numPhrases": min(args.limit, 2000)}
    if args.region:
        body["regions"] = _regions(args.region)
    r = api_request("POST", f"{API}/topRequests", token, scheme="Bearer", body=body)
    if r["ok"]:
        d = r["data"]
        r["data"] = {"phrase": args.phrase, "regions": body.get("regions"),
                     "total_count": d.get("totalCount"),
                     "top": [{"phrase": x.get("phrase"), "count": x.get("count")} for x in d.get("topRequests", [])],
                     "associations": [{"phrase": x.get("phrase"), "count": x.get("count")}
                                      for x in d.get("associations", [])][:30]}
    return r


def cmd_dynamics(token, args):
    to_date = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    from_date = (to_date - dt.timedelta(days=365)).replace(day=1)
    body = {"phrase": args.phrase, "period": args.period,
            "fromDate": from_date.isoformat(), "toDate": to_date.isoformat()}
    if args.region:
        body["regions"] = _regions(args.region)
    r = api_request("POST", f"{API}/dynamics", token, scheme="Bearer", body=body)
    if r["ok"]:
        r["data"] = {"phrase": args.phrase, "period": args.period,
                     "points": [{"date": x.get("date"), "count": x.get("count"), "share": x.get("share")}
                                for x in r["data"].get("dynamics", [])]}
    return r


def cmd_regions(token, args):
    r = api_request("POST", f"{API}/regions", token, scheme="Bearer",
                    body={"phrase": args.phrase, "regionType": args.type})
    if r["ok"]:
        rows = sorted(r["data"].get("regions", []), key=lambda x: -(x.get("count") or 0))
        names = {v: k for k, v in REGION_IDS.items()}
        r["data"] = {"phrase": args.phrase, "regions": [
            {"region_id": x.get("regionId"), "name": names.get(x.get("regionId")),
             "count": x.get("count"), "affinity_index": x.get("affinityIndex")} for x in rows[:args.limit]]}
    return r


def cmd_batch(token, args):
    with open(args.phrase, encoding="utf-8") as f:
        phrases = [x.strip() for x in f if x.strip() and not x.startswith("#")]
    out = []
    for ph in phrases:
        args_one = argparse.Namespace(phrase=ph, region=args.region, limit=1)
        r = cmd_top(token, args_one)
        out.append({"phrase": ph, "total_count": r["data"]["total_count"] if r["ok"] else None,
                    "error": None if r["ok"] else r["error"]})
    out.sort(key=lambda x: -(x["total_count"] or 0))
    return {"ok": True, "data": {"regions": _regions(args.region), "phrases": out}}


def main() -> int:
    p = argparse.ArgumentParser(description="Yandex Wordstat API for Claude SEO")
    p.add_argument("command", choices=["top", "dynamics", "regions", "batch", "region-id"])
    p.add_argument("phrase", help="phrase, file (batch) or city name (region-id)")
    p.add_argument("--region", help="Yandex region id(s), comma-separated, e.g. 213 or 65,54")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--period", default="monthly", choices=["monthly", "weekly", "daily"])
    p.add_argument("--type", default="cities", choices=["cities", "regions", "all"])
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.command == "region-id":
        hits = {k: v for k, v in REGION_IDS.items() if args.phrase.lower() in k.lower()}
        print(json.dumps(hits or {"error": "not in built-in table; use Wordstat getRegionsTree"},
                         ensure_ascii=False, indent=2))
        return 0 if hits else 1
    fn = {"top": cmd_top, "dynamics": cmd_dynamics, "regions": cmd_regions, "batch": cmd_batch}[args.command]
    r = fn(_token(), args)
    if not r["ok"]:
        print(f"Error ({r.get('status')}): {r['error']}", file=sys.stderr)
        return 1
    print(json.dumps(r["data"], ensure_ascii=False, indent=2 if args.json else 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
