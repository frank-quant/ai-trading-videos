# EP003 · Kimi Code 提示词(ETH · 30m · 三段划分)

把下面「提示词正文」整段喂给 Kimi Code CLI。喂之前先按步骤一把数据下好。

## 环境前提

| 项 | 值 |
|---|---|
| Freqtrade | 2026.x(Docker),`lookahead-analysis` / `recursive-analysis` 可用 |
| config | `user_data/config_eth30m.json`:futures / isolated / fee 0.0005 / 30m |
| 交易对 | ETH/USDT:USDT(U 本位永续,可做空,杠杆 1x) |
| 数据 | 30m OHLCV + mark + funding_rate,2020-01 → 2026-07 |

三段基准(ETH 买入持有):TRAIN **+2569%** / VALID **−27%** / TEST **−36.9%**。
TEST 段策略只要亏损明显小于它、或正收益,就是跑赢大盘。

> Git Bash 下容器内绝对路径会被转换,`--config` 一律用相对路径 `user_data/config_eth30m.json`。

## 步骤一:下载数据

```bash
docker compose run --rm freqtrade download-data --config user_data/config_eth30m.json --exchange binance --pairs ETH/USDT:USDT --timeframes 30m --trading-mode futures --timerange 20200101-20260701
```

合约模式下会**自动连带下载 mark price 和 funding rate**(回测算持仓成本要用)。验证数据完整:

```bash
docker compose run --rm freqtrade list-data --config user_data/config_eth30m.json --trading-mode futures --show-timerange --pairs ETH/USDT:USDT
```

## 步骤二:提示词正文

> 里面的「工作目录」换成你自己的路径。

