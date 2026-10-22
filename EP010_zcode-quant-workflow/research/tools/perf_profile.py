# -*- coding: utf-8 -*-
"""
tools/perf_profile.py —— 单配置回测耗时剖析（第 2 步任务 B）

把一次完整回测拆四桶计时：面板加载 / 零件取值 / 撮合循环 / 台账写入（+其他）。
零插桩：不改任何 engine/ 代码，wall-clock + cProfile 函数级归类，两遍顺序固定：

  遍 1（cProfile，**冷零件缓存**）：进程首个配置的完整成本——零件全量值
       缓存（backtest._StoreCtx.spec_cache，进程内跨配置共享，backtest.py:634）
       尚未填充，零件求值真实计入本遍。四桶秒数全部取自本遍。
  遍 2（wall-clock，**热零件缓存**）：同一进程紧随其后的第二次同配置回测，
       全部零件值命中缓存——这是批量回测（funnel/农场，每 worker 进程跑
       几十上百个配置）中「第 2+ 个配置」的每配置成本口径。

口径：
  * 面板加载 = wall-clock 的 panel_store.real_store()（profiler 段之外）；
  * 回测段 = run_backtest(store, cfg, DEFAULT, DEFAULT, group=test, record=True)，
    与生产完全同一代码路径（含 ch14、落盘、台账）；QUANT_BT_RESULT_CACHE=0
    关掉结果复用，保证两遍都是真算；
  * 零件取值桶 = operators.py / parts/ 已登记零件模块全部函数 tottime 之和
    + backtest 零件取值支撑函数（_op_values/_etf_values/_etf_value_on/_val/
    _spec_values_on）tottime 之和；
  * 撮合循环桶 = cumtime(Backtester.run) − 零件取值桶（run 子树内除零件求值
    外的全部：日循环、买卖撮合、截面准备、排名/中性化）；
  * 台账写入桶 = cumtime(record_ledger)（跨进程锁 + CSV 追加整棵子树）；
  * 其他 = cProfile 段总时长 − run 子树 − 台账 − ch14(_attach_ch14) −
    基准(run_benchmark) − 落盘(_dump_artifacts)（后三项单列）。
  * cProfile 自身有开销；四桶秒数（遍 1）与总时长对照（遍 2 wall）分开报告，
    绝不混用。

用法：python tools/perf_profile.py perf_corpus/pc_s10.yaml [--group test]
输出：stdout 摘要 + 重写 reports/perf_profile_buckets.json（机器可读）。
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import sys
import time
from pathlib import Path

os.environ.setdefault("QUANT_BT_RESULT_CACHE", "0")   # 剖析必须真算（绕过结果复用）
os.environ.setdefault("QUANT_BT_RUN_DIR_REUSE", "0")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

import guard  # noqa: E402  先于 numpy/pandas

import panel_store
from backtest import (DEFAULT_END, DEFAULT_START,  # noqa: E402
                      run_backtest)

# 零件取值支撑函数（backtest.py 内，值数组来自 operators.eval_spec）
PARTS_SUPPORT_BT = {"_op_values", "_etf_values", "_etf_value_on", "_val",
                    "_spec_values_on"}


def _bucket_of(filename: str, funcname: str) -> str:
    """cProfile 条目 → 桶名（'parts' / 'bt_module' / 'ledger' / 'ext'）。"""
    f = filename.replace("\\", "/")
    if f.endswith("engine/operators.py") or "/parts/" in f:
        return "parts"
    if f.endswith("engine/backtest.py"):
        if funcname in PARTS_SUPPORT_BT:
            return "parts"
        return "bt_module"
    return "ext"


def profile_one(cfg_path: str, group: str) -> dict:
    t0 = time.perf_counter()
    store = panel_store.real_store(quiet=True)
    panel_load_s = time.perf_counter() - t0

    # ---- 遍 1：cProfile，冷零件缓存（进程首个配置的完整成本）----
    pr = cProfile.Profile()
    t1 = time.perf_counter()
    pr.enable()
    res1 = run_backtest(store, cfg_path, DEFAULT_START, DEFAULT_END,
                        group=group, quiet=True)
    pr.disable()
    run_prof_s = time.perf_counter() - t1

    # ---- 遍 2：wall-clock，热零件缓存（批量模式第 2+ 配置口径）----
    t2 = time.perf_counter()
    res2 = run_backtest(store, cfg_path, DEFAULT_START, DEFAULT_END,
                        group=group, quiet=True)
    run_wall_hot_s = time.perf_counter() - t2

    st = pstats.Stats(pr)
    tt_parts_support = 0.0                # backtest 零件支撑函数自身耗时
    ct_parts = 0.0                        # cumtime(operators.eval_spec) 之和
    ct_ledger = ct_run = ct_ch14 = ct_bench = ct_dump = 0.0
    for (fn, _line, name), (cc, nc, tt, ct, callers) in st.stats.items():
        b = _bucket_of(fn, name)
        if b == "parts":
            if fn.replace("\\", "/").endswith("engine/operators.py") \
                    and name == "eval_spec":
                ct_parts += ct            # 每个唯一 spec 一次，整棵求值子树
            elif fn.replace("\\", "/").endswith("engine/backtest.py"):
                tt_parts_support += tt    # _op_values 等五支撑函数自身耗时
        elif b == "bt_module":
            if name == "record_ledger":
                ct_ledger = ct
            elif name == "run":
                ct_run = ct              # Backtester.run（backtest.py 内唯一 run）
            elif name == "_attach_ch14":
                ct_ch14 = ct
            elif name == "run_benchmark":
                ct_bench = ct
            elif name == "_dump_artifacts":
                ct_dump = ct

    # 桶秒数（全部来自遍 1 cProfile）。零件取值 = Σcumtime(eval_spec)：
    # 覆盖整棵求值子树（含 pandas to_numpy/rank 等库时间），比 tottime 求和
    # 完整；再加 backtest 侧支撑函数自身耗时（毫秒级）。
    parts_s = ct_parts + tt_parts_support
    match_s = max(0.0, ct_run - parts_s)      # run 子树除零件求值外 = 撮合循环
    ledger_s = ct_ledger
    other_s = max(0.0, run_prof_s - ct_run - ledger_s - ct_ch14 - ct_bench - ct_dump)

    # 热点：tottime Top（截取 pstats 输出的函数行）
    buf = io.StringIO()
    st.stream = buf
    st.sort_stats("tottime").print_stats(28)
    lines = [ln.rstrip() for ln in buf.getvalue().splitlines()
             if ln.strip() and ("backtest.py" in ln or "operators.py" in ln
                                or "prices.py" in ln or "panel_store.py" in ln
                                or "ch14.py" in ln or "/parts/" in ln
                                or "pandas" in ln or "numpy" in ln)][:24]

    out = {
        "config": str(cfg_path),
        "start_end": [DEFAULT_START, DEFAULT_END],
        "group": group,
        "n_trades": res1.get("n_trades"),
        "n_rebalances": res1.get("n_rebalances"),
        "panel_load_s": round(panel_load_s, 2),
        "run_prof_cold_s": round(run_prof_s, 2),
        "run_wall_hot_s": round(run_wall_hot_s, 2),
        "buckets_prof_cold": {
            "面板加载(段外wall)": round(panel_load_s, 2),
            "零件取值": round(parts_s, 2),
            "撮合循环": round(match_s, 2),
            "台账写入": round(ledger_s, 2),
            "其他(run子树外)": round(other_s, 2),
        },
        "other_detail": {"ch14指标_挂载": round(ct_ch14, 2),
                         "基准日线": round(ct_bench, 2),
                         "产物落盘": round(ct_dump, 2)},
        "top_tottime_lines": lines,
    }
    j = ROOT / "reports" / "perf_profile_buckets.json"
    j.parent.mkdir(parents=True, exist_ok=True)
    j.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in
                      ("config", "n_trades", "n_rebalances", "panel_load_s",
                       "run_prof_cold_s", "run_wall_hot_s", "buckets_prof_cold",
                       "other_detail")}, ensure_ascii=False, indent=1))
    print("[perf_profile] 热点（tottime Top，引擎/库行）：")
    for ln in lines:
        print("  " + ln)
    print(f"[perf_profile] 明细 JSON：{j}")
    return out


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="单配置回测四桶剖析")
    ap.add_argument("config")
    ap.add_argument("--group", default="test")
    a = ap.parse_args(argv)
    guard.check_date_range(DEFAULT_START, DEFAULT_END)
    profile_one(a.config, a.group)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
