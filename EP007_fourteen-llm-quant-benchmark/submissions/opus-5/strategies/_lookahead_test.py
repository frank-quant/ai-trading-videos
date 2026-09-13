# -*- coding: utf-8 -*-
"""Look-ahead verification for XSTrendEnsemble (working file, not a deliverable).

Replicates the strategy's _legs_for_pair/_composite EXACTLY (same code path is
imported where possible) and checks the hard requirement:

    composite computed on the FULL sample, restricted to t <= T
      ==  composite computed on data TRUNCATED at T

for several cut points T. If any future bar leaked into a value at or before T,
the two would differ.
"""
import os

import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path(os.environ.get("EP004_DATA", "/freqtrade/user_data/data/binance/futures"))
PAIRS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "LINK", "LTC", "BCH",
         "AVAX", "DOT", "UNI", "ATOM", "NEAR", "FIL", "ETC", "TRX", "XLM", "AAVE"]
BPD = 6                      # 4h
MOM_D, MAF_D, MAS_D, SMOOTH_D = 14, 25, 45, 10   # the submitted parameters
VALID_E = pd.Timestamp("2025-06-30", tz="UTC")


def legs_for_pair(d):
    """byte-for-byte the same maths as XSTrendEnsemble._legs_for_pair"""
    idx = pd.DatetimeIndex(d["date"])
    close = pd.Series(d["close"].to_numpy(dtype="float64"), index=idx)
    high = pd.Series(d["high"].to_numpy(dtype="float64"), index=idx)
    low = pd.Series(d["low"].to_numpy(dtype="float64"), index=idx)
    lr = np.log(close).diff()
    n_mom, n_f, n_s = MOM_D * BPD, MAF_D * BPD, MAS_D * BPD
    n_p = n_f

    def trend(n):
        vol = lr.rolling(n).std().replace(0.0, np.nan)
        return (close / close.rolling(n).mean() - 1.0) / vol

    hh, ll = high.rolling(n_p).max(), low.rolling(n_p).min()
    return {"mom": close.pct_change(n_mom), "ma_fast": trend(n_f),
            "ma_slow": trend(n_s),
            "pos": (close - ll) / (hh - ll).replace(0.0, np.nan) - 0.5}


def composite(frames):
    legs = {}
    for p, d in frames.items():
        for name, s in legs_for_pair(d).items():
            legs.setdefault(name, {})[p] = s
    comp = None
    for name, cols in legs.items():
        panel = pd.DataFrame(cols).sort_index()
        rk = (panel.rank(axis=1, pct=True) - 0.5) * 2.0
        comp = rk if comp is None else comp.add(rk, fill_value=np.nan)
    comp = comp / float(len(legs))
    return comp.rolling(SMOOTH_D * BPD).mean()


frames_full = {}
for p in PAIRS:
    d = pd.read_feather(DATA / f"{p}_USDT_USDT-4h-futures.feather")
    d["date"] = pd.to_datetime(d["date"], utc=True)
    frames_full[p] = d[d["date"] <= VALID_E].reset_index(drop=True)

full = composite(frames_full)
print(f"full composite: {full.shape[0]} bars x {full.shape[1]} pairs, "
      f"{full.index.min()} .. {full.index.max()}")

ok = True
for T in ["2021-09-15", "2022-06-01", "2023-03-20", "2024-06-30", "2024-11-11", "2025-04-01"]:
    T = pd.Timestamp(T, tz="UTC")
    trunc = {p: d[d["date"] <= T].reset_index(drop=True) for p, d in frames_full.items()}
    ct = composite(trunc)
    a = full.loc[:T]
    b = ct.loc[:T]
    a, b = a.align(b, join="inner")
    same_nan = (a.isna() == b.isna()).all().all()
    diff = (a - b).abs().max().max()
    n_cmp = int(a.notna().sum().sum())
    bad = (not same_nan) or (not np.isnan(diff) and diff > 1e-12)
    ok &= not bad
    print(f"  cut {T.date()}  compared {n_cmp:7d} values  max|diff|="
          f"{0.0 if np.isnan(diff) else diff:.3e}  nan-pattern-identical={same_nan}  "
          f"{'FAIL' if bad else 'PASS'}")

print("\nLOOK-AHEAD TEST:", "PASS - composite at t uses only data <= t" if ok else "FAIL")
