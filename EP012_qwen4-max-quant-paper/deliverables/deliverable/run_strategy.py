"""Self-contained runner for the delivered research-candidate strategy.

Reloads the saved factor formulas (the 'model'), reconstructs scores from same-spec
market data, and runs the fixed trading engine. Verifies reconstruction matches the
saved scores, then writes NAV/metrics.

Usage (from project root): python -I deliverable/run_strategy.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from coa.backtest import run_backtest
from coa.combine import percentile_transform
from coa.data import load_market
from coa.formula import compile_expr, evaluate


def reconstruct_scores(spec: dict, md) -> pd.DataFrame:
    pcts = []
    for fac in spec["factors"]:
        root, _ = compile_expr(fac["expression"], md.cfg)
        values = evaluate(root, md.fields)
        pcts.append(percentile_transform(values, md.eligible))
    if spec["combiner"] == "single_factor_percentile":
        scores = pcts[0]
    elif spec["combiner"] == "rank_average":
        scores = pd.concat(pcts).groupby(level=0).mean()
    else:
        raise ValueError(spec["combiner"])
    return scores


def main():
    spec = json.loads((HERE / "strategy.json").read_text(encoding="utf-8"))
    md = load_market()
    scores = reconstruct_scores(spec, md)

    saved_path = HERE / "scores_saved.parquet"
    if saved_path.exists():
        saved = pd.read_parquet(saved_path).astype("float64")
        a = scores.to_numpy().ravel()
        b = saved.reindex(index=scores.index, columns=scores.columns).to_numpy().ravel()
        mask = np.isfinite(a) & np.isfinite(b)
        max_diff = float(np.max(np.abs(a[mask] - b[mask]))) if mask.any() else 0.0
        print(f"[reload check] reconstructed vs saved scores: max abs diff = {max_diff:.3e} "
              f"({'PASS' if max_diff < 1e-6 else 'FAIL'})")

    res = run_backtest(md, scores, tiebreak=scores)
    out = HERE / "run_output"
    out.mkdir(exist_ok=True)
    res["nav"].to_csv(out / "nav.csv")
    res["trades"].to_csv(out / "trades.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(res["metrics"], indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res["metrics"]["strategy"], indent=2, ensure_ascii=False))
    print("excess:", json.dumps(res["metrics"]["excess"], ensure_ascii=False))


if __name__ == "__main__":
    main()