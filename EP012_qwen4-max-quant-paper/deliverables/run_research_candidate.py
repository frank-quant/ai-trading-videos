"""Research-candidate fallback (both LightGBM versions weak): factor-ranking strategies
through the SAME trading engine. Clearly labeled, not the fixed-protocol deliverable.

Usage: python -I run_research_candidate.py
Tests: rc_single (best factor optC2 percentile) and rc_rankavg (mean percentile of v2 pool).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from scipy.stats import spearmanr

from coa.backtest import run_backtest
from coa.combine import percentile_transform
from coa.data import ROOT, load_market


def main():
    md = load_market()
    base = ROOT / "output"
    pool = json.loads((base / "v2" / "pool.json").read_text(encoding="utf-8"))
    pcts = {p["id"]: percentile_transform(
        pd.read_parquet(base / "factor_values" / f"{p['id']}.parquet").astype("float64"),
        md.eligible) for p in pool}

    # confirm v2 mechanism
    s2 = pd.read_parquet(base / "v2" / "scores.parquet").astype("float64")
    champ = pcts["optC2"]
    cors = []
    for d in md.seg_days["validation"]:
        m = md.eligible.loc[d] & s2.loc[d].notna()
        if int(m.sum()) < 100:
            continue
        cors.append(spearmanr(s2.loc[d][m], champ.loc[d][m]).statistic)
    print(f"v2 score vs optC2 daily Spearman: {sum(cors)/len(cors):.3f}")

    rankavg = pd.concat(list(pcts.values())).groupby(level=0).mean()
    candidates = {"rc_single": pcts["optC2"], "rc_rankavg": rankavg}
    summary = {}
    for name, scores in candidates.items():
        out = base / name
        out.mkdir(parents=True, exist_ok=True)
        res = run_backtest(md, scores, tiebreak=scores)
        res["nav"].to_csv(out / "nav.csv")
        res["trades"].to_csv(out / "trades.csv", index=False)
        (out / "metrics.json").write_text(json.dumps(res["metrics"], indent=2, ensure_ascii=False), encoding="utf-8")
        m = res["metrics"]
        summary[name] = {
            "final_nav": m["strategy"]["final_nav"],
            "ann_excess": m["excess"]["annualized_excess_arithmetic"],
            "ir": m["excess"]["information_ratio"],
            "max_dd": m["strategy"]["max_drawdown"],
            "ann_vol": m["strategy"]["annualized_vol"],
            "fees": m["strategy_account"]["fees_paid"],
            "buys": m["strategy_account"]["buys"], "sells": m["strategy_account"]["sells"],
        }
        print(name, json.dumps(summary[name], ensure_ascii=False))
    (base / "research_candidates_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()