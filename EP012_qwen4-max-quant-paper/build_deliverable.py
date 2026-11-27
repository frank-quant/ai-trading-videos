"""Assemble the chosen deliverable (research candidate rc_single) into deliverable/.

Usage: python -I build_deliverable.py
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from coa.combine import percentile_transform
from coa.data import ROOT, load_market
from coa.formula import compile_expr, evaluate

CHOSEN = "rc_single"
FACTOR_ID = "optC2"


def main():
    md = load_market()
    base = ROOT / "output"
    dest = ROOT / "deliverable"
    dest.mkdir(exist_ok=True)
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    opt = [json.loads(l) for l in open(base / "optimization_ledger.jsonl", encoding="utf-8") if l.strip()]
    sub = next(e for e in opt if e["type"] == "opt_submission" and e["id"] == FACTOR_ID)
    ev = next(e for e in opt if e["type"] == "opt_evaluation" and e["id"] == FACTOR_ID)

    spec = {
        "label": "research_candidate",
        "note": "Both fixed-protocol LightGBM versions (v1, v2) had negative validation excess. "
                "This factor-ranking strategy is a clearly-labeled research candidate, NOT the "
                "paper-protocol deliverable. Uses the SAME data splits, universe, trading rules, "
                "fees and benchmark as the initial version; only the combiner differs (single-factor "
                "percentile ranking instead of LightGBM).",
        "combiner": "single_factor_percentile",
        "factors": [{"id": FACTOR_ID, "name": sub.get("seed", "") + " optimized",
                     "expression": sub["expression"],
                     "lineage": ["b3_low_range_20", "optC1", "optC2"],
                     "val_rankic": ev["metrics"]["validation_rankic"],
                     "val_rankicir": ev["metrics"]["validation_rankicir"]}],
        "selection": "daily top-30 eligible by factor percentile; deterministic tie-break by same percentile",
        "data_spec": cfg["data"],
        "label_spec": cfg["label"],
        "universe_exclusions": cfg["backtest"]["exclusions"],
        "trading": cfg["backtest"],
        "validation_metrics": json.loads((base / CHOSEN / "metrics.json").read_text(encoding="utf-8")),
    }
    (dest / "strategy.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    # save the scoring artifact for reload verification (full precision, same path as runner)
    root, _ = compile_expr(sub["expression"], md.cfg)
    values = evaluate(root, md.fields)
    scores = percentile_transform(values, md.eligible)
    scores.to_parquet(dest / "scores_saved.parquet")

    for f in ("nav.csv", "trades.csv", "metrics.json"):
        shutil.copy(base / CHOSEN / f, dest / f)
    shutil.copy(ROOT / "config.json", dest / "config_snapshot.json")
    print("deliverable assembled:", dest)
    print("factor:", sub["expression"])


if __name__ == "__main__":
    main()