"""Branch unblinded evaluation of the three SAVED strategy versions on new BaoStock data.

Versions (loaded as saved, no retrain / no tuning / no factor swap):
  v1          output/        LightGBM 38 trees, pool [b3_low_range_20, b4_max_lottery]
  v2          output/v2/     LightGBM 117 trees, pool [optC2, b2_low_range, b3_cc_vol, optD1, optA2]
  deliverable deliverable/   optC2 single-factor percentile ranking

Data: evaluation/local_data_20261120 (2024 warmup; eval 2025-01-02 .. 2026-11-20, 456 days).
Same market data, equal-weight benchmark, positions, execution rules and fees for all three.
Cumulative return measured from pre-build cash (1,000,000), including first-day P&L.

Usage (from project root): python -I evaluation/run_three_versions_branch.py
Results -> evaluation/reproduced_20261120/ (existing results untouched).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from coa.backtest import run_backtest
from coa.combine import percentile_transform
from coa.data import load_market
from coa.formula import compile_expr, evaluate

DATA_DIR = "evaluation/local_data_20261120"
OUT = HERE / "reproduced_20261120"
EVAL_WINDOW = ["2025-01-02", "2026-11-20"]
INITIAL_CASH = 1_000_000


def build_md():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg["data"]["bars"] = f"{DATA_DIR}/daily_bars.parquet"
    cfg["data"]["members"] = f"{DATA_DIR}/hs300_members.parquet"
    cfg["data"]["train"] = ["2024-01-01", "2024-12-31"]
    cfg["data"]["validation"] = EVAL_WINDOW
    cfg["backtest"]["execution_window"] = EVAL_WINDOW
    cfg["backtest"]["initial_cash"] = INITIAL_CASH
    cfg["backtest"]["benchmark"]["initial_cash"] = INITIAL_CASH
    return load_market(cfg), cfg


def factor_pct(expr, md, cfg):
    root, _ = compile_expr(expr, md.cfg)
    return percentile_transform(evaluate(root, md.fields), md.eligible)


def score_lgbm(pool, model_path, md, cfg):
    pcts = {p["id"]: factor_pct(p["expression"], md, cfg) for p in pool}
    booster = lgb.Booster(model_str=Path(model_path).read_text(encoding="utf-8"))
    feats = booster.feature_name()
    long = pd.DataFrame({cid: pcts[cid].stack() for cid in feats})
    elig = md.eligible.stack()
    long = long.reindex(elig[elig].index).dropna()
    pred = pd.Series(booster.predict(long[feats]), index=long.index, name="score")
    scores = pred.unstack("code").reindex(index=md.calendar, columns=md.adj_close.columns)
    tiebreak = pd.concat([pcts[f] for f in feats]).groupby(level=0).mean()
    return scores, tiebreak, booster.num_trees()


def score_single(spec, md, cfg):
    fac = spec["factors"][0]
    pct = factor_pct(fac["expression"], md, cfg)
    return pct, pct


def metrics_from(nav, trades, bench_nav):
    s = nav["strategy_nav"]
    b = bench_nav
    years = len(s) / 252
    total = s.iloc[-1] / INITIAL_CASH - 1
    btotal = b.iloc[-1] / INITIAL_CASH - 1
    dd = (s / s.cummax().clip(lower=INITIAL_CASH) - 1).min()
    bdd = (b / b.cummax().clip(lower=INITIAL_CASH) - 1).min()
    fills = trades[trades["status"] == "filled"].copy()
    fills["notional"] = fills["price"] * fills["shares"]
    buy_notional = fills[(fills["side"] == "buy") & (fills["book"] == "strategy")]["notional"].sum()
    turnover = buy_notional / s.mean() / years
    # per-year chained returns
    peryear = {}
    prev = INITIAL_CASH
    for yr, g in s.groupby(s.index.year):
        peryear[str(yr)] = float(g.iloc[-1] / prev - 1)
        prev = g.iloc[-1]
    bprev = INITIAL_CASH
    byear = {}
    for yr, g in b.groupby(b.index.year):
        byear[str(yr)] = float(g.iloc[-1] / bprev - 1)
        bprev = g.iloc[-1]
    return {
        "final_nav": float(s.iloc[-1]),
        "cumulative_return": float(total),
        "benchmark_cumulative": float(btotal),
        "return_vs_benchmark": float(total - btotal),
        "max_drawdown": float(dd),
        "benchmark_max_drawdown": float(bdd),
        "annual_one_way_turnover": float(turnover),
        "per_year": peryear,
        "benchmark_per_year": byear,
        "trading_days": int(len(s)),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    md, cfg = build_md()
    print(f"calendar {md.calendar[0].date()}..{md.calendar[-1].date()}; "
          f"eval days {len(md.calendar[(md.calendar>=EVAL_WINDOW[0])&(md.calendar<=EVAL_WINDOW[1])])}", flush=True)

    versions = {}
    pool1 = json.loads((ROOT / "output/pool.json").read_text(encoding="utf-8"))
    s1, tb1, nt1 = score_lgbm(pool1, ROOT / "output/lgbm_model.txt", md, cfg)
    versions["v1"] = (s1, tb1, f"LightGBM {nt1} trees, pool {[p['id'] for p in pool1]}")
    pool2 = json.loads((ROOT / "output/v2/pool.json").read_text(encoding="utf-8"))
    s2, tb2, nt2 = score_lgbm(pool2, ROOT / "output/v2/lgbm_model.txt", md, cfg)
    versions["v2"] = (s2, tb2, f"LightGBM {nt2} trees, pool {[p['id'] for p in pool2]}")
    spec = json.loads((ROOT / "deliverable/strategy.json").read_text(encoding="utf-8"))
    s3, tb3 = score_single(spec, md, cfg)
    versions["deliverable"] = (s3, tb3, f"single-factor percentile {spec['factors'][0]['id']}")

    combined_nav = None
    bench_nav = None
    all_metrics = {}
    for name, (scores, tb, desc) in versions.items():
        res = run_backtest(md, scores, tiebreak=tb)
        nav = res["nav"]
        trades = res["trades"]
        nav.to_csv(OUT / f"nav_{name}.csv")
        trades.to_csv(OUT / f"trades_{name}.csv", index=False)
        m = metrics_from(nav, trades, nav["benchmark_nav"])
        m["description"] = desc
        m["fees_paid"] = res["metrics"]["strategy_account"]["fees_paid"]
        m["buys"] = res["metrics"]["strategy_account"]["buys"]
        m["sells"] = res["metrics"]["strategy_account"]["sells"]
        m["blocked_attempts"] = res["metrics"]["strategy_account"]["blocked_attempts"]
        all_metrics[name] = m
        col = nav["strategy_nav"].rename(name)
        combined_nav = col.to_frame() if combined_nav is None else combined_nav.join(col)
        bench_nav = nav["benchmark_nav"].rename("benchmark")
        print(f"{name}: cum {m['cumulative_return']*100:.1f}% vs bench {m['return_vs_benchmark']*100:+.1f}% "
              f"DD {m['max_drawdown']*100:.1f}% turnover {m['annual_one_way_turnover']:.1f} fees {m['fees_paid']:.0f}", flush=True)

    combined_nav = combined_nav.join(bench_nav)
    combined_nav.to_csv(OUT / "nav_daily.csv")
    (OUT / "metrics.json").write_text(json.dumps(all_metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    # comparison table
    rows = []
    for name, m in all_metrics.items():
        rows.append({"version": name, "cum_return_%": round(m["cumulative_return"] * 100, 2),
                     "bench_cum_%": round(m["benchmark_cumulative"] * 100, 2),
                     "vs_bench_pp": round(m["return_vs_benchmark"] * 100, 2),
                     "max_dd_%": round(m["max_drawdown"] * 100, 2),
                     "turnover_yr": round(m["annual_one_way_turnover"], 2),
                     "fees": round(m["fees_paid"]),
                     **{f"ret_{y}_%": round(r * 100, 2) for y, r in m["per_year"].items()}})
    cmp = pd.DataFrame(rows)
    cmp.to_csv(OUT / "comparison.csv", index=False, encoding="utf-8-sig")

    # plot
    fig, ax = plt.subplots(figsize=(12, 6.5))
    colors = {"v1": "tab:blue", "v2": "tab:orange", "deliverable": "tab:red"}
    for name in versions:
        ax.plot(combined_nav.index, combined_nav[name] / 1e6, label=name, lw=1.6, color=colors[name])
    ax.plot(combined_nav.index, combined_nav["benchmark"] / 1e6, label="benchmark (HS300 hist. EW)",
            lw=1.3, color="gray", ls="--")
    ax.set_ylabel("NAV (million CNY)")
    ax.set_title("Three saved versions unblinded — 2025-01-02 to 2026-11-20 (456 days, next-open, same rules)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "nav_all_versions.png", dpi=130)

    print("\n" + cmp.to_string(index=False))
    print("\nresults ->", OUT)


if __name__ == "__main__":
    main()
