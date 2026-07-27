# EP001 · Claude 操控 Freqtrade 机器人

让 Claude Code 自己读配置、写策略、跑回测、再迭代——你只动嘴。

这期讲清两条路子的分工:
- **freqtrade-mcp**:把 Freqtrade 的 REST API 包成 MCP 工具,让 AI 用自然语言"遥控"一个已经在跑的 bot(查状态、启停、下单、改黑名单)。它是一组固定的"遥控按钮"。
- **Claude Code**:直接读写项目文件——改 `config.json`、写策略代码、跑 `download-data` / `backtesting`。想让 AI 帮你**开发**策略,得用这条路。

一句话:查状态、控盘用 mcp;写代码、跑回测用 Claude Code。

## 你需要什么

- Freqtrade(Docker 版最省事),一个 `user_data/` 项目目录
- Claude Code CLI
- (可选,做遥控演示)freqtrade-mcp:`github.com/kukapay/freqtrade-mcp`,MIT 许可,需 Python 3.13+ 和一个开了 REST API 的 Freqtrade 实例

## 怎么复现

1. 装好 Freqtrade,确认 `docker compose run --rm freqtrade --version` 能跑通。
2. 打开 Claude Code,进到 `user_data` 所在目录。
3. 把 [`prompts/claude-code-实操提示词.md`](prompts/claude-code-实操提示词.md) 里的四段依次贴进去:
   改配置 → 写策略(布林带 + RSI 均值回归)→ 下数据回测 → 加 ATR 移动止损再对比。
4. Claude Code 执行命令时会弹权限,点允许即可。

## 三个坑(照着做能少踩)

1. **timeframe 三处要一致**:`config.json`、策略的 `timeframe` 属性、下载/回测的周期,统一成 5m,否则报错或对不上。
2. **下数据慢且要联网**:建议先 `download-data` 把数据下好,再跑回测更顺。
3. **迭代要真做**:先自己跑一遍,确认"第一版回撤偏大 → 加 ATR 后改善"确实成立,别把没验证的改进当结论。

## ⚠️ 合规提醒

- 全程用 `dry_run: true`(模拟成交),不接真钱。
- 仅教学演示,不构成投资建议。历史回测不代表未来收益。
