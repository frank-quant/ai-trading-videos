# -*- coding: utf-8 -*-
"""
检查一：撕报纸测试（防未来函数）—— tests/newspaper_test.py

方法：固定随机种子 42，从 20140601~20221231（rules.md 第 1 节搜索期）的交易日里
随机抽 200 个日期 T（面板始于更早历史，T 最早 2014-06，保证 >=250 日预热）。
对每个 T 构造「截至 T 日（含）的世界切片」，与「全量世界」比对 T 日的零件值与信号：

  * 面板切片：每码「date <= T」的最后 255 **行**（rules.md 第 7 节最大合法窗口
    250 + 5 行余量；零件窗口一律按行计。Tushare daily 无停牌行，停牌多的股票
    在 255 个**日历日**里凑不满 250 行，故不能按日历宽度切片——那会把窗口
    左边界截进「更早的过去」，造成假性不一致）。切片直接取自引擎
    DataStore.panel 的行（含引擎预计算的 adj_nav / af 列），是引擎眼中
    「截至 T 的世界」（PanelView.asof 语义）的子集，一次加载、内存切片，
    不重新读盘。按 (code,date) 升序的码块尾片保持原序。
  * 成分快照切片：trade_date <= T 的行；股票池从切片快照取（各指数 as-of-T
    最近一份快照的并集，与 DataStore.universe_on 同口径）。
  * ETF 切片：date <= T 的最后 255 行（按 ETF 自己的日历）。
  * 全量世界 = 引擎回测器实际使用的口径：完整面板（data/raw 全历史，
    即 Backtester._op_values 的求值对象）+ 全量快照 + 全量 ETF。

覆盖：
  A) operators.py OPERATORS 注册表全部零件：窗口零件 × 全部 7 个合法
     窗口（3/5/10/20/60/120/250）+ 无窗零件（含第 3 步资金面零件：
     top_list_n / margin_chg_n / hk_chg_n 窗口件，inst_netbuy / margin_ratio /
     hk_ratio 无窗件），在 T 行逐股比对；
  B) 示例配置单的信号生成：规则型（买入条件布尔、rank 排序后的候选序列、
     卖出条件布尔）与打分型（去极值+截面排名+加权[+中性化分组秩]的总分、
     前 30 目标列表），以及股票池 as-of、上市满 250 日判定、当日截面过滤
     （ST/停牌）；示例含 tests/fixtures/ 的龙虎榜规则型与
     行业内中性化打分型；
  C) 资金面表对齐口径（第 3 步新增）：龙虎榜（top_list/top_inst）T 日行
     必须 == 用 trade_date ≤ T 的原始记录独立重算的值；两融（margin_detail）
     与北向（hk_hold SH/SZ）必须 == 用 trade_date < T（≤ T-1，次日披露）
     重算的值——世界切片语义的直接验证。

无界窗口的处理（streak_up / streak_down）：其回看无上界。若某股在切片内的
连涨/连跌天数恰好等于它在切片内的行数（run 触到切片左边界），切片值可能被
截断——这取决于更早的【过去】，不是未来函数。此时用全量世界值判定：
全量值 > 切片值 视为「左边界截断（预期，不算失败）」并单独计数；
其余任何不一致（含全量值 < 切片值）都是失败。

etf_above_ma_n 的语义说明：本测试按设计文档语义（该零件在【ETF 日线】上求值，
operators.py etf_above_ma_n "panel 必须是单只 ETF 的日线长表"）评估信号；
引擎 _val/_spec_values_on 对该零件同样走 _etf_value_on（ETF 日线），
两侧口径一致。（历史上规则型路径曾在股票面板上误求值该零件，属另一项
已了结的独立发现，见 reports/audit_engine.md。）

adj_nav / af / 上市天数(seq) 的 as-of 合法性：
  * adj_nav = close × adj_factor（prices.py DataStore 构造），第 T 行按构造
    只依赖 <= T 的行；其数值正确性由 tests/value_test.py 用朴素实现从
    data/raw 独立对拍；
  * af = adj_factor，单行；
  * seq（cumcount）第 T 行 = 该股 date < T 的行数——本测试对抽样 T 的
    全部股票直接断言这一恒等式；
  * 切片侧的「上市满 250 个交易日」判定用切片自身行数-1（每码尾片 255 行 >
    250，判定结果与全量侧 cumcount 必然一致，也顺带检验了该过滤无未来函数）。

容差：abs(a-b) <= 1e-9；NaN 对 NaN 视为一致，NaN 对数值视为不一致。
退出码：全部一致 = 0，任何不一致 = 1。
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import guard  # noqa: E402  （引擎封存守卫，本测试不读任何封存数据）
import operators as op  # noqa: E402
from config import load_config  # noqa: E402
from prices import DataStore  # noqa: E402
import backtest as bt  # noqa: E402  （只用其纯函数 _cmp/_winsorize_mad/_cross_rank）

SEED = 42
N_DATES = 200
T_LO, T_HI = "20140601", "20221231"   # 搜索期（rules.md 第 1 节；与
                                      #  engine/register_operator.py 同口径。原
                                      #  "2014-06-01"/"2020-12-31" 是旧数据布局的
                                      #  带杠日期，与 YYYYMMDD 面板字符串比较时
                                      #  实际只覆盖 2014~2019，一并修正）
MAX_WINDOW = 250
SLICE_WIDTH = MAX_WINDOW + 5          # 255 行/每码，覆盖最大窗口 250 + 余量
WINDOWS = [3, 5, 10, 20, 60, 120, 250]
WINDOWED_OPS = ["ret_n", "ma_n", "close_over_ma_n", "dist_high_n", "dist_low_n",
                "vol_ratio_n", "turn_ma_n", "vol_n", "atr_close_n", "break_high_n",
                "etf_above_ma_n",
                # 第 3 步资金面窗口零件（面板列已在 DataStore 里 point-in-time 对齐）
                "top_list_n", "margin_chg_n", "hk_chg_n"]
NOARG_OPS = ["close_pos_range", "turn", "streak_up", "streak_down",
             "size_ln", "pe_ttm", "pb", "ps_ttm", "roe", "or_yoy", "netprofit_yoy",
             "fc_type_code", "fc_chg_mid", "fc_days", "ex_yoy", "ex_days",
             # 第 3 步资金面无窗零件
             "inst_netbuy", "margin_ratio", "hk_ratio"]
TOL = 1e-9
MIN_LISTED = 250                       # rules.md 第 2 节 / backtest.MIN_LISTED_DAYS
# 示例配置（2 规则型 + 2 打分型 + 第 3 步 4 个示例：龙虎榜规则型、行业内
# 中性化打分型、月度打分型、两融+北向规则型）。注：本工作区初始化
# （04abe68）时示例文件已改用 a_/b_ 命名，此处原引用的
# rule_pullback_lowvol / score_momentum_quality / score_trend_value 三个旧名
# 从未存在，测试在加载即 FileNotFoundError——按现名修正，断言一字未动。
CONFIG_PATHS = [ROOT / "tests/fixtures/rule_breakout_ma20.yaml",
                ROOT / "tests/fixtures/a_pullback_lowvol.yaml",
                ROOT / "tests/fixtures/b_momentum_quality.yaml",
                ROOT / "tests/fixtures/b_trend_value.yaml",
                ROOT / "tests/fixtures/s3_rule_toplist.yaml",
                ROOT / "tests/fixtures/s3_score_industry_neut.yaml",
                ROOT / "tests/fixtures/s3_score_monthly.yaml",
                ROOT / "tests/fixtures/s3_rule_margin_hk.yaml"]

ETF_BENCH = "510300.SH"               # = backtest.ETF_BENCHMARK（prices.py）

failures: list[str] = []
samples: list[str] = []                # 差异样本（零件名/T/两侧值）
stats: dict[str, dict] = {}            # item -> {"n": 比对次数, "bad": 不一致次数}
truncation_hits = 0                    # streak 左边界截断（预期）计数


def note(item: str, n: int, bad: int):
    s = stats.setdefault(item, {"n": 0, "bad": 0})
    s["n"] += n
    s["bad"] += bad


def eq_scalar(a, b, tol=TOL) -> bool:
    a, b = float(a), float(b)
    if np.isnan(a) and np.isnan(b):
        return True
    if np.isnan(a) or np.isnan(b):
        return False
    return abs(a - b) <= tol


def eq_array(a, b) -> tuple[int, int]:
    """返回 (比对数, 不一致数)。NaN==NaN 一致。"""
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    assert len(a) == len(b)
    both_nan = np.isnan(a) & np.isnan(b)
    ok = both_nan | (np.abs(a - b) <= TOL)
    return len(a), int((~ok).sum())


def universe_from(members: pd.DataFrame, t: str) -> list[str]:
    """镜像 prices.DataStore.universe_on：各指数「快照日 <= t 的最近一份」成分的并集。

    （members 为 Tushare index_members：trade_date / index_code / con_code，
    沪深300 ∪ 中证500 ∪ 中证1000 三路各自取 as-of 快照后求并；旧实现的
    单快照流假设不适用于多指数成员表。）"""
    sub = members[members["trade_date"] <= t]
    if not len(sub):
        return []
    pool: set[str] = set()
    for _idx, g in sub.groupby("index_code"):
        snap = g["trade_date"].max()
        pool |= set(g.loc[g["trade_date"] == snap, "con_code"].astype(str))
    return sorted(pool)


# ---------------------------------------------------------------- 信号评估
# 镜像 backtest.py 的截面与信号语义（Tushare 版面板口径）：
#   截面过滤    非ST（is_st != 1，NaN 视为非 ST）+ 当日有行情行（Tushare daily
#              无停牌行，两侧 T 行集天然只含有行者）+ 开盘价有效（有限值）
#              + 上市满 250 个交易日；股票池 as-of 一致性由主流程第 2) 步单独断言
#   规则型买入   buy 全部条件 AND，_cmp 比较（非有限值 → False）
#   规则型排序   rank 值排序，desc 取负，并列按代码升序；etf_above_ma_n 恒按代码
#   规则型卖出   sell 任一条件 OR
#   打分型       winsorize MAD -> 截面百分位排名 -> 加权 -> 降序前 holdings 只
# 唯一差别：etf_above_ma_n 按设计文档语义取 ETF 日线值（见文件头说明）。

def eval_signal(cfg: dict, getval, etfval, cross: list[str], meta: dict) -> dict:
    """meta: {code: (l1_code, circ_mv)}——中性化分组键（rules.md 7.5，第 3 步）。"""

    def v(spec, c):
        if spec["op"] == "etf_above_ma_n":
            return etfval(spec["n"])
        return getval((spec["op"], spec.get("n")), c)

    if cfg["type"] == "rule":
        cands = [c for c in cross
                 if all(bt._cmp(v(s, c), s) for s in cfg["buy"])]
        rank = cfg["rank"]
        if rank is not None and cands:
            name, n = rank["op"], rank.get("n")
            if name == "etf_above_ma_n":
                ordered = sorted(cands)                      # backtest.py:597-598
            elif rank["order"] == "desc":
                ordered = sorted(cands, key=lambda c: (-v({"op": name, "n": n}, c), c))
            else:
                ordered = sorted(cands, key=lambda c: (v({"op": name, "n": n}, c), c))
            rankvals = {c: v({"op": name, "n": n}, c) for c in cands}
        else:
            ordered = sorted(cands)
            rankvals = {}
        sell = {c: (any(bt._cmp(v(s, c), s) for s in cfg["sell"]) if cfg["sell"] else False)
                for c in cross}
        return {"kind": "rule", "cands": ordered, "rankvals": rankvals, "sell": sell}
    # ---- score（镜像 backtest._run_score：winsorize→截面秩→[行业内秩]→[市值档内秩]）----
    rows = cross
    l1s = np.array([meta[c][0] for c in rows], dtype=object)
    cms = np.array([meta[c][1] for c in rows], dtype="float64")
    total = np.zeros(len(rows))
    for f in cfg["factors"]:
        name, n = f["op"], f.get("n")
        if name == "etf_above_ma_n":
            x = etfval(n)
            arr = np.full(len(rows), np.nan if x is None else x)
        else:
            arr = np.array([getval((name, n), c) for c in rows], dtype="float64")
        r = bt._cross_rank(bt._winsorize_mad(arr))
        if cfg.get("neut_industry"):
            r = bt._group_rank_pct(l1s, r)
        if cfg.get("neut_size"):
            r = bt._group_rank_pct(bt._size_buckets(cms), r)
        total += f["weight"] * r
    order = sorted(range(len(rows)), key=lambda i: (-total[i], rows[i]))
    target = [rows[i] for i in order[:cfg["holdings"]]]
    return {"kind": "score", "total": total, "target": target}


def compare_signals(name: str, cfg: dict, a: dict, b: dict, cross_a: list[str],
                    cross_b: list[str], T: str):
    """a=切片世界, b=全量世界。"""
    if cross_a != cross_b:
        failures.append(f"{name} T={T}: 截面股票集不一致 "
                        f"(切片 {len(cross_a)} 只 / 全量 {len(cross_b)} 只)")
        note(f"signal:{name}:cross", 1, 1)
        return
    note(f"signal:{name}:cross", 1, 0)
    if a["kind"] == "rule":
        if a["cands"] != b["cands"]:
            failures.append(f"{name} T={T}: 候选序列不一致（切片 {a['cands'][:5]}... "
                            f"vs 全量 {b['cands'][:5]}...）")
            note(f"signal:{name}:cands", 1, 1)
        else:
            note(f"signal:{name}:cands", 1, 0)
        bad = 0
        for c, va in a["rankvals"].items():
            if not eq_scalar(va, b["rankvals"].get(c, np.nan)):
                bad += 1
                if len(samples) < 30:
                    samples.append(f"{name} rank值 T={T} {c}: 切片={va} 全量={b['rankvals'].get(c)}")
        note(f"signal:{name}:rankvals", len(a["rankvals"]), bad)
        bad = 0
        for c in cross_a:
            if bool(a["sell"][c]) != bool(b["sell"][c]):
                bad += 1
                if len(samples) < 30:
                    samples.append(f"{name} 卖出条件 T={T} {c}: 切片={a['sell'][c]} 全量={b['sell'][c]}")
        note(f"signal:{name}:sell", len(cross_a), bad)
    else:
        n, bad = eq_array(a["total"], b["total"])
        if bad:
            failures.append(f"{name} T={T}: 打分总分有 {bad}/{n} 个不一致")
        note(f"signal:{name}:total", n, bad)
        if a["target"] != b["target"]:
            failures.append(f"{name} T={T}: 前30目标列表不一致")
            note(f"signal:{name}:target", 1, 1)
        else:
            note(f"signal:{name}:target", 1, 0)


# ---------------------------------------------------------------- 主流程

def main() -> int:
    t_start = time.time()
    print(f"[newspaper] 加载引擎数据对象（data/raw，经 guard）……", flush=True)
    store = DataStore()
    panel = store.panel
    dates_arr = panel["date"].to_numpy()
    codes_arr = panel["code"].to_numpy()
    cal = store.calendar
    print(f"[newspaper] 面板 {len(panel)} 行 {panel['code'].nunique()} 只，"
          f"日历 {cal[0]} ~ {cal[-1]}", flush=True)

    pool = [d for d in cal if T_LO <= d <= T_HI]
    rng = random.Random(SEED)
    Ts = sorted(rng.sample(pool, N_DATES))
    print(f"[newspaper] 种子 {SEED} 抽样 {N_DATES} 个交易日: {Ts[0]} ~ {Ts[-1]}", flush=True)

    # ---- 每个 T 在全量面板中的行号 ----
    T_rows: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for T in Ts:
        idx = np.flatnonzero(dates_arr == T)
        T_rows[T] = (idx, codes_arr[idx])

    # ---- seq（cumcount）恒等式抽查：seq[T行] == 该股 date<T 行数 ----
    seq_full = panel.groupby("code", sort=False).cumcount().to_numpy()
    for T in Ts[::40]:
        prior = panel[dates_arr < T].groupby("code").size()
        idx, tcodes = T_rows[T]
        pv = prior.reindex(tcodes).fillna(0).to_numpy()
        n, bad = eq_array(seq_full[idx].astype("float64"), pv.astype("float64"))
        note("seq恒等式(cumcount==date<T行数)", n, bad)
        if bad:
            failures.append(f"seq 恒等式 T={T}: {bad} 只股票 cumcount != date<T 行数")

    # ---- 全量世界：全部 (零件,窗口) 在 T 行的值 ----
    print("[newspaper] 全量世界零件求值（与 Backtester._op_values 同口径）……", flush=True)
    full_val: dict[tuple, dict[str, np.ndarray]] = {}
    for name in WINDOWED_OPS:
        if name == "etf_above_ma_n":
            continue
        for n in WINDOWS:
            res = op.OPERATORS[name](panel, n)["value"].to_numpy()
            full_val[(name, n)] = {T: res[T_rows[T][0]] for T in Ts}
    for name in NOARG_OPS:
        res = op.OPERATORS[name](panel)["value"].to_numpy()
        full_val[(name, None)] = {T: res[T_rows[T][0]] for T in Ts}
    etf = store.etfs[ETF_BENCH]
    etf_dates = etf["date"].to_numpy()
    full_etf_by_n = {n: op.etf_above_ma_n(etf, n)["value"].to_numpy() for n in WINDOWS}

    # 全量侧截面过滤需要的当日字段（Tushare 版面板：is_st + 开盘有效性；
    # 「未停牌」= 当日有行情行——daily 表无停牌行，两侧 T 行集天然只含有行者）
    col_isst = panel["is_st"].to_numpy()
    col_open = panel["open"].to_numpy()
    col_l1 = panel["l1_code"].to_numpy()
    col_cm = panel["circ_mv"].to_numpy()

    cfgs = [load_config(p) for p in CONFIG_PATHS]

    # ---- 逐 T：切片世界 vs 全量世界 ----
    for k, T in enumerate(Ts):
        # 面板切片 = 每码「date <= T」的最后 SLICE_WIDTH 行（255 = 最大合法窗口
        # 250 + 5 行余量，按**行**计——全部零件窗口都是行窗口）。
        # 旧实现按「T 往前 255 个日历交易日」切片，隐含「每日有行」假设
        # （旧数据布局停牌日也有 tradestatus 行）；Tushare daily 无停牌行，
        # 停牌多的股票在 255 个日历日里凑不满 250 行，窗口左边界被截——
        # 实测 atr_close_n(250) 的全部不一致股票切片行数 <= 250、切片值恒
        # NaN（那是历史不足，不是未来函数）。按行取尾片后所有 <= 250 行窗口
        # 必然完整包含；切片仍是「date <= T」的子集，as-of 性质不变。
        sub_all = panel[dates_arr <= T]
        sa_pos = np.arange(len(sub_all))
        sa_codes_all = sub_all["code"].to_numpy()
        bnds = np.flatnonzero(np.r_[True, sa_codes_all[1:] != sa_codes_all[:-1]])
        bnds = np.r_[bnds, len(sa_codes_all)]
        keep_from = np.maximum(bnds[:-1], bnds[1:] - SLICE_WIDTH)
        sub = sub_all[sa_pos >= np.repeat(keep_from, np.diff(bnds))]
        sub_dates = sub["date"].to_numpy()
        sub_codes = sub["code"].to_numpy()
        tmask = sub_dates == T
        sub_t_codes = sub_codes[tmask]
        idx_full, codes_full_T = T_rows[T]

        # 1) 两侧 T 行股票集合一致
        if not np.array_equal(sub_t_codes, codes_full_T):
            failures.append(f"面板切片 T={T}: T 行股票集与全量不一致")
            note("panel:T行股票集", 1, 1)
        else:
            note("panel:T行股票集", 1, 0)

        # 2) 成分快照切片 -> 股票池 as-of（与全量快照取池必须一致）
        uni_slice = universe_from(store.members, T)
        uni_full = store.universe_on(T)
        if uni_slice != uni_full:
            failures.append(f"股票池 T={T}: 切片快照取池 != 全量快照取池")
            note("universe(as-of快照)", 1, 1)
        else:
            note("universe(as-of快照)", 1, 0)

        # 3) 上市满 250 日判定：切片侧行数-1 vs 全量 cumcount
        counts_in_slice = sub.groupby("code").size()
        slice_cnt = np.array([counts_in_slice[c] for c in sub_t_codes], dtype="int64")
        verdict_slice = (slice_cnt - 1) >= MIN_LISTED
        verdict_full = seq_full[idx_full] >= MIN_LISTED
        if not np.array_equal(verdict_slice, verdict_full):
            failures.append(f"上市满250日判定 T={T}: 切片与全量不一致")
            note("listed>=250判定", len(verdict_slice), int((verdict_slice != verdict_full).sum()))
        else:
            note("listed>=250判定", len(verdict_slice), 0)

        # 4) 窗口零件 × 全部窗口（股票面板）
        tvals: dict[tuple, np.ndarray] = {}
        for name in WINDOWED_OPS:
            if name == "etf_above_ma_n":
                continue
            for n in WINDOWS:
                res = op.OPERATORS[name](sub, n)["value"].to_numpy()
                sv = res[tmask]
                fv = full_val[(name, n)][T]
                nb, bad = eq_array(sv, fv)
                note(f"op:{name}(n={n})", nb, bad)
                if bad:
                    j = int(np.argmax(~(np.isnan(sv) & np.isnan(fv))
                                      & ~(np.abs(sv - fv) <= TOL)))
                    failures.append(f"零件 {name}(n={n}) T={T}: {bad}/{nb} 只股票不一致，"
                                    f"如 {sub_t_codes[j]}: 切片={sv[j]} 全量={fv[j]}")
                    if len(samples) < 30:
                        samples.append(f"{name}(n={n}) T={T} {sub_t_codes[j]}: "
                                       f"切片={sv[j]!r} 全量={fv[j]!r} diff={sv[j]-fv[j]}")
                tvals[(name, n)] = sv

        # 5) 无窗零件
        for name in NOARG_OPS:
            res = op.OPERATORS[name](sub)["value"].to_numpy()
            sv = res[tmask]
            fv = full_val[(name, None)][T]
            nb, bad = eq_array(sv, fv)
            note(f"op:{name}", nb, bad)
            if bad:
                j = int(np.argmax(~(np.isnan(sv) & np.isnan(fv)) & ~(np.abs(sv - fv) <= TOL)))
                failures.append(f"零件 {name} T={T}: {bad}/{nb} 不一致，"
                                f"如 {sub_t_codes[j]}: 切片={sv[j]} 全量={fv[j]}")
                if len(samples) < 30:
                    samples.append(f"{name} T={T} {sub_t_codes[j]}: 切片={sv[j]!r} 全量={fv[j]!r}")
            if name in ("streak_up", "streak_down"):
                # 无界窗口：触到切片左边界的 run 视为预期截断（详见文件头）
                global truncation_hits
                for j, c in enumerate(sub_t_codes):
                    k_rows = int(counts_in_slice[c])
                    s_v, f_v = float(sv[j]), float(fv[j])
                    if s_v == float(k_rows) and f_v > s_v:
                        truncation_hits += 1
            tvals[(name, None)] = sv

        # 6) etf_above_ma_n（ETF 日线，注册表语义）
        i_end = int(np.searchsorted(etf_dates, T, side="right"))
        i_start = max(0, i_end - SLICE_WIDTH)
        etf_sub = etf.iloc[i_start:i_end]
        etf_slice_vals = {}
        for n in WINDOWS:
            sv = float(op.etf_above_ma_n(etf_sub, n)["value"].to_numpy()[-1])
            fv = float(full_etf_by_n[n][i_end - 1])
            etf_slice_vals[n] = sv
            note(f"op:etf_above_ma_n(n={n})", 1, 0 if eq_scalar(sv, fv) else 1)
            if not eq_scalar(sv, fv):
                failures.append(f"零件 etf_above_ma_n(n={n}) T={T}: 切片={sv} 全量={fv}")

        # 7) 信号生成（示例配置单；打分型含中性化分组秩镜像）
        sub_isst = sub["is_st"].to_numpy()[tmask]
        sub_open = sub["open"].to_numpy()[tmask]
        sub_l1 = sub["l1_code"].to_numpy()[tmask]
        sub_cm = sub["circ_mv"].to_numpy()[tmask]
        full_isst = col_isst[idx_full]
        full_open = col_open[idx_full]
        full_l1 = col_l1[idx_full]
        full_cm = col_cm[idx_full]

        cross_slice = [c for j, c in enumerate(sub_t_codes)
                       if sub_isst[j] != 1 and np.isfinite(sub_open[j]) and verdict_slice[j]]
        cross_full = [c for j, c in enumerate(codes_full_T)
                      if full_isst[j] != 1 and np.isfinite(full_open[j]) and verdict_full[j]]
        pos_slice = {c: j for j, c in enumerate(sub_t_codes)}
        pos_full = {c: j for j, c in enumerate(codes_full_T)}
        meta_slice = {c: (sub_l1[j], sub_cm[j]) for j, c in enumerate(sub_t_codes)}
        meta_full = {c: (full_l1[j], full_cm[j]) for j, c in enumerate(codes_full_T)}

        def mk_getval(source: str):
            def getval(key, c):
                name, n = key
                if source == "slice":
                    return float(tvals[(name, n if n is not None else None)][pos_slice[c]])
                return float(full_val[(name, n if n is not None else None)][T][pos_full[c]])
            return getval

        def mk_etfval(source: str):
            def f(n):
                return etf_slice_vals[n] if source == "slice" else float(full_etf_by_n[n][i_end - 1])
            return f

        for cfg in cfgs:
            a = eval_signal(cfg, mk_getval("slice"), mk_etfval("slice"),
                            cross_slice, meta_slice)
            b = eval_signal(cfg, mk_getval("full"), mk_etfval("full"),
                            cross_full, meta_full)
            compare_signals(cfg["name"], cfg, a, b, cross_slice, cross_full, T)

        if (k + 1) % 20 == 0:
            print(f"[newspaper] {k+1}/{N_DATES} 个 T 完成，累计失败 {len(failures)}，"
                  f"用时 {time.time()-t_start:.0f}s", flush=True)

    # ---------------------------------------------------------------- 8) 资金面表对齐口径
    # 世界切片语义的直接验证（第 3 步新增）：面板列在 T 行的值，必须等于用
    # 原始表按**披露口径**切片（龙虎榜 trade_date ≤ T；两融/北向 trade_date < T，
    # 即 ≤ T-1 次日披露）独立重算的值。重算路径不复用 prices.DataStore 的事件
    # 构造，直接从 raw 列聚合（机构专用 net_buy 合计 / l_amount 最大值）。
    print("[newspaper] 资金面对齐口径检查（原始表独立重算 vs 面板列）……", flush=True)
    import bisect

    def _by_code_series(df, val_col):
        out = {}
        for code, g in df.groupby("ts_code", sort=False):
            g = g.sort_values("trade_date", kind="stable")
            out[str(code)] = (g["trade_date"].astype(str).tolist(),
                              g[val_col].tolist())
        return out

    # 龙虎榜事件（独立重算）：机构专用净买入合计（元）/ 当日 l_amount 最大值（元）×100
    tl_raw = store.top_list
    ti_raw = store.top_inst
    inst_raw = ti_raw[ti_raw["exalter"].astype("string") == "机构专用"]
    ev = (tl_raw.groupby(["ts_code", "trade_date"])["l_amount"].max()
          .to_frame("l_amount")
          .join(inst_raw.groupby(["ts_code", "trade_date"])["net_buy"].sum()
                .rename("net_buy"), how="left"))
    ev["net_buy"] = ev["net_buy"].fillna(0.0)
    ev["pct"] = np.where(ev["l_amount"] > 0,
                         ev["net_buy"] / ev["l_amount"] * 100.0, np.nan)
    ev = ev.reset_index()
    tl_ev = _by_code_series(ev, "pct")
    margin_s = _by_code_series(store.margin, "rzye")
    hk_s = _by_code_series(store.hk, "ratio")
    col_tl_on = panel["tl_on_list"].to_numpy()
    col_tl_pct = panel["tl_inst_netbuy_pct"].to_numpy()
    col_rzye = panel["margin_rzye"].to_numpy()
    col_hkr = panel["hk_ratio"].to_numpy()
    align_bad = 0
    for T in Ts[::5]:
        idx_full, codes_full_T = T_rows[T]
        rowpos = {c: j for j, c in enumerate(codes_full_T)}
        # 龙虎榜 ≤ T：最新一次上榜事件
        for code, j in rowpos.items():
            dates, pcts = tl_ev.get(code, ([], []))
            pos = bisect.bisect_right(dates, T) - 1
            exp_pct = pcts[pos] if pos >= 0 else float("nan")
            exp_on = 1.0 if (pos >= 0 and dates[pos] == T) else 0.0
            r = int(idx_full[j])
            if not eq_scalar(col_tl_pct[r], exp_pct) or col_tl_on[r] != exp_on:
                align_bad += 1
                if len(samples) < 30:
                    samples.append(f"龙虎榜对齐 T={T} {code}: 面板"
                                   f"(on={col_tl_on[r]}, pct={col_tl_pct[r]!r}) "
                                   f"重算(on={exp_on}, pct={exp_pct!r})")
            note("align:top_list(≤T)", 1, 0)
        # 两融 < T（次日披露 → 只能用 ≤ T-1）
        for code, j in rowpos.items():
            dates, vals = margin_s.get(code, ([], []))
            pos = bisect.bisect_left(dates, T) - 1
            exp = vals[pos] if pos >= 0 else float("nan")
            r = int(idx_full[j])
            if not eq_scalar(col_rzye[r], exp):
                align_bad += 1
                if len(samples) < 30:
                    samples.append(f"两融对齐 T={T} {code}: 面板={col_rzye[r]!r} 重算={exp!r}")
            note("align:margin(<T)", 1, 0)
        # 北向 < T（同上；只用 SH/SZ 记录）
        for code, j in rowpos.items():
            dates, vals = hk_s.get(code, ([], []))
            pos = bisect.bisect_left(dates, T) - 1
            exp = vals[pos] if pos >= 0 else float("nan")
            r = int(idx_full[j])
            if not eq_scalar(col_hkr[r], exp):
                align_bad += 1
                if len(samples) < 30:
                    samples.append(f"北向对齐 T={T} {code}: 面板={col_hkr[r]!r} 重算={exp!r}")
            note("align:hk_hold(<T)", 1, 0)
    if align_bad:
        failures.append(f"资金面对齐口径：{align_bad} 个 (code,T) 面板值 != 原始表重算值")

    # ---------------------------------------------------------------- 输出
    print("\n===== 撕报纸测试逐项结果 =====")
    for item in sorted(stats):
        s = stats[item]
        flag = "PASS" if s["bad"] == 0 else "FAIL"
        print(f"  [{flag}] {item:44s} 比对 {s['n']:>8d} 次，不一致 {s['bad']} 次")
    print(f"\n  streak 左边界截断（预期，非未来函数）出现 {truncation_hits} 次")
    if samples:
        print("\n  差异样本（前 30 条）:")
        for s in samples[:30]:
            print(f"    - {s}")
    n_total = sum(s["n"] for s in stats.values())
    n_bad = sum(s["bad"] for s in stats.values())
    print(f"\n[newspaper] 摘要：{N_DATES} 个随机日期 × {len(WINDOWED_OPS)} 个窗口零件"
          f" × {len(WINDOWS)} 个窗口 × {len(NOARG_OPS)} 个无窗零件"
          f" × {len(CONFIG_PATHS)} 个示例配置信号 + 资金面表对齐口径重算，"
          f"共 {n_total} 次比对，不一致 {n_bad} 次，"
          f"失败项 {len(failures)} 条；总用时 {time.time()-t_start:.0f}s")
    if failures:
        print("[newspaper] 结论：FAIL（存在依赖 T 日之后数据的值/信号）")
        for f in failures[:20]:
            print(f"    ! {f}")
        return 1
    print("[newspaper] 结论：PASS（截至 T 的世界切片与全量世界在 T 日的值/信号完全一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