```
你是量化策略开发助手。我用 Freqtrade（Docker），你负责写一个能做多也能做空的
ETH 永续合约策略，并优化到能用。

## 环境
- 工作目录：<你的 freqtrade 工作目录>
- 所有命令通过 docker compose 执行，格式：docker compose run --rm freqtrade [子命令] --config user_data/config_eth30m.json ...
- --config 一律用相对路径，不要写 /freqtrade/... 开头的绝对路径（Git Bash 会转换出错）
- 市场：U 本位永续合约（futures, isolated），可做多可做空
- 交易对：ETH/USDT:USDT，周期 30m
- 数据已下载完毕（30m OHLCV + mark + funding_rate，2020-01 至 2026-07），无需 download-data
- 策略文件：user_data/strategies/KimiK3StrategyV2.py，类名 KimiK3StrategyV2

## 数据三段（严格遵守）

  TRAIN  20200101-20240630   hyperopt 在这里优化
  VALID  20240701-20250630   只回测、不优化，用来筛选参数
  TEST   20250701 之后        我保留的最终测试，你不许访问、回测或以任何方式利用

即使你判断"多用数据效果更好"，也不行。这条没有例外。

## 硬约束

1. 杠杆固定 1 倍
   策略实现 leverage() 返回 1.0。做空能力靠合约获得，不靠杠杆放大。

2. 必须真正用上 hyperopt
   用 IntParameter / DecimalParameter / CategoricalParameter 声明可优化参数，
   标注 space（'buy'/'sell'）。例：buy_rsi = IntParameter(20, 40, default=30, space='buy')
   ⚠️ 可优化参数不能放在 populate_indicators 里——hyperopt 不为每个 epoch 重算指标，
   放那里会一直用初始值，优化静默失效（不报错但等于白跑）。

   优化命令：
     --spaces buy sell roi stoploss
     --epochs 800
     --timerange 20200101-20240630
     --print-all
   跑完保留 user_data/hyperopt_results/，不要删。

3. 止损必须宽松，禁止紧止损
   30m ETH 日内波动大，紧止损会被噪声反复扫掉。
   用策略内【嵌套】的 HyperOpt 类覆盖搜索空间：

   class KimiK3StrategyV2(IStrategy):
       ...
       class HyperOpt:          # 必须嵌套在策略类内部，且不要继承 IHyperOpt
           @staticmethod
           def stoploss_space():
               return [SKDecimal(-0.30, -0.10, decimals=3, name='stoploss')]

   API 以本版 freqtrade 为准，但【止损不得紧于 -10%】必须落实。
   跑完抽查 .fthypt，确认所有 epoch 的 stoploss 都在 [-0.30, -0.10] 内。

4. 三种损失函数各跑一次，用 VALID 选
   在 TRAIN 上分别用 SharpeHyperOptLoss / CalmarHyperOptLoss / SortinoHyperOptLoss 跑三次。
   每组最优参数拿到 VALID（20240701-20250630）上回测。
   选择顺序：
     a) VALID 上不亏、且跑赢同期买入持有（−27%）的优先
     b) TRAIN→VALID 衰减小的优先
     c) 都不理想就如实说，别硬凑
   ⚠️ 训练集收益最高的那组通常最脆，不要因为它数字大就选它。
   ⚠️ ratio 类损失函数会偏好"近零交易"的退化解（只有几笔交易也能刷高 Sharpe），
      只在满足最低笔数要求的 epoch 里选。

5. 平台选参
   别取孤立最优 epoch。用 hyperopt-list 看最优解附近：参数成簇、loss 平滑的是平台，
   参数一动就崩的是尖峰，尖峰一律淘汰。报告里说明你选的是不是平台。

6. 预算：每种损失函数最多 800 epochs，整体最多 3 轮迭代。

7. 成本：fee 已设 0.0005，资金费率由 Freqtrade 自动计算。不许调低或关闭任何成本项。

## 策略设计

1. 双向交易
   can_short = True，用 enter_long/exit_long/enter_short/exit_short 信号列。
   上涨趋势 → 做多；下跌趋势 → 做空。

2. 趋势过滤（核心）
   用均线方向 + ADX 判断趋势：EMA20 与 EMA50 的相对位置、EMA50 斜率、
   ADX 超过阈值确认趋势强度。只在趋势明确时开仓，方向跟着趋势走。

3. 震荡过滤
   无趋势的横盘/缠绕行情里，多空信号会被反复打脸持续失血。加一层过滤让它空仓：
   - Choppiness Index 高于阈值 → 震荡 → 不开仓
   - 或 |EMA20−EMA50| 小于 N×ATR（均线缠绕）→ 不开仓
   阈值设成可优化参数交给 hyperopt。
   原则：宁可少开单错过机会，也不要在震荡里两头挨打。

4. 入场/出场
   入场：升势中价格回调后上穿 EMA20 做多（RSI 高于下限过滤崩跌）；
        跌势中反弹后下穿 EMA20 做空（RSI 低于上限过滤爆拉）。
   出场：RSI 极值或 EMA20/50 趋势翻转为主，ROI 阶梯止盈，宽止损兜底。
   不使用移动止损（trailing_stop = False）。

5. 开单笔数
   TRAIN 段多空合计不少于 250 笔（保证统计意义），不追求高频。

## 禁止（未来函数）

- 任何 shift(-n) / 负向 shift
- 用整段数据的全局统计量做阈值（df['close'].mean()、全局 quantile 等）
- 多周期合并引用未来 bar（必须用 merge_informative_pair）
- populate_entry_trend 中引用当根未收盘 K 线

## 自检（必做）

写完策略后执行，输出原样贴给我：

  docker compose run --rm freqtrade lookahead-analysis \
    --config user_data/config_eth30m.json \
    --strategy KimiK3StrategyV2 --timerange 20200101-20240630

  docker compose run --rm freqtrade recursive-analysis \
    --config user_data/config_eth30m.json \
    --strategy KimiK3StrategyV2 --timerange 20200101-20240630

报出 bias 先修再优化，不许跳过。
（注：lookahead-analysis 强制市价单，可能与 config 的 price_side:"same" 冲突。
  若被拒，可另建只改 price_side 的副本 config 供该工具使用，主 config 不要动。）

一致性验证：用选定参数在 TRAIN 跑一次 backtesting，结果应与 hyperopt best result 一致。
不一致说明参数没生效，必须排查。

## 交付物

1. 策略文件路径
2. 参数对比表：参数名 | 默认值 | 优化后值（每个可优化参数都列；仍等于默认值的标出来）
3. 三种损失函数对比表：
   | 损失函数 | TRAIN 收益/Sharpe/回撤 | VALID 收益/Sharpe/回撤 | 笔数 | 平台是否成簇 | 是否选中 |
   说明为什么选中那一组
4. 选定参数报告：TRAIN 和 VALID 各自的总收益、Sharpe、最大回撤、笔数、多单/空单盈亏
5. hyperopt 跑了多少 epochs、最优 epoch 在第几轮、平台判断依据
6. 优化出的固定止损是多少（须在 -10%~-30%）
7. 策略逻辑说明：趋势怎么判断、震荡怎么过滤、跌市里靠什么赚钱

现在开始，不用等我确认。
```

## 步骤三:TEST 段验收

Kimi 交付后,自己在从没让它碰过的 TEST 段跑一次回测:

```bash
docker compose run --rm freqtrade backtesting --config user_data/config_eth30m.json --strategy KimiK3StrategyV2 --timerange 20250701-20260701 --export trades
```
