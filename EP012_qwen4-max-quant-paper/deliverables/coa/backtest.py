"""Validation backtest: top-30 drop-3 strategy vs equal-weight historical-constituent benchmark.

Signal at close of t, execution at open of t+1. Backward-adjusted prices for fills/valuation;
raw preclose + board rules for limit estimation. Sells before buys; blocked trades never count.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data import MarketData

CHINEXT_20PCT_START = pd.Timestamp("2020-08-24")


def limit_rate(code: str, day: pd.Timestamp) -> float:
    num = code.split(".")[1]
    if num.startswith(("688", "689")):
        return 0.20
    if num.startswith(("300", "301")):
        return 0.20 if day >= CHINEXT_20PCT_START else 0.10
    return 0.10


def round_half_up_cent(x: float) -> float:
    return math.floor(x * 100 + 0.5) / 100


@dataclass
class Book:
    cash: float
    shares: dict[str, float] = field(default_factory=dict)
    last_close: dict[str, float] = field(default_factory=dict)
    fees_paid: float = 0.0
    n_buys: int = 0
    n_sells: int = 0
    n_blocked: int = 0

    def _px(self, md: MarketData, day: pd.Timestamp, code: str, use_open: bool) -> float | None:
        frame = md.adj_open if use_open else md.adj_close
        p = frame.at[day, code]
        if md.tradestatus.at[day, code] == 1 and pd.notna(p) and p > 0:
            return float(p)
        return None

    def mark(self, md: MarketData, day: pd.Timestamp, use_open: bool = False) -> float:
        total = self.cash
        for c, sh in self.shares.items():
            p = self._px(md, day, c, use_open)
            total += sh * (p if p is not None else self.last_close.get(c, 0.0))
        return total

    def refresh_last_close(self, md: MarketData, day: pd.Timestamp):
        for c in self.shares:
            p = self._px(md, day, c, use_open=False)
            if p is not None:
                self.last_close[c] = p


def trade_block(md: MarketData, day: pd.Timestamp, code: str, side: str) -> str | None:
    if md.tradestatus.at[day, code] != 1:
        return "suspended"
    ao = md.adj_open.at[day, code]
    ro = md.raw_open.at[day, code]
    pc = md.preclose.at[day, code]
    if pd.isna(ao) or ao <= 0 or pd.isna(ro) or ro <= 0:
        return "missing_open"
    if pd.isna(pc) or pc <= 0:
        return "missing_preclose"
    rate = limit_rate(code, day)
    up = round_half_up_cent(pc * (1 + rate))
    down = round_half_up_cent(pc * (1 - rate))
    if side == "buy" and ro >= up:
        return "limit_up"
    if side == "sell" and ro <= down:
        return "limit_down"
    return None


def run_backtest(md: MarketData, scores: pd.DataFrame,
                 tiebreak: pd.DataFrame | None = None) -> dict:
    bt = md.cfg["backtest"]
    fees = bt["fees"]
    lo, hi = (pd.Timestamp(x) for x in bt["execution_window"])
    exec_days = md.calendar[(md.calendar >= lo) & (md.calendar <= hi)]
    pos = {d: i for i, d in enumerate(md.calendar)}
    k = bt["first_day_max_buys"]
    cap_b, cap_s = bt["daily_max_successful_buys"], bt["daily_max_successful_sells"]

    strat = Book(bt["initial_cash"])
    bench = Book(bt["initial_cash"])
    trades, nav_rows = [], []
    bench_rebal_days = {d for d in exec_days
                        if d.month != md.calendar[pos[d] - 1].month}

    def do_sell(book, day, code, shares, note):
        reason = trade_block(md, day, code, "sell")
        if reason:
            book.n_blocked += 1
            trades.append({"date": day, "book": note, "side": "sell", "code": code,
                           "shares": shares, "status": f"blocked:{reason}"})
            return False
        px = float(md.adj_open.at[day, code])
        proceeds = shares * px * (1 - fees["sell"])
        book.cash += proceeds
        book.fees_paid += shares * px * fees["sell"]
        book.shares[code] -= shares
        if book.shares[code] <= 1e-9:
            del book.shares[code]
        book.n_sells += 1
        trades.append({"date": day, "book": note, "side": "sell", "code": code,
                       "shares": shares, "price": px, "status": "filled"})
        return True

    def do_buy(book, day, code, budget, note):
        reason = trade_block(md, day, code, "buy")
        if reason:
            book.n_blocked += 1
            trades.append({"date": day, "book": note, "side": "buy", "code": code,
                           "budget": budget, "status": f"blocked:{reason}"})
            return False
        px = float(md.adj_open.at[day, code])
        shares = budget / (px * (1 + fees["buy"]))
        if shares <= 0:
            return False
        cost = shares * px * (1 + fees["buy"])
        book.cash -= cost
        book.fees_paid += shares * px * fees["buy"]
        book.shares[code] = book.shares.get(code, 0.0) + shares
        book.n_buys += 1
        trades.append({"date": day, "book": note, "side": "buy", "code": code,
                       "shares": shares, "price": px, "status": "filled"})
        return True

    for d in exec_days:
        t = md.calendar[pos[d] - 1]
        # ---- strategy: signal from t close, trade at d open ----
        elig_t = md.eligible.loc[t]
        sc = scores.loc[t].where(elig_t).dropna()
        tb = (tiebreak.loc[t].reindex(sc.index).fillna(0.0)
              if tiebreak is not None else pd.Series(0.0, index=sc.index))
        target = sorted(sc.index, key=lambda c: (float(sc[c]), float(tb[c])),
                        reverse=True)[:k]
        target_set = set(target)
        open_equity = strat.mark(md, d, use_open=True)
        first_day = d == exec_days[0]

        sell_cands = sorted((c for c in strat.shares if c not in target_set),
                            key=lambda c: (sc.get(c, -np.inf), tb.get(c, 0.0)))
        sold_scores, n_sold = [], 0
        for c in sell_cands:
            if n_sold >= cap_s:
                break
            if do_sell(strat, d, c, strat.shares[c], "strategy"):
                n_sold += 1
                sold_scores.append(sc.get(c, -np.inf))

        if first_day or not strat.shares:
            score_floor = -np.inf
        elif sold_scores:
            score_floor = min(sold_scores)
        else:
            score_floor = min(sc.get(c, -np.inf) for c in strat.shares)
        n_bought = 0
        per_cap = open_equity / k
        for c in target:
            if c in strat.shares:
                continue
            if n_bought >= (k if first_day else cap_b):
                break
            if sc[c] <= score_floor:
                continue
            budget = min(per_cap, strat.cash)
            if budget <= 1.0:
                break
            if do_buy(strat, d, c, budget, "strategy"):
                n_bought += 1

        # ---- benchmark: monthly equal-weight rebalance ----
        if d in bench_rebal_days:
            b_target = [c for c in md.snapshot_asof(t) if bool(elig_t.get(c, False))]
            b_set = set(b_target)
            b_equity = bench.mark(md, d, use_open=True)
            tv = b_equity / len(b_target) if b_target else 0.0
            for c in list(bench.shares):
                if c not in b_set:
                    do_sell(bench, d, c, bench.shares[c], "benchmark")
                    continue
                p = bench._px(md, d, c, use_open=True)
                if p is None:
                    bench.n_blocked += 1
                    trades.append({"date": d, "book": "benchmark", "side": "sell",
                                   "code": c, "status": "blocked:rebalance"})
                    continue
                cur = bench.shares[c] * p
                if cur > tv:
                    do_sell(bench, d, c, (cur - tv) / p, "benchmark")
            for c in b_target:
                p = bench._px(md, d, c, use_open=True)
                if p is None:
                    bench.n_blocked += 1
                    trades.append({"date": d, "book": "benchmark", "side": "buy",
                                   "code": c, "status": "blocked:rebalance"})
                    continue
                cur = bench.shares.get(c, 0.0) * p
                if cur < tv:
                    budget = min(tv - cur, bench.cash)
                    if budget > 1.0:
                        do_buy(bench, d, c, budget, "benchmark")

        strat.refresh_last_close(md, d)
        bench.refresh_last_close(md, d)
        nav_rows.append({"date": d, "strategy_nav": strat.mark(md, d),
                         "benchmark_nav": bench.mark(md, d),
                         "strategy_cash": strat.cash,
                         "strategy_holdings": len(strat.shares),
                         "benchmark_holdings": len(bench.shares)})

    nav = pd.DataFrame(nav_rows).set_index("date")
    tr = pd.DataFrame(trades)
    metrics = compute_metrics(nav, strat, bench)
    return {"nav": nav, "trades": tr, "metrics": metrics}


def compute_metrics(nav: pd.DataFrame, strat: Book, bench: Book) -> dict:
    P = 252
    out = {}
    for name, col in (("strategy", "strategy_nav"), ("benchmark", "benchmark_nav")):
        s = nav[col]
        r = s.pct_change().dropna()
        n = len(s)
        out[name] = {
            "final_nav": float(s.iloc[-1]),
            "total_return": float(s.iloc[-1] / s.iloc[0] - 1),
            "cagr_geometric": float((s.iloc[-1] / s.iloc[0]) ** (P / n) - 1),
            "annualized_return_arithmetic": float(r.mean() * P),
            "annualized_vol": float(r.std(ddof=1) * np.sqrt(P)),
            "sharpe_no_rf": float(r.mean() / r.std(ddof=1) * np.sqrt(P)),
            "max_drawdown": float((s / s.cummax() - 1).min()),
            "trading_days": int(n),
        }
    sr = nav["strategy_nav"].pct_change()
    br = nav["benchmark_nav"].pct_change()
    ex = (sr - br).dropna()
    out["excess"] = {
        "annualized_excess_arithmetic": float(ex.mean() * P),
        "information_ratio": float(ex.mean() / ex.std(ddof=1) * np.sqrt(P)),
        "win_rate_vs_benchmark": float((ex > 0).mean()),
    }
    out["strategy_account"] = {"fees_paid": strat.fees_paid, "buys": strat.n_buys,
                               "sells": strat.n_sells, "blocked_attempts": strat.n_blocked}
    out["benchmark_account"] = {"fees_paid": bench.fees_paid, "buys": bench.n_buys,
                                "sells": bench.n_sells, "blocked_attempts": bench.n_blocked}
    return out