"""Build factor pool + LightGBM combiner. Optional tag selects a version subdir.

Usage: python -I run_pool.py [tag]
  no tag -> output/ (initial, ledger.jsonl only)
  v2     -> output/v2/ (merges ledger.jsonl + optimization_ledger.jsonl)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from coa.combine import build_dataset, fit_combine
from coa.data import ROOT, load_market
from coa.evaluate import Ledger
from coa.pool import select_pool


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    md = load_market()
    base = ROOT / "output"
    out = base / tag if tag else base
    out.mkdir(parents=True, exist_ok=True)

    entries = Ledger(base / "ledger.jsonl").read()
    if tag:
        entries += Ledger(base / "optimization_ledger.jsonl").read()
    evals = [e for e in entries if e["type"] in ("evaluation", "opt_evaluation")]
    passed = [e for e in evals if e["status"] == "passed_gates"]
    subs = {e["id"]: e for e in entries if e["type"] in ("submission", "opt_submission")}
    for e in passed:
        src = subs[e["id"]]
        e["name"] = src.get("name", src.get("seed", e["id"]))
        e["hypothesis"] = src.get("hypothesis", src.get("reason", ""))
        e["expression"] = src["expression"]

    vdir = base / "factor_values"
    values = {e["id"]: pd.read_parquet(vdir / f"{e['id']}.parquet").astype("float64")
              for e in passed}
    pool, dropped = select_pool(passed, values, md)

    ledger = Ledger(out / "pool_ledger.jsonl")
    for e in dropped:
        ledger.append({"type": "pool_decision", "id": e["id"], "status": e["status"],
                       **{k: e[k] for k in ("max_abs_corr", "corr_with", "truncation") if k in e}})
    for e in pool:
        ledger.append({"type": "pool_decision", "id": e["id"], "status": "pooled",
                       "truncation": e["truncation"]})

    pool_doc = [{"id": e["id"], "name": e["name"], "expression": e["expression"],
                 "hypothesis": e["hypothesis"],
                 "val_rankic": e["metrics"]["validation_rankic"],
                 "val_rankicir": e["metrics"]["validation_rankicir"],
                 "truncation": e["truncation"]} for e in pool]
    (out / "pool.json").write_text(json.dumps(pool_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if not pool:
        print("EMPTY POOL")
        return

    ids = [e["id"] for e in pool]
    print(f"[{tag or 'v1'}] pool ({len(pool)}): {ids}", flush=True)
    stack = build_dataset(ids, values, md)
    print(f"dataset rows: {len(stack)}", flush=True)
    booster, scores, info = fit_combine(stack, md)
    (out / "lgbm_model.txt").write_text(booster.model_to_string(), encoding="utf-8")
    scores.astype("float32").to_parquet(out / "scores.parquet")
    (out / "combine_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(pd.DataFrame(pool_doc)[["id", "val_rankic", "val_rankicir"]].to_string(index=False))
    print("combine:", json.dumps(info))


if __name__ == "__main__":
    main()