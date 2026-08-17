# AI + 量化交易 · 视频配套仓库

用能跑通的代码和真实回测,讲清楚 AI 在量化交易里到底怎么用、哪里有坑。

这个仓库放每期视频的**配套资料**:提示词、可运行的代码/脚本,以及一份"怎么自己复现"的说明。频道在这两个平台:

- **B站(bilibili):[frank-quant](https://space.bilibili.com/3546589501066099)**
- **YouTube:[@frankquant](https://www.youtube.com/@frankquant)**

## 分期目录

| 期号    | 主题                                                     | 一句话                              | 配套            | 视频                                                                                                          |
| ----- | ------------------------------------------------------ | -------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------- |
| EP001 | [Claude 操控 Freqtrade 机器人](EP001_claude-freqtrade-bot/) | 让 Claude Code 自己写策略、跑回测、迭代       | 提示词 + 策略      | [B站](https://www.bilibili.com/video/BV1RhNA6jELx/) · [YouTube](https://www.youtube.com/watch?v=HXz_TcSSAMc) |
| EP002 | [AI 伯克希尔 · 四大师 AI 投研](EP002_ai-berkshire-research/)           | 别再直接问 AI「这股能不能买」,把它变成投研团队        | 命令速查          | [B站](https://www.bilibili.com/video/BV1nwKc6pEmi/) · [YouTube](https://www.youtube.com/watch?v=YtfBUUh4hnA) |
| EP003 | [Kimi K3 写量化策略](EP003_kimi-k3-strategy/)                    | 让 Kimi 写一个能做空的 ETH 合约策略,严守样本内外纪律 | 提示词 + 策略 + 脚本 | [B站](https://www.bilibili.com/video/BV1Np3j6QEQc/) · [YouTube](https://www.youtube.com/watch?v=vNC-_rIajrw) |
| EP004 | [四个大模型同一道量化题](EP004_four-llm-quant-benchmark/) | 同题同数据,四家写量化策略,扔进跌 45% 的样本外年份 | 题目 + 四家交付物 + 验证脚本 + 完整报告 | [B站](https://www.bilibili.com/video/BV15HMS6DETZ/) · [YouTube](https://youtu.be/eLvZ_S8D3jU) |
| EP007 | [用 GLM-5.3 搭 A 股投研工作流](EP007_glm53-tradingagents-workflow/) | 给多 Agent 交易框架补四个模块,每天早上自动推手机 | 提示词 + 四模块代码 + 复现步骤 | 〔待补〕 |

## 每期目录里有什么

- `README.md` — 这期讲了啥、怎么自己跑一遍,以及视频链接
- `prompts/` — 喂给 Claude Code / Kimi 的提示词原文,可直接复制
- `strategy/` — 这期跑出来的策略文件(有的话)
- `scripts/` — 可运行的辅助脚本(有的话)
- `submissions/` — 多模型对比类选题里,各家的完整交付物(有的话)
- `results/` — 实验结果与图表(有的话)

## ⚠️ 免责声明

本仓库所有内容仅用于**技术教学与演示**,不构成任何投资建议,也不是荐股。
所有回测/演示均为历史数据模拟,**历史表现不代表未来收益**。据此操作,风险自负。
