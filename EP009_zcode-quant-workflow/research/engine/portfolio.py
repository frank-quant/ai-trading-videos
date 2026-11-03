# -*- coding: utf-8 -*-
"""
engine/portfolio.py —— 组合层（rules.md 第 5.5 节，第 3 版）

  底仓   沪深300 ETF（510300.SH）在 200 日均线上方持有，跌破换黄金 ETF
         （518880.SH）；均线与收益都用复权价 close × fund_adj.adj_factor。
  卫星   本组 3 个入围策略等权（各策略日收益已含其自身成本）。
  组合   底仓 60% + 卫星 40%，日收益 = 0.6×底仓 + 0.4×卫星 − 换腿成本
         （换腿日扣 0.6 × (佣金 0.025% + 滑点 0.1%)）。

T 日的持仓状态由 T−1 收盘的均线位置决定（无未来函数）。三段（搜索期 /
验证期 / 封存期）分别输出年化、最大回撤、相对沪深300 ETF 买入持有的超额；
封存期未开封时如实标注并跳过。组合最大回撤 < 25% 是检验项、不是筛选项。

核心计算是纯函数（naive 可逐项对拍）：
  base_state_series / satellite_returns / portfolio_returns

CLI：
  python engine/portfolio.py --shortlist data/shortlist_example.json \
      --out data/portfolio_example.json --md reports/portfolio_example.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard  # noqa: E402  必须先于 numpy/pandas（guard 钉死 BLAS 线程环境变量）

import numpy as np
import pandas as pd

from backtest import (COMMISSION, RUNS_DIR, SLIPPAGE, annualized_return,  # noqa: E402
                      max_drawdown)
from funnel import SEARCH_START, SEARCH_END, VALID_START, VALID_END  # noqa: E402
from prices import ETF_BENCHMARK, ETF_GOLD, DataStore  # noqa: E402

ROOT = guard.ROOT
DATA_DIR = ROOT / "data"

BASE_WEIGHT = 0.60
SAT_WEIGHT = 0.40
MA_WINDOW = 200                    # 底仓均线档位（rules.md 第 7 节窗口档位）
SWITCH_COST = BASE_WEIGHT * (COMMISSION + SLIPPAGE)

PERIODS = [("search", SEARCH_START, SEARCH_END),
           ("validation", VALID_START, VALID_END),
           ("sealed", "20250101", str(pd.Timestamp.today().strftime("%Y%m%d")))]


def _periods_with_data_end(c300_last_date: str) -> list[tuple[str, str, str]]:
    """封存期终点 = min(今天, 底仓 ETF 最后可用复权日)。

    trade_cal 会延伸到年末，直接取「今天」会把无行情数据的日历日按 0 收益
    计入底仓/基准/卫星，伪造平坦尾段（本轮数据冻结在 2026-09-30，AGENTS.md：
    原文「至今」限于已有数据截止）。其余两段区间由 rules.md 第 1 节常量给定。
    """
    out = list(PERIODS)
    out[2] = ("sealed", "20250101",
              min(str(pd.Timestamp.today().strftime("%Y%m%d")), str(c300_last_date)))
    return out


# ================================================================ 纯函数（可对拍）

def base_state_series(close_adj: pd.Series, ma_window: int = MA_WINDOW) -> pd.Series:
    """底仓每日「应持有腿」：T 日持有腿由 T−1 收盘的均线位置决定（无未来函数）。

    close_adj[t-1] > ma(close_adj, ma_window)[t-1] → 沪深300；否则黄金。
    均线不足 ma_window 个样本时（历史前段）视为「不在上方」→ 黄金腿（保守）。
    返回与输入同索引的 Series（值为 ETF 代码）。
    """
    ma = close_adj.rolling(ma_window).mean()
    above = (close_adj > ma).shift(1)
    state = pd.Series(ETF_GOLD, index=close_adj.index, dtype=object)
    state[above == True] = ETF_BENCHMARK   # noqa: E712（NaN 不进沪深300）
    state[close_adj.index[0]] = ETF_GOLD   # 首日无 T−1 → 黄金（保守）
    return state


def satellite_returns(daily_by_cfg: dict[str, pd.DataFrame],
                      dates: list[str], configs: list[str]) -> pd.Series:
    """卫星日收益 = 入围策略等权平均（缺数据的策略跳过、无策略日为 0）。"""
    series = []
    for c in configs:
        df = daily_by_cfg.get(c)
        if df is None:
            continue
        s = pd.Series(df["strategy_ret"].to_numpy(), index=df["date"].astype(str))
        series.append(s)
    if not series:
        return pd.Series(0.0, index=dates)
    mat = pd.concat(series, axis=1, join="outer").reindex(dates)
    return mat.mean(axis=1, skipna=True).fillna(0.0)


def portfolio_returns(state: pd.Series, etf_ret: dict[str, pd.Series],
                      sat: pd.Series, dates: list[str]) -> tuple[pd.Series, pd.Series]:
    """组合日收益（naive 逐日循环，可对拍）与底仓日收益。

    组合 = BASE_WEIGHT×底仓 + SAT_WEIGHT×卫星 − 换腿成本（换腿日）。
    首日无换腿成本。
    """
    rets, base_rets = [], []
    prev_state = None
    for d in dates:
        leg = state.loc[d]
        br = float(etf_ret[leg].get(d, 0.0))
        cost = SWITCH_COST if (prev_state is not None and leg != prev_state) else 0.0
        sr = float(sat.loc[d])
        rets.append(BASE_WEIGHT * br + SAT_WEIGHT * sr - cost)
        base_rets.append(br)
        prev_state = leg
    return (pd.Series(rets, index=dates, dtype="float64"),
            pd.Series(base_rets, index=dates, dtype="float64"))


# ================================================================ 编排

def _load_strategy_daily(name: str) -> pd.DataFrame | None:
    segments = [(SEARCH_START, SEARCH_END), (VALID_START, VALID_END)]
    if guard.OPEN_SEALED_MARKER.is_file():
        # 开封后（rules 5.5 封存期组合检验）：追加封存期日收益段。封存回测
        # 目录以 20250101 起；目录数 ≠ 1 直接报错——多于一个违反第 7 步
        # 「只跑一次」，为零说明封存回测未跑，两者都不许静默拿 0 顶数。
        sealed_dirs = sorted(p for p in RUNS_DIR.glob(f"{name}__20250101_*")
                             if (p / "daily_returns.csv").is_file())
        if len(sealed_dirs) != 1:
            raise RuntimeError(
                f"{name}：封存期 run 目录数 = {len(sealed_dirs)}（应为 1；"
                f"手册第 7 步「只跑一次」——先跑封存回测，且不得重跑）")
        seg = sealed_dirs[0].name.split("__", 1)[1]
        segments.append(tuple(seg.split("_", 1)))
    frames = []
    for s, e in segments:
        p = RUNS_DIR / f"{name}__{s}_{e}" / "daily_returns.csv"
        if p.exists():
            frames.append(pd.read_csv(p, dtype={"date": str}))
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def run_portfolio(shortlist_names: list[str], group: str,
                  store: DataStore | None = None) -> dict:
    """三段组合层检验（封存期未开封时跳过并如实标注）。"""
    store = store or DataStore()
    c300 = store.etfs[ETF_BENCHMARK].set_index("date")["close_adj"].astype(float)
    etf_ret = {ETF_BENCHMARK: store.etfs[ETF_BENCHMARK].set_index("date")["ret"].astype(float),
               ETF_GOLD: store.etfs[ETF_GOLD].set_index("date")["ret"].astype(float)}
    state_full = base_state_series(c300.sort_index())

    daily_by_cfg = {n: _load_strategy_daily(n) for n in shortlist_names}
    missing = [n for n, d in daily_by_cfg.items() if d is None]
    if missing:
        raise RuntimeError(f"入围策略缺少回测日收益（先跑搜索期+验证期回测）：{missing}")

    out: dict = {
        "group": group,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "base_rule": f"510300.SH 在 {MA_WINDOW} 日均线上方持有，"
                     f"跌破换 518880.SH（复权价口径，T−1 收盘定 T 日腿）",
        "weights": {"base": BASE_WEIGHT, "satellite": SAT_WEIGHT},
        "satellite": shortlist_names,
        "switch_cost_per_event": SWITCH_COST,
        "periods": {},
        "note": "组合最大回撤 < 25% 是检验项、不是筛选项（rules.md 5.5）。"
                "年化按 250 交易日；封存期在 OPEN_SEALED 出现前不输出。",
    }
    for pname, s, e in _periods_with_data_end(c300.index.max()):
        if pname == "sealed" and not guard.OPEN_SEALED_MARKER.is_file():
            out["periods"][pname] = {"available": False,
                                     "note": "封存期未开封（rules.md 第 1 节），不计算"}
            continue
        dates = [d for d in store.calendar if s <= d <= e]
        if not dates:
            out["periods"][pname] = {"available": False, "note": "区间内无交易日"}
            continue
        state = state_full.reindex(dates).ffill().bfill()
        sat = satellite_returns(daily_by_cfg, dates, shortlist_names)
        port, base = portfolio_returns(state, etf_ret, sat, dates)
        bench = pd.Series([float(etf_ret[ETF_BENCHMARK].get(d, 0.0)) for d in dates],
                          index=dates, dtype="float64")
        ex = port - bench

        def stat(sr: pd.Series) -> dict:
            return {"ann_ret": float(annualized_return(list(sr))),
                    "max_dd": float(max_drawdown(list(sr)))}

        port_s, base_s, bench_s = stat(port), stat(base), stat(bench)
        out["periods"][pname] = {
            "available": True,
            "from": dates[0], "to": dates[-1], "n_days": len(dates),
            "portfolio": {**port_s,
                          "ann_excess_vs_510300_bh": port_s["ann_ret"] - bench_s["ann_ret"],
                          "excess_max_dd": float(max_drawdown(list(ex))),
                          "check_mdd_lt_25pct": bool(port_s["max_dd"] > -0.25)},
            "base_only": base_s,
            "bench_510300_bh": bench_s,
            "satellite_only": stat(sat),
        }
    return out


def render_md(result: dict) -> str:
    g = result["group"]
    lines = [f"# 组合层检验（{g} 组，rules.md 5.5）", ""]
    lines.append(f"- 生成时间：{result['generated_at']}")
    lines.append(f"- 底仓：{result['base_rule']}（权重 {result['weights']['base']:.0%}）")
    lines.append(f"- 卫星（权重 {result['weights']['satellite']:.0%}，等权）："
                 + "、".join(result["satellite"]))
    lines.append(f"- 换腿成本：每次 {result['switch_cost_per_event']:.4%}（对组合净值）")
    lines.append("")
    lines.append("| 区间 | 组合年化 | 组合最大回撤 | vs 510300 买入持有年化超额 | 超额最大回撤 | 组合回撤<25% 检验 |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for pname, p in result["periods"].items():
        label = {"search": "搜索期", "validation": "验证期", "sealed": "封存期"}[pname]
        if not p.get("available"):
            lines.append(f"| {label} | — | — | — | — | {p.get('note', '不可用')} |")
            continue
        pf = p["portfolio"]
        lines.append(
            f"| {label}（{p['from']}~{p['to']}） | {pf['ann_ret']*100:.2f}% | "
            f"{pf['max_dd']*100:.2f}% | {pf['ann_excess_vs_510300_bh']*100:+.2f}% | "
            f"{pf['excess_max_dd']*100:.2f}% | {'达标' if pf['check_mdd_lt_25pct'] else '未达标（检验项，照实报告）'} |")
    lines.append("")
    b = result["periods"].get("search", {})
    if b.get("available"):
        lines.append(f"- 参考（搜索期）：底仓单独年化 {b['base_only']['ann_ret']*100:.2f}%、"
                     f"卫星单独年化 {b['satellite_only']['ann_ret']*100:.2f}%、"
                     f"510300 买入持有 {b['bench_510300_bh']['ann_ret']*100:.2f}%。")
    lines.append("")
    return "\n".join(lines)


# ================================================================ CLI

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="engine/portfolio.py", description="5.5 组合层检验")
    ap.add_argument("--shortlist", required=True, help="shortlist JSON（含 shortlist 名单）")
    ap.add_argument("--group", default=None, help="组名（默认取 shortlist JSON 的 group）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--md", default=None)
    a = ap.parse_args(argv)
    sj = json.loads(Path(a.shortlist).read_text(encoding="utf-8"))
    group = a.group or sj.get("group", "AI")
    names = list(sj.get("shortlist", []))
    if not names:
        print("[portfolio] shortlist 为空，无法组合")
        return 2
    result = run_portfolio(names, group)
    out = Path(a.out) if a.out else DATA_DIR / f"portfolio_{group}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    md = Path(a.md) if a.md else ROOT / "reports" / f"portfolio_{group}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_md(result), encoding="utf-8")
    print(f"[portfolio] {group}: 三段检验完成 -> {out}")
    print(f"[portfolio] 报告 -> {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
