# -*- coding: utf-8 -*-
"""Working file (not a deliverable): build metrics.json from the final backtest.

  docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" \
      freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/_make_metrics.py \
      --epochs 300
"""
import argparse
import glob
import json
import os

import pandas as pd

from _ep004_metrics import TRAIN_S, VALID_S, VALID_E, stats, load_latest

KEYS = ["ann_return", "sharpe", "sortino", "calmar", "max_drawdown", "win_rate",
        "profit_factor", "turnover_per_year", "n_trades", "sharpe_net_of_costs"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, required=True)
    ap.add_argument("--userdir", default="/freqtrade/user_data")
    a = ap.parse_args()

    df, src = load_latest(a.userdir)
    df["close_date"] = pd.to_datetime(df["close_date"], utc=True)
    cd = df["close_date"]

    def seg(d, s, e, label):
        r = stats(d, s, e, label)
        # every number already comes from a backtest that charged 6 bps a side plus
        # funding, so the net-of-costs Sharpe IS the Sharpe.
        r["sharpe_net_of_costs"] = r["sharpe"]
        return {k: r[k] for k in KEYS}

    out = {
        "model": "XSTrendEnsemble",
        "seed": 20240701,
        # horizons are the chosen (post-hyperopt) values; the composite is the
        # equal-weight mean of these four cross-sectional percentiles, then
        # smoothed with a 10-day rolling mean
        "factors": ["xs_rank(momentum_14d)",
                    "xs_rank((close/SMA_25d - 1) / realised_vol_25d)",
                    "xs_rank((close/SMA_45d - 1) / realised_vol_45d)",
                    "xs_rank(position_in_25d_high_low_range)"],
        "timeframe": "4h",
        "epochs_used": a.epochs,
        "strategy_family": "cross-sectional",
        "turnover_control": ("rolling-mean smoothing of the composite score "
                             "(smooth_days) as the primary control, plus a rank "
                             "hysteresis band (exit_buffer) and a max holding "
                             "period (max_hold_days) that recycles positions"),
        "fee_bps": 6.0,
        "slippage_bps": 0.0,
        "funding_included": True,
        "train": seg(df.loc[cd < VALID_S], TRAIN_S, VALID_S, "train"),
        "valid": seg(df.loc[(cd >= VALID_S) & (cd <= VALID_E)], VALID_S, VALID_E, "valid"),
    }
    p = os.path.join(a.userdir, "metrics.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
