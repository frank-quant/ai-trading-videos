"""Factor evaluation metrics and the candidate ledger."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .data import MarketData, ROOT


def daily_rankic(values: pd.DataFrame, labels: pd.DataFrame, eligible: pd.DataFrame,
                 days: pd.DatetimeIndex, min_stocks: int) -> pd.Series:
    out = {}
    for d in days:
        m = eligible.loc[d] & values.loc[d].notna() & labels.loc[d].notna()
        if int(m.sum()) < min_stocks:
            continue
        v = values.loc[d][m].to_numpy()
        y = labels.loc[d][m].to_numpy()
        if np.std(v) == 0 or np.std(y) == 0:
            continue
        out[d] = spearmanr(v, y).statistic
    return pd.Series(out, dtype=float)


def coverage(values: pd.DataFrame, eligible: pd.DataFrame, days: pd.DatetimeIndex) -> float:
    e = eligible.loc[days]
    return float((values.loc[days].notna() & e).to_numpy().sum() / e.to_numpy().sum())


def top30_turnover(values: pd.DataFrame, eligible: pd.DataFrame,
                   days: pd.DatetimeIndex, k: int = 30) -> float:
    sets = []
    for d in days:
        m = eligible.loc[d] & values.loc[d].notna()
        row = values.loc[d][m]
        sets.append(set(row.nlargest(min(k, len(row))).index) if len(row) else set())
    vals = []
    for a, b in zip(sets[:-1], sets[1:]):
        if not a and not b:
            continue
        vals.append(len(a ^ b) / k)
    return float(np.mean(vals)) if vals else np.nan


def evaluate_factor(values: pd.DataFrame, md: MarketData) -> dict:
    g = md.cfg["pool_gates"]
    ms = g["min_stocks_per_cross_section"]
    res = {}
    for seg in ("train", "validation"):
        ic = daily_rankic(values, md.labels[seg], md.eligible, md.seg_days[seg], ms)
        res[f"{seg}_rankic"] = float(ic.mean()) if len(ic) else np.nan
        res[f"{seg}_rankicir"] = float(ic.mean() / ic.std(ddof=1)) if len(ic) > 2 else np.nan
        res[f"{seg}_ic_days"] = int(len(ic))
    res["val_coverage"] = coverage(values, md.eligible, md.seg_days["validation"])
    res["val_top30_turnover"] = top30_turnover(values, md.eligible, md.seg_days["validation"])
    gates = {
        "train_rankic_positive": res["train_rankic"] > g["train_rankic_min_exclusive"],
        "val_rankic": res["validation_rankic"] >= g["val_rankic_min"],
        "val_rankicir": res["validation_rankicir"] >= g["val_rankicir_min"],
        "val_coverage": res["val_coverage"] >= g["val_coverage_min"],
        "val_turnover": res["val_top30_turnover"] <= g["val_top30_turnover_max"],
    }
    res["gates"] = gates
    res["passed_all_gates"] = bool(all(gates.values()))
    return res


def cross_corr_mean(a: pd.DataFrame, b: pd.DataFrame, eligible: pd.DataFrame,
                    days: pd.DatetimeIndex, min_stocks: int) -> float:
    vals = []
    for d in days:
        m = eligible.loc[d] & a.loc[d].notna() & b.loc[d].notna()
        if int(m.sum()) < min_stocks:
            continue
        x, y = a.loc[d][m].to_numpy(), b.loc[d][m].to_numpy()
        if np.std(x) == 0 or np.std(y) == 0:
            continue
        vals.append(spearmanr(x, y).statistic)
    return float(np.mean(vals)) if vals else np.nan


def truncation_test(values: pd.DataFrame, md: MarketData) -> dict:
    g = md.cfg["pool_gates"]
    days = md.seg_days["validation"]
    e = md.eligible.loc[days]
    v = values.loc[days].where(e)
    lo = v.quantile(0.01, axis=1)
    hi = v.quantile(0.99, axis=1)
    clipped = v.clip(lower=lo, upper=hi, axis=0)
    ic = daily_rankic(clipped, md.labels["validation"], md.eligible, days,
                      g["min_stocks_per_cross_section"])
    rankic = float(ic.mean()) if len(ic) else np.nan
    return {
        "method": "winsorize daily cross-section at 1/99 percentiles",
        "val_rankic_after": rankic,
        "val_rankicir_after": float(ic.mean() / ic.std(ddof=1)) if len(ic) > 2 else np.nan,
        "passed": bool(rankic >= g["truncation_test"]["pass_val_rankic_min"]),
    }


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: dict):
        entry["recorded_at"] = datetime.now(timezone.utc).isoformat()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]