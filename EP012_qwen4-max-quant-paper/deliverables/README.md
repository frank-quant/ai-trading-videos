# 本次实际执行交付物

这里保存了视频所用的研究文件和历史输出。五步提示词在 [prompts](../prompts/五步执行提示词.md)。

| 阶段 | 从这里打开 |
|---|---|
| 初版复现 | [初版报告](output/report.md) · [候选公式与指标](output/candidates.csv) · [候选账本](output/ledger.jsonl) |
| 因子优化 | [优化报告](output/optimization_report.md) · [父子公式和指标](output/lineage.md) · [优化账本](output/optimization_ledger.jsonl) |
| 冻结策略 | [v1 因子池](output/pool.json) · [v1 模型](output/lgbm_model.txt) · [v2 因子池](output/v2/pool.json) · [v2 模型](output/v2/lgbm_model.txt) · [optC2 公式与交易配置](deliverable/strategy.json) |
| 样本外揭盲 | [评测报告](evaluation/three_versions_branch_20261120/report.md) · [净值曲线](evaluation/three_versions_branch_20261120/nav_all_versions.png) · [三版对比表](evaluation/three_versions_branch_20261120/comparison.csv) · [逐日净值](evaluation/three_versions_branch_20261120/nav_daily.csv) |
| 逐笔成交 | [v1](evaluation/three_versions_branch_20261120/trades_v1.csv) · [v2](evaluation/three_versions_branch_20261120/trades_v2.csv) · [optC2](evaluation/three_versions_branch_20261120/trades_deliverable.csv) |

本目录也是复跑代码的项目根目录。行情字段、文件位置和运行命令见 [复跑说明](../README.md#复跑保存的策略)。
