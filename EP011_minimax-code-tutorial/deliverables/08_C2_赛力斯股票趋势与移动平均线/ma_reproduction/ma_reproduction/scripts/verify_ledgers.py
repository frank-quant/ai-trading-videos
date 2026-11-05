"""Independent verification of the two ledgers (rewritten with correct relations).

Ledger row semantics:
  * row.date          -> the trading day the row describes
  * row.signal        -> the crossover signal produced by THIS day's close (known only after close)
  * row.action        -> what happened at THIS day's open (BUY / SELL / IGNORED / NONE)
  * therefore an action on row i is caused by the signal on row i-1 (next-day-open execution)
  * row.shares        -> END-of-day holding (0 on a SELL row)
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEE_RATE = 0.00075
INITIAL = 1_000_000.0
WARMUP_ROWS = 59


def read(fname):
    with (ROOT / fname).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    prices = read("prices.csv")
    pmap = {p["date"]: p for p in prices}
    dates = [p["date"] for p in prices]
    rep = {}

    for fname, rate in (("Ledger_Gross.csv", 0.0), ("Ledger.csv", FEE_RATE)):
        rows = read(fname)
        v = {"rows": len(rows),
             "date_axis_matches_prices": [r["date"] for r in rows] == dates,
             "nav_equals_cash_plus_position": all(
                 abs(float(r["cash"]) + float(r["position_value"]) - float(r["nav"])) < 0.01
                 for r in rows),
             "warmup_row_count": sum(1 for r in rows if r["is_warmup"] == "1"),
             "warmup_flat_no_action": all(
                 r["is_warmup"] == "1" and r["action"] == "NONE" and r["exec_date"] == ""
                 and float(r["shares"]) == 0.0 and abs(float(r["nav"]) - INITIAL) < 0.01
                 and float(r["fee"]) == 0.0 for r in rows[:WARMUP_ROWS]),
             }

        bad_chain, bad_price, bad_fee, bad_cash, bad_state = [], [], [], [], []
        prev_shares = 0.0
        for i, r in enumerate(rows):
            act = r["action"]
            if act in ("BUY", "SELL"):
                # (1) execution must be exactly one trading day after the signal bar
                if i == 0:
                    bad_chain.append((r["date"], "no prior bar"))
                else:
                    want = "golden_cross" if act == "BUY" else "death_cross"
                    if rows[i - 1]["signal"] != want:
                        bad_chain.append((r["date"], f"prev signal={rows[i-1]['signal']} want={want}"))
                    if r["exec_date"] != r["date"]:
                        bad_chain.append((r["date"], f"exec_date={r['exec_date']}"))
                # (2) fill price must equal that day's OPEN
                if abs(float(r["fill_price"]) - float(pmap[r["date"]]["open"])) > 1e-6:
                    bad_price.append(r["date"])
                # (3) fee = notional * rate, notional uses shares traded on this bar
                traded = prev_shares if act == "SELL" else float(r["shares"])
                notional = traded * float(r["fill_price"])
                if abs(float(r["fee"]) - notional * rate) > 0.02:
                    bad_fee.append((r["date"], float(r["fee"]), round(notional * rate, 4)))
                # (4) position state machine
                if act == "BUY":
                    if prev_shares != 0.0:
                        bad_state.append((r["date"], "buy while holding"))
                    if abs(float(r["cash"])) > 0.01:
                        bad_cash.append((r["date"], float(r["cash"])))
                    if float(r["shares"]) <= 0:
                        bad_state.append((r["date"], "non-positive shares"))
                else:
                    if prev_shares <= 0.0:
                        bad_state.append((r["date"], "sell while flat"))
                    if float(r["shares"]) != 0.0:
                        bad_state.append((r["date"], "sell leaves shares"))
            elif act == "IGNORED":
                pass
            prev_shares = float(r["shares"])

        v["exec_chain_violations"] = bad_chain
        v["fill_price_equals_open_violations"] = bad_price
        v["fee_formula_violations"] = bad_fee
        v["buy_leaves_zero_cash_violations"] = bad_cash
        v["position_state_violations"] = bad_state
        v["signals_in_ledger"] = sum(1 for r in rows if r["signal"] != "none")
        v["actions"] = {}
        for r in rows:
            v["actions"][r["action"]] = v["actions"].get(r["action"], 0) + 1
        # every recorded signal must be followed by an execution on the next bar (or be ignored)
        v["signal_rows"] = [(i, r["date"], r["signal"]) for i, r in enumerate(rows)
                            if r["signal"] != "none"]
        v["signals_without_following_exec"] = [
            (d, s) for i, d, s in v["signal_rows"]
            if i + 1 < len(rows) and rows[i + 1]["action"] == "NONE"
            and rows[i + 1]["exec_date"] == ""]
        v["last_row"] = {k: rows[-1][k] for k in
                         ("date", "signal", "action", "exec_date", "shares",
                          "position_value", "cash", "fee", "cum_fee", "nav", "cum_return")}
        v["end_state_flat"] = float(rows[-1]["shares"]) == 0.0
        v["end_cash_equals_nav"] = abs(float(rows[-1]["cash"]) - float(rows[-1]["nav"])) < 0.01
        v["no_forced_liquidation_at_end"] = rows[-1]["action"] not in ("SELL",)
        rep[fname] = v

    g = read("Ledger_Gross.csv")
    f = read("Ledger.csv")
    rep["fee_vs_gross"] = {
        "nav_gross_final": float(g[-1]["nav"]),
        "nav_fee_final": float(f[-1]["nav"]),
        "fee_version_never_exceeds_gross": all(
            float(f[i]["nav"]) <= float(g[i]["nav"]) + 1e-6 for i in range(len(g))),
        "total_fees_fee_ledger": float(f[-1]["cum_fee"]),
        "total_fees_gross_ledger": float(g[-1]["cum_fee"]),
        "final_gap": float(g[-1]["nav"]) - float(f[-1]["nav"]),
    }
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
