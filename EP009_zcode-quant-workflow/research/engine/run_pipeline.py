# -*- coding: utf-8 -*-
"""
engine/run_pipeline.py —— 全流程单入口（纯 engine 调用，无任何运行时补丁）

串联（rules.md 第 5 节）：
  1. 搜索期 + 验证期回测：逐个配置单执行两次 run_backtest（全部落台账，
     每次执行的归属组 = --group，rules.md 第 6 节）；
  2. 漏斗 L5~L8：funnel.run_layers（展示分路按台账 group 列）；
  3. 入围名单：shortlist（5.3 分级 + 5.4 入围分，名单必为 3 个）；
  4. 组合层：portfolio（5.5 底仓 60% + 卫星 40% 三段检验）。

输出契约（每次运行结束逐组打印）：
  GROUP=<组名> SHORTLIST=<只数>     每组一行；只数 < 3 视为失败
  PORTFOLIO_OK=1                    末尾一行；短名单不足 3 或组合层失败时为 0
  失败时进程退出码非 0。

CLI（区间缺省 = rules.md 第 1 节搜索期 / 第 5.2 节验证期）：
  python engine/run_pipeline.py --group example \
      --search-start 20140101 --search-end 20221231 \
      --val-start 20230101 --val-end 20241231 \
      strategies/examples/a_breakout_ma20.yaml ...（或 --dir strategies/examples）

说明：本脚本只 import 引擎模块并调用其函数（backtest/funnel/shortlist/portfolio），
对 engine/ 不做任何 import 后替换/包裹——分组只认台账 group 列。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402
import panel_store
from backtest import check_group, run_backtest  # noqa: E402
from config import ConfigError  # noqa: E402
from prices import DataStore  # noqa: E402

ROOT = guard.ROOT


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    import argparse

    from funnel import LAYERS_JSON, SEARCH_END, SEARCH_START, VALID_END, VALID_START, \
        run_layers
    from portfolio import run_portfolio
    from shortlist import build_shortlist, load_final_set, render_md

    ap = argparse.ArgumentParser(prog="engine/run_pipeline.py",
                                 description="全流程单入口：回测→漏斗→入围→组合层")
    ap.add_argument("--group", required=True, type=check_group,
                    help="本次全流程的归属组：A / B / monkey_<正整数种子> / example / test")
    ap.add_argument("--dir", default=None, help="配置单目录（*.yaml / *.yml，与位置参数二选一）")
    ap.add_argument("configs", nargs="*", help="配置单 YAML 路径（与 --dir 二选一）")
    ap.add_argument("--search-start", default=SEARCH_START)
    ap.add_argument("--search-end", default=SEARCH_END)
    ap.add_argument("--val-start", default=VALID_START)
    ap.add_argument("--val-end", default=VALID_END)
    ap.add_argument("--layers-out", default=str(LAYERS_JSON))
    ap.add_argument("--workers", type=int, default=None,
                    help="并行 worker 数（缺省 = CPU 核数 − 2，rules.md 第 12 章；1 = 顺序）")
    ap.add_argument("--formal", action="store_true",
                    help="正式跑漏斗（缺省试跑模式：L5 只对每组入围分前 30 名执行，"
                         "rules.md 第 10 章）")
    ap.add_argument("--skip-backtest", action="store_true",
                    help="跳过回测（台账与日收益已就绪时直接跑漏斗→入围→组合层）")
    a = ap.parse_args(argv)

    from funnel import default_workers, make_runner
    workers = default_workers() if a.workers is None else max(1, int(a.workers))

    # ---- 收集配置单 ----
    paths: list[Path] = []
    if a.dir:
        d = Path(a.dir)
        if not d.is_dir():
            print(f"[pipeline] 目录不存在：{d}")
            return 2
        paths = sorted(p for p in d.iterdir() if p.suffix.lower() in (".yaml", ".yml"))
    for c in a.configs:
        p = Path(c)
        if not p.is_file():
            print(f"[pipeline] 配置单不存在：{p}")
            return 2
        paths.append(p)
    if not paths:
        print("[pipeline] 未提供配置单（位置参数或 --dir）")
        return 2
    if a.search_start != SEARCH_START or a.search_end != SEARCH_END \
            or a.val_start != VALID_START or a.val_end != VALID_END:
        print(f"[pipeline] 警告：区间与规则常量不同（搜索 {SEARCH_START}~{SEARCH_END}、"
              f"验证 {VALID_START}~{VALID_END}）；漏斗/入围判定按规则常量区间读台账")

    t0 = time.time()
    store: DataStore | None = None

    # ---- 1. 搜索期 + 验证期回测（全部落台账，group 为每次执行的必填属性）----
    if not a.skip_backtest:
        print(f"[pipeline] {len(paths)} 个配置单，搜索期 {a.search_start}~{a.search_end}、"
              f"验证期 {a.val_start}~{a.val_end}，group={a.group}，workers={workers}")
        tasks = [{"name": f"{p.stem}@{label}", "path": str(p), "start": s, "end": e,
                  "group": a.group}
                 for p in paths for label, s, e in
                 (("搜索期", a.search_start, a.search_end),
                  ("验证期", a.val_start, a.val_end))]
        if workers > 1:
            # 多进程并行（rules.md 第 12 章，指标逐位一致由自测验证）；
            # 常驻池用完即排空回收（后续漏斗阶段自建池）
            r1 = make_runner(workers)
            r1.run(tasks)
            r1.close()
        else:
            print("[pipeline] 加载数据面板（全程共享一次）……", flush=True)
            store = panel_store.real_store()   # 优先跨进程共享缓存
            for i, t in enumerate(tasks, 1):
                t1 = time.time()
                try:
                    res = run_backtest(store, t["path"], t["start"], t["end"],
                                       group=a.group, quiet=True)
                    f = res["funnel"]
                    print(f"[pipeline] ({i}/{len(tasks)}) {t['name']}: "
                          f"L1={f['funnel_l1']} L2={f['funnel_l2']} "
                          f"L3={f['funnel_l3']} L4={f['funnel_l4']} "
                          f"（{time.time() - t1:.1f}s）", flush=True)
                except ConfigError as ex:
                    print(f"[pipeline] ({i}/{len(tasks)}) {t['name']} "
                          f"配置错误（已落台账）：{ex}")
                except Exception as ex:  # noqa: BLE001 —— 报错已由引擎落台账
                    print(f"[pipeline] ({i}/{len(tasks)}) {t['name']} "
                          f"执行失败（已落台账）：{ex!r}")

    # ---- 2. 漏斗 L5~L8（展示分路按台账 group 列）----
    layers_out = Path(a.layers_out)
    if not layers_out.is_absolute():
        layers_out = ROOT / layers_out
    rc_layers = run_layers(layers_out, formal=True if a.formal else None,
                           workers=workers)
    if rc_layers != 0:
        print("PORTFOLIO_OK=0")
        return rc_layers

    # ---- 3. 入围名单（5.3 分级 + 5.4 入围分）----
    from funnel import read_ledger
    ledger = read_ledger()
    final_set, final_src = load_final_set(a.group, layers_out)
    sl = build_shortlist(ledger, a.group, final_set)
    out_json = ROOT / "data" / f"shortlist_{a.group}.json"
    out_md = ROOT / "reports" / f"shortlist_{a.group}.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    sl["final_set_source"] = final_src
    out_json.write_text(json.dumps(sl, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    out_md.write_text(render_md(sl), encoding="utf-8")
    n_short = len(sl["shortlist"])

    # ---- 4. 组合层（5.5）+ 输出契约 ----
    # 契约：每组一行 GROUP=<组名> SHORTLIST=<只数>（<3 视为失败），末尾 PORTFOLIO_OK
    print(f"GROUP={a.group} SHORTLIST={n_short}")
    if n_short < 3:
        print(f"[pipeline] 入围名单只有 {n_short} 个（rules.md 5.4 要求 3 个）→ 失败")
        print("PORTFOLIO_OK=0")
        return 1
    try:
        result = run_portfolio(list(sl["shortlist"]), a.group, store=store)
        p_json = ROOT / "data" / f"portfolio_{a.group}.json"
        p_md = ROOT / "reports" / f"portfolio_{a.group}.md"
        p_json.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        from portfolio import render_md as _render_md
        p_md.write_text(_render_md(result), encoding="utf-8")
        print(f"[pipeline] 组合层三段检验完成 -> {p_json}")
        print(f"[pipeline] 报告 -> {p_md}")
    except Exception as ex:  # noqa: BLE001
        print(f"[pipeline] 组合层失败：{ex!r}")
        print("PORTFOLIO_OK=0")
        return 1

    print(f"[pipeline] 全流程完成（用时 {time.time() - t0:.1f}s）："
          f"{len(paths)} 个配置单 → 漏斗 → 入围 {n_short} 个 → 组合层")
    print("PORTFOLIO_OK=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
