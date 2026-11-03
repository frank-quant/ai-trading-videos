#!/usr/bin/env python3
"""Deterministic SOXX/SPY/BIL monthly rotation backtest, 2020-2025.

Run from any directory: python backtest.py
Inputs are the included data/*_daily.csv files. No network access is used.
"""
from pathlib import Path
import json
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INITIAL_CAPITAL = 100_000.0
START = pd.Timestamp("2020-01-02")
END = pd.Timestamp("2025-12-31")
LOOKBACK = 60
FEES = (0.001, 0.002)
TICKERS = ("SOXX", "SPY", "BIL")


def load_data():
    frames = {}
    quality = {"provider": "Yahoo Finance", "tickers": {}, "checks": {}}
    for ticker in TICKERS:
        df = pd.read_csv(DATA / f"{ticker}_daily.csv", parse_dates=["Date"]).set_index("Date").sort_index()
        frames[ticker] = df
        quality["tickers"][ticker] = {
            "rows": int(len(df)),
            "first_date": str(df.index.min().date()),
            "last_date": str(df.index.max().date()),
            "duplicate_dates": int(df.index.duplicated().sum()),
            "missing_critical_fields": int(df[["Open", "Close", "Adj Close"]].isna().sum().sum()),
            "nonpositive_prices": int((df[["Open", "Close", "Adj Close"]] <= 0).sum().sum()),
            "dividend_events_2019_2025": int((df["Dividends"] > 0).sum()),
            "dividend_events_backtest": int((df.loc[START:END, "Dividends"] > 0).sum()),
            "split_events": {str(k.date()): float(v) for k, v in df.loc[df["Stock Splits"] > 0, "Stock Splits"].items()},
        }
    common = frames["SOXX"].index
    for ticker in TICKERS[1:]:
        common = common.intersection(frames[ticker].index)
    common = common[(common >= pd.Timestamp("2019-01-01")) & (common <= END)]
    for ticker in TICKERS:
        frames[ticker] = frames[ticker].loc[common].copy()
    quality["checks"] = {
        "identical_calendars": all(frames[t].index.equals(common) for t in TICKERS),
        "no_duplicate_dates": all(frames[t].index.duplicated().sum() == 0 for t in TICKERS),
        "no_missing_critical_fields": all(frames[t][["Open", "Close", "Adj Close"]].notna().all().all() for t in TICKERS),
        "positive_prices": all((frames[t][["Open", "Close", "Adj Close"]] > 0).all().all() for t in TICKERS),
        "covers_initial_signal": pd.Timestamp("2019-12-31") in common,
        "covers_backtest": START in common and END in common,
        "adequate_60_session_warmup": int(common.get_loc(pd.Timestamp("2019-12-31"))) >= LOOKBACK,
    }
    if not all(quality["checks"].values()):
        raise ValueError(f"Data quality check failed: {quality['checks']}")
    return frames, common, quality


def build_signals(frames, calendar):
    rows = []
    month_ends = calendar.to_series().groupby(calendar.to_period("M")).max()
    for signal_date in month_ends[month_ends >= pd.Timestamp("2019-12-31")]:
        loc = calendar.get_loc(signal_date)
        if loc < LOOKBACK:
            continue
        base_date = calendar[loc - LOOKBACK]
        soxx_ret = frames["SOXX"].at[signal_date, "Adj Close"] / frames["SOXX"].at[base_date, "Adj Close"] - 1.0
        spy_ret = frames["SPY"].at[signal_date, "Adj Close"] / frames["SPY"].at[base_date, "Adj Close"] - 1.0
        if soxx_ret == spy_ret and soxx_ret > 0:
            target = "SPY"
            selection_rule = "tie_positive_choose_SPY"
        elif soxx_ret > spy_ret:
            target = "SOXX" if soxx_ret > 0 else "BIL"
            selection_rule = "SOXX_higher_positive" if target == "SOXX" else "best_return_nonpositive"
        elif spy_ret > soxx_ret:
            target = "SPY" if spy_ret > 0 else "BIL"
            selection_rule = "SPY_higher_positive" if target == "SPY" else "best_return_nonpositive"
        else:
            target = "BIL"
            selection_rule = "tie_nonpositive"
        execution_date = calendar[loc + 1] if loc + 1 < len(calendar) else pd.NaT
        executable = pd.notna(execution_date) and START <= execution_date <= END
        rows.append({
            "signal_date": signal_date,
            "lookback_start_date": base_date,
            "lookback_sessions": LOOKBACK,
            "SOXX_total_return": soxx_ret,
            "SPY_total_return": spy_ret,
            "target": target,
            "selection_rule": selection_rule,
            "execution_date": execution_date,
            "executed_in_backtest": bool(executable),
        })
    signals = pd.DataFrame(rows)
    prior = None
    changed = []
    for row in signals.itertuples():
        if row.executed_in_backtest:
            changed.append(prior is not None and row.target == prior)
            prior = row.target
        else:
            changed.append(False)
    signals["position_unchanged_no_trade"] = changed
    return signals


