# RUNBOOK · 从零复现这场测评

> 命令用 Freqtrade 2026.6 官方 Docker 镜像。
> 下文的 `<模型目录>` / `<完整数据目录>` / `<样本外数据目录>` 换成你自己的路径。

---

## 0. 目录约定

关键在于**样本外数据要放在模型够不着的地方**:

```
<工作根目录>/
├── ft_kimi-k3/            ← 模型在这里工作,只挂 TRAIN+VALID 数据
├── ft_opus-5/
├── ft_fable-5/
├── ft_deepseek/
└── data_shared/           ← 只到 2025-06-30 的数据

<另一个盘符或另一个根目录>/
└── data_full/             ← 含 2025-07 之后的完整数据,揭盲时才挂
```

> **不要**把样本外数据放在工作根目录下面的任何位置。模型如果开了自动确认模式,
> 是会自己 `ls` 到处翻的。物理隔离比提示词约束可靠。

---

## 1. 准备环境

把 `scaffold/` 里的文件放进每个模型目录:

```
ft_<model>/
├── strategies/
│   ├── cross_sectional_base.py     # 横截面基类(含防未来函数的 shift)
│   └── ExampleXSMomentum.py        # 一个能跑通的最小示例
├── EP004ValidLoss.py               # 统一目标函数,不许改
├── export_hyperopt.py              # 把 hyperopt 结果导成标准 json
├── config.json                     # 由 base_config.json 改名而来
├── GOAL.md
└── README_FOR_MODEL.md
```

`base_config.json` 里已经定好 20 个标的、`fee 0.0006`、`max_open_trades 20`、
`dry_run_wallet 10000`、`StaticPairList`。**注意里面故意没有 `timeframe` 字段**——
它会覆盖策略自己的设置。

## 2. 下数据

```bash
docker run --rm -v "<模型目录>:/freqtrade/user_data" \
  freqtradeorg/freqtrade:stable \
  download-data --config /freqtrade/user_data/config.json \
  --timerange 20210101-20260701 \
  --timeframes 30m 1h 4h 1d --trading-mode futures
```

下完把 2025-07 之后的部分**移出去**,留一份完整的在别处。

## 3. 出题

进模型目录,启动它对应的 CLI,给一句话:

```
读 GOAL.md 和 README_FOR_MODEL.md,然后完成任务,别动脚手架。
```

然后就不要再干预了。四家收到的这句话必须逐字相同。

---

## 4. 验收:三段回测

三条命令只有 `--timerange` 不同。`<CLS>` 换成策略类名
(`KimiK3XSTrend` / `XSTrendEnsemble` / `XSRiskMomentum` / `DeepSeekMomentumXS`)。

**TRAIN**

```bash
docker run --rm -v "<模型目录>:/freqtrade/user_data" -v "<完整数据目录>:/freqtrade/user_data/data:ro" \
  freqtradeorg/freqtrade:stable backtesting --strategy <CLS> \
  --config /freqtrade/user_data/config.json \
  --cache none --fee 0.0006 --timerange 20210101-20240630 --export trades
```

**VALID** — 同上,`--timerange 20240701-20250630`

**TEST(揭盲)** — 同上,`--timerange 20250701-20260701`,**这一步才挂样本外数据目录**

> ⚠️ 三个参数每条都要带:
> - `--cache none`:默认缓存会复用旧结果,改了代码也看不出来(实测踩过)
> - `--fee 0.0006`:统一成本,覆盖模型自报的 fee
> - 数据目录挂对

> ⚠️ `--export-filename` 在 2026.6 上不生效,结果统一落在
> `backtest_results/backtest-result-<时间戳>.zip`。

### 看哪一行夏普

回测报告里有两个夏普:

```
Sharpe (closed trades)         -0.76   ← 按每笔交易算,持仓重叠时虚高
Sharpe (daily wallet balance)  -0.62   ← 按每日资金曲线算 ✅ 用这个
```

同时持仓 20 个的时候交易互相重叠,按每笔算会明显偏高。**全程用 daily wallet balance 那一行。**

---

## 5. 作弊检测

```bash
docker run --rm -v "<模型目录>:/freqtrade/user_data" -v "<完整数据目录>:/freqtrade/user_data/data:ro" \
  --entrypoint python freqtradeorg/freqtrade:stable \
  /freqtrade/user_data/factor_causality_check.py --strategy <CLS>
```

对同一时点用全量数据算一遍信号,再用截断到那一刻的数据算一遍。
**两次结果一致 = 因果 PASS;不一致 = 用了未来数据。**

自动识别策略类型:用脚手架的测 `factor_score`,自己写的测最终 entry/exit 信号。

> Freqtrade 自带的 `lookahead-analysis` 对横截面策略**会误报**——它把边界第一根 K 线的
> 排名变化当成 bias。本脚本的全量 vs 截断对照更可靠。

---

## 6. 统计检验(在宿主机跑,不进 Docker)

先在宿主机装依赖(和容器无关,建议开个 venv):

```bash
python -m pip install -r requirements.txt
```

**Deflated Sharpe**

```bash
python scripts/deflated_sharpe.py \
  --hyperopt <模型目录>/hyperopt_results.json \
  --backtest <模型目录>/backtest_results/
```

回答:以你这个搜索规模,纯靠运气能刷到多高的夏普?实际拿到的有没有超过它。

**蒙特卡洛**

```bash
python scripts/mc_bootstrap.py \
  --trades <模型目录>/backtest_results/ \
  --iters 5000 --block 10 --plot ./out/mc_<model>.png
```

对成交序列做分块自助重采样,给出终值为正的概率。

**搜索收敛 + 过拟合散点**

```bash
python scripts/hyperopt_plot.py \
  --input <模型目录>/hyperopt_results.json \
  --outdir ./out --tag <model>
```

---

## 7. 复现全部图表

四家都跑完之后:

```bash
python scripts/make_video_charts.py --out ./out
python scripts/make_metric_charts.py --out ./out
```

两个脚本里的常量已经填好本次实测值;想用自己的数据,改文件顶部的字典即可。
`make_metric_charts.py` 会直接读 `hyperopt_results.json` 和行情数据现算,不吃硬编码。

---

## 8. 成本统计(可选)

```bash
python scripts/usage_cost.py --dir <模型目录>
```

读 Claude Code 的本地会话日志,按公开单价折算等效成本。
**只对走 Claude Code 的模型有效**;走 API 的模型直接看厂商后台的逐请求明细。

> 口径差异要说清楚:走 API 的是真实扣费,走订阅的是「如果按 API 计费会花多少」的折算值。
> 另外各厂商缓存计价规则差异极大,跨厂商比较只看数量级,别抠到个位数。

---

## 常见坑

| 现象 | 原因 |
|---|---|
| 改了策略但回测结果不变 | 没加 `--cache none` |
| hyperopt 参数怎么调结果都一样 | 参数在 `populate_indicators` 里算的,`--spaces buy` 不会重新求值。要在 entry/exit 里算,或用参数签名做缓存键 |
| Git Bash 里挂载路径变成 `D:/softwares/freqtrade/...` | MSYS 路径转换,先 `export MSYS_NO_PATHCONV=1` |
| PowerShell 报 `&&` 不是有效分隔符 | Windows PowerShell 5.1 不支持,分两行写 |
| `lookahead-analysis` 报横截面策略有 bias | 已知误报,用 `factor_causality_check.py` 复核 |
| 策略的 timeframe 设置不生效 | `config.json` 里有 `timeframe` 字段会覆盖策略,删掉 |
