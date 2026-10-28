#!/usr/bin/env python3
"""SOXX/SPY/BIL 月末 60 交易日总回报轮动回测。

离线复现：python backtest.py
输入：data/*_daily.csv（由 fetch_data.py 下载并随结果一同交付）。
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INITIAL_CAPITAL = 100_000.0
START = pd.Timestamp("2020-01-02")
END = pd.Timestamp("2025-12-31")
LOOKBACK = 60
BASE_FEE = 0.001
DOUBLE_FEE = 0.002
TICKERS = ("SOXX", "SPY", "BIL")


@dataclass
class Result:
    key: str
    label: str
    fee_rate: float
    daily: pd.DataFrame
    trades: pd.DataFrame
    dividends: pd.DataFrame
    metrics: dict


def load_market_data() -> dict[str, pd.DataFrame]:
    market = {}
    for ticker in TICKERS:
        frame = pd.read_csv(DATA / f"{ticker}_daily.csv", parse_dates=["date"])
        frame = frame.set_index("date").sort_index()
        numeric = ["open", "high", "low", "close", "adj_close", "volume", "dividend"]
        frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
        market[ticker] = frame
    return market


def select_target(soxx_return: float, spy_return: float) -> str:
    """正收益较高者；相等且为正选 SPY；否则 BIL。"""
    if spy_return >= soxx_return and spy_return > 0:
        return "SPY"
    if soxx_return > spy_return and soxx_return > 0:
        return "SOXX"
    return "BIL"


def build_signals(market: dict[str, pd.DataFrame], calendar: pd.DatetimeIndex) -> pd.DataFrame:
    adj = pd.DataFrame({ticker: market[ticker]["adj_close"] for ticker in ("SOXX", "SPY")})
    month_ends = adj.groupby(adj.index.to_period("M")).tail(1).index
    records = []
    for signal_date in month_ends:
        if not (pd.Timestamp("2019-12-01") <= signal_date <= pd.Timestamp("2025-11-30")):
            continue
        loc = calendar.get_loc(signal_date)
        if loc < LOOKBACK or loc + 1 >= len(calendar):
            raise AssertionError(f"信号数据不足或没有次交易日: {signal_date}")
        start_date = calendar[loc - LOOKBACK]
        soxx_return = adj.at[signal_date, "SOXX"] / adj.at[start_date, "SOXX"] - 1
        spy_return = adj.at[signal_date, "SPY"] / adj.at[start_date, "SPY"] - 1
        target = select_target(float(soxx_return), float(spy_return))
        records.append({
            "signal_date": signal_date,
            "lookback_start": start_date,
            "lookback_trading_days": LOOKBACK,
            "soxx_adj_close_start": adj.at[start_date, "SOXX"],
            "soxx_adj_close_end": adj.at[signal_date, "SOXX"],
            "spy_adj_close_start": adj.at[start_date, "SPY"],
            "spy_adj_close_end": adj.at[signal_date, "SPY"],
            "soxx_total_return_60d": soxx_return,
            "spy_total_return_60d": spy_return,
            "selected": target,
            "execution_date": calendar[loc + 1],
            "execution_price": "next trading day unadjusted open",
        })
    signals = pd.DataFrame(records)
    if len(signals) != 72:
        raise AssertionError(f"应有 72 个月度决策（含 2019 年末初始信号），实际 {len(signals)}")
    return signals


def run_portfolio(
    key: str,
    label: str,
    fee_rate: float,
    market: dict[str, pd.DataFrame],
    calendar: pd.DatetimeIndex,
    signals: pd.DataFrame,
    benchmark: bool = False,
) -> Result:
    dates = calendar[(calendar >= START) & (calendar <= END)]
    schedule = {} if benchmark else signals.set_index("execution_date").to_dict("index")
    cash = INITIAL_CAPITAL
    shares = 0.0
    holding: str | None = None
    trade_id = 0
    trade_rows: list[dict] = []
    dividend_rows: list[dict] = []
    daily_rows: list[dict] = []

    for date in dates:
        signal = None
        target = "SPY" if benchmark and date == dates[0] else None
        if not benchmark and date in schedule:
            signal = schedule[date]
            target = signal["selected"]

        if target is not None and target != holding:
            trade_id += 1
            signal_date = START if benchmark else signal["signal_date"]
            soxx_ret = np.nan if benchmark else signal["soxx_total_return_60d"]
            spy_ret = np.nan if benchmark else signal["spy_total_return_60d"]
            if holding is not None:
                ticker = holding
                price = float(market[ticker].at[date, "open"])
                sold_shares = shares
                gross = sold_shares * price
                fee = gross * fee_rate
                cash += gross - fee
                trade_rows.append({
                    "trade_id": trade_id, "date": date, "side": "SELL", "ticker": ticker,
                    "shares": sold_shares, "price_open": price, "gross_amount": gross,
                    "fee_rate": fee_rate, "fee": fee, "cash_flow_after_fee": gross - fee,
                    "cash_after": cash, "holding_after": "", "signal_date": signal_date,
                    "soxx_total_return_60d": soxx_ret, "spy_total_return_60d": spy_ret,
                    "selected": target, "reason": "monthly signal switch",
                })
                shares = 0.0
                holding = None

            ticker = target
            price = float(market[ticker].at[date, "open"])
            budget = cash
            bought_shares = budget / (price * (1.0 + fee_rate))
            gross = bought_shares * price
            fee = gross * fee_rate
            cash -= gross + fee
            if abs(cash) < 1e-7:
                cash = 0.0
            shares = bought_shares
            holding = ticker
            trade_rows.append({
                "trade_id": trade_id, "date": date, "side": "BUY", "ticker": ticker,
                "shares": bought_shares, "price_open": price, "gross_amount": gross,
                "fee_rate": fee_rate, "fee": fee, "cash_flow_after_fee": -(gross + fee),
                "cash_after": cash, "holding_after": holding, "signal_date": signal_date,
                "soxx_total_return_60d": soxx_ret, "spy_total_return_60d": spy_ret,
                "selected": target,
                "reason": "SPY buy-and-hold initial purchase" if benchmark else "monthly signal target",
            })

        dividend_cash = 0.0
        dividend_per_share = 0.0
        additional_shares = 0.0
        if holding is not None:
            dividend_per_share = float(market[holding].at[date, "dividend"])
            if dividend_per_share != 0:
                close = float(market[holding].at[date, "close"])
                pre_shares = shares
                dividend_cash = pre_shares * dividend_per_share
                additional_shares = dividend_cash / close
                shares += additional_shares
                dividend_rows.append({
                    "strategy": key, "ex_date": date, "ticker": holding,
                    "pre_shares": pre_shares, "dividend_per_share": dividend_per_share,
                    "cash_dividend": dividend_cash, "reinvest_price_close": close,
                    "additional_shares": additional_shares, "post_shares": shares,
                    "reinvestment_fee": 0.0,
                })

        if holding is None:
            equity = cash
            close = np.nan
        else:
            close = float(market[holding].at[date, "close"])
            equity = cash + shares * close
        daily_rows.append({
            "date": date, "strategy": key, "position": holding or "CASH", "ticker": holding or "",
            "shares": shares, "close": close, "cash": cash,
            "dividend_per_share": dividend_per_share, "dividend_cash_reinvested": dividend_cash,
            "equity": equity, "net_value": equity / INITIAL_CAPITAL,
        })

    daily = pd.DataFrame(daily_rows).set_index("date")
    equity_with_start = pd.concat([
        pd.Series([INITIAL_CAPITAL], index=[START - pd.Timedelta(days=1)]),
        daily["equity"],
    ])
    running_peak = equity_with_start.cummax()
    drawdown_with_start = equity_with_start / running_peak - 1.0
    daily["drawdown"] = drawdown_with_start.iloc[1:].to_numpy()
    daily["daily_return"] = daily["equity"].pct_change()
    daily.iloc[0, daily.columns.get_loc("daily_return")] = daily["equity"].iloc[0] / INITIAL_CAPITAL - 1.0

    trades = pd.DataFrame(trade_rows)
    dividends = pd.DataFrame(dividend_rows)
    total_return = daily["equity"].iloc[-1] / INITIAL_CAPITAL - 1.0
    years = (dates[-1] - dates[0]).days / 365.25
    cagr = (daily["equity"].iloc[-1] / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    volatility = float(daily["daily_return"].std(ddof=1) * np.sqrt(252))
    trough_date = drawdown_with_start.idxmin()
    peak_value = running_peak.loc[trough_date]
    peak_date = equity_with_start.loc[:trough_date].idxmax()
    after_trough = equity_with_start.loc[trough_date:].iloc[1:]
    recovered = after_trough[after_trough >= peak_value]
    recovery_date = recovered.index[0] if len(recovered) else pd.NaT
    metrics = {
        "strategy": key, "label": label, "fee_rate": fee_rate,
        "start_date": dates[0], "end_date": dates[-1], "initial_capital": INITIAL_CAPITAL,
        "final_equity": daily["equity"].iloc[-1], "total_return": total_return,
        "cagr": cagr, "annualized_volatility": volatility,
        "max_drawdown": drawdown_with_start.min(), "max_drawdown_peak_date": peak_date,
        "max_drawdown_trough_date": trough_date, "max_drawdown_recovery_date": recovery_date,
        "total_fees": trades["fee"].sum(), "buy_count": int((trades["side"] == "BUY").sum()),
        "sell_count": int((trades["side"] == "SELL").sum()),
        "allocation_changes": int(trades["trade_id"].nunique()),
        "dividend_cash_reinvested": dividends["cash_dividend"].sum() if len(dividends) else 0.0,
        "dividend_events": len(dividends), "end_position": daily["position"].iloc[-1],
        "end_shares": daily["shares"].iloc[-1], "end_close": daily["close"].iloc[-1],
        "forced_liquidation": False,
    }
    return Result(key, label, fee_rate, daily, trades, dividends, metrics)


def annual_returns(results: list[Result]) -> pd.DataFrame:
    output = pd.DataFrame(index=range(2020, 2026))
    for result in results:
        equity = result.daily["equity"]
        values = []
        for year in output.index:
            year_equity = equity[equity.index.year == year]
            beginning = INITIAL_CAPITAL if year == 2020 else equity[equity.index.year == year - 1].iloc[-1]
            values.append(year_equity.iloc[-1] / beginning - 1.0)
        output[result.key] = values
    output.index.name = "year"
    return output


def validate_data(market: dict[str, pd.DataFrame], calendar: pd.DatetimeIndex, signals: pd.DataFrame) -> dict:
    validation: dict = {"checks": {}, "price_adjustment_reconciliation": {}}
    validation["checks"]["common_calendar_2011_bars"] = all(len(market[t]) == 2011 for t in TICKERS) and all(
        market[t].index.equals(calendar) for t in TICKERS
    )
    validation["checks"]["no_missing_ohlc_or_adjclose"] = all(
        not market[t][["open", "high", "low", "close", "adj_close"]].isna().any().any() for t in TICKERS
    )
    validation["checks"]["positive_prices"] = all((market[t][["open", "close", "adj_close"]] > 0).all().all() for t in TICKERS)
    validation["checks"]["backtest_dates"] = calendar[(calendar >= START) & (calendar <= END)][0] == START and calendar[-1] == END
    validation["checks"]["72_next_day_decisions"] = len(signals) == 72 and all(
        calendar[calendar.get_loc(row.signal_date) + 1] == row.execution_date for row in signals.itertuples()
    )
    validation["checks"]["tie_rule_positive_selects_spy"] = select_target(0.1, 0.1) == "SPY"
    validation["checks"]["nonpositive_selects_bil"] = select_target(-0.1, -0.05) == "BIL" and select_target(0.0, 0.0) == "BIL"
    validation["checks"]["soxx_split_recorded"] = str(market["SOXX"].at[pd.Timestamp("2024-03-07"), "split_ratio"]) == "3:1"

    for ticker in TICKERS:
        frame = market[ticker]
        factor = (frame["close"] + frame["dividend"]) / frame["close"].shift(1)
        factor.iloc[0] = 1.0
        tri = factor.cumprod()
        tri *= frame["adj_close"].iloc[-1] / tri.iloc[-1]
        relative_error = (tri / frame["adj_close"] - 1.0).abs()
        validation["price_adjustment_reconciliation"][ticker] = {
            "method": "cash dividend reinvested at ex-date close; normalized to Yahoo final adjusted close",
            "median_absolute_relative_error": float(relative_error.median()),
            "max_absolute_relative_error": float(relative_error.max()),
            "dividend_events_2018_2025": int((frame["dividend"] != 0).sum()),
        }

    gtimg_path = DATA / "raw" / "SOXX_gtimg_qfq_kline.json"
    if gtimg_path.exists():
        bars = json.loads(gtimg_path.read_text(encoding="utf-8"))["bars"]
        gtimg = pd.DataFrame([bar[:6] for bar in bars], columns=["date", "open", "close", "high", "low", "volume"])
        gtimg["date"] = pd.to_datetime(gtimg["date"])
        gtimg["close"] = pd.to_numeric(gtimg["close"])
        gtimg = gtimg.set_index("date")["close"].pct_change().rename("gtimg_return")
        yahoo = market["SOXX"]["adj_close"].pct_change().rename("yahoo_adj_return")
        joined = pd.concat([yahoo, gtimg], axis=1, join="inner").dropna()
        difference = (joined["yahoo_adj_return"] - joined["gtimg_return"]).abs()
        validation["soxx_independent_qfq_crosscheck"] = {
            "source": "Tencent gtimg qfqday via institutional-finance-kit finance-data",
            "shared_return_days": len(joined),
            "median_absolute_daily_return_difference": float(difference.median()),
            "p99_absolute_daily_return_difference": float(difference.quantile(0.99)),
            "max_absolute_daily_return_difference": float(difference.max()),
            "note": "不同供应商的复权基准和四舍五入不同，因此比较日收益而非价格水平。",
        }
    validation["all_checks_passed"] = all(validation["checks"].values())
    if not validation["all_checks_passed"]:
        raise AssertionError(f"数据验证失败: {validation['checks']}")
    return validation


def make_charts(results: list[Result]) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    styles = {
        "rotation_fee_10bps": ("#0052CC", "-"),
        "rotation_fee_20bps": ("#36B37E", "--"),
        "spy_buy_hold_fee_10bps": ("#FF5630", "-"),
        "spy_buy_hold_fee_20bps": ("#6554C0", "--"),
    }
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True, gridspec_kw={"height_ratios": [1.35, 1]})
    for result in results:
        color, linestyle = styles[result.key]
        axes[0].plot(result.daily.index, result.daily["net_value"], label=result.label, color=color, linestyle=linestyle, linewidth=1.6)
        axes[1].plot(result.daily.index, result.daily["drawdown"] * 100, label=result.label, color=color, linestyle=linestyle, linewidth=1.3)
    axes[0].set_title("SOXX / SPY / BIL Monthly Rotation vs SPY Buy & Hold (2020–2025)", fontsize=14, weight="bold")
    axes[0].set_ylabel("Net value (initial = 1.00)")
    axes[0].grid(alpha=0.25)
    axes[0].legend(ncol=2, frameon=False)
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].set_xlabel("Date")
    axes[1].grid(alpha=0.25)
    axes[1].axhline(0, color="black", linewidth=0.7)
    fig.tight_layout()
    fig.savefig(ROOT / "equity_drawdown.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def fmt_date(value) -> str:
    return "未修复" if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def generate_reports(results: list[Result], signals: pd.DataFrame, annual: pd.DataFrame, validation: dict) -> None:
    metrics = pd.DataFrame([r.metrics for r in results])
    by_key = {r.key: r for r in results}
    rot = by_key["rotation_fee_10bps"].metrics
    rot2 = by_key["rotation_fee_20bps"].metrics
    spy = by_key["spy_buy_hold_fee_10bps"].metrics
    spy2 = by_key["spy_buy_hold_fee_20bps"].metrics
    fee_drag = rot["final_equity"] - rot2["final_equity"]
    benchmark_drag = spy["final_equity"] - spy2["final_equity"]
    exposure = by_key["rotation_fee_10bps"].daily.groupby("position").size()
    exposure_text = "、".join(f"{idx} {int(val)} 日（{val / len(by_key['rotation_fee_10bps'].daily):.1%}）" for idx, val in exposure.items())
    initial = signals.iloc[0]
    last = signals.iloc[-1]
    recon = validation["price_adjustment_reconciliation"]
    max_recon = max(item["max_absolute_relative_error"] for item in recon.values())

    summary_headers = ["组合", "期末资产", "累计收益", "年化收益", "最大回撤", "年化波动", "总费用", "买/卖笔数"]
    summary_rows = []
    for r in results:
        m = r.metrics
        summary_rows.append([
            r.label, fmt_money(m["final_equity"]), fmt_pct(m["total_return"]), fmt_pct(m["cagr"]),
            fmt_pct(m["max_drawdown"]), fmt_pct(m["annualized_volatility"]), fmt_money(m["total_fees"]),
            f"{m['buy_count']} / {m['sell_count']}",
        ])
    annual_rows = [[str(year)] + [fmt_pct(annual.loc[year, r.key]) for r in results] for year in annual.index]
    signal_rows = []
    for row in signals.itertuples():
        signal_rows.append([
            pd.Timestamp(row.signal_date).strftime("%Y-%m-%d"), pd.Timestamp(row.execution_date).strftime("%Y-%m-%d"),
            fmt_pct(row.soxx_total_return_60d), fmt_pct(row.spy_total_return_60d), row.selected,
        ])

    def markdown_table(headers, rows):
        lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
        lines += ["| " + " | ".join(map(str, row)) + " |" for row in rows]
        return "\n".join(lines)

    md = f"""# SOXX、SPY、BIL 月度轮动策略回测报告

