"""Teaching backtest: SMA5 x SMA20 crossover, long-only, next-day-open execution.

Rules (as specified):
  * golden cross on bar t  -> buy  100% of NAV at the OPEN of bar t+1
  * death  cross on bar t  -> sell 100% of position at the OPEN of bar t+1
  * no shorting; a death cross while flat is recorded but not traded
  * no trades during the warmup window (first 59 bars)
  * no forced liquidation at the end of the sample -> the final position stays open
  * Ledger_Gross = zero cost; Ledger = 0.075% one-way, no stamp duty, no transfer fee

Prices are the forward-adjusted OHLC from prices.csv; signals come from the
validated signals.csv (signal_family = sma5_sma20) and are re-verified here
against indicators.csv before any trade is taken.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INITIAL_CAPITAL = 1_000_000.0
FEE_RATE = 0.00075          # one-way, 0.075%
WARMUP_ROWS = 59


def load_prices():
    with (ROOT / "prices.csv").open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_signals():
    with (ROOT / "signals.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["signal_family"] == "sma5_sma20"]


def load_indicators():
    with (ROOT / "indicators.csv").open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def verify_signals(indicators, signals):
    """Re-verify every signal is a genuine sign flip on the stated bar."""
    idx = {r["date"]: i for i, r in enumerate(indicators)}
    for s in signals:
        i = idx[s["date"]]
        if i == 0:
            raise AssertionError(f"signal on first bar: {s['date']}")
        prev = float(s["spread_prev"])
        now = float(s["spread_now"])
        if s["signal_type"] == "golden_cross":
            assert prev <= 0 < now, f"{s['date']} not a golden cross"
        else:
            assert prev >= 0 > now, f"{s['date']} not a death cross"
        assert int(s["row_index"]) == i + 1, f"row_index mismatch at {s['date']}"
        assert int(s["row_index"]) > WARMUP_ROWS, f"signal inside warmup: {s['date']}"
    return len(signals)


def run(prices, signals_by_date, fee_rate):
    n = len(prices)
    dates = [p["date"] for p in prices]
    opens = [float(p["open"]) for p in prices]
    closes = [float(p["close"]) for p in prices]

    sig_at = {}
    for i, d in enumerate(dates):
        if d in signals_by_date:
            sig_at[i] = signals_by_date[d]

    cash = INITIAL_CAPITAL
    shares = 0.0
    cum_fee = 0.0
    pending = None          # (signal_type, signal_date)
    navs = []
    rows_out = []
    trades = []             # round trips
    open_trade = None

    for i in range(n):
        is_warm = i < WARMUP_ROWS
        sig = sig_at.get(i)
        exec_date = ""
        fill_price = ""
        action = "NONE"
        fee = 0.0

        # ---- execute a pending order at today's open ----
        if pending is not None and not is_warm:
            sig_type, sig_date = pending
            P = opens[i]
            if sig_type == "golden_cross" and shares == 0.0:
                if fee_rate == 0.0:
                    shares = cash / P
                else:
                    shares = cash / (P * (1.0 + fee_rate))
                notional = shares * P
                fee = notional * fee_rate
                cash -= notional + fee
                action = "BUY"
                open_trade = {"signal_date": sig_date, "entry_date": dates[i],
                              "entry_price": P, "shares": shares, "entry_fee": fee}
            elif sig_type == "death_cross" and shares > 0.0:
                notional = shares * P
                fee = notional * fee_rate
                cash += notional - fee
                action = "SELL"
                if open_trade:
                    open_trade.update({"exit_date": dates[i], "exit_price": P,
                                        "exit_fee": fee,
                                        "return": (P / open_trade["entry_price"]) - 1.0,
                                        "days": i - next(j for j, d in enumerate(dates)
                                                         if d == open_trade["entry_date"])})
                    trades.append(open_trade)
                    open_trade = None
                shares = 0.0
            else:
                action = "IGNORED"       # signal direction does not match the position
            exec_date = dates[i]
            fill_price = f"{P:.4f}"
            pending = None
        elif pending is not None and is_warm:
            pending = None              # warmup must not trade

        # ---- record today's signal (signal is known only after today's close) ----
        signal_label = "none"
        if sig is not None:
            signal_label = sig
            if not is_warm:
                pending = (sig, dates[i])

        cum_fee += fee
        pos_value = shares * closes[i]
        nav = cash + pos_value
        navs.append(nav)

        rows_out.append({
            "date": dates[i], "is_warmup": "1" if is_warm else "0",
            "open": f"{opens[i]:.4f}", "close": f"{closes[i]:.4f}",
            "signal": signal_label,
            "action": action,
            "exec_date": exec_date,
            "fill_price": fill_price,
            "shares": f"{shares:.6f}",
            "position_value": f"{pos_value:.4f}",
            "cash": f"{cash:.4f}",
            "fee": f"{fee:.4f}",
            "cum_fee": f"{cum_fee:.4f}",
            "nav": f"{nav:.4f}",
        })

    # ---- daily return / cumulative return / drawdown ----
    peak = navs[0]
    for i, r in enumerate(rows_out):
        prev_nav = navs[i - 1] if i > 0 else INITIAL_CAPITAL
        r["daily_return"] = f"{(navs[i] / prev_nav - 1.0):.8f}"
        r["cum_return"] = f"{(navs[i] / INITIAL_CAPITAL - 1.0):.8f}"
        peak = max(peak, navs[i])
        r["peak_nav"] = f"{peak:.4f}"
        r["drawdown"] = f"{(navs[i] / peak - 1.0):.8f}"

    cols = ["date", "is_warmup", "open", "close", "signal", "action", "exec_date",
            "fill_price", "shares", "position_value", "cash", "fee", "cum_fee",
            "nav", "daily_return", "cum_return", "peak_nav", "drawdown"]
    return rows_out, cols, trades, open_trade, pending


def summarize(rows, trades, open_trade, pending, label):
    navs = [float(r["nav"]) for r in rows]
    daily = [float(r["daily_return"]) for r in rows]
    peak = navs[0]
    mdd = 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    # 年化口径：N 个净值观测点 = N-1 个日收益期 → 指数 252/(N-1)
    ann = (navs[-1] / navs[0]) ** (252 / (len(navs) - 1)) - 1
    vol = (sum((x - sum(daily) / len(daily)) ** 2 for x in daily) / (len(daily) - 1)) ** 0.5 * (252 ** 0.5)
    closed = trades
    wins = [t for t in closed if t["return"] > 0]
    return {
        "ledger": label,
        "rows": len(rows),
        "first_date": rows[0]["date"], "last_date": rows[-1]["date"],
        "initial_capital": INITIAL_CAPITAL,
        "final_nav": navs[-1],
        "final_cum_return": navs[-1] / INITIAL_CAPITAL - 1,
        "annualized_return": ann,
        "annualized_vol": vol,
        "max_drawdown": mdd,
        "closed_round_trips": len(closed),
        "win_rate": (len(wins) / len(closed)) if closed else None,
        "avg_win": (sum(t["return"] for t in wins) / len(wins)) if wins else None,
        "avg_loss": (sum(t["return"] for t in closed if t["return"] <= 0) /
                     len([t for t in closed if t["return"] <= 0])) if len(closed) != len(wins) else None,
        "total_fees": float(rows[-1]["cum_fee"]),
        "total_fee_drag": float(rows[-1]["cum_fee"]) / INITIAL_CAPITAL,
        "still_open_position": open_trade,
        "unexecuted_pending_signal": pending,
    }


def main():
    prices = load_prices()
    indicators = load_indicators()
    signals = load_signals()
    n_sig = verify_signals(indicators, signals)
    signals_by_date = {s["date"]: s["signal_type"] for s in signals}

    out = {}
    for label, rate, fname in (("Ledger_Gross", 0.0, "Ledger_Gross.csv"),
                                ("Ledger", FEE_RATE, "Ledger.csv")):
        rows, cols, trades, open_trade, pending = run(prices, signals_by_date, rate)
        with (ROOT / fname).open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        out[label] = summarize(rows, trades, open_trade, pending, label)
        out[label]["file"] = fname
        out[label]["round_trips"] = trades

    (ROOT / "raw").mkdir(exist_ok=True)
    (ROOT / "raw" / "backtest_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "round_trips"}
                      for k, v in out.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
