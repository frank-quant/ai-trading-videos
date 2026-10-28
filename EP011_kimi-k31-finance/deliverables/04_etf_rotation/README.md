# 第4个任务 SOXX SPY BIL轮动回测

按固定月度规则下载真实行情并回测，比较SPY基准与双倍交易费用，交付代码、报告和账本。

[任务提示词](../../prompts/04_SOXX_SPY_BIL轮动回测.md) · [全部案例](../../README.md) · [复核说明](../../复核说明.md)

## 主要交付

- [图文报告](output/report.html)

- [Markdown报告](output/report.md)

- [净值与回撤图](output/equity_drawdown.png)

- [原始回测代码](output/backtest.py)

- [原始交付运行说明](output/README.md)

## 阅读说明

原代码在换仓与除息日重合时存在分红权利归属错误。本包保留原始结果，尚未提供正式修正版。

这里的文件为当次原始交付；整理时没有修正财务数值、公式或交易规则。文件中原有的自检结论应结合本目录复核说明阅读。

视频顺序为第4项，对应原执行目录CASE05。`output/`内的相对结构保持不变。

## 离线复算原始结果

为避免覆盖本次归档，先复制整个`output/`到独立目录，再在副本中运行：

```bash
python -m pip install -r requirements.txt
python backtest.py
python verify_results.py
```

这些命令重现原始实现。`verify_results.py`检查文件和部分账务恒等式，没有覆盖已发现的分红权利归属错误；正式使用需修复规则并重跑。重新执行`fetch_data.py`会下载新快照，结果可能随供应商数据修订而变化。
