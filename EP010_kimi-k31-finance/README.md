# EP010 · Kimi K3.1 Pro金融实测：提示词与交付物

本目录整理视频中的六个任务：宇树投委会、海力士财报、Meta估值、ETF回测、数据库财务筛选、Anthropic IPO问询。

先看实际提示词，再打开对应交付。所有模型交付原件保持原文件内容，阅读索引、统计与复核说明单独列出。

## 提示词与交付入口

| 顺序 | 任务 | 实际提示词 | 交付索引 | 主要成果 |
|---|---|---|---|---|
| 1 | 宇树科技投委会PPT | [查看](prompts/01_宇树科技投委会PPT.md) | [查看](deliverables/01_unitree_ic/README.md) | 投委会PPT、研究结构与页纲、数据出处台账 |
| 2 | SK海力士财报解读 | [查看](prompts/02_SK海力士财报解读.md) | [查看](deliverables/02_sk_hynix/README.md) | HTML业绩点评、Word业绩点评、Excel关键数据表 |
| 3 | Meta财务预测与DCF估值 | [查看](prompts/03_Meta财务预测与DCF估值.md) | [查看](deliverables/03_meta_model/README.md) | 季度预测与DCF模型、年度预测与DCF模型、季度模型文件说明 |
| 4 | SOXX／SPY／BIL轮动回测 | [查看](prompts/04_SOXX_SPY_BIL轮动回测.md) | [查看](deliverables/04_etf_rotation/README.md) | HTML回测报告、Markdown回测报告、回测代码 |
| 5 | 汽车产业链候选池财务筛选 | [查看](prompts/05_汽车产业链候选池财务筛选.md) | [查看](deliverables/05_auto_screen/README.md) | Excel筛选结果、筛选说明、提取后财务字段 |
| 6 | Anthropic IPO监管问询研究 | [查看](prompts/06_Anthropic_IPO监管问询研究.md) | [查看](deliverables/06_anthropic_ipo/README.md) | HTML问询研究报告、Markdown问询研究报告、来源清单 |

## 阅读方式

1. 从上表打开对应提示词，或查看[六任务提示词汇总](提示词汇总.md)。提示词正文来自实际发送的消息，不以准备模板替代。
2. 从交付索引进入PPT、Word、Excel、HTML或Markdown。HTML可在本地浏览器打开，相关资料保持原有目录结构。
3. Meta优先阅读季度模型；年度模型与季度模型同属一个任务，两个任务消息均予保留。
4. ETF的 `output/` 包含行情、分红、交易明细、依赖和代码；离线复现请在副本目录中按其运行说明操作。
5. [复核说明](docs/复核说明.md)、[工具插件Skill清单](docs/工具插件Skill清单.md)与[运行资源](docs/运行资源.csv)单独保存。

## 文件与提示词口径

- 按视频中的任务顺序命名，不使用执行批次标签。
- 各任务的资料日期以实际提示词为准，没有统一改成一个信息截止日。
- 插件选择从客户端标记中提取后另列；仅移除时间元信息和控制符，保留提示词正文。
- 原交付内容未改写；内部文件如含原执行环境的路径，仍按原件保留。
- 源文件与副本逐一SHA-256核对。完整指纹见[MANIFEST.json](MANIFEST.json)。

## 文件核对

共六个任务、七条实际任务消息、246个原始交付文件，合计约57.24 MiB。交付来自作者确认的案例原件目录，已逐一核对文件指纹。

Meta保留年度模型与季度模型，主要阅读季度模型，执行时间与Token按整个任务合计。工具、插件和Skill记录单独列在配套说明中。