def make_trade(trades, scenario, fee_rate, date, signal_date, side, ticker, price, shares, fee, cash_after, target):
    gross = price * shares
    trades.append({
        "scenario": scenario,
        "fee_rate": fee_rate,
        "date": date,
        "signal_date": signal_date,
        "side": side,
        "ticker": ticker,
        "price_split_adjusted": price,
        "shares": shares,
        "gross_amount": gross,
        "fee": fee,
        "net_cash_flow": -gross - fee if side == "BUY" else gross - fee,
        "cash_after": cash_after,
        "target_after_trade": target,
    })


def simulate(frames, calendar, fee_rate, signals=None, benchmark=False):
    scenario = ("SPY_buy_hold" if benchmark else "rotation") + f"_fee_{fee_rate:.3f}"
    execution_map = {}
    if not benchmark:
        executable = signals.loc[signals["executed_in_backtest"]]
        execution_map = {row.execution_date: row for row in executable.itertuples()}
    sessions = calendar[(calendar >= START) & (calendar <= END)]
    cash = INITIAL_CAPITAL
    holding = None
    shares = 0.0
    trades, dividend_rows, nav_rows = [], [], []
    for date in sessions:
        dividend_cash = 0.0
        # Ex-date entitlement comes from the prior close position; credit before any open trade.
        if holding is not None:
            dividend_per_share = float(frames[holding].at[date, "Dividends"])
            if dividend_per_share > 0:
                dividend_cash = shares * dividend_per_share
                cash += dividend_cash
                dividend_rows.append({
                    "scenario": scenario, "fee_rate": fee_rate, "date": date,
                    "ticker": holding, "shares": shares,
                    "dividend_per_share_split_adjusted": dividend_per_share,
                    "cash_dividend": dividend_cash, "cash_after": cash,
                })
        if benchmark and date == START:
            signal_date = pd.NaT
            target = "SPY"
        elif not benchmark and date in execution_map:
            signal_row = execution_map[date]
            signal_date = signal_row.signal_date
            target = signal_row.target
        else:
            target = holding
        if target is not None and target != holding:
            if holding is not None:
                price = float(frames[holding].at[date, "Open"])
                gross = shares * price
                fee = gross * fee_rate
                cash += gross - fee
                make_trade(trades, scenario, fee_rate, date, signal_date, "SELL", holding, price, shares, fee, cash, target)
                shares = 0.0
                holding = None
            price = float(frames[target].at[date, "Open"])
            shares = cash / (price * (1.0 + fee_rate))
            gross = shares * price
            fee = gross * fee_rate
            cash -= gross + fee
            if abs(cash) < 1e-7:
                cash = 0.0
            holding = target
            make_trade(trades, scenario, fee_rate, date, signal_date, "BUY", holding, price, shares, fee, cash, target)
        close = float(frames[holding].at[date, "Close"]) if holding is not None else 0.0
        nav = cash + shares * close
        nav_rows.append({
            "Date": date, "scenario": scenario, "fee_rate": fee_rate,
            "holding": holding, "shares": shares, "close_split_adjusted": close,
            "cash": cash, "dividend_cash": dividend_cash, "nav": nav,
        })
    nav = pd.DataFrame(nav_rows).set_index("Date")
    nav["daily_return"] = nav["nav"].pct_change()
    nav.iloc[0, nav.columns.get_loc("daily_return")] = nav.iloc[0]["nav"] / INITIAL_CAPITAL - 1.0
    running_peak = np.maximum.accumulate(np.r_[INITIAL_CAPITAL, nav["nav"].to_numpy()])[1:]
    nav["running_peak"] = running_peak
    nav["drawdown"] = nav["nav"] / nav["running_peak"] - 1.0
    return nav, pd.DataFrame(trades), pd.DataFrame(dividend_rows)


