# -*- coding: utf-8 -*-
"""
EP004 · 导出 hyperopt_results.json（规定 schema)
================================================
读:
  - user_data/hyperopt_results/*.fthypt (最新一个:每轮 params + loss)
  - user_data/hyperopt_trials.jsonl     (EP004ValidLoss 每轮记的 train/valid sharpe)
用 loss 值做 join key 配对(**并行安全,不依赖顺序**),写出 hyperopt_results.json。

容器里跑(--entrypoint python):
  docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" \
    freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model kimi_k3
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="model")
    ap.add_argument("--userdir", default="/freqtrade/user_data")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = a.out or os.path.join(a.userdir, "hyperopt_results.json")

    result_dir = os.path.join(a.userdir, "hyperopt_results")
    files = sorted(glob.glob(os.path.join(result_dir, "*.fthypt")), key=os.path.getmtime)
    if not files:
        sys.exit(f"[export] 没找到 .fthypt in {result_dir}")
    latest = Path(files[-1])
    from freqtrade.optimize.hyperopt_tools import HyperoptTools
    epochs = HyperoptTools.load_filtered_results(latest, {})[0]
    n = len(epochs)

    # jsonl 用 loss 值做 join key(并行安全:不依赖写入顺序)
    jl = os.path.join(a.userdir, "hyperopt_trials.jsonl")
    by_loss = {}
    if os.path.exists(jl):
        with open(jl, encoding="utf-8") as f:
            for x in f:
                if not x.strip():
                    continue
                try:
                    r = json.loads(x)
                except Exception:
                    continue
                by_loss.setdefault(round(float(r.get("loss", 0)), 6), r)

    trials = []
    matched = 0
    for i, ep in enumerate(epochs):
        rec = {"epoch": i + 1, "params": ep.get("params_dict", {})}
        r = by_loss.get(round(float(ep.get("loss", 0)), 6))
        rec["train_sharpe"] = r.get("train_sharpe") if r else None
        rec["valid_sharpe"] = r.get("valid_sharpe") if r else None
        matched += 1 if r else 0
        trials.append(rec)
    tv = [1] * matched   # 兼容下方打印

    with open(out, "w", encoding="utf-8") as f:
        json.dump({"model": a.model, "n_epochs": n, "trials": trials}, f, ensure_ascii=False, indent=2)

    vs = [t["valid_sharpe"] for t in trials if t["valid_sharpe"] is not None]
    print(f"[export] {n} trials, {len(tv)} 有 train/valid -> {out}")
    if vs:
        arr = [t["valid_sharpe"] if t["valid_sharpe"] is not None else -1e9 for t in trials]
        bi = int(np.argmax(arr))
        print(f"[export] best valid_sharpe={max(vs):.3f} @epoch {trials[bi]['epoch']}  params={trials[bi]['params']}")


if __name__ == "__main__":
    main()
