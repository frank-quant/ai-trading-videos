# -*- coding: utf-8 -*-
"""
EP004 metrics.json builder (working file, not a strategy).

Reads two freqtrade backtest-result zips (TRAIN and VALID runs) and writes
metrics.json using the SAME Sharpe definition as EP004ValidLoss:
daily PnL summed per calendar day / starting wallet, non-trading days = 0,
annualised by sqrt(365). All figures are net of the 0.06%-per-side fee
(the backtests include it), so sharpe == sharpe_net_of_costs by construction.

Run inside the freqtrade container:
  docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" \
    freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/compute_metrics.py \
    --train <train_result.zip> --valid <valid_result.zip>
"""
import argparse
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

WALLET = 10000.0


def load_trades(zip_path: str) -> pd.DataFrame:
    zp = Path(zip_path)
    with zipfile.ZipFile(zp) as z:
        inner = zp.with_suffix(".json").name
        with z.open(inner) as f:
            data = json.load(f)
    strat = list(data["strategy"].keys())[0]
    return pd.DataFrame(data["strategy"][strat]["trades"])


def segment_metrics(trades: pd.DataFrame, start: str, end: str, years: float) -> dict:
    pnl = pd.to_numeric(trades["profit_abs"], errors="coerce").fillna(0.0)
    day = pd.to_datetime(trades["close_date"], utc=True).dt.floor("D")
    daily = pnl.groupby(day).sum() / WALLET
    idx = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), freq="D")
    daily = daily.reindex(idx, fill_value=0.0)

    mean, sd = float(daily.mean()), float(daily.std())
    sharpe = mean / sd * np.sqrt(365.0) if sd > 0 else 0.0
    downside = float(np.sqrt((np.minimum(daily, 0.0) ** 2).mean()))
    sortino = mean / downside * np.sqrt(365.0) if downside > 0 else 0.0
    ann_return = mean * 365.0

    equity = daily.cumsum()  # on starting-wallet basis, consistent with Sharpe defn
    dd = float((equity.cummax() - equity).max())
    calmar = ann_return / dd if dd > 0 else 0.0

    wins = trades.loc[trades["profit_abs"] > 0, "profit_abs"]
    losses = trades.loc[trades["profit_abs"] < 0, "profit_abs"]
    win_rate = float(len(wins)) / len(trades) if len(trades) else 0.0
    profit_factor = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else float("inf")

    # one round trip = entry notional + exit notional ~= 2 * stake
    notional = 2.0 * pd.to_numeric(trades["stake_amount"], errors="coerce").fillna(0.0).sum()
    turnover_per_year = notional / WALLET / years

    return {
        "ann_return": round(ann_return, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "max_drawdown": round(dd, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "turnover_per_year": round(turnover_per_year, 2),
        "n_trades": int(len(trades)),
        "sharpe_net_of_costs": round(sharpe, 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--valid", required=True)
    ap.add_argument("--out", default="/freqtrade/user_data/metrics.json")
    a = ap.parse_args()

    tr = load_trades(a.train)
    va = load_trades(a.valid)
    n_long = int((va["is_short"] == False).sum())  # noqa: E712
    n_short = int((va["is_short"] == True).sum())  # noqa: E712
    print(f"[metrics] valid trades: {len(va)} (long {n_long} / short {n_short})")

    out = {
        "model": "XSRiskMomentum",
        "seed": 42,
        "factors": ["risk_adjusted_momentum (N-day return / realized vol, skip recent day)"],
        "timeframe": "4h",
        "epochs_used": 300,
        "strategy_family": "cross-sectional",
        "turnover_control": "rank hysteresis (exit_buffer) + min holding period (min_hold bars); 4h rebalance",
        "fee_bps": 6, "slippage_bps": 0, "funding_included": True,
        "train": segment_metrics(tr, "2021-01-01", "2024-06-30", 3.4959),
        "valid": segment_metrics(va, "2024-07-01", "2025-06-30", 0.9973),
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[metrics] wrote {a.out}")
    print(json.dumps({"train": out["train"], "valid": out["valid"]}, indent=2))


if __name__ == "__main__":
    main()
