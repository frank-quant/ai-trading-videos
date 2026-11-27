"""Run validation backtest for a version. Optional tag selects subdir.

Usage: python -I run_backtest.py [tag]
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from coa.backtest import run_backtest
from coa.combine import percentile_transform
from coa.data import ROOT, load_market


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    md = load_market()
    base = ROOT / "output"
    out = base / tag if tag else base
    scores = pd.read_parquet(out / "scores.parquet").astype("float64")
    pool = json.loads((out / "pool.json").read_text(encoding="utf-8"))
    pcts = []
    for p in pool:
        v = pd.read_parquet(base / "factor_values" / f"{p['id']}.parquet").astype("float64")
        pcts.append(percentile_transform(v, md.eligible))
    tiebreak = pd.concat(pcts).groupby(level=0).mean() if pcts else None
    res = run_backtest(md, scores, tiebreak=tiebreak)
    res["nav"].to_csv(out / "nav.csv")
    res["trades"].to_csv(out / "trades.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(res["metrics"], indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copy(ROOT / "config.json", out / "config_snapshot.json")

    nav = res["nav"]
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(nav.index, nav["strategy_nav"] / 1e6, label=f"Strategy [{tag or 'v1'}]", lw=1.4)
    axes[0].plot(nav.index, nav["benchmark_nav"] / 1e6, label="HS300 historical equal-weight", lw=1.2)
    axes[0].set_ylabel("NAV (million CNY)")
    axes[0].legend()
    axes[0].set_title(f"Chain-of-Alpha [{tag or 'v1'}] — validation 2023-2024 (next-open)")
    rel = nav["strategy_nav"] / nav["benchmark_nav"]
    axes[1].plot(nav.index, rel, color="tab:red", lw=1.2)
    axes[1].axhline(1.0, color="gray", lw=0.6)
    axes[1].set_ylabel("Strategy / Benchmark")
    fig.tight_layout()
    fig.savefig(out / "nav.png", dpi=130)
    print(json.dumps(res["metrics"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()