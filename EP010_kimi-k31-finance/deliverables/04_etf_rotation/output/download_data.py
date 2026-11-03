#!/usr/bin/env python3
"""Download SOXX/SPY/BIL daily prices and corporate actions from Yahoo Finance.

Requires: pandas, yfinance. The saved data are sufficient for offline reproduction
with backtest.py; rerunning this script refreshes the input data and may therefore
change results if Yahoo revises its history.
"""
from pathlib import Path
import json
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
START = "2019-01-01"
END = "2026-01-02"  # exclusive; includes 2025-12-31
TICKERS = ("SOXX", "SPY", "BIL")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    manifest = {
        "provider": "Yahoo Finance",
        "library": f"yfinance {yf.__version__}",
        "method": "Ticker.history(auto_adjust=False, back_adjust=False, actions=True)",
        "start": START,
        "end_exclusive": END,
        "files": {},
    }
    for ticker in TICKERS:
        frame = yf.Ticker(ticker).history(
            start=START,
            end=END,
            interval="1d",
            auto_adjust=False,
            back_adjust=False,
            actions=True,
        )
        if frame.empty:
            raise RuntimeError(f"No data returned for {ticker}")
        frame = frame.reset_index()
        date_col = "Date" if "Date" in frame.columns else "Datetime"
        frame[date_col] = pd.to_datetime(frame[date_col], utc=True).dt.tz_convert(None).dt.normalize()
        frame = frame.rename(columns={date_col: "Date"})
        wanted = [
            "Date", "Open", "High", "Low", "Close", "Adj Close", "Volume",
            "Dividends", "Stock Splits", "Capital Gains",
        ]
        for col in wanted:
            if col not in frame.columns:
                frame[col] = 0.0
        frame = frame[wanted].sort_values("Date").drop_duplicates("Date", keep="last")
        if frame[["Open", "Close", "Adj Close"]].isna().any().any():
            raise ValueError(f"Missing critical price fields for {ticker}")
        path = DATA / f"{ticker}_daily.csv"
        frame.to_csv(path, index=False, date_format="%Y-%m-%d", float_format="%.12f")
        manifest["files"][ticker] = {
            "path": path.name,
            "rows": len(frame),
            "first_date": str(frame["Date"].min().date()),
            "last_date": str(frame["Date"].max().date()),
            "dividend_events": int((frame["Dividends"] > 0).sum()),
            "split_events": int((frame["Stock Splits"] > 0).sum()),
        }
    (DATA / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