## 一、结论摘要

回测区间为 **2020-01-02 开盘至 2025-12-31 收盘**，初始资金 **$100,000**，允许碎股，不做参数优化。基础单边费率为 **0.10%**，压力情形为 **0.20%**；买入持有基准也在同一日起始开盘买入 SPY，并支付相同费率。

- 基础费率下，轮动策略期末资产 **{fmt_money(rot['final_equity'])}**，累计收益 **{fmt_pct(rot['total_return'])}**，年化收益 **{fmt_pct(rot['cagr'])}**，最大回撤 **{fmt_pct(rot['max_drawdown'])}**。
- 同费率 SPY 买入持有期末资产 **{fmt_money(spy['final_equity'])}**，累计收益 **{fmt_pct(spy['total_return'])}**，年化收益 **{fmt_pct(spy['cagr'])}**，最大回撤 **{fmt_pct(spy['max_drawdown'])}**。
- 费率从 0.10% 提至 0.20% 后，轮动策略期末资产减少 **{fmt_money(fee_drag)}**，SPY 基准减少 **{fmt_money(benchmark_drag)}**。差额包含费用本身及复利机会成本，不等于费用总额的简单差额。
- 期末均按 2025-12-31 收盘价估值，未强制清仓，也未计任何假想平仓费。

