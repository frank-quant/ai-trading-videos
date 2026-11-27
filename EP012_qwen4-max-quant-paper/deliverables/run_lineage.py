"""Build side-by-side lineage tables (seed -> variants) from the ledgers.

Usage: python -I run_lineage.py
Writes output/lineage.md and prints the representative seed D chain.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from coa.data import ROOT


def metrics_of(evals, fid):
    e = evals.get(fid)
    if not e or "metrics" not in e:
        return None
    m = e["metrics"]
    return {"train_ic": m["train_rankic"], "val_ic": m["validation_rankic"],
            "val_icir": m["validation_rankicir"], "cov": m["val_coverage"],
            "to": m["val_top30_turnover"], "status": e["status"]}


def main():
    base = ROOT / "output"
    orig = [json.loads(l) for l in open(base / "ledger.jsonl", encoding="utf-8") if l.strip()]
    opt = [json.loads(l) for l in open(base / "optimization_ledger.jsonl", encoding="utf-8") if l.strip()]
    orig_evals = {e["id"]: e for e in orig if e["type"] == "evaluation"}
    orig_subs = {e["id"]: e for e in orig if e["type"] == "submission"}
    opt_evals = {e["id"]: e for e in opt if e["type"] == "opt_evaluation"}
    opt_subs = {e["id"]: e for e in opt if e["type"] == "opt_submission"}
    allex = {**orig_evals, **opt_evals}

    seeds = ["b3_low_range_20", "b4_max_lottery", "b3_cc_vol", "b4_pv_diverge_amount"]
    lines = ["# 因子优化链血缘（父 → 子）\n"]
    for seed in seeds:
        s = orig_subs[seed]
        sm = metrics_of(allex, seed)
        lines.append(f"## 种子 {seed}（{s['name']}）")
        lines.append(f"父公式：`{s['expression']}`")
        if sm:
            lines.append(f"父指标：train IC {sm['train_ic']:.4f} / val IC {sm['val_ic']:.4f} / ICIR {sm['val_icir']:.4f} / 换手 {sm['to']:.3f} / {sm['status']}\n")
        kids = [v for v in opt_subs.values() if v["seed"] == seed]
        kids.sort(key=lambda v: v["id"])
        rows = []
        for v in kids:
            m = metrics_of(allex, v["id"])
            rows.append({"变体": v["id"], "父": v["parent"], "公式": v["expression"],
                         "为什么改": v["reason"],
                         "val IC": f"{m['val_ic']:.4f}" if m else "ERR",
                         "ICIR": f"{m['val_icir']:.4f}" if m else "ERR",
                         "换手": f"{m['to']:.3f}" if m else "ERR",
                         "结果": m["status"] if m else opt_evals[v["id"]].get("error", "error")})
        if rows:
            lines.append(pd.DataFrame(rows).to_markdown(index=False))
        lines.append("")
    (base / "lineage.md").write_text("\n".join(lines), encoding="utf-8")

    # representative: seed D side-by-side
    print("=== 代表性血缘：b4_max_lottery（MAX 彩票）父→子并排 ===")
    chain = ["b4_max_lottery", "optD1", "optD2"]
    cols = {}
    for fid in chain:
        m = metrics_of(allex, fid)
        expr = orig_subs[fid]["expression"] if fid in orig_subs else opt_subs[fid]["expression"]
        cols[fid] = {"公式": expr,
                     "val IC": f"{m['val_ic']:.4f}", "ICIR": f"{m['val_icir']:.4f}",
                     "train IC": f"{m['train_ic']:.4f}", "换手": f"{m['to']:.3f}",
                     "覆盖率": f"{m['cov']:.4f}", "状态": m["status"]}
    print(pd.DataFrame(cols).to_string())
    print("\nlineage.md written")


if __name__ == "__main__":
    main()