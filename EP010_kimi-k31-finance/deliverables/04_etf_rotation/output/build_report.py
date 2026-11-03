#!/usr/bin/env python3
"""Render charts plus Markdown and fully self-contained HTML from backtest outputs."""
from pathlib import Path
import base64
import html
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parent
CHARTS = ROOT / "charts"
INITIAL = 100_000.0
SCENARIOS = ["rotation_fee_0.001", "SPY_buy_hold_fee_0.001", "rotation_fee_0.002", "SPY_buy_hold_fee_0.002"]
LABELS = {
    "rotation_fee_0.001": "轮动策略｜单边 0.1%",
    "SPY_buy_hold_fee_0.001": "SPY 持有｜单边 0.1%",
    "rotation_fee_0.002": "轮动策略｜单边 0.2%",
    "SPY_buy_hold_fee_0.002": "SPY 持有｜单边 0.2%",
}
SHORT = {
    "rotation_fee_0.001": "轮动 0.1%",
    "SPY_buy_hold_fee_0.001": "SPY 0.1%",
    "rotation_fee_0.002": "轮动 0.2%",
    "SPY_buy_hold_fee_0.002": "SPY 0.2%",
}


def money(x):
    return f"${x:,.2f}"


def pct(x, digits=2):
    return f"{x * 100:.{digits}f}%"


def num(x, digits=3):
    return f"{x:.{digits}f}"


def load():
    metrics = pd.read_csv(ROOT / "metrics.csv").set_index("scenario").loc[SCENARIOS]
    nav = pd.read_csv(ROOT / "daily_nav.csv", parse_dates=["Date"])
    annual = pd.read_csv(ROOT / "annual_returns.csv", parse_dates=["period_end"])
    signals = pd.read_csv(ROOT / "signals.csv", parse_dates=["signal_date", "lookback_start_date", "execution_date"])
    trades = pd.read_csv(ROOT / "trades.csv", parse_dates=["date", "signal_date"])
    quality = json.loads((ROOT / "data_quality.json").read_text(encoding="utf-8"))
    return metrics, nav, annual, signals, trades, quality


def make_chart(nav):
    CHARTS.mkdir(exist_ok=True)
    wide = nav.pivot(index="Date", columns="scenario", values="nav") / INITIAL * 100.0
    dd = nav.pivot(index="Date", columns="scenario", values="drawdown") * 100.0
    baseline = pd.DataFrame([[100.0] * len(SCENARIOS)], index=[pd.Timestamp("2019-12-31")], columns=SCENARIOS)
    wide = pd.concat([baseline, wide[SCENARIOS]])
    dd = pd.concat([pd.DataFrame([[0.0] * len(SCENARIOS)], index=[pd.Timestamp("2019-12-31")], columns=SCENARIOS), dd[SCENARIOS]])
    colors = {"rotation": "#0f2d55", "SPY": "#357af6"}
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": "#b2b2b2",
        "axes.labelcolor": "#42566a", "xtick.color": "#42566a", "ytick.color": "#42566a",
        "axes.titlecolor": "#051c2c", "figure.facecolor": "white", "axes.facecolor": "white",
    })
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [1.65, 1], "hspace": 0.14})
    for scenario in SCENARIOS:
        family = "SPY" if scenario.startswith("SPY") else "rotation"
        high = scenario.endswith("0.002")
        label = ("SPY buy & hold" if family == "SPY" else "Rotation") + (" | 0.2% fee" if high else " | 0.1% fee")
        axes[0].plot(wide.index, wide[scenario], color=colors[family], linestyle="--" if high else "-", linewidth=1.6 if high else 2.1, label=label)
        axes[1].plot(dd.index, dd[scenario], color=colors[family], linestyle="--" if high else "-", linewidth=1.4 if high else 1.8, label=label)
    axes[0].set_title("Portfolio value (initial = 100)", loc="left", fontsize=15, fontweight="bold", pad=12)
    axes[0].set_ylabel("Indexed NAV")
    axes[0].legend(loc="upper left", frameon=False, ncol=2, fontsize=9)
    axes[1].set_title("Drawdown from running peak", loc="left", fontsize=13, fontweight="bold", pad=10)
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].set_xlabel("Date")
    for ax in axes:
        ax.grid(axis="y", color="#e6e6e6", linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.axhline(0, color="#b2b2b2", linewidth=0.7)
        ax.margins(x=0.01)
    axes[1].xaxis.set_major_locator(mdates.YearLocator())
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[1].set_xlim(pd.Timestamp("2019-12-15"), pd.Timestamp("2026-01-15"))
    fig.text(0.075, 0.015, "Source: Yahoo Finance daily data; deterministic calculations in backtest.py. Dividends are held as cash, not reinvested.", fontsize=8.5, color="#42566a")
    fig.subplots_adjust(left=0.075, right=0.975, top=0.95, bottom=0.09)
    fig.savefig(CHARTS / "nav_drawdown.png", dpi=180, facecolor="white")
    plt.close(fig)


def metrics_table_html(metrics):
    headers = ["方案", "期末净值", "累计收益", "CAGR", "年化波动", "Sharpe（rf=0）", "最大回撤", "累计费用", "交易腿"]
    rows = []
    for scenario, r in metrics.iterrows():
        cells = [LABELS[scenario], money(r.final_nav), pct(r.total_return), pct(r.CAGR), pct(r.annualized_volatility), num(r.Sharpe_rf0), pct(r.max_drawdown), money(r.total_fees), str(int(r.trade_legs))]
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in cells) + "</tr>")
    return "<div class=\"table-wrap\"><table><thead><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"