def performance_metrics(nav, trades, dividends):
    end_nav = float(nav["nav"].iloc[-1])
    years = (nav.index[-1] - nav.index[0]).days / 365.2425
    rets = nav["daily_return"]
    total_return = end_nav / INITIAL_CAPITAL - 1.0
    cagr = (end_nav / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    vol = float(rets.std(ddof=1) * math.sqrt(252))
    sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(252)) if rets.std(ddof=1) > 0 else np.nan
    trough = nav["drawdown"].idxmin()
    max_dd = float(nav.at[trough, "drawdown"])
    peak_candidates = nav.loc[:trough].loc[nav.loc[:trough, "nav"] == nav.at[trough, "running_peak"]]
    peak_date = peak_candidates.index[-1] if len(peak_candidates) else nav.index[0]
    recovery = nav.loc[trough:].loc[nav.loc[trough:, "nav"] >= nav.at[trough, "running_peak"]]
    recovery_date = recovery.index[0] if len(recovery) else pd.NaT
    exposures = nav["holding"].value_counts(normalize=True).to_dict()
    return {
        "scenario": str(nav["scenario"].iloc[0]),
        "fee_rate": float(nav["fee_rate"].iloc[0]),
        "start_date": str(nav.index[0].date()),
        "end_date": str(nav.index[-1].date()),
        "initial_capital": INITIAL_CAPITAL,
        "final_nav": end_nav,
        "total_return": total_return,
        "CAGR": cagr,
        "annualized_volatility": vol,
        "Sharpe_rf0": sharpe,
        "max_drawdown": max_dd,
        "max_drawdown_peak_date": str(peak_date.date()),
        "max_drawdown_trough_date": str(trough.date()),
        "max_drawdown_recovery_date": str(recovery_date.date()) if pd.notna(recovery_date) else "not_recovered_by_end",
        "Calmar": cagr / abs(max_dd) if max_dd < 0 else np.nan,
        "trade_legs": int(len(trades)),
        "switches": int((trades["side"] == "SELL").sum()) if len(trades) else 0,
        "total_fees": float(trades["fee"].sum()) if len(trades) else 0.0,
        "dividend_cash_received": float(dividends["cash_dividend"].sum()) if len(dividends) else 0.0,
        "ending_cash": float(nav["cash"].iloc[-1]),
        "SOXX_exposure_days_pct": float(exposures.get("SOXX", 0.0)),
        "SPY_exposure_days_pct": float(exposures.get("SPY", 0.0)),
        "BIL_exposure_days_pct": float(exposures.get("BIL", 0.0)),
    }


def periodic_returns(all_nav, frequency):
    rows = []
    for scenario, nav in all_nav.items():
        period_end_nav = nav["nav"].resample(frequency).last()
        period_ret = period_end_nav.pct_change()
        period_ret.iloc[0] = period_end_nav.iloc[0] / INITIAL_CAPITAL - 1.0
        for date, value in period_ret.items():
            rows.append({"scenario": scenario, "period_end": date, "return": value})
    return pd.DataFrame(rows)


def cross_validate_connector(quality):
    raw = DATA / "raw"
    if not raw.exists():
        quality["connector_cross_validation"] = {"status": "not_available; direct Yahoo inputs used"}
        return
    result = {}
    for ticker in TICKERS:
        direct = pd.read_csv(DATA / f"{ticker}_daily.csv", parse_dates=["Date"]).set_index("Date")
        parts = [pd.read_csv(p, parse_dates=["Date"]) for p in raw.glob(f"{ticker}_2*.csv")]
        if not parts:
            continue
        connector = pd.concat(parts)
        connector["Date"] = connector["Date"].dt.tz_convert(None).dt.normalize()
        connector = connector.set_index("Date").sort_index()
        joined = direct.join(connector[["Close", "Dividends"]], rsuffix="_connector", how="inner")
        result[ticker] = {
            "overlap_rows": int(len(joined)),
            "max_abs_adj_close_difference": float((joined["Adj Close"] - joined["Close_connector"]).abs().max()),
            "max_abs_dividend_difference": float((joined["Dividends"] - joined["Dividends_connector"]).abs().max()),
        }
    quality["connector_cross_validation"] = result


