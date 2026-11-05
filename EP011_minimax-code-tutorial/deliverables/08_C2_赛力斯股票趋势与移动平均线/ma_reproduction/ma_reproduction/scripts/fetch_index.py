"""Fetch CSI 300 (000300.SH) daily data from the iFinD connector in <=90-day chunks.

Why chunking: the iFinD connector caps a single answer at 100 rows and silently
downsamples longer ranges. The underlying date axis is the *calendar* day; on
non-trading days only 收盘价 is forward-filled and the other fields are blank.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mc import call  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"

START = dt.date(2023, 6, 1)
END = dt.date(2026, 10, 23)
CHUNK = 90  # calendar days per request, under the 100-row cap

FIELD_ALIASES = {
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "成交量": "volume",
    "成交金额": "amount",
    "成交额": "amount",
}
UNIT_RE = re.compile(r"（.*?）|\(.*?\)")


def norm_header(h: str) -> str:
    return UNIT_RE.sub("", h).strip()


def to_num(v: str):
    """Convert '1234.5亿' -> 123450000000 ; returns None for blank."""
    v = (v or "").strip()
    if not v:
        return None
    mult = 1
    if v.endswith("万亿"):
        mult, v = 10**12, v[:-2]
    elif v.endswith("亿"):
        mult, v = 10**8, v[:-1]
    elif v.endswith("万"):
        mult, v = 10**4, v[:-1]
    v = v.replace(",", "")
    try:
        return float(v) * mult
    except ValueError:
        return None


def parse_answer(answer: str):
    rows = []
    header = None
    for line in answer.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or not cells[0]:
            continue
        if cells[0] == "证券代码":
            header = [norm_header(c) for c in cells]
            continue
        if set(cells[0]) <= set("-") and set(cells[0]):
            continue
        if header is None:
            continue
        rec = {}
        for name, val in zip(header, cells):
            key = FIELD_ALIASES.get(name)
            if key:
                rec[key] = to_num(val) if key in ("volume", "amount") else (
                    None if not val.strip() else float(val)
                )
        rec["date"] = cells[2]
        rec["code"] = cells[0]
        rec["name"] = cells[1]
        rows.append(rec)
    return rows


def chunks():
    d = START
    while d <= END:
        e = min(d + dt.timedelta(days=CHUNK - 1), END)
        yield d, e
        d = e + dt.timedelta(days=1)


def main():
    all_rows = {}
    meta = []
    for d, e in chunks():
        rng = f"{d.year}年{d.month}月{d.day}日至{e.year}年{e.month}月{e.day}日"
        q = (f"沪深300(000300.SH) {rng} 每个交易日的开盘价、最高价、最低价、"
             f"收盘价、成交量、成交额")
        data = call(
            "connector__thsifind__get_security_indicators",
            {"market": "指数", "query": q},
            save_as=f"ifind_csi300_{d.isoformat()}_{e.isoformat()}.json",
            quiet=True,
        )
        answer = data.get("data", {}).get("answer", "")
        rows = parse_answer(answer)
        expect = (e - d).days + 1
        got = len({r["date"] for r in rows})
        status = "FULL" if got == expect else f"PARTIAL({got}/{expect})"
        print(f"{d} -> {e}: rows={got} expected={expect} {status}", file=sys.stderr)
        meta.append({"start": d.isoformat(), "end": e.isoformat(), "rows": got,
                     "expected": expect, "status": status})
        for r in rows:
            key = f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}"
            r["date"] = key
            all_rows[key] = r

    out = sorted(all_rows.values(), key=lambda r: r["date"])
    (RAW / "ifind_csi300_merged.json").write_text(
        json.dumps({"chunks": meta, "rows": out}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trading = [r for r in out if r.get("open") is not None]
    print(f"merged calendar rows={len(out)}  trading-day rows={len(trading)}", file=sys.stderr)


if __name__ == "__main__":
    main()
