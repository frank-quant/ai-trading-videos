"""Factor Optimization Chain runner: record reason + parent first, then evaluate.

Usage: python -I run_optimize.py opt/round1.json
Each variant: {id, seed, parent, reason, target, expression}. Lineage kept in ledger.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from coa.data import ROOT, load_market
from coa.evaluate import Ledger, evaluate_factor
from coa.formula import compile_expr, evaluate

MAX_VARIANTS = 20
MAX_PER_SEED = 5


def main():
    batch = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    variants = batch["variants"]
    md = load_market()
    ledger = Ledger(ROOT / "output" / "optimization_ledger.jsonl")
    prior = [e for e in ledger.read() if e["type"] == "opt_submission"]
    assert len(prior) + len(variants) <= MAX_VARIANTS, "exceeds 20 total variants"
    per_seed = {}
    for e in prior:
        per_seed[e["seed"]] = per_seed.get(e["seed"], 0) + 1
    for v in variants:
        per_seed[v["seed"]] = per_seed.get(v["seed"], 0) + 1
        assert per_seed[v["seed"]] <= MAX_PER_SEED, f"seed {v['seed']} exceeds 5 revisions"

    vdir = ROOT / "output" / "factor_values"
    vdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for v in variants:
        ledger.append({"type": "opt_submission", "round": batch["round"], "id": v["id"],
                       "seed": v["seed"], "parent": v["parent"], "reason": v["reason"],
                       "target": v.get("target", ""), "expression": v["expression"]})
        try:
            root, info = compile_expr(v["expression"], md.cfg)
            values = evaluate(root, md.fields)
            metrics = evaluate_factor(values, md)
            values.astype("float32").to_parquet(vdir / f"{v['id']}.parquet")
            status = "passed_gates" if metrics["passed_all_gates"] else "rejected_gates"
            ledger.append({"type": "opt_evaluation", "id": v["id"], "seed": v["seed"],
                           "parent": v["parent"], "constraints": info,
                           "metrics": metrics, "status": status})
            rows.append({"id": v["id"], "seed": v["seed"], "status": status,
                         "train_ic": metrics["train_rankic"], "val_ic": metrics["validation_rankic"],
                         "val_icir": metrics["validation_rankicir"], "cov": metrics["val_coverage"],
                         "to": metrics["val_top30_turnover"],
                         "failed": [k for k, x in metrics["gates"].items() if not x]})
        except Exception as e:
            ledger.append({"type": "opt_evaluation", "id": v["id"], "seed": v["seed"],
                           "parent": v["parent"], "status": "error", "error": f"{type(e).__name__}: {e}"})
            rows.append({"id": v["id"], "seed": v["seed"], "status": "error", "error": str(e)})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()