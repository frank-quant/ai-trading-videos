# 交付：Chain-of-Alpha 复现 — 研究候选可运行策略

> **状态：研究候选（research_candidate），非论文口径交付物。**
> 两个固定口径 LightGBM 版本（v1 年化超额 -7.0%、v2 -9.9%）验证段均为负超额。
> 本策略改用单因子百分位排序替代 LightGBM 合成器；**数据分段、股票池、交易规则、费率、基准与初版完全一致**。
> 验证段结果偏乐观（兼作选因子/早停），2025+ 行情未触碰，真正样本外留待最后。

## 策略

- 因子 optC2（低日内波幅60日·VWAP版）：`Sub(0, Mean(Div(Sub($high, $low), $vwap), 60))`
  - 血缘 b3_low_range_20 → optC1 → optC2；验证 RankIC 0.1212 / ICIR 0.4619。
- 合成：当日合格股截面百分位排序（单因子），取前 30，平局按同百分位确定性打破。
- 交易：收盘出信号、次日开盘成交；100万起、纯多头无杠杆、小数份额；首日≤30买，之后每日成功买卖各≤3；
  先卖后买、新仓≤开盘权益1/30；停牌/缺价/涨跌停阻塞；买0.03%卖0.10%；后复权成交估值、未复权前收估涨跌停。
- 基准：沪深300历史成分等权，月末信号次日开盘调仓，同费率同阻塞。

## 验证段表现（2023-01-03 ~ 2024-12-31）

| 指标 | 值 |
|---|---|
| 期末净值 | 1,573,330（+57.1%） |
| 年化超额（算术） | +19.55% |
| 信息比率 IR | 1.53 |
| 最大回撤 | -8.7% |
| 年化波动 | 14.4% |
| 年换手（单边） | ~8.0 |
| 费用 | 20,503 元 |

## 文件

- `strategy.json` — 公式、合成器、数据/标签/交易口径、验证指标（运行唯一入口配置）
- `scores_saved.parquet` — 保存的打分（float64），用于重载校验
- `nav.csv` / `trades.csv` / `metrics.json` — 验证段净值、逐笔成交、指标
- `config_snapshot.json` — 全局配置快照
- `run_strategy.py` — 自包含运行脚本
- `run_output/` — 最近一次重载运行的输出

## 如何运行（同口径行情）

在项目根目录（含 `coa/` 包与 `data/`）执行：

```powershell
python -I deliverable/run_strategy.py
```

脚本流程：从 `strategy.json` 重载公式 → 用 `coa.formula` 重新编译并在行情上求值 → 截面百分位 →
与 `scores_saved.parquet` 校验（max abs diff = 0，PASS）→ 跑 `coa.backtest` 同口径回测 → 写 `run_output/`。

换同口径行情：替换 `data/daily_bars.parquet`（date/code/未复权OHLC+preclose/volume/amount/tradestatus/isST/后复权adj_*）
与 `data/hs300_members.parquet`（date/code 月末快照），口径见 `config_snapshot.json`，重跑即可。
分段默认 2013 预热 / 2014–2022 训练 / 2023–2024 验证；改分段编辑 `config.json` 的 data 段。

## 重载验证

`python -I deliverable/run_strategy.py` 首行输出：
`[reload check] reconstructed vs saved scores: max abs diff = 0.000e+00 (PASS)`，
净值精确复现 1,573,330.1511814282。