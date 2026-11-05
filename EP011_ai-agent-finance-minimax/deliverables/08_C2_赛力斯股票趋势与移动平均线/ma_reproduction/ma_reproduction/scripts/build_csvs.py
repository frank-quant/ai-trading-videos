"""Validate both series and emit prices.csv / prices_bench.csv aligned on common trading days."""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"

STOCK_FILE = RAW / "seres_fwd.json"
INDEX_FILE = RAW / "ifind_csi300_merged.json"

STOCK_CODE, STOCK_NAME = "601127.SH", "赛力斯"
BENCH_CODE, BENCH_NAME = "000300.SH", "沪深300"

RANGE_START = dt.date(2023, 6, 1)
RANGE_END = dt.date(2026, 10, 23)


def ohlc_sane(r):
    """True when the bar satisfies basic OHLC invariants (None values are reported separately)."""
    o, h, l, c = r["open"], r["high"], r["low"], r["close"]
    if None in (o, h, l, c):
        return False
    return h >= max(o, c) and l <= min(o, c) and l <= h and h >= l


def load_stock():
    d = json.loads(STOCK_FILE.read_text(encoding="utf-8"))
    rows = {}
    dup = []
    for it in d["items"]:
        if it["date"] in rows:
            dup.append(it["date"])
        rows[it["date"]] = it
    return d, rows, dup


def load_index():
    d = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    rows = {}
    dup = []
    for it in d["rows"]:
        if it["date"] in rows:
            dup.append(it["date"])
        rows[it["date"]] = it
    return d, rows, dup


def main():
    report = {}

    # ---------- stock ----------
    s_meta, stock, s_dup = load_stock()
    s_dates = sorted(stock)
    s_null = {k: sum(1 for r in stock.values() if r.get(k) is None)
              for k in ("open", "high", "low", "close", "previousClose", "volume", "amount")}
    s_bad = [d for d in s_dates if not ohlc_sane(stock[d])]
    s_nonfinal = [d for d in s_dates if stock[d].get("isFinal") is not True]
    s_quote_src = [d for d in s_dates if stock[d].get("source") != "provider_daily"]
    s_gap = []
    for a, b in zip(s_dates, s_dates[1:]):
        da = dt.date.fromisoformat(a)
        db = dt.date.fromisoformat(b)
        if (db - da).days > 10:  # long holiday gap
            s_gap.append((a, b, (db - da).days))
    report["stock"] = {
        "n": len(s_dates),
        "first": s_dates[0], "last": s_dates[-1],
        "duplicates": s_dup,
        "nulls": s_null,
        "ohlc_violations": s_bad,
        "non_final_rows": s_nonfinal,
        "non_provider_daily": s_quote_src,
        "long_gaps": s_gap,
        "status": s_meta.get("status"), "cacheStatus": s_meta.get("cacheStatus"),
        "coverageComplete": s_meta.get("coverageComplete"),
        "adjustment": s_meta.get("adjustment"),
        "basisVersion": s_meta.get("basisVersion"),
        "revision": s_meta.get("revision"),
        "fetchedAt": s_meta.get("fetchedAt"),
        "effectiveRange": s_meta.get("effectiveRange"),
        "quality": s_meta.get("quality"),
        "errors": s_meta.get("errors"),
    }

    # ---------- index ----------
    i_meta, index, i_dup = load_index()
    i_trading = {d: r for d, r in index.items() if r.get("open") is not None}
    i_dates = sorted(i_trading)
    i_null = {k: sum(1 for r in i_trading.values() if r.get(k) is None)
              for k in ("open", "high", "low", "close", "volume", "amount")}
    i_bad = [d for d in i_dates if not ohlc_sane(i_trading[d])]
    i_nonpos = [d for d in i_dates if not (i_trading[d]["close"] > 0)]
    report["index"] = {
        "n_calendar_rows": len(index),
        "n_trading": len(i_dates),
        "first": i_dates[0], "last": i_dates[-1],
        "duplicates": i_dup,
        "nulls_in_trading_rows": i_null,
        "ohlc_violations": i_bad,
        "non_positive_close": i_nonpos,
        "chunks": i_meta.get("chunks"),
    }

    # ---------- alignment ----------
    s_set, i_set = set(s_dates), set(i_dates)
    common = sorted(s_set & i_set)
    only_stock = sorted(s_set - i_set)
    only_index = sorted(i_set - s_set)
    report["alignment"] = {
        "common_trading_days": len(common),
        "only_in_stock": only_stock,
        "only_in_index": only_index,
        "requested_start": RANGE_START.isoformat(),
        "requested_end": RANGE_END.isoformat(),
        "first_common": common[0] if common else None,
        "last_common": common[-1] if common else None,
    }

    # ---------- write CSVs ----------
    with (ROOT / "prices.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "symbol", "name", "open", "high", "low", "close",
                    "pre_close", "volume", "amount", "adjustment"])
        for d in common:
            r = stock[d]
            w.writerow([d, STOCK_CODE, STOCK_NAME, r["open"], r["high"], r["low"],
                        r["close"], r["previousClose"], r["volume"], r["amount"], "forward"])

    with (ROOT / "prices_bench.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "symbol", "name", "open", "high", "low", "close",
                    "volume", "amount", "index_type"])
        for d in common:
            r = i_trading[d]
            w.writerow([d, BENCH_CODE, BENCH_NAME,
                        r["open"], r["high"], r["low"], r["close"],
                        int(round(r["volume"])), int(round(r["amount"])), "price_index"])

    (RAW / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