{markdown_table(summary_headers, summary_rows)}

![净值与回撤](equity_drawdown.png)

## 二、策略与成交口径

1. **信号**：每个自然月最后一个交易日收盘后，以现金分红和拆股复权收盘价计算 `当日复权收盘 / 60 个交易日前复权收盘 - 1`。该定义有 60 个日收益区间、使用 61 个收盘观察值。
2. **选择规则**：SOXX 与 SPY 中过去 60 日总回报较高且为正者入选；相等且为正时选 SPY；两者都不满足正回报条件时持有 BIL。
3. **执行**：信号次一交易日按 Yahoo 未做现金分红复权的开盘价全仓成交。持仓不变不交易，因此不产生费用。
4. **初始持仓**：2019-12-31 信号的 SOXX 60 日回报为 **{fmt_pct(initial.soxx_total_return_60d)}**、SPY 为 **{fmt_pct(initial.spy_total_return_60d)}**，选择 **{initial.selected}**，于 **{pd.Timestamp(initial.execution_date).strftime('%Y-%m-%d')} 开盘**建仓。
5. **最后一次已执行信号**：{pd.Timestamp(last.signal_date).strftime('%Y-%m-%d')} 选择 **{last.selected}**，于 {pd.Timestamp(last.execution_date).strftime('%Y-%m-%d')} 开盘执行。2025-12-31 信号需在 2026 年执行，不纳入本回测。
6. **费用**：买入满足 `股数 = 可用现金 / [开盘价 × (1 + 费率)]`，费用为买入成交额乘费率；卖出费用同样为卖出成交额乘费率。换仓卖出与买入分别收费。

