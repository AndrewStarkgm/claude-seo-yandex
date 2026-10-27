"""Yandex Webmaster / Metrika / Wordstat clients: parsing and safety regressions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("requests")
import yandex_auth as ya  # noqa: E402
import yandex_metrika as ym  # noqa: E402
import yandex_webmaster as yw  # noqa: E402
import yandex_wordstat as yws  # noqa: E402


def ok(data):
    return {"ok": True, "data": data, "status": 200}


@pytest.fixture(autouse=True)
def _user_id(monkeypatch):
    monkeypatch.setattr(yw, "_user_id_cache", 42)


def test_host_id_formats():
    assert ya.host_id_from_url("https://Shop.Example.ru/catalog/") == "https:shop.example.ru:443"
    assert ya.host_id_from_url("http://example.ru") == "http:example.ru:80"
    assert ya.host_id_from_url("example.ru") == "https:example.ru:443"
    assert ya.host_id_from_url("https:example.ru:443") == "https:example.ru:443"
    with pytest.raises(ValueError):
        ya.host_id_from_url("ftp://example.ru")


def test_redact_hides_tokens():
    text = "401 for header OAuth y0_AgAAAABBBBccccDDDDeeeeFFFFggggHHHH and Bearer abc.def-123"
    out = ya.redact(text)
    assert "y0_AgAA" not in out and "abc.def-123" not in out
    assert "<redacted>" in out


def test_summary_maps_fields():
    args = argparse.Namespace(host="https://example.ru")
    with patch.object(yw, "api_request", return_value=ok(
            {"sqi": 470, "searchable_pages_count": 120, "excluded_pages_count": 7,
             "site_problems": {"RECOMMENDATION": 2}})) as m:
        r = yw.cmd_summary("t", args)
    assert r["data"] == {"host": "https://example.ru", "iks_sqi": 470, "searchable_pages": 120,
                         "excluded_pages": 7, "site_problems": {"RECOMMENDATION": 2}}
    assert "/user/42/hosts/https%3Aexample.ru%3A443/summary" in m.call_args.args[1]


def test_diagnostics_present_only_sorted_by_severity():
    problems = {
        "NO_REGIONS": {"severity": "RECOMMENDATION", "state": "PRESENT"},
        "URL_ALERT_5XX": {"severity": "CRITICAL", "state": "PRESENT"},
        "THREATS": {"severity": "FATAL", "state": "ABSENT"},
    }
    args = argparse.Namespace(host="example.ru", all=False)
    with patch.object(yw, "api_request", return_value=ok({"problems": problems})):
        r = yw.cmd_diagnostics("t", args)
    codes = [p["code"] for p in r["data"]["problems"]]
    assert codes == ["URL_ALERT_5XX", "NO_REGIONS"]
    assert r["data"]["problems"][1]["note"].startswith("Регион")


def test_queries_ctr_and_totals():
    queries = [{"query_text": "бензопила купить", "indicators": {"TOTAL_SHOWS": 200, "TOTAL_CLICKS": 10,
                                                                  "AVG_SHOW_POSITION": 7.5}},
               {"query_text": "пила", "indicators": {"TOTAL_SHOWS": 0, "TOTAL_CLICKS": 0}}]
    args = argparse.Namespace(host="example.ru", days=28, limit=50, order_by="TOTAL_SHOWS")
    with patch.object(yw, "api_request", return_value=ok({"queries": queries})) as m:
        r = yw.cmd_queries("t", args)
    assert r["data"]["queries"][0]["ctr"] == 5.0
    assert r["data"]["queries"][1]["ctr"] == 0
    assert r["data"]["total_shows"] == 200 and r["data"]["total_clicks"] == 10
    sent = dict(m.call_args.kwargs["params"])
    assert sent["order_by"] == "TOTAL_SHOWS"


def test_recrawl_respects_quota_and_host(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("https://example.ru/a/\nhttps://example.ru/b/\nhttps://other.ru/x/\n# c\n", encoding="utf-8")
    args = argparse.Namespace(host="https://example.ru", urls_file=str(f), dry_run=False)
    calls = []

    def fake(method, url, token, **kw):
        calls.append((method, url, kw.get("body")))
        if url.endswith("/recrawl/quota"):
            return ok({"daily_quota": 100, "quota_remainder": 1})
        return ok({})

    with patch.object(yw, "api_request", side_effect=fake):
        r = yw.cmd_recrawl("t", args)
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1 and posts[0][2] == {"url": "https://example.ru/a/"}
    assert r["data"]["submitted"] == 1 and r["data"]["skipped_foreign_host"] == 1


def test_recrawl_dry_run_sends_nothing(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("https://example.ru/a/\n", encoding="utf-8")
    args = argparse.Namespace(host="example.ru", urls_file=str(f), dry_run=True)
    with patch.object(yw, "api_request", return_value=ok({"quota_remainder": 50})) as m:
        r = yw.cmd_recrawl("t", args)
    assert all(c.args[0] == "GET" for c in m.call_args_list)
    assert r["data"]["would_submit"] == 1


def test_metrika_rows_and_not_set():
    payload = {"data": [{"dimensions": [{"name": "yandex"}], "metrics": [120, 20.5, 2.1, 90]},
                        {"dimensions": [{"name": None}], "metrics": [3, 0, 1, 10]}],
               "totals": [123, 20, 2, 89], "sampled": False}
    with patch.object(ym, "api_request", return_value=ok(payload)):
        r = ym._report("t", 1, "2026-01-01", "2026-01-28", ym.METRICS, "ym:s:lastSearchEngineRoot")
    rows = r["data"]["rows"]
    assert rows[0]["dims"] == ["yandex"] and rows[0]["visits"] == 120
    assert rows[1]["dims"] == ["(not set)"]
    assert r["data"]["totals"]["visits"] == 123


def test_metrika_engine_filter():
    assert ym._engine_filter("yandex").endswith("ym:s:lastSearchEngineRoot=='yandex'")
    assert ym._engine_filter(None) == ym.ORGANIC


def test_wordstat_top_parsing_and_bearer():
    data = {"totalCount": 5000, "topRequests": [{"phrase": "бензопила штиль", "count": 900}],
            "associations": [{"phrase": "цепь для бензопилы", "count": 300}]}
    args = argparse.Namespace(phrase="бензопила", region="65", limit=10)
    with patch.object(yws, "api_request", return_value=ok(data)) as m:
        r = yws.cmd_top("t", args)
    assert r["data"]["total_count"] == 5000 and r["data"]["regions"] == [65]
    assert m.call_args.kwargs["scheme"] == "Bearer"
    assert m.call_args.kwargs["body"]["regions"] == [65]


def test_region_table_has_key_cities():
    for city in ("Москва", "Санкт-Петербург", "Новосибирск", "Красноярск", "Екатеринбург"):
        assert isinstance(yws.REGION_IDS[city], int)
