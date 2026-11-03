# -*- coding: utf-8 -*-
"""
engine/selftest.py —— 引擎自测（可重复执行的验收脚本，Tushare 版）

覆盖（与独立审计清单一一对应）：
  1. 封存守卫：data/sealed/ 下全部 15 个数据文件读取被拦；2025+ 区间被拦；
     验证期放行。
  2. 零件手算：合成小面板逐项核对（ret_n / ma_n / streak_up / dist_high_n /
     break_high_n / size_ln / pe_ttm / roe / fc_* / ex_*）。
  3. 撕报纸测试（新旧零件全覆盖，含嵌套 spec）：全量面板第 T 行值 ==
     as-of-T 切片第 T 行值（只回看性质）。
  4. 财务 / 预告 / 快报专项：把某条记录 ann_date 往后推一天，T 日可见的值
     必须跟着变（align_by_ann_date 纯函数复算）。
  5. 行业专项：合成夹具（≥2 条不同一级行业记录）验证换前/换后/边界日
     归属、空 l1_code 记录剔除与 industry_on（真实数据每码仅 1 条当前行业
     记录，无换行业样本——数据源形态限制，见 data_check.md）。
  6. ST 专项：中途戴帽又摘帽的股票，戴帽期间被剔除、之外不被剔除。
  7. 复权专项：000001.SZ 2020-12-31 的 adj_nav 日收益 == pct_chg（≈+0.73%）。
  8. 对拍：入围分、组合层（底仓状态/组合收益）、时序分位、截面分位、
     行业内排名用朴素实现逐项比对，误差 < 1e-9。
  9. 入围制反例：「0 个满足硬性资格」→ 3 个补位（未过第 1 层标注）；
     「只有 1 个满足」→ 1 合格 + 2 补位（验证期未通过标注）。
 10. 分组反例：前缀与 group 矛盾时，分组只认台账 group 列；漏斗展示分路
     （config_track）同样只认 group 列。
 11. 撮合专项：合成小回测——涨停买不进（顺延次日成交）、ST 不入截面、
     停牌（无行情行）顺延；跌停卖不出。
 12. 档位校验：非法窗口 / 无量纲零件作条件 / industry_cap 越档被拒。
 13. 3.2 邻域探针（rules.md 5.2）：名字含 __ 的探针在候选集（layer_lists）、
     邻域规划（plan_l5_l6 不为探针生成邻域，杜绝二阶递归）、L7（l7_dedup）、
     入围排名（build_shortlist）四处被排除；台账行与组 N 口径不变
     （探针照常带 L1~L4 标记、照常计入 n_trials_for）。
 14. 3.2 试跑模式（rules.md 第 10 章）：trial_select 只取每组入围分前 30、
     并列按 |超额回撤|；execute_l5_l6_with_runner 试跑路径先对全部幸存者跑
     验证期、只对 top 生成邻域、其余标注「未做邻域检验」且不得进 L5~final；
     --formal 口径恢复全量邻域检验。
 15. 3.2 猴子独立性（rules.md 第 11 章）：canonical_config 结构归一（键排序、
     数值统一格式、列表保序）；gen_monkey 与台账任何组已有配置去重、重复的
     用同一随机流重采样；同 seed + 同台账 → 输出确定（逐位一致）。
 16. 3.2 并行执行（rules.md 第 12 章）：default_workers = CPU−2；
     同一批合成配置 SeqRunner 与 PoolRunner 回测指标逐位一致；常驻池跨批次
     复用、close() 后重建仍逐位一致。
 17. 3.2 台账并发追加：多进程并发 record_ledger（临时目录台账）不丢行、
     不串行（msvcrt/fcntl 跨进程锁）；字节级行尾断言——全部行恰为 CRLF、
     无 \r\r\n 双 CR（Windows 文本模式翻译是已修复的行尾污染根因）。

用法：.venv/Scripts/python.exe -X utf8 engine/selftest.py   （退出码 0 = 全过）
"""

from __future__ import annotations

import copy
import csv
import io
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402  必须先于 numpy/pandas（guard 钉死 BLAS 线程环境变量）

import numpy as np
import pandas as pd
import yaml
import operators as op  # noqa: E402
from backtest import (LEDGER_COLS, Backtester, funnel_flags,  # noqa: E402
                      record_ledger, run_benchmark)
from config import ConfigError, load_config  # noqa: E402
from funnel import (MAIN_MONKEY_SEED, SEARCH_END, SEARCH_START,  # noqa: E402
                    TAG_NO_L5_CHECK, TRIAL_L5_TOP_K, VALID_END, VALID_START,
                    SeqRunner, PoolRunner, _synthetic_store, build_neighbor_set,
                    canonical_config, default_workers, entry_score,
                    execute_l5_l6_with_runner, existing_canonical_configs,
                    find_config_yaml, flags_of, gen_monkey, group_to_track,
                    is_probe, l7_dedup, layer_lists, latest_search_rows,
                    make_runner, n_trials_for, plan_l5_l6, plan_validation,
                    read_ledger, run_dir_of, trial_select)
from portfolio import (BASE_WEIGHT, MA_WINDOW, SAT_WEIGHT, SWITCH_COST,  # noqa: E402
                       base_state_series, portfolio_returns, satellite_returns)
from prices import (ETF_BENCHMARK, ETF_GOLD, DataStore,  # noqa: E402
                    _interval_value, align_by_ann_date, industry_intervals,
                    st_intervals)
from shortlist import (GRADE_OUT, GRADE_SHORT, TAG_NO_L1, TAG_NO_VAL,  # noqa: E402
                       build_shortlist)

ROOT = Path(__file__).resolve().parent.parent

SEALED_FILES = ["daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d",
                "namechange", "fina_indicator", "forecast", "express",
                "index_member_all", "index_members", "stock_basic", "trade_cal",
                "fund_daily", "fund_adj"]

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str]] = []


def check(name: str, cond, detail: str = ""):
    ok = bool(cond)
    results.append((name, PASS if ok else FAIL))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  {detail}" if detail and not ok else ""))