## 三、分红、拆股与估值

- **分红**：Yahoo 公司行动中的每股现金分红按除息日归属。若当日开盘换仓，先按新持仓成交，再在当日收盘将新持仓应得现金分红按当日收盘价再投资；不再另收再投资费用。持仓随分红增加，因而不需要把分红留作闲置现金。BIL 的收益也通过这一机制计入。
- **拆股**：Yahoo 历史 OHLC 与分红金额均已按后续拆股调整，回测股数也是拆股调整后的可比股数。SOXX 在 **2024-03-07** 的 **3:1** 拆股已计入数据，不被当作投资损失或收益。SPY、BIL 在回测期无拆股。
- **信号价格**：使用 `adj_close`，即拆股和现金分红复权收盘价。**成交与期末估值**：使用未做现金分红复权的 `open` / `close`，并单独用分红账本增加股数，避免重复计息。
- **对账**：用 `(当日收盘 + 当日每股分红) / 前收盘` 自建总回报指数，与 Yahoo `adj_close` 比较；三只 ETF 全样本最大相对误差为 **{max_recon:.6%}**，差异主要来自供应商精度与舍入。SOXX 另与腾讯前复权日收益交叉检查，见 `data_validation.json`。
- **其他假设**：无滑点、买卖价差、税费和分红预扣税；开盘价可足额成交；分红再投资允许碎股。现金只在同一换仓流程中瞬时存在，不另计利息。