def metrics_table_md(metrics):
    lines = ["| 方案 | 期末净值 | 累计收益 | CAGR | 年化波动 | Sharpe（rf=0） | 最大回撤 | 累计费用 | 交易腿 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for scenario, r in metrics.iterrows():
        lines.append(f"| {LABELS[scenario]} | {money(r.final_nav)} | {pct(r.total_return)} | {pct(r.CAGR)} | {pct(r.annualized_volatility)} | {num(r.Sharpe_rf0)} | {pct(r.max_drawdown)} | {money(r.total_fees)} | {int(r.trade_legs)} |")
    return "\n".join(lines)


def annual_table(annual, as_html=False):
    annual = annual.copy()
    annual["year"] = annual["period_end"].dt.year
    wide = annual.pivot(index="year", columns="scenario", values="return").loc[:, SCENARIOS]
    if as_html:
        head = ["年份"] + [SHORT[s] for s in SCENARIOS]
        body = []
        for year, row in wide.iterrows():
            body.append("<tr><td>" + str(year) + "</td>" + "".join(f"<td class=\"{'neg' if row[s] < 0 else ''}\">{pct(row[s])}</td>" for s in SCENARIOS) + "</tr>")
        return "<div class=\"table-wrap\"><table><thead><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    lines = ["| 年份 | 轮动 0.1% | SPY 0.1% | 轮动 0.2% | SPY 0.2% |", "|---:|---:|---:|---:|---:|"]
    for year, row in wide.iterrows():
        lines.append(f"| {year} | " + " | ".join(pct(row[s]) for s in SCENARIOS) + " |")
    return "\n".join(lines)


def build():
    metrics, nav, annual, signals, trades, quality = load()
    make_chart(nav)
    image64 = base64.b64encode((CHARTS / "nav_drawdown.png").read_bytes()).decode("ascii")
    r1 = metrics.loc["rotation_fee_0.001"]
    s1 = metrics.loc["SPY_buy_hold_fee_0.001"]
    r2 = metrics.loc["rotation_fee_0.002"]
    s2 = metrics.loc["SPY_buy_hold_fee_0.002"]
    initial = signals.iloc[0]
    base_gap = r1.final_nav - s1.final_nav
    high_gap = r2.final_nav - s2.final_nav
    fee_drag = r1.final_nav - r2.final_nav
    exposure = {t: r1[f"{t}_exposure_days_pct"] for t in ["SOXX", "SPY", "BIL"]}
    generated = pd.Timestamp.today().date().isoformat()
    source_note = "Yahoo Finance（yfinance 1.7.0，auto_adjust=False）；数据截至 2025-12-31"
    summary = (
        f"基础费率下，轮动策略期末为 {money(r1.final_nav)}，略低于 SPY 买入持有的 {money(s1.final_nav)}，"
        f"差额为 {money(abs(base_gap))}；同时年化波动更高（{pct(r1.annualized_volatility)} 对 {pct(s1.annualized_volatility)}），"
        f"最大回撤更深（{pct(r1.max_drawdown)} 对 {pct(s1.max_drawdown)}）。"
    )
    conclusions = [
        summary,
        f"单边费率由 0.1% 升至 0.2% 后，轮动策略期末净值减少 {money(fee_drag)}，累计收益从 {pct(r1.total_return)} 降至 {pct(r2.total_return)}，CAGR 从 {pct(r1.CAGR)} 降至 {pct(r2.CAGR)}。高费率下落后 SPY 基准 {money(abs(high_gap))}。",
        f"共 72 个可执行月度信号（含 2019 年末初始信号），46 次持仓不变不交易，实际换仓 25 次、交易腿 51 条。基础费率累计费用 {money(r1.total_fees)}，费率和换手是该策略的重要拖累。",
        f"持仓交易日占比为 SOXX {pct(exposure['SOXX'])}、SPY {pct(exposure['SPY'])}、BIL {pct(exposure['BIL'])}。分年度看并非持续落后，例如 2025 年轮动策略表现强于 SPY，但六年综合结果未形成风险调整后的优势。",
        "本结果只支持对该固定规则在 2020—2025 年历史样本的事后评价，不支持推断未来收益；未进行参数寻优或样本外验证。",
    ]
    methodology = [
        "股票池固定为 SOXX、SPY、BIL，只做多、允许碎股，初始资金 100,000 美元。回测交易日为 2020-01-02 至 2025-12-31，共 1,508 个共同交易日。",
        "每月最后一个共同交易日收盘后，分别计算 SOXX 与 SPY 的 60 交易日总回报：Adj Close(t) / Adj Close(t−60) − 1。选择回报较高且为正者；相等且为正选 SPY；两者均非正或最高回报非正时选 BIL。",
        "信号后的下一个交易日开盘执行。持仓不变不交易。2019-12-31 信号用于 2020-01-02 开盘建仓，其 60 日窗口从 2019-10-04 开始；初始信号选择 SOXX（SOXX 18.03%，SPY 9.88%）。2025-12-31 信号因执行日落在样本外，不产生样本内交易。",
        "信号使用 Yahoo Adj Close（拆股与现金分红调整的总回报代理）。交易与估值使用同一数据源仅拆股调整的 Open / Close，不把分红复权价当成成交价。SOXX 2024-03-07 的 3:1 拆股已在价格、每股分红和份额单位中一致反映，不再次调整持仓份额。",
        "分红在除息日按开盘交易前的既有持仓计入现金，不自动再投资、现金不计息；下一次实际换仓时现金一并投入。若一直持有，分红现金留存到期末。基准采用同样的现金分红处理。",
        "换仓卖出和买入分别按成交额收取单边 0.1%；翻倍情景为单边 0.2%。买入份额 = 可用现金 / [开盘价 × (1 + 费率)]。不计价差、滑点、税费和冲击成本。期末按 2025-12-31 收盘价加现金估值，不强制清仓、不扣期末卖出费。",
        "SPY 基准于 2020-01-02 开盘一次性买入并持有，按相同费率只扣初始买入费；分红留现金，期末口径与策略一致。",
        "CAGR 按实际起止天数 / 365.2425 年化；波动率与 Sharpe 使用日收益、252 交易日年化，Sharpe 无风险利率取 0；最大回撤基于每日收盘净值，初始资金计入历史高点。",
    ]
    limitations = [
        "前视偏差：通过。信号只使用月末及此前 Adj Close，交易推迟至下一交易日开盘；预热数据只用于信号。",
        "幸存者偏差：固定三只存续 ETF，无成分股筛选或退市处理问题；标的选择本身来自用户设定，不能视为点时可投资股票池研究。",
        "数据偏差：Yahoo 历史数据可能被事后修订，无严格 point-in-time 快照保证。已检查日期对齐、缺失、重复、非正价格，并用另一 Yahoo 连接通道交叉核对复权收盘与分红。",
        "成交可行性：假设全部按开盘价成交且允许碎股；未模拟买卖价差、滑点、市场冲击、税务、现金利息与交易暂停。因此结果是规则回测估计，不是可实现收益保证。",
        "稳健性：仅执行用户指定的费用翻倍与分年度观察，没有调参；未做替代持有期、样本外或不同市场状态检验。",
    ]
    files = [
        ("report.md", "Markdown 报告"), ("report.html", "完全自包含 HTML 报告"),
        ("charts/nav_drawdown.png", "净值与回撤图"), ("metrics.csv", "汇总指标"),
        ("annual_returns.csv", "分年度收益"), ("monthly_returns.csv", "分月收益"),
        ("signals.csv", "全部月末信号与执行日"), ("trades.csv", "逐笔交易腿明细"),
        ("dividend_cashflows.csv", "分红现金流水"), ("daily_nav.csv", "每日持仓、现金、净值与回撤"),
        ("data/SOXX_daily.csv、data/SPY_daily.csv、data/BIL_daily.csv", "输入日线与公司行动"),
        ("data_quality.json", "数据质量与一致性检查"), ("backtest.py", "离线回测代码"),
        ("download_data.py", "Yahoo 数据刷新代码"), ("build_report.py", "图表和报告生成代码"),
    ]

    md = f"""# SOXX / SPY / BIL 月度轮动策略回测

> 回测区间：2020-01-02 开盘至 2025-12-31 收盘｜初始资金：100,000 美元｜研究生成日：{generated}  
> 本报告为历史规则回测，不构成投资建议或收益预测。

## 一、主要结论

""" + "\n".join(f"{i+1}. {text}" for i, text in enumerate(conclusions)) + f"""

## 二、策略规则与计算口径

""" + "\n".join(f"{i+1}. {text}" for i, text in enumerate(methodology)) + f"""

## 三、策略与 SPY 基准：两档费用结果

{metrics_table_md(metrics)}

注：所有数值均为脚本输出的历史回测估计。累计收益以期初 100,000 美元为基数；期末不强制清仓。

## 四、净值与回撤

![轮动策略与SPY基准的净值及回撤](charts/nav_drawdown.png)

实线为单边 0.1%，虚线为单边 0.2%；深蓝为轮动策略，亮蓝为 SPY 买入持有。净值以初始资金 = 100 标准化。

## 五、分年度收益

{annual_table(annual)}

2020 年收益从 2020-01-02 开盘前的初始资金起算；其余年份按上一年最后一个交易日收盘净值起算。

## 六、交易与持仓摘要

- 初始信号：2019-12-31；SOXX 60 日总回报 {pct(initial.SOXX_total_return)}，SPY {pct(initial.SPY_total_return)}；2020-01-02 开盘买入 SOXX。
- 可执行信号 72 个；持仓不变不交易 46 次；实际换仓 25 次；交易腿 51 条（含初始买入）。
- 轮动策略基础费率累计分红现金 {money(r1.dividend_cash_received)}，期末残留现金 {money(r1.ending_cash)}；SPY 基准分别为 {money(s1.dividend_cash_received)} 和 {money(s1.ending_cash)}。
- 基础费率最大回撤区间为 {r1.max_drawdown_peak_date} 至 {r1.max_drawdown_trough_date}，{r1.max_drawdown_recovery_date} 修复；SPY 基准为 {s1.max_drawdown_peak_date} 至 {s1.max_drawdown_trough_date}，{s1.max_drawdown_recovery_date} 修复。

## 七、数据来源、质量与偏差检查

数据来源：{source_note}。每只 ETF 1,760 条日线，覆盖 2019-01-02 至 2025-12-31；回测期共同交易日 1,508 天。`Adj Close` 只用于总回报信号，`Open` / `Close` 用于成交与估值，现金分红另行入账。

""" + "\n".join(f"- {text}" for text in limitations) + """

## 八、交付文件与复现方法

""" + "\n".join(f"- `{path}`：{desc}" for path, desc in files) + """

在本目录运行（已附带数据，无需联网）：

```bash
python -m pip install -r requirements.txt
python backtest.py
python build_report.py
```

如需重新下载并刷新 Yahoo 数据（历史修订可能改变结果）：

```bash
python download_data.py
python backtest.py
python build_report.py
```

直接用浏览器打开 `report.html` 即可完整阅读；HTML 已内嵌 CSS 与 PNG 图表，无网络依赖。原始连接通道文件另存于 `data/raw/`，主回测仅读取 `data/*_daily.csv`。
"""

    html_conclusions = "".join(f"<li>{html.escape(x)}</li>" for x in conclusions)
    html_methods = "".join(f"<li>{html.escape(x)}</li>" for x in methodology)
    html_limits = "".join(f"<li>{html.escape(x)}</li>" for x in limitations)
    html_files = "".join(f"<li><code>{html.escape(path)}</code><span>{html.escape(desc)}</span></li>" for path, desc in files)
    html_doc = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SOXX / SPY / BIL 月度轮动策略回测</title>
<style>
:root{--paper:#fff;--ink:#051c2c;--mid:#42566a;--low:#8595a6;--line:#dcdcdc;--navy:#0f2d55;--blue:#357af6;--neg:#c02030;--serif:"Iowan Old Style",Palatino,"Palatino Linotype","Book Antiqua",Georgia,"Songti SC",serif;--mono:Menlo,Consolas,"SF Mono","Liberation Mono","DejaVu Sans Mono",monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--serif);font-size:16px;line-height:1.8}main{max-width:960px;margin:0 auto;padding:0 24px}.prose{max-width:760px;margin-left:auto;margin-right:auto}header{padding:80px 0 48px;border-bottom:1px solid var(--line)}.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--mid);margin:0 0 16px}h1{font-size:40px;line-height:1.25;font-weight:700;margin:0 0 20px}h2{font-size:25px;line-height:1.4;margin:0 0 24px}h3{font-size:18px;margin:32px 0 12px}.dek{font-size:19px;font-style:italic;color:var(--mid);max-width:760px;margin:0}.meta{font-family:var(--mono);font-size:12px;line-height:1.8;color:var(--mid);margin-top:24px}section{padding:64px 0 0}.lead{font-size:18px;line-height:1.85}ol,ul{padding-left:24px;margin:16px 0}li{margin:0 0 16px}li::marker{color:var(--mid)}figure{margin:32px 0 0}figure img{display:block;width:100%;height:auto}figcaption{font-family:var(--mono);font-size:11px;line-height:1.7;color:var(--mid);margin-top:12px}.table-wrap{overflow-x:auto;margin:24px 0 16px;border-top:1px solid var(--ink);border-bottom:1px solid var(--line)}table{border-collapse:collapse;width:100%;min-width:820px;font-family:var(--mono);font-size:12px;line-height:1.5}th{text-align:right;font-weight:400;color:var(--mid);padding:12px 8px;border-bottom:1px solid var(--line);white-space:nowrap}td{text-align:right;padding:12px 8px;border-bottom:1px solid #f0f0f0;white-space:nowrap;font-variant-numeric:tabular-nums}th:first-child,td:first-child{text-align:left}tbody tr:last-child td{border-bottom:0}.neg{color:var(--neg)}.note{font-family:var(--mono);font-size:11px;line-height:1.8;color:var(--mid)}.keyline{border-top:1px solid var(--ink);border-bottom:1px solid var(--line);padding:24px 0;margin:32px 0}.keyline p{margin:0;font-size:20px;line-height:1.7}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin:32px 0}.fact{border-top:1px solid var(--line);padding-top:12px}.fact b{display:block;font-family:var(--mono);font-size:20px;font-weight:400;color:var(--navy)}.fact span{font-family:var(--mono);font-size:11px;color:var(--mid)}.files{list-style:none;padding:0}.files li{display:flex;gap:16px;padding:8px 0;margin:0;border-bottom:1px solid #f0f0f0}.files code{font-family:var(--mono);font-size:12px;min-width:290px;color:var(--navy);overflow-wrap:anywhere}.files span{color:var(--mid);font-size:14px}pre{overflow-x:auto;background:#f5f5f5;padding:16px;font-family:var(--mono);font-size:12px;line-height:1.8}code{font-family:var(--mono)}footer{padding:64px 0 80px;color:var(--mid);font-size:13px}.warning{font-family:var(--mono);font-size:11px;color:var(--mid);border-top:1px solid var(--line);padding-top:16px}a{color:var(--navy)}@media(max-width:640px){main{padding:0 16px}header{padding:48px 0 32px}h1{font-size:30px}.dek{font-size:17px}section{padding-top:48px}.facts{grid-template-columns:1fr}.files li{display:block}.files code{display:block;min-width:0}.lead{font-size:16px}}@media print{body{font-size:11pt}main{max-width:none}section{break-inside:auto}figure,.table-wrap{break-inside:avoid}header{padding-top:0}.table-wrap{overflow:visible}table{min-width:0;font-size:8pt}}
</style>
</head>
<body><main>
<header><p class="eyebrow">ETF rotation · 2020—2025 · reproducible backtest</p><h1>SOXX / SPY / BIL<br>月度轮动策略回测</h1><p class="dek">60 交易日总回报动量、次日开盘执行、BIL 防守；对照同费用口径的 SPY 买入持有。</p><div class="meta">回测：2020-01-02 开盘 — 2025-12-31 收盘<br>初始资金：USD 100,000 · 允许碎股 · 不调参<br>研究生成日：__GENERATED__</div></header>
<section><div class="prose"><p class="eyebrow">01 / 主要结论</p><h2>终值接近，不代表风险与成本相同</h2><div class="keyline"><p>__SUMMARY__</p></div><div class="facts"><div class="fact"><b>__R1NAV__</b><span>轮动期末 · 单边 0.1%</span></div><div class="fact"><b>__R2NAV__</b><span>轮动期末 · 单边 0.2%</span></div><div class="fact"><b>__FEES__</b><span>基础费率累计交易费用</span></div></div><ol>__CONCLUSIONS__</ol></div></section>
<section><div class="prose"><p class="eyebrow">02 / 规则与口径</p><h2>信号、成交、分红和费用严格分离</h2><ol>__METHODS__</ol></div></section>
<section><p class="eyebrow">03 / 两档结果</p><h2>策略与 SPY 买入持有</h2>__METRICS_TABLE__<p class="note">所有数值均为 backtest.py 输出的历史回测估计。CAGR 按实际天数年化；Sharpe 的无风险利率为 0；期末不强制清仓。</p></section>
<section><p class="eyebrow">04 / 净值与回撤</p><h2>费用上升主要侵蚀轮动策略复利</h2><figure><img src="data:image/png;base64,__IMAGE64__" alt="轮动策略与SPY基准在2020至2025年的净值及回撤图"><figcaption>实线为单边 0.1%，虚线为单边 0.2%；深蓝为轮动策略，亮蓝为 SPY。净值以初始资金 = 100 标准化。图已内嵌，可离线阅读。</figcaption></figure></section>
<section><p class="eyebrow">05 / 分年度</p><h2>年度表现存在差异，六年综合未占优</h2>__ANNUAL_TABLE__<p class="note">2020 年从开盘前初始资金起算，其余年份从上一年末净值起算。</p></section>
<section><div class="prose"><p class="eyebrow">06 / 数据与偏差</p><h2>真实行情，但仍需遵守回测边界</h2><p>数据来源：<strong>__SOURCE__</strong>。每只 ETF 1,760 条日线，覆盖 2019-01-02 至 2025-12-31；共同回测交易日 1,508 天。另一 Yahoo 连接通道的复权收盘与分红记录已交叉核对，最大差异仅来自浮点精度。</p><ul>__LIMITS__</ul></div></section>
<section><div class="prose"><p class="eyebrow">07 / 文件与复现</p><h2>离线重跑，不必重新取数</h2><ul class="files">__FILES__</ul><h3>使用附带数据复现</h3><pre>python -m pip install -r requirements.txt
python backtest.py
python build_report.py</pre><h3>刷新 Yahoo 数据后复现</h3><pre>python download_data.py
python backtest.py
python build_report.py</pre><p class="note">刷新数据可能因供应商修订历史而改变结果。主回测只读取 data/*_daily.csv；data/raw/ 仅保留连接通道核验材料。</p></div></section>
<footer><div class="prose"><p class="warning">历史回测不构成投资建议、交易指令或收益承诺。结果未计价差、滑点、税费与市场冲击；现金分红不再投资且现金不计息。</p></div></footer>
</main></body></html>"""
    replacements = {
        "__GENERATED__": generated, "__SUMMARY__": html.escape(summary),
        "__R1NAV__": money(r1.final_nav), "__R2NAV__": money(r2.final_nav), "__FEES__": money(r1.total_fees),
        "__CONCLUSIONS__": html_conclusions, "__METHODS__": html_methods,
        "__METRICS_TABLE__": metrics_table_html(metrics), "__IMAGE64__": image64,
        "__ANNUAL_TABLE__": annual_table(annual, as_html=True), "__SOURCE__": html.escape(source_note),
        "__LIMITS__": html_limits, "__FILES__": html_files,
    }
    for key, value in replacements.items():
        html_doc = html_doc.replace(key, value)
    (ROOT / "report.md").write_text(md, encoding="utf-8")
    (ROOT / "report.html").write_text(html_doc, encoding="utf-8")
    print(f"Wrote report.md, report.html and {CHARTS / 'nav_drawdown.png'}")
    print(f"Embedded PNG bytes: {(CHARTS / 'nav_drawdown.png').stat().st_size:,}; HTML bytes: {(ROOT / 'report.html').stat().st_size:,}")


if __name__ == "__main__":
    build()