def main():
    frames, calendar, quality = load_data()
    signals = build_signals(frames, calendar)
    all_nav, all_trades, all_dividends, metrics = {}, [], [], []
    for fee in FEES:
        nav, trades, dividends = simulate(frames, calendar, fee, signals=signals)
        key = f"rotation_fee_{fee:.3f}"
        all_nav[key] = nav
        all_trades.append(trades)
        all_dividends.append(dividends)
        metrics.append(performance_metrics(nav, trades, dividends))
        bench_nav, bench_trades, bench_dividends = simulate(frames, calendar, fee, benchmark=True)
        bench_key = f"SPY_buy_hold_fee_{fee:.3f}"
        all_nav[bench_key] = bench_nav
        all_trades.append(bench_trades)
        all_dividends.append(bench_dividends)
        metrics.append(performance_metrics(bench_nav, bench_trades, bench_dividends))
    metrics_df = pd.DataFrame(metrics)
    trades_df = pd.concat(all_trades, ignore_index=True)
    dividends_df = pd.concat(all_dividends, ignore_index=True)
    nav_df = pd.concat(all_nav.values()).reset_index()
    annual = periodic_returns(all_nav, "YE")
    monthly = periodic_returns(all_nav, "ME")

    # Deterministic consistency gates.
    assert len(signals.loc[signals["executed_in_backtest"]]) == 72
    assert signals.iloc[0]["signal_date"] == pd.Timestamp("2019-12-31")
    assert signals.iloc[0]["execution_date"] == START
    assert signals.iloc[-1]["signal_date"] == END and not signals.iloc[-1]["executed_in_backtest"]
    assert np.isfinite(metrics_df[["final_nav", "total_return", "CAGR", "max_drawdown"]].to_numpy()).all()
    assert (trades_df["fee"] >= 0).all() and (nav_df["nav"] > 0).all()
    assert (nav_df["cash"] >= -1e-7).all()
    for key, nav in all_nav.items():
        expected_legs = 1 if key.startswith("SPY") else None
        if expected_legs is not None:
            assert len(trades_df.loc[trades_df["scenario"] == key]) == expected_legs
        assert abs(nav["nav"].iloc[-1] - (nav["cash"].iloc[-1] + nav["shares"].iloc[-1] * nav["close_split_adjusted"].iloc[-1])) < 1e-6

    signals.to_csv(ROOT / "signals.csv", index=False, date_format="%Y-%m-%d", float_format="%.12f")
    trades_df.to_csv(ROOT / "trades.csv", index=False, date_format="%Y-%m-%d", float_format="%.12f")
    dividends_df.to_csv(ROOT / "dividend_cashflows.csv", index=False, date_format="%Y-%m-%d", float_format="%.12f")
    nav_df.to_csv(ROOT / "daily_nav.csv", index=False, date_format="%Y-%m-%d", float_format="%.12f")
    metrics_df.to_csv(ROOT / "metrics.csv", index=False, float_format="%.12f")
    annual.to_csv(ROOT / "annual_returns.csv", index=False, date_format="%Y-%m-%d", float_format="%.12f")
    monthly.to_csv(ROOT / "monthly_returns.csv", index=False, date_format="%Y-%m-%d", float_format="%.12f")
    quality["backtest"] = {
        "start": str(START.date()), "end": str(END.date()), "sessions": int(len(all_nav["rotation_fee_0.001"])),
        "initial_signal_date": "2019-12-31", "initial_lookback_start": str(signals.iloc[0]["lookback_start_date"].date()),
        "initial_target": signals.iloc[0]["target"],
        "executable_signal_count": int(signals["executed_in_backtest"].sum()),
        "no_trade_signal_count": int(signals.loc[signals["executed_in_backtest"], "position_unchanged_no_trade"].sum()),
        "december_2025_signal_excluded_from_trading": True,
        "end_liquidation": False,
    }
    quality["validation_assertions"] = "all passed"
    cross_validate_connector(quality)
    (ROOT / "data_quality.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    print(metrics_df[["scenario", "final_nav", "total_return", "CAGR", "annualized_volatility", "Sharpe_rf0", "max_drawdown", "trade_legs", "total_fees", "dividend_cash_received"]].to_string(index=False))
    print("\nInitial signal:")
    print(signals.iloc[0].to_string())
    print("\nData quality:", quality["backtest"])


if __name__ == "__main__":
    main()