def make_mini_panel() -> pd.DataFrame:
    """合成小面板：1 只股票 × 40 行，新列名，数值规则简单可手算。"""
    n = 40
    dates = [f"2014{m:02d}{d:02d}" for m, d in
             zip([1] * 20 + [2] * 20, list(range(1, 21)) * 2)]
    closes = np.round(10 + np.arange(n) * 0.1, 2)
    pct = np.round((closes[1:] / closes[:-1] - 1) * 100, 4).tolist() + [0.5]
    return pd.DataFrame({
        "date": dates, "code": ["000001.SZ"] * n,
        "open": closes + 0.01, "high": closes + 0.05, "low": closes - 0.05,
        "close": closes, "pre_close": np.r_[closes[0], closes[:-1]],
        "pct_chg": pct, "vol": np.arange(n, dtype=float) + 1,
        "amount": np.arange(n, dtype=float) * 10,
        "af": 2.0, "adj_nav": closes * 2.0,
        "turnover_rate": np.linspace(1, 3, n), "pe_ttm": np.linspace(8, 30, n),
        "pb": np.linspace(0.8, 2.5, n), "ps_ttm": np.linspace(1, 4, n),
        "total_mv": np.linspace(5e5, 9e5, n), "circ_mv": np.linspace(3e5, 7e5, n),
        "up_limit": np.full(n, np.nan), "down_limit": np.full(n, np.nan),
        "is_st": 0.0, "l1_code": ["801010"] * n, "l1_name": ["农林牧渔"] * n,
        "fin_end_date": [None] * n, "roe": np.linspace(5, 15, n),
        "or_yoy": np.linspace(-5, 25, n), "netprofit_yoy": np.linspace(-10, 40, n),
        "fc_ann_date": [None] * n, "fc_type": [None] * n,
        "fc_type_code": np.where(np.arange(n) % 2 == 0, 2.0, -2.0),
        "fc_chg_mid": np.linspace(-50, 80, n), "fc_days": np.arange(n, dtype=float),
        "ex_ann_date": [None] * n, "ex_yoy": np.linspace(-8, 33, n),
        "ex_days": np.arange(n, dtype=float) + 1,
        "n_listed": np.arange(n, dtype=float) + 400,
        # 资金面列（prices.DataStore 对齐后的面板形态）：
        # 龙虎榜：第 2 / 10 行上榜；上榜即有机构净买入占比，之后保持最近一次值
        "tl_on_list": np.where(np.isin(np.arange(n), [2, 10]), 1.0, 0.0),
        "tl_inst_netbuy_pct": np.where(np.arange(n) < 2, np.nan,
                                       np.where(np.arange(n) < 10, 5.0, -3.0)),
        # 两融：前 5 行无数据（NaN）；北向：前 10 行无数据（NaN，2016-08 前语义）
        "margin_rzye": np.where(np.arange(n) < 5, np.nan, 1e9 + np.arange(n) * 1e7),
        "hk_ratio": np.where(np.arange(n) < 10, np.nan, 0.5 + np.arange(n) * 0.01),
    })


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    store = DataStore(quiet=True)

    # ============================================================
    print("== 1. 封存守卫（全部新数据文件 + 区间）==")
    blocked = 0
    for f in SEALED_FILES:
        try:
            guard.read_parquet(f"data/sealed/{f}.parquet")
            check(f"sealed/{f}.parquet 拦截", False)
        except guard.SealedDataError:
            blocked += 1
    check(f"data/sealed/ 全部 {len(SEALED_FILES)} 个文件读取被拦", blocked == len(SEALED_FILES))
    try:
        guard.list_dir("data/sealed")
        check("列封存目录被拦", False)
    except guard.SealedDataError:
        check("列封存目录被拦", True)
    for rng, ok in [(("20140101", "20221231"), True), (("20230101", "20241231"), True),
                    (("20210101", "20250101"), False), (("20250101", "20260101"), False),
                    (("20140101", "2025-01-01"), False)]:
        try:
            guard.check_date_range(*rng)
            check(f"区间 {rng} 守卫放行", ok)
        except guard.SealedDataError:
            check(f"区间 {rng} 守卫拦截", not ok)

    # ============================================================
    print("== 2. 零件手算（合成面板）==")
    p = make_mini_panel()
    d = p
    ma3 = op.ma_n(p, 3)["value"].to_numpy()
    i = 10
    check("ma_3 手算", abs(ma3[i] - d["adj_nav"].iloc[i - 2:i + 1].mean()) < 1e-12)
    r5 = op.ret_n(p, 5)["value"].to_numpy()
    hand = (d["adj_nav"].iloc[i] / d["adj_nav"].iloc[i - 5] - 1) * 100
    check("ret_5 手算", abs(r5[i] - hand) < 1e-9)
    su = op.streak_up(p)["value"].to_numpy()
    exp = 0.0
    exps = []
    for v in d["pct_chg"]:
        exp = exp + 1 if v > 0 else 0.0
        exps.append(exp)
    check("streak_up 手算", np.array_equal(su, np.array(exps)))
    dh = op.dist_high_n(p, 5)["value"].to_numpy()
    hq = (d["high"] * d["af"]).to_numpy()
    hand = (d["adj_nav"].to_numpy()[i] / hq[i - 4:i + 1].max() - 1) * 100
    check("dist_high_5 手算", abs(dh[i] - hand) < 1e-9)
    bh = op.break_high_n(p, 5)["value"].to_numpy()
    check("break_high_5 手算", bh[9] == (1.0 if hq[9] > hq[4:9].max() else 0.0))
    sl = op.size_ln(p)["value"].to_numpy()
    check("size_ln 手算", np.allclose(sl, np.log(d["circ_mv"]), equal_nan=True))
    check("pe_ttm 直通", np.allclose(op.pe_ttm(p)["value"].to_numpy(), d["pe_ttm"]))
    check("roe 直通", np.allclose(op.roe(p)["value"].to_numpy(), d["roe"]))
    check("fc_type_code 直通", np.allclose(op.fc_type_code(p)["value"].to_numpy(),
                                           d["fc_type_code"]))
    check("fc_days 直通", np.allclose(op.fc_days(p)["value"].to_numpy(), d["fc_days"]))
    check("ex_yoy 直通", np.allclose(op.ex_yoy(p)["value"].to_numpy(), d["ex_yoy"]))
    # ---- 资金面零件手算（rules.md 7.5 第 3.4 版）----
    tl5 = op.top_list_n(p, 5)["value"].to_numpy()
    tl_on = d["tl_on_list"].to_numpy()
    exp_tl = [np.nan] * len(p)
    for j in range(4, len(p)):                # 窗口完整才定义；含当日 5 行
        exp_tl[j] = 1.0 if tl_on[j - 4:j + 1].max() > 0 else 0.0
    check("top_list_5 手算（近5行含当日是否上过榜；前4行 NaN）",
          np.array_equal(tl5, np.array(exp_tl, dtype=float),
                         equal_nan=True))
    check("top_list_20 窗口内必有榜 → 1", op.top_list_n(p, 20)["value"].to_numpy()[19] == 1.0)
    check("inst_netbuy 直通（上榜后保持最近一次值）",
          np.allclose(op.inst_netbuy(p)["value"].to_numpy(),
                      d["tl_inst_netbuy_pct"], equal_nan=True))
    mr = op.margin_ratio(p)["value"].to_numpy()
    hand_mr = d["margin_rzye"].to_numpy() / (d["circ_mv"].to_numpy() * 1e4) * 100.0
    check("margin_ratio 手算（rzye 元 / circ_mv 万元×1e4）",
          np.allclose(mr, hand_mr, equal_nan=True))
    check("margin_ratio 无两融记录 → NaN（不 0 填充）", bool(np.isnan(mr[:5]).all()))
    mc5 = op.margin_chg_n(p, 5)["value"].to_numpy()
    zy = d["margin_rzye"].to_numpy()
    hand_mc = (zy[10] / zy[5] - 1.0) * 100.0
    check("margin_chg_5 手算（对齐值 10 行 vs 5 行）", abs(mc5[10] - hand_mc) < 1e-12)
    check("margin_chg_5 前值 NaN → NaN", bool(np.isnan(mc5[9])))
    check("hk_ratio 直通（北向占比）",
          np.allclose(op.hk_ratio(p)["value"].to_numpy(), d["hk_ratio"], equal_nan=True))
    hc20 = op.hk_chg_n(p, 20)["value"].to_numpy()
    hr = d["hk_ratio"].to_numpy()
    check("hk_chg_20 手算（当前占比 − 20 行前占比，百分点）",
          abs(hc20[35] - (hr[35] - hr[15])) < 1e-12)
    check("hk_chg_20 20 行前缺失 → NaN", bool(np.isnan(hc20[25])))
    try:
        op.ret_n(p, 7)
        check("非法窗口拦截", False)
    except ValueError:
        check("非法窗口拦截", True)
    f = funnel_flags({"type": "rule", "ir": 0.4, "excess_max_dd": -0.30,
                      "ann_excess": 0.05, "beat_years": 6, "n_trades": 200})
    check("L3 v3 边界：ir=0.4 且超额回撤=30% 不取等", f["funnel_l3"] == 0)
    f = funnel_flags({"type": "rule", "ir": 0.4 + 1e-12, "excess_max_dd": -0.30 + 1e-12,
                      "ann_excess": 0.05, "beat_years": 6, "n_trades": 200})
    check("L3 v3：ir>0.4 且超额回撤<30% 通过", f["funnel_l3"] == 1)
    # L1 按调仓频率分档 / L4 ≥6 年（rules.md 5.2，3.4 修订版口径）
    check("L1 分档：打分型缺省（周度）300 期过",
          funnel_flags({"type": "score", "n_rebalances": 300, "ann_excess": 0.05,
                        "ir": 1.0, "excess_max_dd": -0.1, "beat_years": 6})["funnel_l1"] == 1)
    check("L1 分档：周度 299 期不过",
          funnel_flags({"type": "score", "n_rebalances": 299, "ann_excess": 0.05,
                        "ir": 1.0, "excess_max_dd": -0.1, "beat_years": 6})["funnel_l1"] == 0)
    check("L1 分档：月度 80 期过",
          funnel_flags({"type": "score", "n_rebalances": 80, "ann_excess": 0.05,
                        "ir": 1.0, "excess_max_dd": -0.1, "beat_years": 6,
                        "rebalance": "monthly_first_trade_day"})["funnel_l1"] == 1)
    check("L1 分档：月度 79 期不过",
          funnel_flags({"type": "score", "n_rebalances": 79, "ann_excess": 0.05,
                        "ir": 1.0, "excess_max_dd": -0.1, "beat_years": 6,
                        "rebalance": "monthly_first_trade_day"})["funnel_l1"] == 0)
    check("L4：beat_years=5 不过（门槛 ≥6）",
          funnel_flags({"type": "rule", "n_trades": 200, "ann_excess": 0.05,
                        "ir": 1.0, "excess_max_dd": -0.1, "beat_years": 5})["funnel_l4"] == 0)
    check("L4：beat_years=6 恰过",
          funnel_flags({"type": "rule", "n_trades": 200, "ann_excess": 0.05,
                        "ir": 1.0, "excess_max_dd": -0.1, "beat_years": 6})["funnel_l4"] == 1)

    # ============================================================
    print("== 3. 撕报纸（全量 == as-of 切片；新旧零件全覆盖，含嵌套 spec）==")
    full = store.panel
    specs: list[dict] = []
    for name in ("ret_n", "ma_n", "close_over_ma_n", "dist_high_n", "dist_low_n",
                 "vol_ratio_n", "turn_ma_n", "vol_n", "atr_close_n", "break_high_n"):
        for n in (3, 20, 250):
            specs.append({"op": name, "n": n})
    for name in ("close_pos_range", "turn", "streak_up", "streak_down", "size_ln",
                 "pe_ttm", "pb", "ps_ttm", "roe", "or_yoy", "netprofit_yoy",
                 "fc_type_code", "fc_chg_mid", "fc_days", "ex_yoy", "ex_days"):
        specs.append({"op": name})
    # 资金面零件（rules.md 7.5 第 3.4 版；面板列已在 DataStore 里 point-in-time 对齐）
    for name in ("top_list_n", "margin_chg_n", "hk_chg_n"):
        for n in (3, 20, 250):
            specs.append({"op": name, "n": n})
    for name in ("inst_netbuy", "margin_ratio", "hk_ratio"):
        specs.append({"op": name})
    specs.append({"op": "ts_pct", "n": 20, "of": {"op": "ret_n", "n": 5}})
    specs.append({"op": "ts_pct", "n": 250, "of": {"op": "pe_ttm"}})
    specs.append({"op": "xsec_pct", "of": {"op": "vol_n", "n": 20}})
    specs.append({"op": "ind_rank", "of": {"op": "ret_n", "n": 20}})
    specs.append({"op": "ts_pct", "n": 5, "of": {"op": "xsec_pct", "of": {"op": "pb"}}})
    specs.append({"op": "xsec_pct", "of": {"op": "hk_ratio"}})
    specs.append({"op": "ind_rank", "of": {"op": "margin_ratio"}})

    T_dates = ["20160630", "20201231"]
    allok = True
    bad = []
    for T in T_dates:
        sub = full[full["date"] <= T].reset_index(drop=True)
        key_full = pd.MultiIndex.from_arrays([full["code"], full["date"]])
        key_sub = pd.MultiIndex.from_arrays([sub["code"], sub["date"]])
        pos_in_full = key_full.get_indexer(key_sub)
        for spec in specs:
            try:
                a = op.eval_spec(full, spec)["value"].to_numpy()[pos_in_full]
                b = op.eval_spec(sub, spec)["value"].to_numpy()
            except ValueError as e:
                bad.append((T, op.canon_spec(spec), f"error {e}"))
                allok = False
                continue
            same = (np.isnan(a) & np.isnan(b)) | (a == b)
            if not bool(np.all(same)):
                dd = np.abs(a[~same] - b[~same]).max()
                bad.append((T, op.canon_spec(spec), f"maxdiff={dd}"))
                allok = False
    check(f"撕报纸：{len(specs)} 个 spec × {len(T_dates)} 个 T 日全等（含嵌套）",
          allok, f"{bad[:3]}")
    etf = store.etfs[ETF_BENCHMARK]
    es = etf[etf["date"] <= "20180630"].reset_index(drop=True)
    ok = all(np.array_equal(op.etf_above_ma_n(etf, n)["value"].to_numpy()[:len(es)],
                            op.etf_above_ma_n(es, n)["value"].to_numpy())
             for n in (3, 20, 250))
    check("撕报纸：etf_above_ma_n（ETF 日线）", ok)

    # ============================================================
    print("== 4. 财务 / 预告 / 快报 ann_date 专项（推迟一天 → T 日可见值必须变）==")
    for label, recs, col in [("fina_indicator", store.fin, "roe"),
                             ("forecast", store.fcs, "p_change_min"),
                             ("express", store.exps, "yoy_net_profit")]:
        df = recs.dropna(subset=["ann_date", "end_date"]).copy()
        df["ann_date"] = df["ann_date"].astype(str)
        df = df.sort_values(["ts_code", "ann_date"])
        found = False
        for (code, ann), grp in df.groupby(["ts_code", "ann_date"]):
            if str(code) not in set(store.panel["code"]):
                continue
            g = store.panel[store.panel["code"] == str(code)].reset_index(drop=True)
            sorted_dates = np.sort(g["date"].to_numpy())
            idx = int(np.searchsorted(sorted_dates, str(ann), side="left"))
            if idx >= len(sorted_dates):
                continue          # 该公告日之后没有行情行（退市/长期停牌），换下一条
            pos = idx            # T 日 = ann 之后第一个行情日：变异前该记录必可见
            codes = g["code"].to_numpy(dtype=object)
            dates_q = g["date"].to_numpy(dtype=object)
            base_ann = align_by_ann_date(recs, codes, dates_q, ["ann_date"])["ann_date"]
            mut = recs.copy()
            mask = (mut["ts_code"] == code) & (mut["ann_date"].astype(str) == ann)
            mut.loc[mask, "ann_date"] = (pd.Timestamp(ann)
                                         + pd.Timedelta(days=1)).strftime("%Y%m%d")
            mut_ann = align_by_ann_date(mut, codes, dates_q, ["ann_date"])["ann_date"]
            b_ann = str(base_ann[pos]) if base_ann[pos] is not None else None
            m_ann = str(mut_ann[pos]) if mut_ann[pos] is not None else None
            if not (b_ann == str(ann) and m_ann != str(ann)):
                continue          # 变异前后可见记录相同（有更新的其他记录覆盖），换下一条
            base_val = align_by_ann_date(recs, codes, dates_q, [col])[col]
            mut_val = align_by_ann_date(mut, codes, dates_q, [col])[col]
            bv = float(base_val[pos]) if base_val[pos] is not None else np.nan
            mv = float(mut_val[pos]) if mut_val[pos] is not None else np.nan
            val_changed = (np.isfinite(bv) != np.isfinite(mv)) or \
                          (np.isfinite(bv) and np.isfinite(mv) and bv != mv)
            if not val_changed:
                continue          # 前一条记录值恰好相同，换一条样本
            check(f"{label}：{code} 的 ann_date={ann} 推迟一天后 T 日可见记录改变",
                  True)
            check(f"{label}：T 日 {col} 数值跟着变（{bv} → {mv}）", True)
            found = True
            break
        if not found:
            check(f"{label}：找到可验证的 ann_date 样本", False)

    # ============================================================
    print("== 5. 行业专项（中途换申万一级行业；合成夹具）==")
    # data/raw/index_member_all.parquet 每码恰 1 条当前行业记录（数据源形态
    # 限制，真实数据不存在换行业样本），改用合成夹具驱动**同一生产逻辑**：
    # industry_intervals（区间解析）→ _interval_value（面板列归属，与
    # DataStore 构造 l1_code/l1_name 是同一调用）→ DataStore.industry_on
    # （逐码逐日归属）。断言强度不低于旧版，另补边界日/单记录/无记录用例。
    pool = set(store.codes)          # §6 ST 专项仍用真实面板股票池
    ind = pd.DataFrame({
        "ts_code": ["999999.SZ", "999999.SZ", "888888.SH", "777777.SH"],
        "in_date": ["20130104", "20160701", "20140102", "20150105"],
        "out_date": ["20160701", None, None, "20140103"],
        "l1_code": ["801010", "801080", "801050", ""],
        "l1_name": ["农林牧渔", "计算机", "银行", None],
    })
    iv = industry_intervals(ind)
    check("行业：夹具解析出 2 个有效代码（空 l1_code 记录被剔除）",
          set(iv) == {"999999.SZ", "888888.SH"}, f"{sorted(iv)}")
    ins, outs, l1s, l1ns = iv["999999.SZ"]
    check("行业：999999.SZ 有 ≥2 条不同一级行业记录",
          len(ins) >= 2 and str(l1s[0]) != str(l1s[1]), f"ins={len(ins)} {list(l1s)}")
    d1, d2 = "20150105", "20170103"      # 换行业前 / 换行业后的查询日
    qcodes = np.array(["999999.SZ"] * 3 + ["888888.SH", "666666.SZ"], dtype=object)
    qdates = np.array([d1, "20160701", d2, d2, d1], dtype=object)
    lc, ln = _interval_value(qcodes, qdates, iv, 2, 3)
    check("行业：换行业前归属旧一级行业（801010 农林牧渔）",
          str(lc[0]) == "801010" and str(ln[0]) == "农林牧渔", f"{lc[0]}/{ln[0]}")
    check("行业：切换当日已归新行业（in_date ≤ T < out_date）",
          str(lc[1]) == "801080", f"{lc[1]}")
    check("行业：换行业后归属新一级行业（801080 计算机）",
          str(lc[2]) == "801080" and str(ln[2]) == "计算机", f"{lc[2]}/{ln[2]}")
    check("行业：单记录代码按唯一区间归属", str(lc[3]) == "801050", f"{lc[3]}")
    check("行业：无记录代码无归属（None）", lc[4] is None, f"{lc[4]!r}")
    shim = SimpleNamespace(ind=ind)   # industry_on 只用 self.ind → 合成注入
    check("行业：industry_on 换行业前 = 旧行业代码",
          DataStore.industry_on(shim, "999999.SZ", d1) == "801010",
          f"{DataStore.industry_on(shim, '999999.SZ', d1)!r}")
    check("行业：industry_on 换行业后 = 新行业代码",
          DataStore.industry_on(shim, "999999.SZ", d2) == "801080",
          f"{DataStore.industry_on(shim, '999999.SZ', d2)!r}")
    check("行业：industry_on 首期之前无归属",
          DataStore.industry_on(shim, "999999.SZ", "20121231") is None,
          f"{DataStore.industry_on(shim, '999999.SZ', '20121231')!r}")

    # ============================================================
    print("== 6. ST 专项（戴帽期间剔除、摘帽后不剔除）==")
    sti = st_intervals(store.namechg)
    st_code, st_on_day, st_off_day = None, None, None
    for code, (starts, ends, flags) in sti.items():
        if code not in pool:
            continue
        idx_on = np.flatnonzero(flags == 1)
        for k in idx_on:
            on, off = str(starts[k]), str(ends[k])
            if off == "99999999" or on < "20140101" or off > "20241231":
                continue
            ds = store.panel[store.panel["code"] == code]["date"]
            if len(ds) and str(ds.iloc[0]) < on and str(ds.iloc[-1]) > off:
                st_code, st_on_day, st_off_day = code, on, off
                break
        if st_code:
            break
    if st_code:
        check("ST：戴帽期间 is_st_on=True",
              store.is_st_on(st_code, st_on_day) and store.is_st_on(st_code, st_off_day[:4] + "0615"),
              f"{st_code} @{st_on_day}")
        check("ST：摘帽后 is_st_on=False", not store.is_st_on(st_code, st_off_day))
        # 截面剔除：戴帽日不在 cross_rows，摘帽后出现过
        cfg = load_config(ROOT / "strategies/examples/b_trend_value.yaml")
        bt = Backtester(store, cfg, "20140101", "20221231")
        cross_on = bt._cross_rows(st_on_day)
        check("ST：戴帽日不入截面", all(c != st_code for c, _ in cross_on))
        rows_off = store.panel[(store.panel["code"] == st_code)
                               & (store.panel["date"] > st_off_day)]
        check("ST：摘帽后有行情行（可回截面）", len(rows_off) > 0)
    else:
        check("ST：找到戴帽又摘帽的样本", False)

    # ============================================================
    print("== 7. 复权专项（000001.SZ @ 2020-12-31）==")
    g = store.panel[store.panel["code"] == "000001.SZ"].reset_index(drop=True)
    pos = int(np.searchsorted(g["date"].to_numpy(), "20201231"))
    prev_adj, cur_adj = float(g["adj_nav"].iloc[pos - 1]), float(g["adj_nav"].iloc[pos])
    r_adj = (cur_adj / prev_adj - 1) * 100
    pct = float(g["pct_chg"].iloc[pos])
    # 价格 2 位小数的四舍五入噪声 ~1e-5pp；这里要求远小于 0.5pp 自检阈值
    check("000001.SZ 20201231 复权日收益 == pct_chg", abs(r_adj - pct) < 1e-3,
          f"adj={r_adj:.6f}% pct_chg={pct:.6f}%")
    check("000001.SZ 20201231 pct_chg ≈ +0.73%", abs(pct - 0.73) < 0.01, f"{pct:.4f}")

    # ============================================================
    print("== 8. 对拍（朴素实现逐项比对，误差 < 1e-9）==")
    # 8a. 时序分位 ts_pct
    vals = np.array([3.0, 1.0, 2.0, np.nan, 5.0, 0.5, 4.0, 2.5, 2.5, 7.0,
                     6.0, 1.5, 2.2, 2.2, 9.0, 0.1, 3.3, 4.4, 5.5, 6.6] * 2)
    tp = pd.DataFrame({"code": ["x"] * len(vals), "date": [f"d{i:02d}" for i in range(len(vals))],
                       "l1_code": ["A"] * len(vals)})
    n = 5
    got = op.ts_pct(tp, n, pd.Series(vals))["value"].to_numpy()
    naive = np.full(len(vals), np.nan)
    for t in range(len(vals)):
        if t >= n - 1:
            w = vals[t - n + 1:t + 1]
            if np.isfinite(w).all():
                naive[t] = float((w <= vals[t]).mean())
    check("对拍：ts_pct == 朴素窗口分位", np.allclose(got, naive, equal_nan=True, atol=1e-12))
    # 8b. 截面分位 xsec_pct（两日 × 多股）
    n2 = 8
    tp2 = pd.DataFrame({
        "code": [f"c{i}" for i in range(n2)] * 2,
        "date": ["d1"] * n2 + ["d2"] * n2,
        "l1_code": (["A", "A", "B", "B", "A", "B", "A", "B"]) * 2})
    v2 = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0, np.nan, 0.5, 2.5,
                    10.0, 8.0, 9.0, 7.0, 6.0, 5.5, 11.0, np.nan])
    got2 = op.xsec_pct(tp2, v2)["value"].to_numpy()
    naive2 = np.full(len(v2), np.nan)
    for dt in ("d1", "d2"):
        idx = [i for i in range(len(v2)) if tp2["date"][i] == dt and np.isfinite(v2[i])]
        srt = sorted(idx, key=lambda i: v2[i])
        m = len(srt)
        for rank, i in enumerate(srt):
            naive2[i] = rank / (m - 1) if m > 1 else 0.5
    check("对拍：xsec_pct == 朴素截面分位", np.allclose(got2, naive2, equal_nan=True, atol=1e-12))
    # 8c. 行业内排名 ind_rank
    got3 = op.ind_rank(tp2, v2)["value"].to_numpy()
    naive3 = np.full(len(v2), np.nan)
    for dt in ("d1", "d2"):
        for ind_name in ("A", "B"):
            idx = [i for i in range(len(v2))
                   if tp2["date"][i] == dt and tp2["l1_code"][i] == ind_name
                   and np.isfinite(v2[i])]
            if not idx:
                continue
            srt = sorted(idx, key=lambda i: v2[i])
            m = len(srt)
            for rank, i in enumerate(srt):
                naive3[i] = rank / (m - 1) if m > 1 else 0.5
    check("对拍：ind_rank == 朴素行业内分位", np.allclose(got3, naive3, equal_nan=True, atol=1e-12))
    # 8d. 入围分：min(两段 IR)
    rows = [
        {"ts": "2026-01-01T00:00:00Z", "config": "a_x", "group": "A", "type": "rule",
         "start": "20140101", "end": "20221231", "status": "ok", "n_trades": "200",
         "ann_ret": "", "bench_ann_ret": "", "ann_excess": "0.10", "sharpe": "", "max_dd": "",
         "ir": "1.0", "excess_max_dd": "-0.10", "beat_years": "6", "total_years": "7",
         "funnel_l1": "1", "funnel_l2": "1", "funnel_l3": "1", "funnel_l4": "1", "note": ""},
        {"ts": "2026-01-02T00:00:00Z", "config": "a_x", "group": "A", "type": "rule",
         "start": "20230101", "end": "20241231", "status": "ok", "n_trades": "60",
         "ann_ret": "", "bench_ann_ret": "", "ann_excess": "0.05", "sharpe": "", "max_dd": "",
         "ir": "0.3", "excess_max_dd": "-0.05", "beat_years": "1", "total_years": "2",
         "funnel_l1": "1", "funnel_l2": "1", "funnel_l3": "1", "funnel_l4": "1", "note": ""},
    ]
    led = pd.DataFrame(rows, columns=["ts", "config", "group", "type", "start", "end",
                                      "status", "n_trades", "ann_ret", "bench_ann_ret",
                                      "ann_excess", "sharpe", "max_dd", "ir",
                                      "excess_max_dd", "beat_years", "total_years",
                                      "funnel_l1", "funnel_l2", "funnel_l3", "funnel_l4",
                                      "note"])
    res = build_shortlist(led, "A", final_set=set())
    e = res["entries"][0]
    check("对拍：入围分 = min(1.0, 0.3) = 0.3", e["score"] == 0.3 and res["shortlist"] == ["a_x"])
    # 8e. 组合层：底仓状态 + 组合收益 naive
    rng = np.random.default_rng(11)
    dates8 = [f"2020{i:04d}" for i in range(1, 301)]
    close8 = pd.Series(100 + np.cumsum(rng.normal(0.05, 1.0, 300)), index=dates8)
    st8 = base_state_series(close8, MA_WINDOW)
    # 朴素实现：逐点循环 —— 状态_t 由 T−1 收盘相对「截至 T−1 的 200 日均线」决定
    state_naive = pd.Series([ETF_GOLD] * len(dates8), index=dates8, dtype=object)
    for i in range(1, len(dates8)):
        if i >= MA_WINDOW:
            ma = float(np.mean(close8.iloc[i - MA_WINDOW:i]))   # 截至 T−1 的窗口
            if float(close8.iloc[i - 1]) > ma:
                state_naive.iloc[i] = ETF_BENCHMARK
    check("对拍：底仓状态 == 朴素 T−1 均线判断", st8.equals(state_naive),
          f"diff={[d for d in dates8 if st8[d] != state_naive[d]][:5]}")
    rets_a = {"510300.SH": pd.Series(rng.normal(0, 0.01, 300), index=dates8),
              "518880.SH": pd.Series(rng.normal(0, 0.008, 300), index=dates8)}
    sat8 = pd.Series(rng.normal(0, 0.005, 300), index=dates8)
    port8, base8 = portfolio_returns(st8, rets_a, sat8, dates8)
    naive_port, naive_base, prev = [], [], None
    for d in dates8:
        leg = state_naive.loc[d]
        br = float(rets_a[leg].loc[d])
        cost = SWITCH_COST if (prev is not None and leg != prev) else 0.0
        naive_port.append(BASE_WEIGHT * br + SAT_WEIGHT * float(sat8.loc[d]) - cost)
        naive_base.append(br)
        prev = leg
    check("对拍：组合收益 == 朴素逐日合成",
          np.allclose(port8.to_numpy(), np.array(naive_port), atol=1e-15)
          and np.allclose(base8.to_numpy(), np.array(naive_base), atol=1e-15))
    # 8f. satellite 等权
    dfa = pd.DataFrame({"date": dates8, "strategy_ret": rng.normal(0, 0.01, 300)})
    dfb = pd.DataFrame({"date": dates8, "strategy_ret": rng.normal(0, 0.01, 300)})
    sat_eq = satellite_returns({"s1": dfa, "s2": dfb}, dates8, ["s1", "s2"])
    naive_eq = (dfa["strategy_ret"].to_numpy() + dfb["strategy_ret"].to_numpy()) / 2
    check("对拍：卫星等权 == 朴素均值", np.allclose(sat_eq.to_numpy(), naive_eq, atol=1e-15))

    # ============================================================
    print("== 9. 入围制反例（名单不为空 & 补位标注）==")
    def mk_led(specs9):
        rows9 = []
        for k, (cfg9, g9, s_ir, v_ir, s_ex, v_ex, l1) in enumerate(specs9):
            ts9 = f"2026-01-{k + 1:02d}T00:00:00Z"
            common = {"ts": ts9, "config": cfg9, "group": g9, "type": "rule",
                      "status": "ok", "n_trades": "200", "ann_ret": "", "bench_ann_ret": "",
                      "sharpe": "", "max_dd": "", "beat_years": "5", "total_years": "7",
                      "note": ""}
            rows9.append({**common, "start": "20140101", "end": "20221231",
                          "ann_excess": str(s_ex), "ir": str(s_ir), "excess_max_dd": "-0.10",
                          "funnel_l1": str(l1), "funnel_l2": "1", "funnel_l3": "1",
                          "funnel_l4": "1"})
            rows9.append({**common, "start": "20230101", "end": "20241231",
                          "ann_excess": str(v_ex), "ir": str(v_ir), "excess_max_dd": "-0.05",
                          "funnel_l1": "1", "funnel_l2": "1", "funnel_l3": "1",
                          "funnel_l4": "1"})
        return pd.DataFrame(rows9, columns=led.columns)

    # 反例 A：0 个满足硬性资格（全部年化超额 ≤ 0），且有人过 L1
    led_a = mk_led([("a_1", "A", 1.5, 1.2, -0.01, -0.02, 1),
                    ("a_2", "A", 1.0, 0.8, 0.02, -0.03, 1),
                    ("a_3", "A", 0.8, 0.9, -0.05, 0.01, 1),
                    ("a_4", "A", 0.5, 0.4, 0.01, 0.02, 0)])
    res_a = build_shortlist(led_a, "A", final_set=set())
    grades = {e["config"]: (e["grade"], tuple(e["tags"])) for e in res_a["entries"]}
    check("反例A：0 个硬性合格仍产出 3 个入围",
          len(res_a["shortlist"]) == 3, f"{res_a['shortlist']}")
    check("反例A：补位标注「验证期未通过」",
          all(TAG_NO_VAL in grades[c][1] for c in res_a["shortlist"]), f"{grades}")
    check("反例A：按搜索期 IR 降序补位",
          res_a["shortlist"] == ["a_1", "a_2", "a_3"], f"{res_a['shortlist']}")
    # 反例 B：只有 1 个满足硬性资格
    led_b = mk_led([("b_1", "B", 1.2, 0.9, 0.08, 0.05, 1),
                    ("b_2", "B", 1.9, 0.1, 0.02, -0.04, 1),
                    ("b_3", "B", 1.1, 1.0, 0.01, -0.01, 1),
                    ("b_4", "B", 0.2, 0.2, -0.02, 0.03, 1)])
    res_b = build_shortlist(led_b, "B", final_set=set())
    entry_b = {e["config"]: e for e in res_b["entries"]}
    check("反例B：1 合格 + 2 补位",
          entry_b["b_1"]["grade"] == GRADE_SHORT and entry_b["b_1"]["tags"] == []
          and entry_b["b_1"]["score"] == min(1.2, 0.9)
          and len(res_b["shortlist"]) == 3, f"{entry_b}")
    check("反例B：补位标注并按搜索期 IR 排序",
          res_b["shortlist"][1:] == ["b_2", "b_3"]
          and all(TAG_NO_VAL in entry_b[c]["tags"] for c in ["b_2", "b_3"]),
          f"{res_b['shortlist']}")
    # 反例 C：连第 1 层都没人过 → 搜索期年化超额最高的 3 个 + 专属标注
    rows_c = []
    for k, cfg9 in enumerate(["a_p1", "a_p2", "a_p3", "a_p4"]):
        rows_c.append({"ts": f"2026-02-0{k+1}T00:00:00Z", "config": cfg9, "group": "A",
                       "type": "rule", "start": "20140101", "end": "20221231",
                       "status": "ok", "n_trades": str(30 + k), "ann_ret": "",
                       "bench_ann_ret": "", "ann_excess": f"{0.01 * (4 - k):.2f}",
                       "sharpe": "", "max_dd": "", "ir": f"{0.5 - 0.1 * k:.2f}",
                       "excess_max_dd": "-0.10", "beat_years": "3", "total_years": "7",
                       "funnel_l1": "0", "funnel_l2": "0", "funnel_l3": "0",
                       "funnel_l4": "0", "note": ""})
    led_c = pd.DataFrame(rows_c, columns=led.columns)
    res_c = build_shortlist(led_c, "A", final_set=set())
    tags_c = {e["config"]: tuple(e["tags"]) for e in res_c["entries"]}
    check("反例C：无人过 L1 → 3 个补位按搜索期超额排序并标注",
          res_c["shortlist"] == ["a_p1", "a_p2", "a_p3"]
          and all(TAG_NO_L1 in tags_c[c] for c in res_c["shortlist"]),
          f"{res_c['shortlist']} {tags_c}")
    # 达标者占名额
    res_d = build_shortlist(led_b, "B", final_set={"b_4"})
    check("达标者占入围名额",
          "b_4" in res_d["shortlist"] and len(res_d["shortlist"]) == 3,
          f"{res_d['shortlist']}")

    # ============================================================
    print("== 10. 分组反例（只认台账 group 列）==")
    led_x = mk_led([("A_cheat", "B", 2.0, 2.0, 0.10, 0.10, 1),
                    ("b_honest", "A", 1.0, 1.0, 0.05, 0.05, 1),
                    ("m999_x", "A", 0.9, 0.9, 0.04, 0.04, 1)])
    from funnel import config_track, group_of_config, group_to_track, n_trials_for
    check("分组：配置名前缀 A_ 但 group=B → 归 B 组",
          group_of_config(led_x, "A_cheat") == "B")
    check("分组：b_ 前缀但 group=A → 归 A 组",
          group_of_config(led_x, "b_honest") == "A")
    res_x = build_shortlist(led_x, "A", final_set=set())
    names_x = {e["config"] for e in res_x["entries"]}
    check("分组：A 组名单含 b_honest/m999_x、不含 A_cheat",
          "A_cheat" not in names_x and {"b_honest", "m999_x"} <= names_x, f"{names_x}")
    check("分组：N 按组 = 台账 group 列（AI 合并口径：A 或 B 查询都= 全 A∪B 行数 6）",
          n_trials_for(led_x, "A") == 6 and n_trials_for(led_x, "B") == 6
          and n_trials_for(led_x, "example") == 0)
    # 展示分路（run_layers / report ①表同口径）：group 列唯一权威，前缀矛盾不误归
    # 主随机种子43；其余随机种子归入农场组。
    check("分路：group→展示路映射（monkey_43→MONKEY、monkey_42→MS、其他种子→MS、example→EXAMPLES）",
          group_to_track("A") == "A" and group_to_track("B") == "B"
          and group_to_track(f"monkey_{MAIN_MONKEY_SEED}") == "MONKEY"
          and group_to_track("monkey_42") == "MS"
          and group_to_track("monkey_7") == "MS"
          and group_to_track("example") == "EXAMPLES"
          and group_to_track("test") is None and group_to_track(None) is None)
    check("分路：a_ 前缀但 group=example → 展示路 EXAMPLES（不认前缀）",
          config_track(led_x, "A_cheat") == "B"
          and config_track(led_x, "b_honest") == "A")
    led_ex = mk_led([("a_breakout_ma20", "example", -0.6, -0.5, -0.10, -0.08, 1),
                     ("b_trend_value", "example", -0.5, -0.4, -0.09, -0.07, 1)])
    check("分路：example 组的 a_/b_ 前缀配置 → 展示路 EXAMPLES（前缀矛盾以 group 为准）",
          config_track(led_ex, "a_breakout_ma20") == "EXAMPLES"
          and config_track(led_ex, "b_trend_value") == "EXAMPLES")
    check("分路：台账查不到的配置 → 不进任何展示路",
          config_track(led_x, "ghost_cfg") is None)

    # ============================================================
    print("== 11. 撮合专项（合成小市场：涨停买不进/ST 剔除/停牌顺延/跌停卖不出）==")
    mini = make_market()
    ms = mini["store"]
    cfg = {"name": "mkt_test", "type": "rule", "desc": "",
           "buy": [{"op": "streak_up", "dir": "above", "threshold": 0.0}],
           "sell": [], "rank": None, "max_hold_days": 20, "stop_loss": None,
           "max_positions": 10, "industry_cap": 0}
    bt = Backtester(ms, cfg, "20140102", "20140131")
    cross_d1 = bt._cross_rows("20140102")
    codes_d1 = {c for c, _ in cross_d1}
    check("撮合：ST 不入截面", "000002.SZ" not in codes_d1, f"{codes_d1}")
    check("撮合：上市满 250 日 + 有行情 + 非 ST 入截面", "000001.SZ" in codes_d1)
    res = bt.run()
    buys = [t for t in res["trades"] if t["side"] == "buy" and t["code"] == "000001.SZ"]
    check("撮合：涨停日买不进（首笔成交日晚于信号日）",
          buys and buys[0]["exec_date"] > buys[0]["signal_date"],
          f"{[(t['signal_date'], t['exec_date']) for t in buys]}")
    sells = [t for t in res["trades"] if t["side"] == "sell" and t["code"] == "000001.SZ"]
    # 跌停卖出直接单元测试：20140130 开盘=跌停 → 拒绝；20140131 恢复 → 成交
    r30 = bt.row_of("000001.SZ", "20140130")
    r31 = bt.row_of("000001.SZ", "20140131")
    pos_fake = {"000001.SZ": {"shares": 100.0, "cost_nav": 10.0, "entry_date": "20140104",
                              "signal_date": "20140103"}}
    ok30, _ = bt._try_sell([], pos_fake, 0.5, "000001.SZ", "20140130", "20140129", "test")
    trades31: list = []
    ok31, cash31 = bt._try_sell(trades31, pos_fake, 0.5, "000001.SZ", "20140131",
                                "20140129", "test")
    check("撮合：跌停日卖不出（_try_sell 拒绝）", ok30 is False)
    check("撮合：次日非跌停可卖出（_try_sell 成交、持仓清空）",
          ok31 is True and "000001.SZ" not in pos_fake and len(trades31) == 1)
    check("撮合：卖出扣全套成本（佣金+印花税+滑点）",
          abs(trades31[0]["fee"] - trades31[0]["gross"] * (0.00025 + 0.001)) < 1e-9)
    check("撮合：跨日收益用 close×adj_factor（af=1.5 时成交净值含因子）",
          buys and abs(buys[0]["exec_nav"]
                       - buys[0]["exec_price"] * 1.5 * 1.001) < 1e-9)

    # ============================================================
    print("== 12. 档位校验 ==")
    bad_yaml = ROOT / "reports" / "_selftest_bad.yaml"
    bad_yaml.write_text(
        "name: bad\n"
        "type: rule\n"
        "buy: [{op: ret_n, n: 7, dir: above, threshold: 3.0}]\n"
        "max_hold_days: 10\n", encoding="utf-8")
    try:
        load_config(bad_yaml)
        check("非法窗口配置被拒", False)
    except ConfigError:
        check("非法窗口配置被拒", True)
    bad_yaml2 = ROOT / "reports" / "_selftest_bad2.yaml"
    bad_yaml2.write_text(
        "name: bad2\n"
        "type: rule\n"
        "buy: [{op: roe, dir: above, threshold: 12.0}]\n"
        "max_hold_days: 10\n", encoding="utf-8")
    try:
        load_config(bad_yaml2)
        check("无阈值量纲零件不可作条件（roe）", False)
    except ConfigError:
        check("无阈值量纲零件不可作条件（roe）", True)
    bad_yaml3 = ROOT / "reports" / "_selftest_bad3.yaml"
    bad_yaml3.write_text(
        "name: bad3\n"
        "type: score\n"
        "factors: [{op: size_ln, weight: 1.0}]\n"
        "industry_cap: 7\n", encoding="utf-8")
    try:
        load_config(bad_yaml3)
        check("industry_cap 越档被拒", False)
    except ConfigError:
        check("industry_cap 越档被拒", True)
    ok_yaml = ROOT / "reports" / "_selftest_ok.yaml"
    ok_yaml.write_text(
        "name: okcaps\n"
        "type: score\n"
        "factors: [{op: size_ln, weight: 1.0}, {op: xsec_pct, of: {op: roe}, weight: 1.0}]\n"
        "industry_cap: 5\n", encoding="utf-8")
    c = load_config(ok_yaml)
    check("嵌套 spec + industry_cap 合法配置通过", c["industry_cap"] == 5
          and c["factors"][1]["of"]["op"] == "roe")
    bad_yaml.unlink()
    bad_yaml2.unlink()
    bad_yaml3.unlink()
    ok_yaml.unlink()

    # ============================================================
    print("== 13. 3.2 邻域探针：候选集/邻域规划/L7/入围排名排除；台账行与 N 口径不变 ==")
    with tempfile.TemporaryDirectory(prefix="selftest_probe_") as td:
        tmp = Path(td)
        # 探针名含 __ 但不与 rule_breakout_ma20 的真实邻居重名（否则
        # skip-existing 会正确地少排一个邻居任务，混淆本用例的断言）
        probe = "rule_breakout_ma20__buy0t_probe"
        rows13 = [
            # 基础配置（过 L1~L4）+ 其验证期行
            _led_row("rule_breakout_ma20", "A", ir="1.2", ann_excess="0.05"),
            _led_row("rule_breakout_ma20", "A", start=VALID_START, end=VALID_END,
                     ir="0.9", ann_excess="0.02", dd="-0.05"),
            # 探针（L1~L4 标记照常落台账；若不排除将以最高 IR 进各处排名）
            _led_row(probe, "A", ir="9.9", ann_excess="0.30", dd="-0.01"),
            _led_row(probe, "A", start=VALID_START, end=VALID_END,
                     ir="8.8", ann_excess="0.20", dd="-0.01"),
            _led_row("a_x2", "A", ir="0.8", ann_excess="0.04"),
            _led_row("a_x3", "A", ir="0.5", ann_excess="0.01", l2="0", l3="0", l4="0"),
        ]
        led13 = pd.DataFrame(rows13, columns=LEDGER_COLS)
        latest13 = latest_search_rows(led13)

        # 13a 候选集：layer_lists 显式排除探针（其 L1~L4 标记照常存在）
        lists13 = layer_lists([probe, "a_x2", "a_x3", "rule_breakout_ma20"], latest13)
        check("探针：layer_lists 不收探针（即便其 L1~L4 全过）",
              all(probe not in lists13[k] for k in ("l1", "l2", "l3", "l4"))
              and lists13["l4"] == ["a_x2", "rule_breakout_ma20"], f"{lists13}")
        check("探针：台账行照常带 L1~L4 标记（L5 判邻居要读）",
              all(v == 1 for v in flags_of(latest13.get(probe))),
              f"{latest13.get(probe)}")
        check("探针：N 口径不变——探针行照常计入所在组 N",
              n_trials_for(led13, "A") == 6,
              f"{n_trials_for(led13, 'A')}")

        # 13b 邻域规划：不为探针生成邻域（杜绝二阶递归）
        nb_dir13, runs13 = tmp / "nb", tmp / "runs"
        planned13 = plan_l5_l6(led13, ["rule_breakout_ma20", probe],
                               neighbor_dir=nb_dir13, runs_dir=runs13)
        p13 = planned13["plan"]
        check("探针：plan_l5_l6 对探针只记 skipped_probe、零邻居",
              p13[probe].get("skipped_probe") is True and p13[probe]["neighbors"] == [],
              f"{p13[probe]}")
        check("探针：无二阶任务（不存在以探针名为前缀的任务）",
              all(not t["name"].startswith(probe) for t in planned13["tasks"]),
              f"{[t['name'] for t in planned13['tasks']][:5]}")
        check("探针：基础配置仍正常规划 27 邻居 + 验证期，组继承 A",
              len(p13["rule_breakout_ma20"]["neighbors"]) == 27
              and len(planned13["tasks"]) == 28
              and all(t["group"] == "A" for t in planned13["tasks"]),
              f"{len(planned13['tasks'])}")

        # 13c L7：探针不进 kept 也不进 dropped
        fake_frame = pd.DataFrame({
            "date": [f"d{i}" for i in range(5)],
            "strategy_ret": [0.01] * 5, "benchmark_ret": [0.002] * 5,
            "excess": [0.008] * 5})

        def loader13(name):
            return fake_frame

        l7res = l7_dedup([{"name": "rule_breakout_ma20", "track": "A"},
                          {"name": probe, "track": "A"}],
                         {"rule_breakout_ma20": 1.2, probe: 9.9}, loader=loader13)
        check("探针：l7_dedup 剔除探针（kept/dropped 均不出现）",
              [k["name"] for k in l7res["kept"]] == ["rule_breakout_ma20"]
              and all(d["name"] != probe for d in l7res["dropped"]),
              f"{l7res}")

        # 13d 入围排名：shortlist 不含探针（其 IR 最高也不行）
        sl13 = build_shortlist(led13, "A", final_set=set())
        entry_names13 = {e["config"] for e in sl13["entries"]}
        check("探针：build_shortlist 不收探针（entries/shortlist 均不出现）",
              probe not in entry_names13 and probe not in sl13["shortlist"],
              f"{sl13['shortlist']}")
        check("探针：入围名单仍按 5.4 产出 3 个（基础配置不受影响）",
              len(sl13["shortlist"]) == 3
              and "rule_breakout_ma20" in sl13["shortlist"]
              and sl13["n_qualified"] == 1,
              f"{sl13['shortlist']} nq={sl13['n_qualified']}")

    # ============================================================
    print("== 14. 3.2 试跑模式：top-30 规划、「未做邻域检验」标注、不得 final；--formal 全量 ==")
    with tempfile.TemporaryDirectory(prefix="selftest_trial_") as td:
        tmp = Path(td)
        # ---- 14a 纯函数：trial_select 排名与标注 ----
        rows14: list[dict] = []
        for i in range(1, 36):                       # 35 个硬性合格者
            nm = f"syn_c{i:02d}"
            s_ir = 1.50 if i == 15 else (0.10 * i)   # c15/c16 同分（并列检验）
            dd = "-0.30" if i == 15 else "-0.10"     # c15 回撤更差 → 排 c16 之后
            rows14.append(_led_row(nm, "A", ir=f"{s_ir:g}", ann_excess="0.05", dd=dd))
            rows14.append(_led_row(nm, "A", start=VALID_START, end=VALID_END,
                                   ir="5.0", ann_excess="0.03", dd="-0.05"))
        # 三个硬性不合格者（无入围分，本就不进排名）
        rows14 += [
            _led_row("nh_l1", "A", ir="9.0", ann_excess="0.05", l1="0", l2="0",
                     l3="0", l4="0"),                 # 未过 L1
            _led_row("nh_vex", "A", ir="9.0", ann_excess="0.05"),   # 验证期超额 ≤ 0
            _led_row("nh_vex", "A", start=VALID_START, end=VALID_END,
                     ir="9.0", ann_excess="-0.02"),
            _led_row("nh_terr", "A", ir="9.0", ann_excess="0.05"),  # 验证期回测报错
            _led_row("nh_terr", "A", start=VALID_START, end=VALID_END,
                     status="error_runtime"),
        ]
        led14 = pd.DataFrame(rows14, columns=LEDGER_COLS)
        survivors14 = [f"syn_c{i:02d}" for i in range(1, 36)] + \
            ["nh_l1", "nh_vex", "nh_terr"]
        top14, defer14, ranked14 = trial_select(led14, survivors14, TRIAL_L5_TOP_K)
        exp_top = {f"syn_c{i:02d}" for i in range(6, 36)}    # 分数 0.6~3.5 的 30 个
        check("试跑：trial_select 只取硬性合格者按入围分的前 30",
              len(top14) == 30 and set(top14) == exp_top,
              f"n={len(top14)} diff={set(top14) ^ exp_top}")
        check("试跑：并列同分按 |超额回撤| 小者优先（c16 先于 c15）",
              top14.index("syn_c16") < top14.index("syn_c15"), f"{top14[:8]}")
        check("试跑：其余全部标注「未做邻域检验」并附原因",
              set(defer14) == ({f"syn_c{i:02d}" for i in range(1, 6)}
                               | {"nh_l1", "nh_vex", "nh_terr"})
              and all(TAG_NO_L5_CHECK in v for v in defer14.values())
              and "未进前 30" in defer14["syn_c01"]
              and "第 1 层" in defer14["nh_l1"]
              and "年化超额" in defer14["nh_vex"]
              and "年化超额" in defer14["nh_terr"], f"{defer14}")
        check("试跑：entry_score 口径 = min(搜索期 IR, 验证期 IR)",
              entry_score(led14, "syn_c35")["score"] == 3.5
              and entry_score(led14, "syn_c35")["hard"] is True,
              f"{entry_score(led14, 'syn_c35')}")
        # k 可缩小（排名键不变）
        top3, _, _ = trial_select(led14, survivors14, 3)
        check("试跑：k 参数生效（前 3 = 分数最高者降序）",
              top3 == ["syn_c35", "syn_c34", "syn_c33"], f"{top3}")

        # ---- 14b 编排：execute_l5_l6_with_runner 试跑路径（回测替身注入）----
        # 三个基础配置单均存在于 strategies/（find_config_yaml 可定位）
        t1, t2, d1 = "rule_breakout_ma20", "a_breakout_ma20", "b_trend_value"
        check("试跑：前置——三个基础配置单 YAML 可定位",
              all(find_config_yaml(n) is not None for n in (t1, t2, d1)))
        base14 = pd.DataFrame([
            _led_row(t1, "A", ir="1.2", ann_excess="0.06"),
            _led_row(t2, "A", ir="1.0", ann_excess="0.05"),
            _led_row(d1, "A", ir="2.0", ann_excess="0.05"),
        ], columns=LEDGER_COLS)
        runs14 = tmp / "runs"    # 不预置任何验证期产物：步骤①必须为全部幸存者排任务

        def make_reader(ledger2, ledger3):
            calls = {"n": 0}

            def reader():
                calls["n"] += 1
                return ledger2 if calls["n"] == 1 else ledger3
            return reader

        val_rows = [
            _led_row(t1, "A", start=VALID_START, end=VALID_END,
                     ir="0.9", ann_excess="0.04", dd="-0.05"),
            _led_row(t2, "A", start=VALID_START, end=VALID_END,
                     ir="0.8", ann_excess="0.03", dd="-0.06"),
            _led_row(d1, "A", start=VALID_START, end=VALID_END,
                     ir="0.7", ann_excess="-0.02", dd="-0.04"),   # D1 硬性不合格
        ]
        ledger2_14 = pd.DataFrame(base14.to_dict("records") + val_rows,
                                  columns=LEDGER_COLS)
        nb_rows = [_led_row(n, "A", ir="1.0", ann_excess="0.05")
                   for n in _neighbor_names_of(t1)]                 # T1 邻居全过
        nb_rows += [_led_row(n, "A", ir="1.0", ann_excess="0.05",
                             l1="0", l2="0", l3="0", l4="0")
                    for n in _neighbor_names_of(t2)]                # T2 邻居全败
        ledger3_14 = pd.DataFrame(ledger2_14.to_dict("records") + nb_rows,
                                  columns=LEDGER_COLS)

        fake = _FakeRunner()
        res14 = execute_l5_l6_with_runner(
            fake, base14, [t1, t2, d1], formal=False,
            read_ledger_fn=make_reader(ledger2_14, ledger3_14),
            neighbor_dir=tmp / "nb", runs_dir=runs14)
        check("试跑：步骤①先对全部幸存者跑验证期（含不合格者的 D1）",
              len(fake.batches) == 2
              and {t["name"] for t in fake.batches[0]}
              == {f"{t1}__val", f"{t2}__val", f"{d1}__val"},
              f"{[sorted(t['name'] for t in b) for b in fake.batches]}")
        batch2 = fake.batches[1]
        check("试跑：步骤③只对 top 生成任务（D1 无任何任务，杜绝未检者晋级；"
              "替身不产物化时 top 的验证期按 skip-existing 在③重排，生产中①已产物化不会重排）",
              batch2
              and all(t["name"].startswith(t1 + "__")
                      or t["name"].startswith(t2 + "__") for t in batch2)
              and all(not t["name"].startswith(d1 + "__") for t in batch2),
              f"{sorted(t['name'] for t in batch2)[:5]}")
        check("试跑：任务组继承台账 group 列（全部 A）",
              all(t["group"] == "A" for b in fake.batches for t in b))
        check("试跑：L5/L6 只收 top 中通过者（T1 过，T2 邻居全败被拦）",
              res14["l5"] == [t1] and res14["l6"] == [t1], f"{res14['l5']} {res14['l6']}")
        check("试跑：D1 标注「未做邻域检验」且无 L5 结论",
              res14["l5_detail"][d1].get("not_checked") is True
              and TAG_NO_L5_CHECK in res14["l5_detail"][d1]["note"]
              and res14["l5_not_checked"] == [d1],
              f"{res14['l5_detail'][d1]}")
        check("试跑：未检验者不得进入 L6（结构上不可达 final/达标）",
              d1 not in res14["l5"] and d1 not in res14["l6"]
              and res14["l5_detail"][t2].get("not_checked") is None,
              f"{res14['l6']}")

        # ---- 14c 对照：--formal 恢复全量邻域检验（D1 也被规划）----
        fake_f = _FakeRunner()
        res_f = execute_l5_l6_with_runner(
            fake_f, base14, [t1, t2, d1], formal=True,
            read_ledger_fn=make_reader(ledger3_14, ledger3_14),
            neighbor_dir=tmp / "nb_f", runs_dir=runs14)
        all_f_tasks = [t["name"] for b in fake_f.batches for t in b]
        check("正式：--formal 对全部幸存者规划邻域（D1 也有任务、无 not_checked 标注）",
              any(n.startswith(d1 + "__") for n in all_f_tasks)
              and res_f["l5_not_checked"] == []
              and "not_checked" not in res_f["l5_detail"][d1],
              f"{res_f['l5_detail'][d1]}")
        check("正式：判定口径不变（T1 过 L5/L6；T2 邻居全败、D1 无邻居台账行均不通过）",
              res_f["l5"] == [t1] and res_f["l6"] == [t1]
              and res_f["l5_detail"][t2]["pass"] is False
              and res_f["l5_detail"][d1]["pass"] is False,
              f"{res_f['l5']} {res_f['l6']}")
        # formal=None（缺省）= 试跑开（TRIAL_MODE_DEFAULT）
        fake_d = _FakeRunner()
        res_d = execute_l5_l6_with_runner(
            fake_d, base14, [t1, t2, d1], formal=None,
            read_ledger_fn=make_reader(ledger2_14, ledger3_14),
            neighbor_dir=tmp / "nb_d", runs_dir=runs14)
        check("试跑：formal=None 缺省即试跑（与 formal=False 同为 top-k 口径）",
              res_d["l5_not_checked"] == [d1] and res_d["l5"] == [t1],
              f"{res_d['l5_not_checked']}")

    # ============================================================
    print("== 15. 3.2 猴子独立性：canonical 归一、台账去重、同流重采样、输出确定 ==")
    with tempfile.TemporaryDirectory(prefix="selftest_monkey_") as td:
        tmp = Path(td)
        check("独立性：canonical_config 键排序+数值归一（1 与 1.0 同构）",
              canonical_config({"a": 1, "b": 2.0, "c": None})
              == canonical_config({"c": None, "b": 2, "a": 1.0}))
        check("独立性：canonical_config 列表保序（条件顺序是结构）",
              canonical_config({"l": [1, 2]}) != canonical_config({"l": [2, 1]}))
        led_base = pd.DataFrame([_led_row("rule_breakout_ma20", "A")],
                                columns=LEDGER_COLS)
        seen15, have15, miss15 = existing_canonical_configs(led_base)
        check("独立性：existing_canonical_configs 从台账+strategies 取到可比配置",
              len(seen15) == 1 and have15 == 1 and miss15 == 0,
              f"have={have15} miss={miss15}")
        gen_a = tmp / "a"
        paths1, names1 = gen_monkey(99, 6, gen_a, ledger=led_base)
        check("独立性：gen_monkey 文件名 m99_001..006 且全部过 load_config",
              [p.name for p in paths1] ==
              [f"m99_{i:03d}.yaml" for i in range(1, 7)]
              and all(load_config(p)["name"] == p.stem for p in paths1))
        canons1 = [canonical_config(yaml.safe_load(open(p, encoding="utf-8")))
                   for p in paths1]
        check("独立性：生成结果与台账任何组已有配置零重复、批内零重复",
              not (set(canons1) & seen15) and len(set(canons1)) == 6)
        gen_b = tmp / "b"
        paths2, _ = gen_monkey(99, 6, gen_b, ledger=led_base)
        check("独立性：同 seed + 同台账 → 输出确定（两次生成逐位一致）",
              all(a.read_bytes() == b.read_bytes()
                  for a, b in zip(paths1, paths2)))
        # 重采样：把首批生成结果注入去重集合（extra_raw 显式注入，非补丁；
        # 注入的配置名必须同时出现在台账里才会被查表），同一随机流必须
        # 继续重采样避开它们
        raws1 = {p.stem: yaml.safe_load(open(p, encoding="utf-8")) for p in paths1}
        led_plus = pd.DataFrame(
            [_led_row("rule_breakout_ma20", "A")]
            + [_led_row(nm, "monkey_43") for nm in sorted(raws1)],
            columns=LEDGER_COLS)
        gen_c = tmp / "c"
        paths3, _ = gen_monkey(99, 6, gen_c, ledger=led_plus, extra_raw=raws1)
        canons3 = [canonical_config(yaml.safe_load(open(p, encoding="utf-8")))
                   for p in paths3]
        check("独立性：台账新增同构配置后重采样避开（同流继续、不重复不放行）",
              not (set(canons3) & set(canons1)) and not (set(canons3) & seen15)
              and len(set(canons3)) == 6, f"{canons3[:2]}")
        gen_d = tmp / "d"
        paths4, _ = gen_monkey(99, 6, gen_d, ledger=led_plus, extra_raw=raws1)
        check("独立性：同 seed + 同台账（含注入）→ 重采样后输出仍确定",
              all(a.read_bytes() == b.read_bytes()
                  for a, b in zip(paths3, paths4)))

    # ============================================================
    print("== 16. 3.2 并行执行：默认 workers=CPU−2；合成配置并行/串行逐位一致 ==")
    with tempfile.TemporaryDirectory(prefix="selftest_par_") as td:
        tmp = Path(td)
        check("并行：default_workers = max(1, CPU−2)",
              default_workers() == max(1, (os.cpu_count() or 2) - 2),
              f"{default_workers()}")
        check("并行：make_runner 语义（1=SeqRunner，>1=PoolRunner）",
              isinstance(make_runner(1), SeqRunner)
              and isinstance(make_runner(3), PoolRunner))
        syn_store = _synthetic_store()
        days16 = syn_store.calendar
        cfgs16 = [("syn_p1", 3, 3.0, 10), ("syn_p2", 10, 5.0, 10),
                  ("syn_p3", 20, 3.0, 20), ("syn_p4", 5, 8.0, 5)]
        paths16 = [_write_syn_config(tmp, nm, window=w, threshold=thr, hold=h)
                   for nm, w, thr, h in cfgs16]
        tasks16 = [{"name": p.stem, "path": str(p), "start": days16[0],
                    "end": days16[-1], "group": "test", "record": False}
                   for p in paths16]
        ledger_len0 = len(read_ledger())
        seq_res = SeqRunner(store_kind="synthetic").run(copy.deepcopy(tasks16))
        pool_runner = PoolRunner(3, store_kind="synthetic")
        pool_res = pool_runner.run(copy.deepcopy(tasks16))
        # 常驻池契约：同池跨批次复用；close() 后再 run() 重建新池（不抛错、结果一致）
        pool_res_b = pool_runner.run(copy.deepcopy(tasks16[:1]))
        pool_runner.close()
        pool_res_c = pool_runner.run(copy.deepcopy(tasks16[:1]))
        pool_runner.close()
        key16 = lambda r: (r["config"], r["period"])  # noqa: E731
        seq_by = {key16(r): r for r in seq_res}
        pool_by = {key16(r): r for r in pool_res}
        check("并行：同一批合成配置两路全部执行成功",
              len(seq_res) == 4 and len(pool_res) == 4
              and all(r["status"] == "ok" for r in seq_res + pool_res),
              f"{[r['status'] for r in seq_res + pool_res]}")
        check("并行：结果集合一致（与完成顺序无关）",
              set(seq_by) == set(pool_by), f"{set(seq_by) ^ set(pool_by)}")
        check("并行：回测指标逐位一致（rules.md 第 12 章）",
              all(seq_by[k]["metrics"] == pool_by[k]["metrics"] for k in seq_by),
              f"{[k for k in seq_by if seq_by[k]['metrics'] != pool_by.get(k, {}).get('metrics')]}")
        check("并行：常驻池跨批次/close 后重建，指标仍与串行逐位一致",
              all(r["status"] == "ok" for r in pool_res_b + pool_res_c)
              and all(seq_by[key16(r)]["metrics"] == r["metrics"]
                      for r in pool_res_b + pool_res_c),
              f"{[r['status'] for r in pool_res_b + pool_res_c]}")
        check("并行：record=False 不落台账（行数不变）",
              len(read_ledger()) == ledger_len0)
        for nm, _w, _t, _h in cfgs16:   # 清理合成回测产物（reports/runs 下）
            shutil.rmtree(ROOT / "reports" / "runs" / f"{nm}__{days16[0]}_{days16[-1]}",
                          ignore_errors=True)

    # ============================================================
    print("== 17. 3.2 台账并发追加：多进程竞态不丢行、不串行 ==")
    with tempfile.TemporaryDirectory(prefix="selftest_race_") as td:
        tmp = Path(td)
        race_led = tmp / "ledger.csv"      # 临时目录台账，绝不写仓库台账
        n_proc, per_proc = 4, 25
        with mp.Pool(n_proc) as pool:
            done = pool.starmap(_race_append_worker,
                                [(str(race_led), f"w{i}", per_proc)
                                 for i in range(n_proc)])
        raw17 = race_led.read_bytes()
        rows17 = list(csv.reader(io.StringIO(raw17.decode("utf-8"), newline="")))
        data17 = rows17[1:]
        check("竞态：4 进程 × 25 行全部落账（无丢行）",
              done == [per_proc] * n_proc and len(rows17) == 1 + n_proc * per_proc
              and len(data17) == n_proc * per_proc,
              f"rows={len(rows17)} done={done}")
        check("竞态：表头恰一且列对齐（无串行/撕裂行）",
              rows17[0] == list(LEDGER_COLS)
              and {len(r) for r in data17} == {len(LEDGER_COLS)},
              f"{rows17[0][:3]} fieldset={sorted({len(r) for r in data17})}")
        check("竞态：100 行配置名互不重复（每行完整独立）",
              len({r[1] for r in data17}) == n_proc * per_proc)
        # 字节级行尾断言（返工单第 1 条）：台账字节必须与既有 CRLF 惯例一致，
        # 不允许 \r\r\n（Windows 文本模式翻译是已修复的根因，见 backtest._ledger_locked）
        n_crlf = raw17.count(b"\r\n")
        check("竞态：字节级行尾——全部行恰为 CRLF，无 \\r\\r\\n 双 CR（csv.reader 不再出空记录）",
              raw17.count(b"\r\r\n") == 0 and n_crlf == 1 + n_proc * per_proc
              and b"\r" not in raw17.replace(b"\r\n", b""),
              f"crlf={n_crlf} crcrlf={raw17.count(b'\r\r\n')}")
        # 锁内表头判定：向同一文件继续追加不产生第二张表头
        record_ledger("race_after_single", "rule", SEARCH_START, SEARCH_END,
                      "ok", "test", metrics=None, note="single", path=race_led)
        raw17b = race_led.read_bytes()
        rows17b = list(csv.reader(io.StringIO(raw17b.decode("utf-8"), newline="")))
        check("竞态：追加后仍单表头、行数 +1",
              len(rows17b) == 2 + n_proc * per_proc
              and sum(1 for r in rows17b if r[:2] == ["config", "group"]) == 0
              and rows17b[0] == list(LEDGER_COLS),
              f"rows={len(rows17b)}")
        check("竞态：追加后字节级行尾仍全部干净 CRLF",
              raw17b.count(b"\r\r\n") == 0 and raw17b.count(b"\r\n") == 2 + n_proc * per_proc,
              f"crlf={raw17b.count(b'\r\n')} crcrlf={raw17b.count(b'\r\r\n')}")

    n_fail = sum(1 for _, s in results if s == FAIL)
    print(f"\n== 自测结果：{len(results) - n_fail}/{len(results)} PASS ==")
    return 1 if n_fail else 0


