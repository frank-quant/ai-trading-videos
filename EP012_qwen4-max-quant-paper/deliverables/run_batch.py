"""Submit one batch of factor candidates: record hypothesis first, then evaluate.

Usage: python -I run_batch.py batches/batch1.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from coa.data import ROOT, load_market
from coa.evaluate import Ledger, evaluate_factor
from coa.formula import compile_expr, evaluate


def main():
    batch_path = Path(sys.argv[1])
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    bid = batch["batch"]
    factors = batch["factors"]
    assert len(factors) <= 5, "max 5 factors per batch"

    md = load_market()
    ledger = Ledger(ROOT / "output" / "ledger.jsonl")
    prior_batches = {e["batch"] for e in ledger.read() if e["type"] == "submission"}
    assert bid not in prior_batches, f"batch {bid} already submitted"
    assert len(prior_batches) < 4, "max 4 batches"

    vdir = ROOT / "output" / "factor_values"
    vdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in factors:
        fid = item["id"]
        ledger.append({"type": "submission", "batch": bid, "id": fid,
                       "name": item["name"], "hypothesis": item["hypothesis"],
                       "expression": item["expression"]})
        try:
            root, info = compile_expr(item["expression"], md.cfg)
            values = evaluate(root, md.fields)
            metrics = evaluate_factor(values, md)
            values.astype("float32").to_parquet(vdir / f"{fid}.parquet")
            status = "passed_gates" if metrics["passed_all_gates"] else "rejected_gates"
            ledger.append({"type": "evaluation", "batch": bid, "id": fid,
                           "constraints": info, "metrics": metrics, "status": status})
            rows.append({"id": fid, "status": status,
                         "train_ic": metrics["train_rankic"],
                         "val_ic": metrics["validation_rankic"],
                         "val_icir": metrics["validation_rankicir"],
                         "cov": metrics["val_coverage"],
                         "to": metrics["val_top30_turnover"],
                         "failed": [k for k, v in metrics["gates"].items() if not v]})
        except Exception as e:
            ledger.append({"type": "evaluation", "batch": bid, "id": fid,
                           "status": "error", "error": f"{type(e).__name__}: {e}"})
            rows.append({"id": fid, "status": "error", "error": str(e)})

    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()