## 四、分年度收益

{markdown_table(["年份"] + [r.label for r in results], annual_rows)}

## 五、回撤、交易与持仓

"""
    for r in results:
        m = r.metrics
        md += f"- **{r.label}**：最大回撤 {fmt_pct(m['max_drawdown'])}，峰值日 {fmt_date(m['max_drawdown_peak_date'])}，谷底日 {fmt_date(m['max_drawdown_trough_date'])}，修复日 {fmt_date(m['max_drawdown_recovery_date'])}；分红再投资 {m['dividend_events']} 次，期末持有 {m['end_position']}。\n"
    md += f"""
轮动持仓日期分布（两档费率信号相同）：{exposure_text}。逐次买卖、信号、成交价、股数和费用见 `trades.csv`；持仓不变但无成交的月份见 `signals.csv`。

## 六、全部月度信号

{markdown_table(["信号日", "执行日", "SOXX 60日总回报", "SPY 60日总回报", "目标"], signal_rows)}

## 七、数据来源与复现

- 主数据：**Yahoo Finance v8 chart**，日线 OHLC、`adjclose`、`events=div,splits`。本次下载为 2018-01-02 至 2025-12-31，每只 2,011 根共同交易日日线。原始 JSON、精确请求 URL、抓取时间与 CSV 均在 `data/`。
- 独立复权核验：SOXX 腾讯 `gtimg-fqkline` 前复权日线，通过 institutional-finance-kit 的 finance-data 场景取得；原始文件位于 `data/raw/SOXX_gtimg_qfq_kline.json`。
- 运行：在本目录执行 `python backtest.py` 即可离线复算；执行 `python fetch_data.py && python backtest.py` 会重新下载后再回测。依赖见 `requirements.txt`。
- 数据快照抓取于 2026-10-27；供应商后续修订历史数据可能使重新下载的结果略有变化。随附数据快照是本次报告数字的复现依据。