# ================================================================ 合成市场（撮合）

def _led_row(cfg: str, group: str, *, start: str = SEARCH_START,
             end: str = SEARCH_END, status: str = "ok", ir: str = "",
             ann_excess: str = "", dd: str = "-0.10", l1: str = "1",
             l2: str = "1", l3: str = "1", l4: str = "1",
             ts: str = "2026-03-01T00:00:00Z", typ: str = "rule") -> dict:
    """合成台账行（3.2 自测用；列与 LEDGER_COLS 对齐）。"""
    return {"ts": ts, "config": cfg, "group": group, "type": typ,
            "start": start, "end": end, "status": status, "n_trades": "500",
            "ann_ret": "", "bench_ann_ret": "", "ann_excess": ann_excess,
            "sharpe": "", "max_dd": "", "ir": ir, "excess_max_dd": dd,
            "beat_years": "5", "total_years": "7",
            "funnel_l1": l1, "funnel_l2": l2, "funnel_l3": l3, "funnel_l4": l4,
            "note": ""}


def _neighbor_names_of(cfg_name: str) -> list[str]:
    """配置单的全部 L5 邻居名（按引擎同一枚举逻辑）。"""
    src = find_config_yaml(cfg_name)
    raw = yaml.safe_load(open(src, encoding="utf-8"))
    return [nb["name"] for nb in build_neighbor_set(raw)]


