# Qwen4-Max 实测｜从量化论文到可运行的交易策略

用 Qwen4-Max 和 Claude Code 复现 [Chain-of-Alpha](https://aclanthology.org/2026.findings-emnlp.506/) 的因子生成与优化流程。演示实验使用沪深 300 历史成分股、BaoStock 日线和次日开盘成交。

## 先选你要看的内容

- **我想跟着做一遍** → [视频里的五步提示词](prompts/五步执行提示词.md)。按顺序复制即可，先在一个新项目里做搜索、解读、初版与优化，冻结策略后再开封存评测。
- **我想看本次实际跑出来的文件** → [执行交付物](deliverables/README.md)。报告、候选账本、模型、逐日净值和逐笔成交都在这里。
- **我想用已经保存的模型复跑** → [复跑保存的策略](#复跑保存的策略)。

## 如何读结果

2014–2022 年训练，2023–2024 年验证与选版。最终揭盲使用 2025-01-02 至 2026-11-20 的行情，沿用已经保存的模型和公式。开发阶段保留 optC2 单因子作为研究候选，最终三版对照中 v2 的累计收益最高。

| 版本 | 最终揭盲累计收益 |
|---|---:|
| v1 两因子 LightGBM | −12.56% |
| v2 五因子 LightGBM | +11.71% |
| optC2 单因子 | +4.05% |
| 沪深 300 历史成分等权基准 | +7.44% |

累计收益从建仓前 100 万元起算。年化单边换手按策略账户的已成交买入额计算。结果供研究与教学。

## 复跑保存的策略

进入 `deliverables/` 目录运行 `python -m pip install -r requirements.txt`。代码和已保存模型可在本地运行回测，无需 Qwen API。行情数据由使用者准备，项目附有原始实验的清单与校验值。

| 用途 | 放置目录 | 对应行情 |
|---|---|---|
| 重载开发阶段的 optC2 | [data/](deliverables/data/) | 2013 年预热至 2024-12-31 |
| 用保存的模型跑三版样本外评测 | [evaluation/local_data_20261120/](deliverables/evaluation/local_data_20261120/) | 含 2024 年预热，评测至 2026-11-20 |

两处均需 `daily_bars.parquet`（`date`、`code`、原始 OHLC、`preclose`、`volume`、`amount`、`tradestatus`、`isST`、后复权 `adj_open`、`adj_high`、`adj_low`、`adj_close`、`adj_vwap`）和 `hs300_members.parquet`（`date`、`code`，历史月末成分快照）。新下载或不同供应商的行情可能与原快照不同，逐项复算原结果需要同一数据版本。直接检查已归档净值和成交明细无需原始行情。

```sh
# optC2 开发段重载，输出写入 deliverable/run_output/
python -I deliverable/run_strategy.py

# 样本外三版对照，输出写入 evaluation/reproduced_20261120/
python -I evaluation/run_three_versions_branch.py
python -I evaluation/report_branch.py
```

从头复现时，在单独的工作副本使用提示词，先准备开发数据，再准备封存评测数据。保存的候选批次、优化轮次和研究配置也可用于复查本次执行。
