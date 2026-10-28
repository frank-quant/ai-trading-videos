# SOXX / SPY / BIL 轮动回测交付说明

## 快速查看

- `report.html`：自包含图文报告，直接用浏览器打开。
- `report.md`：Markdown 报告。
- `equity_drawdown.png`：净值与回撤图。
- `summary_metrics.csv`：两档费率下策略与 SPY 买入持有的核心指标。
- `annual_returns.csv`：2020—2025 分年度收益。

## 明细数据

- `signals.csv`：72 次月度决策，含 2019 年末初始信号、60 日回看起止日期、复权价格、两项回报、目标持仓与执行日。
- `trades.csv`：逐笔买入/卖出，含股数、开盘价、成交额、费率、费用、现金流和信号。
- `dividend_reinvestments.csv`：每次除息日分红与收盘再投资增加股数。
- `daily_equity_drawdown.csv`：四个组合的日度资产、净值与回撤宽表。
- `daily_detail.csv`：四个组合的日度持仓、股数、现金、分红和资产长表。
- `data_validation.json`：交易日、信号、拆股、复权对账和独立行情源核验结果。

## 原始行情

`data/` 内含每只 ETF 的：

- `*_daily.csv`：2018-01-02 至 2025-12-31 日线 OHLC、复权收盘、成交量、分红和拆股。
- `*_corporate_actions.csv`：公司行动明细。
- `*_metadata.json`：数据源、精确请求 URL、抓取时间和口径。
- `raw/*_yahoo_chart.json`：Yahoo Finance 原始响应。
- `raw/SOXX_gtimg_qfq_kline.json`：独立腾讯前复权行情，用于日收益交叉检查。

本次报告使用随附数据快照，抓取日期为 2026-10-27。

## 复现方法

环境：Python 3.10 及以上。依赖安装：

```bash
python -m pip install -r requirements.txt
```

在本目录离线复算（不需要网络，结果对应随附数据快照）：

```bash
python backtest.py
```

重新下载行情并回测：

```bash
python fetch_data.py
python backtest.py
```

或在支持 `&&` 的终端中：

```bash
python fetch_data.py && python backtest.py
```

`fetch_data.py` 仅使用 Python 标准库；`backtest.py` 使用 pandas、numpy 和 matplotlib。供应商未来修订历史数据时，重新下载的结果可能略有变化。

复算后可再执行独立核验（会计恒等式、信号次日成交、仅换仓时交易、基准复权价复算等）：

```bash
python verify_results.py
```

核验结果写入 `verification_results.json`。

## 核心口径

- 每月最后交易日收盘后，以复权收盘计算 60 交易日总回报；次一交易日未复权开盘价成交。
- SOXX、SPY 取回报较高且为正者；相等且为正选 SPY；否则 BIL；持仓不变不交易。
- 初始资金 100,000 美元，允许碎股；基础单边费率 0.10%，压力情形 0.20%；换仓买卖分别收费。
- 分红在除息日收盘按收盘价再投资，不另收再投资费；当日先执行开盘换仓，再处理新持仓分红。
- Yahoo OHLC 和分红金额是拆股调整口径；SOXX 2024-03-07 的 3:1 拆股已计入。
- 2025-12-31 按收盘估值，不强制清仓；无滑点、价差、税费或分红预扣税。

本交付为历史规则回测，不构成投资建议。
