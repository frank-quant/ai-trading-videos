# -*- coding: utf-8 -*-
"""
tools/dump_baseline.py —— 台账逐位基线 dump（第 2 步任务三 A）

从 ledger/ledger.csv 取「指定时间窗内、指定组、指定配置名前缀」的每个配置
最新一行，剔除仅时间戳/路径类字段后写规范 CSV，供优化前后逐位比对。

剔除列（默认）：ts（时间戳）、note（run 目录路径提示，非指标）。
其余列**全部保留**（含全部指标列与 group/type/start/end/status 标识列）。

用法：
  python tools/dump_baseline.py --since 2026-10-17T02:33:00Z --prefix pc_ \
      --group test --out evidence/baseline_pre_opt_metrics.csv [--exclude ts,note]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "ledger" / "ledger.csv"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="台账基线 dump（每配置最新行）")
    ap.add_argument("--since", required=True, help="ISO 时间戳下界（含），如 2026-10-17T02:33:00Z")
    ap.add_argument("--prefix", default="pc_", help="配置名前缀过滤")
    ap.add_argument("--group", default="test", help="台账 group 列过滤")
    ap.add_argument("--out", required=True, help="输出 CSV 路径")
    ap.add_argument("--exclude", default="ts,note", help="剔除列（逗号分隔，默认 ts,note）")
    a = ap.parse_args(argv)

    rows = [r for r in csv.DictReader(open(LEDGER, encoding="utf-8"))
            if r.get("group") == a.group and r.get("config", "").startswith(a.prefix)
            and r.get("ts", "") >= a.since]
    latest: dict[str, dict] = {}
    for r in rows:                      # 文件顺序 = 追加顺序，后行覆盖 → 每 config 最新
        latest[r["config"]] = r
    if not latest:
        print(f"[dump] 窗口内无匹配行（since={a.since}, prefix={a.prefix}, group={a.group}）")
        return 2
    cols = [c for c in rows[0].keys() if c not in set(a.exclude.split(","))]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for name in sorted(latest):
            w.writerow(latest[name])
    n_ok = sum(1 for r in latest.values() if r["status"] == "ok")
    print(f"[dump] {len(latest)} 配置（ok {n_ok}），剔除列 {a.exclude}，写出 {out}")
    bad = [k for k, r in latest.items() if r["status"] != "ok"]
    if bad:
        print(f"[dump] 非 ok 行：{sorted(bad)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
