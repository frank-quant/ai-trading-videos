# -*- coding: utf-8 -*-
"""
engine/run_batch.py —— 批量回测一个目录下全部配置单

单 worker 时一个进程内共享一次数据加载（DataStore 只构造一次），逐个回测、
逐个落台账；--workers > 1 时走 funnel.make_runner 多进程并行（rules.md 第 12 章：
默认 CPU−2，并行不改变任何结果——同一批配置的回测指标逐位一致），
台账追加由 backtest._ledger_locked 跨进程锁保证不丢行、不串行。
并判定漏斗第 1～4 层（rules.md 第 5.2 节，3.4 修订版口径，搜索期）：
  L1 规则型交易 ≥100 笔（买卖各算一笔）/ 打分型按调仓频率分档：周度 ≥300 期、月度 ≥80 期
  L2 扣成本年化超额 > 0
  L3 信息比率 ir > 0.4 且超额最大回撤 < 30%（严格不等，rules.md 第 3 版）
  L4 9 个完整年份至少 6 年年度超额 > 0
每一次执行（成功/报错）都写进台账并带 --group 归属组（rules.md 第 6 节）。

CLI：python engine/run_batch.py --dir strategies/examples --group example \
        [--start 20140101] [--end 20221231] [--workers N]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402
import panel_store
from backtest import DEFAULT_END, DEFAULT_START, check_group, run_backtest  # noqa: E402
from config import ConfigError  # noqa: E402
from prices import DataStore  # noqa: E402

ROOT = guard.ROOT


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse

    from funnel import default_workers, make_runner   # 局部 import（避免重型依赖提前加载）

    ap = argparse.ArgumentParser(description="批量回测目录下全部配置单")
    ap.add_argument("--dir", required=True, help="配置单目录（*.yaml / *.yml）")
    ap.add_argument("--group", required=True, type=check_group,
                    help="本次批量执行的归属组：A / B / monkey_<正整数种子> / example / test")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--workers", type=int, default=None,
                    help="并行 worker 数（缺省 = CPU 核数 − 2，rules.md 第 12 章；1 = 顺序）")
    a = ap.parse_args(argv)
    guard.check_date_range(a.start, a.end)

    cfg_dir = Path(a.dir)
    if not cfg_dir.is_dir():
        print(f"[batch] 目录不存在：{cfg_dir}")
        return 2
    cfgs = sorted([p for p in cfg_dir.iterdir()
                   if p.suffix.lower() in (".yaml", ".yml")])
    if not cfgs:
        print(f"[batch] 目录下没有 YAML 配置单：{cfg_dir}")
        return 2

    workers = default_workers() if a.workers is None else max(1, int(a.workers))
    print(f"[batch] {len(cfgs)} 个配置单，区间 {a.start} ~ {a.end}，group={a.group}，"
          f"workers={workers}")

    n_ok = n_fail = 0
    t0 = time.time()
    if workers > 1:
        # 多进程并行（rules.md 第 12 章）：每个 worker 各自加载一次面板，
        # 结果逐位一致由 engine/selftest.py 并行一致性用例验证。
        from funnel import _run_one
        runner = make_runner(workers)
        results = runner.run([{"name": p.stem, "path": str(p),
                               "start": a.start, "end": a.end, "group": a.group}
                              for p in cfgs])
        by_name = {}
        for r in results:
            by_name.setdefault(r["config"], []).append(r)
        for p in cfgs:
            rs = by_name.get(p.stem) or [{"status": "error", "note": "无返回"}]
            r = rs[0]
            if r["status"] == "ok":
                n_ok += 1
                print(f"[batch] {p.stem}: ok")
            else:
                n_fail += 1
                print(f"[batch] 执行失败（已落台账）：{p.stem} {r.get('note', '')}")
    else:
        print("[batch] 加载面板（共享一次）……")
        store = panel_store.real_store()   # 优先跨进程共享缓存，失败退回全量构建
        print(f"[batch] 面板加载完成，用时 {time.time()-t0:.1f}s")
        for i, p in enumerate(cfgs, 1):
            print(f"\n[{i}/{len(cfgs)}] {p.name}")
            t1 = time.time()
            try:
                res = run_backtest(store, p, a.start, a.end, group=a.group)
                n_ok += 1
                f = res["funnel"]
                print(f"[batch] {res['config_name']}: L1={f['funnel_l1']} L2={f['funnel_l2']} "
                      f"L3={f['funnel_l3']} L4={f['funnel_l4']}  （{time.time()-t1:.1f}s）")
            except ConfigError as e:
                n_fail += 1
                print(f"[batch] 配置错误（已落台账）：{e}")
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                print(f"[batch] 执行失败（已落台账）：{e!r}")

    print(f"\n[batch] 完成：成功 {n_ok}，失败 {n_fail}，总用时 {time.time()-t0:.1f}s")
    print("[batch] 台账：ledger/ledger.csv")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
