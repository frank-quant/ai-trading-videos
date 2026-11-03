#!/usr/bin/env python3
"""Validate key accounting, timing, output-consistency and offline HTML gates."""
from pathlib import Path
import base64
import hashlib
import json
import re
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    metrics = pd.read_csv(ROOT / "metrics.csv").set_index("scenario")
    nav = pd.read_csv(ROOT / "daily_nav.csv", parse_dates=["Date"])
    trades = pd.read_csv(ROOT / "trades.csv", parse_dates=["date", "signal_date"])
    signals = pd.read_csv(ROOT / "signals.csv", parse_dates=["signal_date", "execution_date"])
    checks = {}
    checks["four_metric_scenarios"] = len(metrics) == 4
    checks["nav_matches_final_metrics"] = all(
        abs(g.iloc[-1]["nav"] - metrics.loc[s, "final_nav"]) < 1e-6
        for s, g in nav.groupby("scenario")
    )
    checks["nav_identity"] = bool((
        nav["nav"] - nav["cash"] - nav["shares"] * nav["close_split_adjusted"]
    ).abs().max() < 1e-6)
    checks["fee_identity"] = bool((
        trades["fee"] - trades["gross_amount"] * trades["fee_rate"]
    ).abs().max() < 1e-6)
    non_benchmark = trades["signal_date"].notna()
    checks["trades_after_signals"] = bool((trades.loc[non_benchmark, "date"] > trades.loc[non_benchmark, "signal_date"]).all())
    checks["benchmark_one_buy_per_fee"] = all(
        len(g) == 1 and g.iloc[0]["side"] == "BUY"
        for _, g in trades.loc[trades["scenario"].str.startswith("SPY")].groupby("scenario")
    )
    checks["no_end_forced_liquidation"] = not bool((
        (trades["date"] == pd.Timestamp("2025-12-31")) & (trades["side"] == "SELL")
    ).any())
    executable = signals.loc[signals["executed_in_backtest"]]
    checks["72_executable_signals"] = len(executable) == 72
    checks["initial_signal_and_execution"] = (
        executable.iloc[0]["signal_date"] == pd.Timestamp("2019-12-31")
        and executable.iloc[0]["execution_date"] == pd.Timestamp("2020-01-02")
        and executable.iloc[0]["target"] == "SOXX"
    )
    checks["no_trade_count_46"] = int(executable["position_unchanged_no_trade"].sum()) == 46
    checks["rotation_51_trade_legs_per_fee"] = all(
        len(g) == 51 for _, g in trades.loc[trades["scenario"].str.startswith("rotation")].groupby("scenario")
    )
    html_text = (ROOT / "report.html").read_text(encoding="utf-8")
    match = re.search(r'<img src="data:image/png;base64,([A-Za-z0-9+/=]+)"', html_text)
    checks["html_embeds_chart"] = bool(match)
    if match:
        checks["embedded_chart_matches_png"] = base64.b64decode(match.group(1)) == (ROOT / "charts" / "nav_drawdown.png").read_bytes()
    checks["html_no_external_scripts_or_styles"] = "<script" not in html_text and "<link" not in html_text
    checks["html_no_template_placeholders"] = not bool(re.search(r"__[A-Z0-9]+__", html_text))
    md = (ROOT / "report.md").read_text(encoding="utf-8")
    checks["markdown_matches_key_final_values"] = all(
        f"${metrics.loc[s, 'final_nav']:,.2f}" in md for s in metrics.index
    )
    required = [
        "report.md", "report.html", "charts/nav_drawdown.png", "metrics.csv",
        "annual_returns.csv", "monthly_returns.csv", "signals.csv", "trades.csv",
        "dividend_cashflows.csv", "daily_nav.csv", "data_quality.json",
        "backtest.py", "download_data.py", "build_report.py", "requirements.txt",
        "data/SOXX_daily.csv", "data/SPY_daily.csv", "data/BIL_daily.csv",
    ]
    checks["required_files_present"] = all((ROOT / p).is_file() for p in required)
    result = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "files": {p: {"bytes": (ROOT / p).stat().st_size, "sha256": sha256(ROOT / p)} for p in required},
    }
    (ROOT / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": checks}, ensure_ascii=False, indent=2))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