> 本报告是历史规则回测，不构成收益承诺或投资建议。
"""
    (ROOT / "report.md").write_text(md, encoding="utf-8")

    def html_table(headers, rows):
        head = "".join(f"<th>{h}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    image64 = base64.b64encode((ROOT / "equity_drawdown.png").read_bytes()).decode("ascii")
    detail_rows = []
    for r in results:
        m = r.metrics
        detail_rows.append([
            r.label, fmt_date(m["max_drawdown_peak_date"]), fmt_date(m["max_drawdown_trough_date"]),
            fmt_date(m["max_drawdown_recovery_date"]), m["dividend_events"], m["end_position"],
        ])
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ETF 轮动回测报告</title>
<style>body{{font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;max-width:1180px;margin:36px auto;padding:0 24px;color:#172b4d;line-height:1.75}}h1,h2{{color:#091e42}}h1{{border-bottom:3px solid #0052cc;padding-bottom:12px}}h2{{margin-top:34px}}table{{border-collapse:collapse;width:100%;font-size:14px;margin:16px 0}}th,td{{border:1px solid #dfe1e6;padding:8px 10px;text-align:right}}th{{background:#f4f5f7}}th:first-child,td:first-child{{text-align:left}}img{{max-width:100%;height:auto;border:1px solid #dfe1e6;border-radius:6px}}.note{{background:#f4f5f7;padding:16px 20px;border-left:4px solid #0052cc}}.small{{font-size:13px;color:#5e6c84}}code{{background:#f4f5f7;padding:2px 5px}}</style></head><body>
<h1>SOXX、SPY、BIL 月度轮动策略回测</h1><p>2020-01-02 开盘至 2025-12-31 收盘｜初始资金 $100,000｜允许碎股｜不调参</p>
<h2>结论摘要</h2><ul><li>基础费率轮动：期末 <b>{fmt_money(rot['final_equity'])}</b>，累计 {fmt_pct(rot['total_return'])}，年化 {fmt_pct(rot['cagr'])}，最大回撤 {fmt_pct(rot['max_drawdown'])}。</li><li>同费率 SPY 买入持有：期末 <b>{fmt_money(spy['final_equity'])}</b>，累计 {fmt_pct(spy['total_return'])}，年化 {fmt_pct(spy['cagr'])}，最大回撤 {fmt_pct(spy['max_drawdown'])}。</li><li>费率翻倍使轮动期末资产减少 {fmt_money(fee_drag)}；基准减少 {fmt_money(benchmark_drag)}。</li></ul>
{html_table(summary_headers, summary_rows)}<img src="data:image/png;base64,{image64}" alt="净值与回撤图">
<h2>规则与会计口径</h2><ol><li>每月最后交易日收盘后，用复权收盘价计算过去 60 交易日总回报；次一交易日未复权开盘价全仓成交。</li><li>较高且为正者入选；相等且为正选 SPY；否则 BIL；目标不变不交易。</li><li>现金分红在除息日收盘按收盘价再投资，不收再投资费；先执行当日开盘换仓，再处理新持仓分红。</li><li>Yahoo OHLC 与分红金额为拆股调整口径；SOXX 2024-03-07 的 3:1 拆股已正确处理。</li><li>买入费用包含在可用现金内；卖出和买入分别收费。期末按收盘估值，不强制清仓。</li></ol>
<p class="note">2019-12-31 初始信号：SOXX {fmt_pct(initial.soxx_total_return_60d)}、SPY {fmt_pct(initial.spy_total_return_60d)}，选择 {initial.selected}，于 {pd.Timestamp(initial.execution_date).strftime('%Y-%m-%d')} 开盘建仓。无滑点、价差、税费或分红预扣税。</p>
<h2>分年度收益</h2>{html_table(["年份"] + [r.label for r in results], annual_rows)}
<h2>回撤与期末持仓</h2>{html_table(["组合", "峰值日", "谷底日", "修复日", "分红再投资次数", "期末持仓"], detail_rows)}
<p>轮动持仓日期分布：{exposure_text}。</p><h2>月度信号</h2>{html_table(["信号日", "执行日", "SOXX 60日总回报", "SPY 60日总回报", "目标"], signal_rows)}
<h2>数据与复现</h2><p>主数据为 Yahoo Finance v8 chart 的日线、复权收盘与分红拆股事件；原始 JSON、请求 URL、CSV 和元数据均在 <code>data/</code>。SOXX 另以腾讯前复权日收益交叉核验。自建总回报指数与 Yahoo 复权收盘的三标的最大相对误差为 {max_recon:.6%}。</p><p>在本目录执行 <code>python backtest.py</code> 离线复算；<code>python fetch_data.py &amp;&amp; python backtest.py</code> 重新下载并回测。数据快照抓取于 2026-10-27。</p><p class="small">历史规则回测，不构成收益承诺或投资建议。</p></body></html>"""
    (ROOT / "report.html").write_text(html, encoding="utf-8")


