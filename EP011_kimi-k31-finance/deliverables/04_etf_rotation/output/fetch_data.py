#!/usr/bin/env python3
"""下载 SOXX/SPY/BIL 的 Yahoo Finance 日线与公司行动，并保存原始 JSON 和 CSV。

数据源：Yahoo Finance v8 chart 接口（研究用途；非交易所官方接口）。
原始 OHLC 为 Yahoo 的拆股调整、未做现金分红复权口径；adjclose 同时计入拆股与现金分红。
"""
from __future__ import annotations

import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
TICKERS = ("SOXX", "SPY", "BIL")
PERIOD1 = int(datetime(2018, 1, 1, tzinfo=timezone.utc).timestamp())
PERIOD2 = int(datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp())
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"


def fetch(ticker: str) -> tuple[dict, str]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={PERIOD1}&period2={PERIOD2}&interval=1d"
        "&events=div%2Csplits&includeAdjustedClose=true"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("chart", {}).get("error"):
        raise RuntimeError(f"{ticker}: {payload['chart']['error']}")
    return payload, url


def save(ticker: str, payload: dict, url: str) -> None:
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    adjclose = result["indicators"]["adjclose"][0]["adjclose"]
    events = result.get("events", {})
    dividends = events.get("dividends", {})
    splits = events.get("splits", {})
    tz = ZoneInfo(result["meta"].get("exchangeTimezoneName", "America/New_York"))

    def event_by_date(items: dict, field: str) -> dict[str, float | str]:
        output = {}
        for item in items.values():
            date = datetime.fromtimestamp(item["date"], tz).date().isoformat()
            output[date] = item[field]
        return output

    div_by_date = event_by_date(dividends, "amount")
    split_by_date = event_by_date(splits, "splitRatio")
    rows = []
    for i, stamp in enumerate(timestamps):
        date = datetime.fromtimestamp(stamp, tz).date().isoformat()
        row = {
            "date": date,
            "open": quote["open"][i],
            "high": quote["high"][i],
            "low": quote["low"][i],
            "close": quote["close"][i],
            "adj_close": adjclose[i],
            "volume": quote["volume"][i],
            "dividend": div_by_date.get(date, 0.0),
            "split_ratio": split_by_date.get(date, ""),
        }
        if any(row[k] is None for k in ("open", "high", "low", "close", "adj_close")):
            continue
        rows.append(row)

    raw_path = RAW / f"{ticker}_yahoo_chart.json"
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = DATA / f"{ticker}_daily.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    event_rows = []
    for item in dividends.values():
        event_rows.append({
            "date": datetime.fromtimestamp(item["date"], tz).date().isoformat(),
            "type": "dividend",
            "value": item["amount"],
            "raw_event": json.dumps(item, ensure_ascii=False),
        })
    for item in splits.values():
        event_rows.append({
            "date": datetime.fromtimestamp(item["date"], tz).date().isoformat(),
            "type": "split",
            "value": item["splitRatio"],
            "raw_event": json.dumps(item, ensure_ascii=False),
        })
    event_rows.sort(key=lambda x: (x["date"], x["type"]))
    with (DATA / f"{ticker}_corporate_actions.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "type", "value", "raw_event"])
        writer.writeheader()
        writer.writerows(event_rows)

    metadata = {
        "ticker": ticker,
        "source": "Yahoo Finance v8 chart",
        "url": url,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "exchange_timezone": str(tz),
        "currency": result["meta"].get("currency"),
        "bars": len(rows),
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
        "raw_price_caliber": "split-adjusted historical OHLC; not cash-dividend adjusted",
        "adj_close_caliber": "split- and cash-dividend-adjusted close",
        "dividend_caliber": "cash amount per share on ex-date, on Yahoo split-adjusted share basis",
        "csv": str(csv_path.relative_to(ROOT)),
        "raw_json": str(raw_path.relative_to(ROOT)),
    }
    (DATA / f"{ticker}_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{ticker}: {len(rows)} bars, {rows[0]['date']} -> {rows[-1]['date']}")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for i, ticker in enumerate(TICKERS):
        payload, url = fetch(ticker)
        save(ticker, payload, url)
        if i + 1 < len(TICKERS):
            time.sleep(1.0)


if __name__ == "__main__":
    main()
