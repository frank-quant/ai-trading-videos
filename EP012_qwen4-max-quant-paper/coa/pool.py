"""Pool selection: gates -> RankIC order -> correlation cap -> truncation test."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import MarketData
from .evaluate import cross_corr_mean, truncation_test


def select_pool(passed: list[dict], values: dict[str, pd.DataFrame], md: MarketData) -> tuple[list[dict], list[dict]]:
    g = md.cfg["pool_gates"]
    days = md.seg_days["validation"]
    ms = g["min_stocks_per_cross_section"]
    ordered = sorted(passed, key=lambda r: r["metrics"]["validation_rankic"], reverse=True)
    pool, dropped = [], []
    for cand in ordered:
        cid = cand["id"]
        if len(pool) >= g["max_pool_size"]:
            dropped.append({**cand, "status": "dropped_pool_cap"})
            continue
        corrs = {}
        for held in pool:
            c = cross_corr_mean(values[cid], values[held["id"]], md.eligible, days, ms)
            corrs[held["id"]] = c
        worst = max((abs(c) for c in corrs.values() if not np.isnan(c)), default=0.0)
        if worst > g["max_abs_mean_daily_spearman_vs_pooled"]:
            dropped.append({**cand, "status": "dropped_correlation",
                            "max_abs_corr": worst, "corr_with": corrs})
            continue
        tt = truncation_test(values[cid], md)
        if not tt["passed"]:
            dropped.append({**cand, "status": "dropped_truncation", "truncation": tt})
            continue
        pool.append({**cand, "status": "pooled", "truncation": tt,
                     "corr_with_at_entry": corrs})
    return pool, dropped