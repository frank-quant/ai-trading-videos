"""Data layer: wide matrices, eligibility masks, segment labels."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    with open(ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class MarketData:
    cfg: dict
    calendar: pd.DatetimeIndex
    fields: dict[str, pd.DataFrame]      # factor inputs, NaN on suspended days
    adj_open: pd.DataFrame
    adj_close: pd.DataFrame
    raw_open: pd.DataFrame
    preclose: pd.DataFrame
    tradestatus: pd.DataFrame
    isST: pd.DataFrame
    eligible: pd.DataFrame               # bool: in snapshot universe & tradable & not ST & valid price
    snapshots: dict[pd.Timestamp, list[str]]
    labels: dict[str, pd.DataFrame]      # segment -> wide label (NaN where invalid)
    seg_days: dict[str, pd.DatetimeIndex]

    def snapshot_asof(self, day: pd.Timestamp) -> list[str]:
        dates = [d for d in self.snapshots if d <= day]
        if not dates:
            return []
        return self.snapshots[max(dates)]


def _wide(bars: pd.DataFrame, col: str) -> pd.DataFrame:
    return bars.pivot(index="date", columns="code", values=col).sort_index()


def load_market(cfg: dict | None = None) -> MarketData:
    cfg = cfg or load_config()
    bars = pd.read_parquet(ROOT / cfg["data"]["bars"])
    mem = pd.read_parquet(ROOT / cfg["data"]["members"])
    bars["date"] = pd.to_datetime(bars["date"])
    mem["date"] = pd.to_datetime(mem["date"])

    calendar = pd.DatetimeIndex(sorted(bars["date"].unique()))
    snapshots = {d: sorted(g["code"].tolist()) for d, g in mem.groupby("date")}

    adj_open = _wide(bars, "adj_open")
    adj_close = _wide(bars, "adj_close")
    raw_open = _wide(bars, "open")
    preclose = _wide(bars, "preclose")
    tradestatus = _wide(bars, "tradestatus").fillna(0).astype(int)
    isST = _wide(bars, "isST").fillna(1).astype(int)

    tradable = tradestatus == 1
    fields = {
        "open": adj_open.where(tradable),
        "high": _wide(bars, "adj_high").where(tradable),
        "low": _wide(bars, "adj_low").where(tradable),
        "close": adj_close.where(tradable),
        "vwap": _wide(bars, "adj_vwap").where(tradable),
        "volume": _wide(bars, "volume").where(tradable),
        "amount": _wide(bars, "amount").where(tradable),
    }
    fields["change"] = fields["close"] / fields["close"].shift(1) - 1

    # eligibility: in latest snapshot universe, tradable, not ST, valid prices
    member_mask = pd.DataFrame(False, index=calendar, columns=adj_close.columns)
    snap_dates = sorted(snapshots)
    for i, d in enumerate(snap_dates):
        end = snap_dates[i + 1] if i + 1 < len(snap_dates) else calendar[-1] + pd.Timedelta(days=1)
        rows = (calendar >= d) & (calendar < end)
        member_mask.loc[rows, snapshots[d]] = True
    valid_price = (adj_close > 0) & (raw_open > 0) & adj_close.notna()
    eligible = member_mask & tradable & (isST == 0) & valid_price

    seg_days, labels = {}, {}
    pos = {d: i for i, d in enumerate(calendar)}
    h = cfg["label"]["horizon_trading_days"]
    for seg in ("train", "validation"):
        lo, hi = (pd.Timestamp(x) for x in cfg["data"][seg])
        days = calendar[(calendar >= lo) & (calendar <= hi)]
        seg_days[seg] = days
        lab = pd.DataFrame(np.nan, index=calendar, columns=adj_close.columns)
        o1 = adj_open.shift(-1)
        o11 = adj_open.shift(-(h + 1))
        t1_ok = tradestatus.shift(-1).fillna(0) == 1
        t11_ok = tradestatus.shift(-(h + 1)).fillna(0) == 1
        raw = o11 / o1 - 1
        for d in days:
            i = pos[d]
            if i + 1 >= len(calendar) or i + h + 1 >= len(calendar):
                continue
            d1, d11 = calendar[i + 1], calendar[i + h + 1]
            if not (lo <= d1 <= hi and lo <= d11 <= hi):
                continue
            ok = t1_ok.loc[d] & t11_ok.loc[d] & (o1.loc[d] > 0) & (o11.loc[d] > 0)
            lab.loc[d] = raw.loc[d].where(ok)
        labels[seg] = lab

    return MarketData(cfg, calendar, fields, adj_open, adj_close, raw_open, preclose,
                      tradestatus, isST, eligible, snapshots, labels, seg_days)