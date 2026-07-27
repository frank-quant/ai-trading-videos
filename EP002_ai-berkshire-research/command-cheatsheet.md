# ai-berkshire 命令速查

装好后按「你想干嘛」查命令。项目:https://github.com/xbtlin/ai-berkshire (MIT)

## 命令速查表

| 你想干嘛 | 命令 | 一句话 |
|---|---|---|
| 全面研究一家公司 | `/investment-research 腾讯` | 四大师综合分析 |
| 要多视角互相拆台 | `/investment-team 美团` | 并行独立 agent + 对撞 |
| 精读一份财报 | `/earnings-review 腾讯 2025Q4` | 只看一手财报,不抄二手研报 |
| 多视角解读财报 | `/earnings-team PDD 2025年报` | 四大师并行读财报 |
| 从全市场筛到 3 家 | `/industry-funnel AI算力` | 漏斗层层收窄 |
| 找行业机会 | `/industry-research 核电` | 产业链全景扫描 |
| 找供应链卡脖子环节 | `/bottleneck-hunter AI基础设施` | 瓶颈套利 |
| 快速排除烂公司 | `/quality-screen` | 7 指标去劣 |
| 核对一个财务数字 | `/financial-data` | 跨源交叉验证 |
| 深挖管理层 | `/management-deep-dive 王兴 美团` | 买股票就是买人 |
| 追踪已买的票有没有变差 | `/thesis-tracker 拼多多` | 论文追踪 |
| 论文有没有漂移 | `/thesis-drift 旧.md 新.md` | 分清事实变化与措辞变化 |
| 股价突然异动想知道为啥 | `/news-pulse 腾讯` | 异动归因 |
| 体检已有持仓 | `/portfolio-review 腾讯30%,美团20%,茅台20%,现金30%` | 组合优化 |
| 把研究写成公众号 | `/wechat-article` | 一键成文 |

> 完整约 19 个技能:深度研究 5 + 财报 2 + 行业筛选 5 + 组合管理 4 + 思维工具 3。以项目主页为准。

## 三条标准工作流(存下来)

- **研究单个公司**:`/investment-research` → `/financial-data`(核关键数)→ `/investment-checklist`(买入前清单)
- **筛一个行业**:`/industry-research` → `/industry-funnel` → `/quality-screen`
- **管已持仓**:`/thesis-tracker` → `/thesis-drift` → `/news-pulse`
- **财报季**:`/earnings-review`(单视角)/ `/earnings-team`(多视角)

## 避坑 Top 5

1. AI 报的数字一律用 `/financial-data` 交叉验证再信。
2. 团队类命令(`/investment-team`)更贵,先用便宜模型跑通流程。
3. 信息不足时看它的 A/B/C 评级,别把 C 级当结论。
4. 一次结果别当真——**可复现**才是价值,横向比多家。
5. 演示/自用都只作研究,不等于买入建议。