class _FakeRunner:
    """execute_l5_l6_with_runner 的回测替身（参数注入，非运行时补丁）：
    记录每批任务并一律返回 ok。"""

    def __init__(self):
        self.batches: list[list[dict]] = []

    def run(self, tasks):
        self.batches.append([dict(t) for t in tasks])
        return [{"config": t["name"], "status": "ok"} for t in tasks]


def _race_append_worker(path_str: str, tag: str, n_rows: int) -> int:
    """并发竞态用例 worker（模块顶层：Windows spawn 可 pickle）：
    向**临时目录**台账追加 n_rows 行，绝不写仓库台账。"""
    p = Path(path_str)
    for i in range(n_rows):
        record_ledger(f"race_{tag}_{i:03d}", "rule", SEARCH_START, SEARCH_END,
                      "ok", "test", metrics=None, note="race", path=p)
    return n_rows


def _write_syn_config(directory: Path, name: str, *, window: int,
                      threshold: float, hold: int) -> Path:
    """写一个合法的合成规则型配置单（load_config 强校验可过）。"""
    cfg = {"name": name, "type": "rule", "desc": "3.2 并行一致性合成配置",
           "buy": [{"op": "streak_up", "dir": "above", "threshold": 3.0},
                   {"op": "ret_n", "n": window, "dir": "above",
                    "threshold": threshold}],
           "sell": [{"op": "close_over_ma_n", "n": 5, "dir": "below",
                     "threshold": 1.0}],
           "max_hold_days": hold, "stop_loss": "无", "max_positions": 10}
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / f"{name}.yaml"
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    load_config(p)          # 非法即抛（档位强校验）
    return p


