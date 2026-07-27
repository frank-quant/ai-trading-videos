# EP003 Kimi Code CLI 提示词（ETH · 30m · 三段划分）

> 复制「提示词正文」整段喂给 Kimi Code CLI。
> 这条 prompt 同时是图文引流资产，可整段放公众号/小红书。

## ✅ 环境已就绪（已验证可复现）

| 项 | 状态 |
|---|---|
| Freqtrade | 2026.6（Docker），`lookahead-analysis` / `recursive-analysis` 可用 |
| config | `user_data/config_eth30m.json`：futures / isolated / fee 0.0005 / **30m** |
| 交易对 | **ETH/USDT:USDT**（U 本位永续，可做空，杠杆 1x） |
| 数据 | 30m OHLCV 115766 根 + mark + funding_rate，2020-01 → 2026-07 |

> ⚠️ Git Bash 下容器内绝对路径会被转换，命令一律用相对路径 `user_data/config_eth30m.json`。

## 📊 ETH 买入持有基准（三段）

| 段 | 区间 | 买入持有 |
|---|---|---|
| TRAIN | 2020-01 ~ 2024-06 | +2569% |
| VALID | 2024-07 ~ 2025-06 | −27% |
| **TEST** | 2025-07 ~ 2026-07 | **−36.86%** |

**TEST 段 ETH 跌 36.9%——策略只要亏损明显小于它、或正收益，就是跑赢大盘。**

## 🎬 双版本并行（互不覆盖）

| | 策略名 | 状态 |
|---|---|---|
| **保底版** | `KimiK3Strategy` | ✅ 已验证 **TEST +4.71%**，文件在 `user_data/strategies/`，另有备份在 `user_data/_verified_eth30m/` |
| **新实验版** | `KimiK3StrategyV2` | 待 Kimi 生成，**写到新文件，不碰保底版** |

**hyperopt 有随机性，V2 的参数和结果不会等于保底版。** 可能更好，也可能更差。

**跑完 V2 的 TEST 后对比，不满意就直接用保底版录制：**

```bash
# 保底版（已验证 +4.71%）
docker compose run --rm freqtrade backtesting --config user_data/config_eth30m.json \
  --strategy KimiK3Strategy --timerange 20250701-20260701

# 新实验版
docker compose run --rm freqtrade backtesting --config user_data/config_eth30m.json \
  --strategy KimiK3StrategyV2 --timerange 20250701-20260701
```

> ⚠️ 保底版备份路径：`user_data/_verified_eth30m/`（含 README 说明恢复方法）。
> 万一 strategies 目录被弄乱，从那里拷回来即可。

---

## 🎬 步骤一：下载数据（这段要录）

在 `D:\freqtrade_demo\ft_userdata` 下执行。

**① 下载数据（就这一条）**
```bash
docker compose run --rm freqtrade download-data --config user_data/config_eth30m.json --exchange binance --pairs ETH/USDT:USDT --timeframes 30m --trading-mode futures --timerange 20200101-20260701
```
合约模式下，Freqtrade 会**自动连带下载 mark price 和 funding rate**（回测算持仓成本要用），不用单独跑。

**② 验证数据完整（录屏效果好，是张表）**
```bash
docker compose run --rm freqtrade list-data --config user_data/config_eth30m.json --trading-mode futures --show-timerange --pairs ETH/USDT:USDT
```

应看到（实测输出）：

| Pair          | Timeframe | Type         | From       | To         | Candles    |
| ------------- | --------- | ------------ | ---------- | ---------- | ---------- |
| ETH/USDT:USDT | 30m       | futures      | 2019-11-27 | 2026-07-05 | **115766** |
| ETH/USDT:USDT | 1h        | funding_rate | 2019-11-27 | 2026-07-03 | 7231       |
| ETH/USDT:USDT | 1h        | mark         | 2019-12-23 | 2026-07-04 | 57239      |

> `--pairs ETH/USDT:USDT` 是为了只显示 ETH。不加的话会把之前下的 BTC 也列出来，画面乱。

> ⚠️ **数据已经下好了**，跑第①条只做增量更新，几秒就完——录屏时会很快闪过。
> 想录「完整下载」的过程可以加 `--erase` 强制重下，但**没必要冒险**：
> 用第②条那张表展示数据完备性，画面更好也更安全。

---

## 🎬 步骤二：提示词正文

```
你是量化策略开发助手。我用 Freqtrade（Docker），你负责写一个能做多也能做空的
ETH 永续合约策略，并优化到能用。

## 环境
- 工作目录：D:\freqtrade_demo\ft_userdata
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

---

## 我要跑的命令（TEST）

```bash
docker compose run --rm freqtrade backtesting \
  --config user_data/config_eth30m.json \
  --strategy KimiK3StrategyV2 \
  --timerange 20250701-20260701 \
  --export trades
```

## ✅ 最终采用：`KimiK3StrategyV2`

| 指标 | TRAIN | VALID | **TEST（最终）** | ETH 买入持有 |
|---|---|---|---|---|
| 总收益 | +113.1% | −24.6% | **+3.15%** | **−36.72%** |
| Sharpe（平仓/日） | 0.22 | −0.60 | **0.08 / 0.26** | 负 |
| 最大回撤 | 49.4% | 39.6% | **24.39%** | ~69% |
| 交易笔数 | 533 | 99 | **110**（胜率 64.5%） | — |
| 多单/空单 | +1233 / −102 | −238 / −8 | **−90.12 / +121.66** | — |

**为什么用 V2 而不是保底版**：V2 是完整跑完全流程的那一版。
保底版（`KimiK3Strategy`，TEST +4.71%）虽然略好，但**看到两个结果再挑好看的那个，
就是在测试集上做选择**——正是本片要批判的做法。用 V2，流程干净。

> 保底版仍保留在 `user_data/strategies/` 和 `user_data/_verified_eth30m/`，作为对照留档。

### 📌 讲解时的诚实分寸

✅ **可以说**：ETH 跌 36.7%，策略赚 3.15%，**跑赢大盘约 40 个百分点**，
回撤 24.4%（大盘约 69%，只有三分之一），**而且这一年数据它从没见过**。
**跌市里是做空（+121.66）扛起了收益，多单是拖累（−90.12）。**

⚠️ **必须补的话**：
- `p-value = 0.88` —— 一年样本，**盈利在统计上跟 0 区分不开，有运气成分**
- `profit factor = 1.04` —— 勉强站在盈亏平衡线上
- **VALID 是亏的（−24.6%）**，最终测试才转正；三组损失函数在 VALID 上全部亏损
- **硬故事是「跑赢大盘 + 回撤砍到三分之一」，不是「稳定赚钱」**

### 🎬 Kimi 表现的高光（录制素材）

1. **三组在 VALID 全亏，它如实报告不硬凑**，并按规则 c 说明
2. **Sortino 组 TRAIN 最高（+258.1%）、聚簇最紧，VALID 却最差（−39%）**
   —— 「训练集收益最高的通常最脆」被第三次验证
3. **它主动排除了退化解**：Calmar 全局最优只有 53 笔、Sortino 只有 63 笔（近零交易刷高 Sharpe）
4. **2400 个 epoch 的 stoploss 全部合规**（[-0.300, -0.102]），它自己抽查确认
5. **它警告继续调参「只会进一步过拟合 TRAIN 牛市」**，建议改结构而非调参
