# TradingAgents Studio

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](pyproject.toml)

[TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) 的增强套件：**不修改原项目任何文件**，为多智能体股票分析补上「读得完、推得出、比得了、看得见」四种能力。

## 1. 背景

[TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) 是一个优秀的多智能体 A 股分析平台——市场分析师、基本面分析师、多空研究团队、交易员、风控经理、投资组合经理轮番上阵，产出一份深度报告。但实际天天用它看盘时，有几个真实的痛点：

1. **报告读不完**：一次"全面"深度分析产出十几万字（光多空辩论就 7 万字），开盘前只有 5 分钟
2. **跑完不吭声**：分析要跑十几分钟，得自己开网页反复刷新看进度
3. **换模型太麻烦**：想对比不同模型的分析效果，只能一个个手动跑、手动抄数据
4. **辩论没法看**：多空双方几个回合的激烈交锋是报告里最有价值的部分，却只能翻终端日志

Studio 就是补这四块拼图的：**四个独立模块 + 一个统一命令行 + 一份集中配置**。

## 目录

- [1. 背景](#1-背景)
- [2. 功能](#2-功能)
  - [2.1 digest 开盘前简报](#21-digest-开盘前简报)
  - [2.2 notify 多渠道推送与定时](#22-notify-多渠道推送与定时)
  - [2.3 compare 多模型对比](#23-compare-多模型对比)
  - [2.4 replay 辩论回放](#24-replay-辩论回放)
- [3. 架构：零侵入集成](#3-架构零侵入集成)
- [4. 安装](#4-安装)
  - [4.1 本机直跑](#41-本机直跑)
  - [4.2 Docker 挂到已有部署](#42-docker-挂到已有部署)
- [5. 使用](#5-使用)
  - [5.1 推送渠道配置](#51-推送渠道配置)
  - [5.2 定时推送](#52-定时推送)
- [6. 开发](#6-开发)
- [7. 致谢](#7-致谢)
- [8. License](#8-license)


## 2. 功能

| 模块 | 解决的问题 | 一句话效果 |
|---|---|---|
| **digest** | 报告读不完 | 十几万字报告提炼成约 200 字开盘前简报（结论/信号/风险/动作四段式） |
| **notify** | 跑完不吭声 | 飞书卡片主动推送（股票名称 + 简报 + 详情按钮），cron 定时全管道自动化 |
| **compare** | 换模型太麻烦 | 一条命令让 N 个模型同题分析，产出耗时/token/成本/决策硬指标对比表 |
| **replay** | 辩论没法看 | 智能体辩论渲染成回放页：聊天流（多空一来一回）+ 多空对垒（分歧点两两配对）|

### 2.1 digest 开盘前简报

从原项目的报告产物中取全文（自动处理模型输出里的转义残留与 dict 转储），用 OpenAI 兼容接口的大模型提炼：

```
【结论】中性偏持有：中报数周内落地可免费裁决参数分歧，事件前不加仓也不割肉
【信号】现价88.90处布林13.1%分位超卖；RSI6=31.3接近超卖；缩量阴跌无恐慌抛售
【风险】中报跳空事件风险；收盘跌破87.80或引发止损盘连锁抛售，下看85整数关口
【动作】存量约15%仓位持有；收盘破87.80无条件清仓，反弹至90.5-92无量可减仓四分之一
```

### 2.2 notify 多渠道推送与定时

- 支持渠道：**飞书** / **钉钉** / **企业微信** / **Telegram** / **通用 JSON webhook**，可同时配多个、全部生效
- 同一渠道可推多个群（`feishu#盯盘群` / `feishu#决策群`），注册式扩展新渠道
- 卡片带股票名称与多空判断，底部按钮直达**完整报告页**（左侧子报告导航 + 右侧内容，手机为抽屉式目录）与**辩论回放页**
- `cron` 调度器常驻：工作日 09:30 自动 `分析 → 提炼 → 推送`，全程无人值守

### 2.3 compare 多模型对比

同一支股票、同一深度、同一批行情数据，让 N 个模型同题分析，自动采集硬指标产出对比表：

```bash
studio compare run 002594 -m glm-5.3,deepseek-v4-pro,kimi-k3 -d 标准
```

**前提**：参与的模型必须先在 TradingAgents-CN 里配置好（网页端「系统设置 → 大模型配置」添加，或直接写库），包含有效的 API Key 和接口地址；`capability_level` 要达到所选深度的要求，否则会被系统静默换成推荐模型。

#### 命令参数

```
studio compare run <股票代码> [选项]
```

| 参数 | 说明 |
|---|---|
| `-m, --models` | **必填**。逗号分隔的模型列表，可用别名（见下） |
| `-d, --depth` | 研究深度：快速/基础/**标准**/深度/全面，默认取配置 `compare.defaults.depth` |
| `-j, --concurrency` | 并发数，默认 2（原项目单用户并发上限 3，不建议超过） |
| `--date` | 分析日期 `YYYY-MM-DD`。**周末/节假日必须指定上一交易日**，否则数据链路会拿到空数据（上游对非交易日的处理缺陷） |
| `--dry-run` | 只打印执行计划，不真实调用（验证配置用） |
| `--out-dir` | 结果输出目录，默认 `data/exports/compare/` |
| `-c, --config` | 指定 studio.yaml 路径 |

#### 采集的指标

| 指标 | 来源 | 说明 |
|---|---|---|
| 状态 | 任务终态 | completed / failed |
| 总耗时 | 提交→终态 | 秒 |
| 报告字数 | 结果报告 | 字符数 |
| 输入/输出 token | 原项目用量统计 | 原项目未记录时为空（已知现状） |
| 成本 | `compare.prices` 单价 × token | 未配单价时为空 |
| 决策 | 最终裁决 | 买入/持有/卖出等 |
| 分步耗时 / 错误 | 任务步骤 | 附在 markdown 末尾 |

#### 输出物

每次运行产出四样：终端彩色表格、`markdown` 报告、`CSV`（Excel 直接打开不乱码）、SQLite 基准记录（`data/studio.db`，可回溯历史）。

#### 模型别名（compare.aliases）

接口层的模型 ID 往往是内部代号，对比表里却希望看到正式名。在 `studio.yaml` 配置别名后：**输入端**（`-m` 参数）与**输出端**（所有表格）都自动换算：

```yaml
compare:
  aliases:
    "<API模型ID>": "<显示名>"    # 例如智谱内测代号 -> 正式名
```

#### 实战示例

三模型对比比亚迪（同批 08-16 真实行情，glm-5.3 为全面深度，其余为标准深度）：

| 指标 | glm-5.3 | deepseek-v4-pro | kimi-k3 |
|---|---|---|---|
| 最终决策 | **持有**（¥96） | **买入**（¥92，战术性轻仓） | **卖出**（¥85，事件前规避） |
| 置信度 / 风险分 | 0.70 / 0.50 | 0.56 / 0.58 | 0.70 / 0.65 |
| 总耗时 | 3520s（全面） | 1066s | 1893s |

同一批数据、三种裁决，分歧焦点高度一致（止损位/压力区/财报事件）——说明差异来自模型的风险偏好与推理风格，这正是 compare 想暴露的东西。

#### 注意事项

- **真实消耗**：每个模型都是完整分析，token 按你的 key 计费；先用 `--dry-run` 验证，深度建议从「标准」开始
- **深度一致才可比**：耗时/报告字数跨深度没有可比性，决策与置信度可横向参考
- **推理模型的参数怪癖**：部分模型只接受特定参数（如 kimi-k3 仅 temperature=1），配置时留意上游报错
- 同股票同日的多次运行会互相覆盖原项目的文件产物；对比结果以 studio 落盘的 markdown/CSV 为准

### 2.4 replay 辩论回放

从研究团队报告的原始数据中**精确解析**出多空双方的轮次发言（不是靠猜），渲染成自包含单文件 HTML，可直接发给任何人：

- **💬 辩论实况**：聊天对话框，多头（红·右）空头（绿·左）一来一回，按轮分隔，长论点折叠展开，底部是研究经理裁决
- **⚔️ 多空对垒**：LLM 把双方论点按话题两两配对——左列多头怎么说、右列空头怎么说，保留关键价位与数字；每个任务只生成一次，落盘缓存

另支持完整分析时间线视图（各 agent 产出按流程分组、搜索、筛选、自动播放）。

## 3. 架构：零侵入集成

Studio 对 TradingAgents-CN **只读**，全部交互走三条通道，原项目一个文件都不用改：

```
┌──────────────┐   HTTP API（登录/发起分析/轮询/取报告/用量）
│              │◀──── MongoDB（可选，仅兜底）
│   studio     │   data/ 卷只读挂载（报告产物/辩论过程）
│              │────▶ 自己的 SQLite / 导出 HTML / 飞书
└──────────────┘
```

唯一的"写"是发起分析请求——与你在网页上点"开始分析"完全等价。

## 4. 安装

### 4.1 本机直跑

```bash
git clone https://github.com/frank-quant/TradingAgents-CN-studio.git studio
cd studio
pip install -e .
cp studio.yaml.example studio.yaml   # 填 api 密码 / llm key / 飞书 webhook
studio doctor                        # 自检：API/登录/数据卷/LLM/渠道
```

要求：Python ≥ 3.10，能访问到 TradingAgents-CN 的 Web 入口（默认 `http://localhost`）。

`studio.yaml` 关键配置：

| 段 | 作用 |
|---|---|
| `api` | 原项目地址与登录账号（密码可用 `${ENV}` 引用） |
| `llm` | digest/对垒配对用的大模型（OpenAI 兼容；`extra_body` 可传 `reasoning_effort` 等供应商参数） |
| `data.ta_dir` | 原项目 `data/` 目录路径（replay/辩论的数据源） |
| `notify.channels` | `feishu.webhook` / 通用 `webhook.url` |
| `notify.report_url_prefix` | 卡片按钮指向的报告服务地址（手机访问填局域网 IP） |
| `cron.jobs` | 定时任务：`schedule` + `symbol` + `depth` + `pipeline` |

### 4.2 Docker 挂到已有部署

在 TradingAgents-CN 的部署目录（有 `docker-compose.hub.nginx.yml` 的那个）：

```bash
git clone https://github.com/frank-quant/TradingAgents-CN-studio.git
docker compose -f docker-compose.hub.nginx.yml \
               -f TradingAgents-CN-studio/docker/docker-compose.studio.yml up -d studio
```

- 加入原项目网络，经 `http://nginx` 访问 API，不依赖宿主机端口（报告服务除外，默认发布 `8890`）
- 原项目 `data/` 卷**只读**挂载，studio 产物写自己的卷
- 不想要了 `down studio` 即可，原项目无感

## 5. 使用

```bash
studio doctor                                  # 自检
studio digest run --symbol 002594              # 提炼该股最近一次分析
studio digest run <task-id> / --file x.md      # 按任务 / 本地文件提炼
studio notify test                             # 向所有渠道发测试消息
studio notify send <task-id>                   # 推送简报卡片（带详情按钮）
studio compare run 002594 -m a,b,c --dry-run   # 对比（先 dry-run 验证计划）
studio replay debate <task-id>                 # 导出辩论回放（聊天流+对垒）
studio replay export <task-id>                 # 导出完整时间线回放
studio report serve --port 8890                # 报告详情服务（卡片按钮落点）
studio cron                                    # 常驻调度（容器里跑的就是它）
```

### 5.1 推送渠道配置

在 `studio.yaml` 的 `notify.channels` 下按需添加，**同时配多个全部生效**；键名支持 `渠道类型#别名` 让同一渠道推多个群：

| 渠道 | 配置项 | 在哪获取 |
|---|---|---|
| `feishu` | `webhook`（必填）、`secret`（开了签名校验才填） | 飞书群 → 设置 → 群机器人 → 添加**自定义机器人** |
| `dingtalk` | `webhook`（必填）、`secret`（安全设置选"加签"时必填） | 钉钉群 → 设置 → 智能群助手 → 添加**自定义**机器人 |
| `wecom` | `webhook`（必填） | 企业微信群 → 右键 → 添加**群机器人** |
| `telegram` | `token`、`chat_id`（必填）、`proxy`（国内网络需要） | `@BotFather` 创建 bot；拉入群后取 chat_id |
| `webhook` | `url`（必填） | 任意接收 `POST {title, body, markdown, buttons}` 的服务 |

```yaml
notify:
  channels:
    feishu:                 # 飞书主群
      webhook: https://open.feishu.cn/open-apis/bot/v2/hook/xxx
      secret: ""
    feishu#决策群:           # 同一渠道的第二个群（#后是别名）
      webhook: https://open.feishu.cn/open-apis/bot/v2/hook/yyy
    dingtalk:               # 钉钉群
      webhook: https://oapi.dingtalk.com/robot/send?access_token=zzz
      secret: SECxxx
```

配置后用一条命令验证（向所有渠道发测试消息，逐个报告成功/失败）：

```bash
studio notify test
```

> Telegram 在国内网络下需配置 `proxy`（如 `http://127.0.0.1:7897`）；飞书/钉钉/企微均使用群机器人 webhook，不需要创建企业应用。

### 5.2 定时推送

`studio.yaml` 的 `cron.jobs` 声明任务，调度器常驻后按 cron 表达式触发完整管道：

```yaml
cron:
  timezone: Asia/Shanghai
  jobs:
    - name: 早盘简报
      schedule: "30 9 * * 1-5"     # 工作日 09:30
      symbol: "002594"
      depth: 标准
      pipeline: [digest, notify]
```

之后每个工作日早上，飞书群会自动收到：**比亚迪(002594) 开盘前简报（中性）**，点按钮看全文或辩论回放。

## 6. 开发

```bash
pip install -e ".[dev]"
pytest                    # 冒烟测试：配置/存储/SSE解析/签名/裁剪，不依赖运行中的原项目
```

目录结构：`src/studio/core`（共享地基：配置 / API 客户端 / SQLite / 事件模型 / 文本清洗），四个业务模块与之平级、互不依赖；`docker/` 为部署补丁；`tests/` 冒烟测试。

### 6.1 开发工具

本项目由 **ZCode**（AI 编程智能体，https://z.ai）驱动 **GLM-5.3**（智谱 BigModel）全程辅助开发：从原项目 API 逆向分析、四模块设计实现、真实数据联调（以一次完整的比亚迪分析作为验收样本）到移动端适配，均在人机协作下完成。

## 7. 致谢

- [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) 及其上游 [TradingAgents](https://github.com/TauricResearch/TradingAgents)

## 8. License

MIT