def make_market() -> dict:
    """两只股票的小市场：
    000001.SZ 正常；20140103 开盘=涨停（买不进），20140130 跌停（卖不出）；
    000002.SZ 全程 ST（不入截面）。af=1.5（验证复权口径）。
    """
    days = [f"201401{d:02d}" for d in range(2, 10)] + [f"20140{d}" for d in
            (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26,
             27, 28, 29, 30)] + ["20140131"]
    rows = []
    px = 10.0
    for i, d in enumerate(days):
        pre = px
        open_ = round(pre * 1.1, 2) if d == "20140103" else (
            round(pre * 0.9, 2) if d == "20140130" else round(pre * 1.01, 2))
        close = round(pre * 1.005, 2)
        px = close
        up = round(pre * 1.1, 2)
        dn = round(pre * 0.9, 2)
        rows.append({"date": d, "code": "000001.SZ", "open": open_,
                     "high": max(open_, close) + 0.01, "low": min(open_, close) - 0.01,
                     "close": close, "pre_close": pre, "pct_chg": (close / pre - 1) * 100,
                     "vol": 1e6, "amount": 1e7, "af": 1.5, "adj_nav": close * 1.5,
                     "turnover_rate": 2.0, "pe_ttm": 20.0, "pb": 2.0, "ps_ttm": 3.0,
                     "total_mv": 1e6, "circ_mv": 8e5, "up_limit": up, "down_limit": dn,
                     "is_st": 0.0, "l1_code": "801010", "l1_name": "农林牧渔",
                     "fin_end_date": None, "roe": 10.0, "or_yoy": 5.0,
                     "netprofit_yoy": 8.0, "fc_ann_date": None, "fc_type": None,
                     "fc_type_code": 2.0, "fc_chg_mid": 50.0, "fc_days": 5.0,
                     "ex_ann_date": None, "ex_yoy": 6.0, "ex_days": 3.0,
                     "n_listed": 1000.0})
        # 000002.SZ：ST；只在部分日期有行情（20140104 停牌一天）
        if d != "20140104":
            rows.append({"date": d, "code": "000002.SZ", "open": 5.0, "high": 5.1,
                         "low": 4.9, "close": 5.0, "pre_close": 5.0, "pct_chg": 0.0,
                         "vol": 1e6, "amount": 1e7, "af": 1.0, "adj_nav": 5.0,
                         "turnover_rate": 1.0, "pe_ttm": 10.0, "pb": 1.0, "ps_ttm": 2.0,
                         "total_mv": 5e5, "circ_mv": 4e5, "up_limit": 5.5,
                         "down_limit": 4.5, "is_st": 1.0, "l1_code": "801120",
                         "l1_name": "食品饮料", "fin_end_date": None, "roe": 3.0,
                         "or_yoy": 1.0, "netprofit_yoy": 1.0, "fc_ann_date": None,
                         "fc_type": None, "fc_type_code": np.nan, "fc_chg_mid": np.nan,
                         "fc_days": np.nan, "ex_ann_date": None, "ex_yoy": np.nan,
                         "ex_days": np.nan, "n_listed": 900.0})
    panel = pd.DataFrame(rows).sort_values(["code", "date"], kind="stable").reset_index(drop=True)

    class MiniStore:  # noqa: 简单命名空间式 DataStore 替身
        pass

    ms = MiniStore()
    ms.panel = panel
    ms.calendar = sorted(panel["date"].unique().tolist())
    ms.universe_on = lambda t: ["000001.SZ", "000002.SZ"]
    etf_days = [f"2013{m:02d}{d:02d}" for m in range(1, 13) for d in (1, 10, 20)] + \
               [f"201401{d:02d}" for d in range(1, 32)]
    ms.etfs = {ETF_BENCHMARK: pd.DataFrame({
        "date": etf_days,
        "close_adj": np.linspace(2.0, 2.6, len(etf_days)),
    })}
    return {"store": ms, "days": days}


if __name__ == "__main__":
    raise SystemExit(main())
