# -*- coding: utf-8 -*-
"""
检查三：封存测试 —— tests/sealed_test.py

在「项目根目录不存在 OPEN_SEALED 文件」的现状下，尝试多条 >= 2025-01-01 的
读取路径，每条都必须抛异常且异常信息指向封存期（含「封存期」字样）；任何一条
没抛即失败。本测试自己绝不读取 data/sealed/ 的内容（只把路径【交给引擎接口】，
断言其拒绝）。日期口径 = rules.md 第 1 节（3.5 版）：搜索期 2014~2022、
验证期 2023-01-01~2024-12-31（**放行**，作对照）、封存期 2025-01-01 起。

覆盖路径：
  1-6  guard.read_parquet：相对路径 / 绝对路径 / ../ 穿越路径 / 大小写变体 /
       反斜杠变体 / 封存目录下不存在的文件（路径检查应先于文件存在性）
  7-8  guard.exists / guard.list_dir 对 data/sealed/
  9-11 guard.check_date_range：end 触界、start 触界、end 恰为 2025-01-01
  12   合法区间放行（对照 = 验证期 2023-01-01~2024-12-31，必须不抛）
  13   Backtester 构造（区间触及 2025）—— backtest.py Backtester.__init__
  14   run_backtest（区间触及 2025）—— 会被 run_backtest 的 except 捕获落一条
       error_runtime 台账后重新抛出（顺带验证：被拦截的执行也进台账）
  15   run_batch.main --end 2025-12-31 —— run_batch.main 入口先过
       guard.check_date_range 再分发（并行/串行两路都在其后）
  16   backtest.main --end 2025-06-30 —— backtest.main 入口同上
  17   项目根目录不存在 OPEN_SEALED 文件（rules.md 第 1 节）
  18   guard.assert_no_sealed_access() 不抛（当前确实未开封）
  19   观察项（不计成败）：DataStore.asof("2025-06-30")——DataStore 只装
       data/raw（<=2024-12-31，全部经 guard），该视图返回的最大日期必须
       <= 2024-12-31，证明此路径不可能带出封存期数据（引擎对它不抛异常是
       合理的：并没有读取任何封存数据）。

退出码：全部按预期 = 0，任何一条未拦截 / 断言失败 = 1。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

import numpy as np  # noqa: E402

import guard  # noqa: E402
from backtest import Backtester, run_backtest  # noqa: E402
from config import load_config  # noqa: E402
from prices import DataStore  # noqa: E402

failures: list[str] = []
n_checked = 0


def expect_sealed(name: str, fn):
    """fn() 必须抛 SealedDataError 且信息含「封存期」。"""
    global n_checked
    n_checked += 1
    try:
        fn()
    except guard.SealedDataError as e:
        msg = str(e)
        if "封存期" not in msg:
            failures.append(f"{name}: 抛了 SealedDataError 但信息未指向封存期：{msg!r}")
            print(f"  [FAIL] {name}: 异常信息未含『封存期』: {msg!r}")
        else:
            print(f"  [PASS] {name}: 拒绝（{msg[:60]}…）")
        return
    except Exception as e:  # noqa: BLE001
        failures.append(f"{name}: 抛了非 SealedDataError 的异常 {type(e).__name__}: {e!r}")
        print(f"  [FAIL] {name}: 异常类型错误 {type(e).__name__}: {e!r}")
        return
    failures.append(f"{name}: 未抛异常（封存路径/区间被放行！）")
    print(f"  [FAIL] {name}: 未抛异常")


def expect_ok(name: str, fn):
    global n_checked
    n_checked += 1
    try:
        fn()
        print(f"  [PASS] {name}: 按预期放行")
    except Exception as e:  # noqa: BLE001
        failures.append(f"{name}: 不应抛异常却抛了 {type(e).__name__}: {e!r}")
        print(f"  [FAIL] {name}: 不应抛异常却抛了 {e!r}")


def main() -> int:
    t0 = time.time()
    print("[sealed] 前置：确认项目根目录无 OPEN_SEALED 文件")
    global n_checked
    n_checked += 1
    marker = ROOT / "OPEN_SEALED"
    if marker.exists():
        failures.append("项目根目录存在 OPEN_SEALED 文件（当前应处于封存状态）")
        print("  [FAIL] OPEN_SEALED 存在")
        return 1
    print("  [PASS] OPEN_SEALED 不存在（封存生效中）")
    n_checked += 1
    try:
        guard.assert_no_sealed_access()
        print("  [PASS] guard.assert_no_sealed_access() 不抛（未开封）")
    except Exception as e:  # noqa: BLE001
        failures.append(f"guard.assert_no_sealed_access() 异常: {e!r}")
        print(f"  [FAIL] guard.assert_no_sealed_access(): {e!r}")

    print("\n[sealed] 1) guard.read_parquet / exists / list_dir 的封存路径")
    expect_sealed("read_parquet 相对路径 data/sealed/etf/sh510300.parquet",
                  lambda: guard.read_parquet("data/sealed/etf/sh510300.parquet"))
    expect_sealed("read_parquet 绝对路径 data/sealed/k_data/sh.600000_3.parquet",
                  lambda: guard.read_parquet(ROOT / "data/sealed/k_data/sh.600000_3.parquet"))
    expect_sealed("read_parquet 穿越路径 data/raw/../sealed/etf/sh510300.parquet",
                  lambda: guard.read_parquet("data/raw/../sealed/etf/sh510300.parquet"))
    expect_sealed("read_parquet 大小写变体 DATA/Sealed/ETF/sh510300.parquet",
                  lambda: guard.read_parquet("DATA/Sealed/ETF/sh510300.parquet"))
    expect_sealed("read_parquet 反斜杠变体 data\\sealed\\etf\\sh510300.parquet",
                  lambda: guard.read_parquet("data\\sealed\\etf\\sh510300.parquet"))
    expect_sealed("read_parquet 封存目录下不存在的文件（路径检查先于 IO）",
                  lambda: guard.read_parquet("data/sealed/etf/__no_such_file__.parquet"))
    expect_sealed("guard.exists('data/sealed')",
                  lambda: guard.exists("data/sealed"))
    expect_sealed("guard.list_dir('data/sealed')",
                  lambda: guard.list_dir("data/sealed"))

    print("\n[sealed] 2) guard.check_date_range 的 2025 区间")
    expect_sealed("check_date_range('2014-01-01','2025-06-30')",
                  lambda: guard.check_date_range("2014-01-01", "2025-06-30"))
    expect_sealed("check_date_range('2025-01-01','2025-06-30')",
                  lambda: guard.check_date_range("2025-01-01", "2025-06-30"))
    expect_sealed("check_date_range('2024-06-01','2025-01-01')（end 恰为封存首日）",
                  lambda: guard.check_date_range("2024-06-01", "2025-01-01"))
    expect_ok("check_date_range('2023-01-01','2024-12-31')（对照 = 验证期，应放行）",
              lambda: guard.check_date_range("2023-01-01", "2024-12-31"))

    print("\n[sealed] 3) 引擎回测入口带 2025 区间")
    store = DataStore()
    cfg = load_config(ROOT / "tests/fixtures/a_pullback_lowvol.yaml")
    expect_sealed("Backtester(store, cfg, '2014-01-01','2025-06-30')",
                  lambda: Backtester(store, cfg, "2014-01-01", "2025-06-30"))

    def _ledger_lines() -> int:
        """台账行数（文件不存在按 0 行计——第 2 版起台账可能尚为空）。"""
        p = ROOT / "ledger/ledger.csv"
        return p.read_text(encoding="utf-8").count("\n") if p.exists() else 0

    ledger_before = _ledger_lines()
    expect_sealed("run_backtest(store, cfg_path, '2014-01-01','2025-12-31', group='test')",
                  lambda: run_backtest(store, ROOT / "tests/fixtures/a_pullback_lowvol.yaml",
                                       "2014-01-01", "2025-12-31", group="test"))
    ledger_after = _ledger_lines()
    n_checked += 1
    if ledger_after == ledger_before + 1:
        print(f"  [PASS] 被拦截的执行也落了台账（{ledger_before} -> {ledger_after} 行）")
    else:
        print(f"  [NOTE] 台账行数 {ledger_before} -> {ledger_after}（预期 +1；"
              f"差额 {(ledger_after-ledger_before)}，仅记录，不计成败）")

    import run_batch
    expect_sealed("run_batch.main(--dir strategies/examples --group test --end 2025-12-31)",
                  lambda: run_batch.main(["--dir", "strategies/examples",
                                          "--group", "test",
                                          "--start", "2014-01-01",
                                          "--end", "2025-12-31"]))
    import backtest
    expect_sealed("backtest.main(cfg, --group test --end 2025-06-30)",
                  lambda: backtest.main([str(ROOT / "tests/fixtures/a_pullback_lowvol.yaml"),
                                         "--group", "test",
                                         "--start", "2014-01-01",
                                         "--end", "2025-06-30"]))

    print("\n[sealed] 4) 观察项：DataStore.asof 越过 2024-12-31 的视图（不读封存数据）")
    view = store.asof("2025-06-30")
    max_d = max(view.calendar)
    n_checked += 1
    if max_d <= "20241231":
        print(f"  [PASS] asof('2025-06-30') 视图最大日期 = {max_d}（<= raw 上界，无封存数据可达）")
    else:
        failures.append(f"asof('2025-06-30') 视图包含 > 2024-12-31 的日期: {max_d}")
        print(f"  [FAIL] asof 视图最大日期 {max_d} 超出 raw 上界")

    print(f"\n[sealed] 摘要：{n_checked} 项检查，失败 {len(failures)} 条；"
          f"总用时 {time.time()-t0:.0f}s")
    if failures:
        print("[sealed] 结论：FAIL（存在未被拦截的封存期读取路径）")
        for f in failures:
            print(f"    ! {f}")
        return 1
    print("[sealed] 结论：PASS（所有 >=2025-01-01 读取路径均被拦截且信息指向封存期）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
