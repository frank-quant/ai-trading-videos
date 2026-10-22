# EP010 · 用 Workflow 做 A 股策略研究

把策略假设、代码执行、独立审核、八层筛选、随机对照和报告交付串成一套研究流程。提示词用于驱动执行角色，代码负责计算，规则负责约束。

本目录同时提供**可以从头执行的研究工程**和**本次实验结果**。两者分开存放，新研究不会自动带入已有名单、台账或收益。

## 从这里开始

- **从零做研究**：[八步操作手册](research/EP010_操作手册.md) → [研究规则](research/rules.md) → [交易者画像](research/profile.md)。先把 `research/` 整体复制到本公开仓库以外的新目录，按手册初始化本地Git，再在该目录执行。
- **直接看实验**：[结果报告](results/研究结果.md)，包括最终漏斗、六条候选、测试集收益曲线、随机对照和局限。
- **下载最终交付**：[PPT与Excel](results/reports/README.md)，来自本期采用的复跑补检后最终交付；保留原文件展示，阅读时注意配套说明中的精度与统计口径提示。
- **核对结果**：在本目录运行 `python verify_results.py`。只用 Python 标准库，不需要 Token、行情数据或大模型，不发起下载。
- **查看核验范围**：[公开材料核验](VERIFICATION.md)。

## 目录

```text
research/                  独立研究工程，启动时没有历史运行状态
  EP010_操作手册.md         环境准备与八步完整提示词
  rules.md / profile.md    规则与示例交易者约束
  AGENTS.md                执行角色纪律
  engine/ / parts/         回测、零件、漏斗、随机生成与组合
  tests/                   未来数据截断、封存守卫与测试配置
  tools/                   数据下载、数据体检、隔离检查、性能工具
  configs/ / docs/          日期设定、数据说明、命令速查
  requirements.txt         案例环境依赖锁定
results/                   本次实验的只读参考归档
  研究结果.md               完整结论及解释边界
  reports/                本期最终PPT与Excel、来源及原文件阅读提示
  funnel_counts.csv        最终八层计数
  funnel_layers.json       最终逐配置判定与全局相关性去重
  shortlist_*.json          六席名单、等级、资格与未过层
  strategies/              六条入围YAML
  strategy_catalog.jsonl   全部研究配置与探针归档，不自动导入工程
  ledger.csv               全部23904条执行记录，含错误和重试
  search_base_metrics.csv  搜索期基础配置的最新记录
  search_distribution.json 搜索分布与两种随机汇总口径
  test_returns/            六条候选的424天策略/基准日收益
  candidate_returns/       六条候选搜索/验证期日收益
  test_metrics.json        从日收益计算的测试集指标
  portfolio_*.json         两组60/40组合三段指标
  diagnostics/             IC、换手、容量、衰减与行业诊断
  figures/                 测试集收益曲线PNG/SVG
  data_manifest.json       案例行情文件指纹，不含原始行情
  provenance.json          来源指纹、口径与必要研究时序说明
MANIFEST.json              公开文件SHA256清单
verify_results.py          无数据下载的结果核对入口
```

## 复现范围

推荐64位 Python 3.14。完整研究需要自己的 Tushare Pro Token、对应接口权限、GB级数据空间、足够内存，以及能执行文件和代码的 AI 工具。下载入口只有一个 Python 脚本；原始供应商行情、凭据、虚拟环境、缓存、个人路径和会话运行记录不随仓库分发。

`/workflow` 提示词针对 ZCode 使用；其他工具需提供相同的执行与独立审核能力。第8步可使用已安装的表格/PPT插件，插件不是回测计算依赖。

这里有两种不同的复现：附带日收益可以直接复算本次结果；重新下载行情、让 AI 再做六轮搜索则属于新实验。数据修订、模型随机性、零件注册时点、生成顺序和试验台账会影响结果，不能保证重新搜索仍得到相同六席或收益。已看过本目录结果，再评估同一历史区间，也不构成新的未知行情盲测。

公开仓库会忽略 `research/` 的本地运行产物，避免混入案例归档；因此不要在此处执行手册中的阶段提交。独立副本内的 `.gitignore` 会保留候选、台账、报告及数据清单的本地版本记录，同时排除原始行情、凭据和缓存。本地提交用于冻结研究状态，不自动推送。

本次严格通过全部八层的策略为 **0**；007、067、068 是研究入围候选。完整解释见结果报告。材料仅供研究，不构成投资建议。许可证沿用仓库根目录 [MIT License](../LICENSE)。