def main() -> None:
    market = load_market_data()
    calendar = market["SPY"].index
    signals = build_signals(market, calendar)
    validation = validate_data(market, calendar, signals)
    specifications = [
        ("rotation_fee_10bps", "轮动 0.10%", BASE_FEE, False),
        ("rotation_fee_20bps", "轮动 0.20%", DOUBLE_FEE, False),
        ("spy_buy_hold_fee_10bps", "SPY买入持有 0.10%", BASE_FEE, True),
        ("spy_buy_hold_fee_20bps", "SPY买入持有 0.20%", DOUBLE_FEE, True),
    ]
    results = [run_portfolio(key, label, fee, market, calendar, signals, benchmark) for key, label, fee, benchmark in specifications]
    if results[0].metrics["final_equity"] <= results[1].metrics["final_equity"]:
        raise AssertionError("轮动费用翻倍后期末资产应下降")
    if results[2].metrics["final_equity"] <= results[3].metrics["final_equity"]:
        raise AssertionError("基准费用翻倍后期末资产应下降")

    signals.to_csv(ROOT / "signals.csv", index=False, encoding="utf-8-sig", float_format="%.12f")
    pd.concat([r.trades.assign(strategy=r.key, strategy_label=r.label) for r in results], ignore_index=True).to_csv(
        ROOT / "trades.csv", index=False, encoding="utf-8-sig", float_format="%.10f"
    )
    pd.concat([r.dividends for r in results], ignore_index=True).to_csv(
        ROOT / "dividend_reinvestments.csv", index=False, encoding="utf-8-sig", float_format="%.10f"
    )
    pd.concat([r.daily.assign(strategy_label=r.label) for r in results]).to_csv(
        ROOT / "daily_detail.csv", encoding="utf-8-sig", float_format="%.10f"
    )
    metrics = pd.DataFrame([r.metrics for r in results])
    metrics.to_csv(ROOT / "summary_metrics.csv", index=False, encoding="utf-8-sig", float_format="%.12f")
    annual = annual_returns(results)
    annual.to_csv(ROOT / "annual_returns.csv", encoding="utf-8-sig", float_format="%.12f")

    wide = pd.DataFrame(index=results[0].daily.index)
    for r in results:
        wide[f"{r.key}_equity"] = r.daily["equity"]
        wide[f"{r.key}_net_value"] = r.daily["net_value"]
        wide[f"{r.key}_drawdown"] = r.daily["drawdown"]
    wide["rotation_position"] = results[0].daily["position"]
    wide.index.name = "date"
    wide.to_csv(ROOT / "daily_equity_drawdown.csv", encoding="utf-8-sig", float_format="%.10f")
    (ROOT / "data_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    make_charts(results)
    generate_reports(results, signals, annual, validation)

    display = metrics[["label", "final_equity", "total_return", "cagr", "max_drawdown", "total_fees", "buy_count", "sell_count"]].copy()
    for col in ("total_return", "cagr", "max_drawdown"):
        display[col] = display[col].map(fmt_pct)
    display["final_equity"] = display["final_equity"].map(fmt_money)
    display["total_fees"] = display["total_fees"].map(fmt_money)
    print(display.to_string(index=False))
    print(f"\n输出目录: {ROOT}")


if __name__ == "__main__":
    main()
