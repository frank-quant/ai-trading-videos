# GPT-6 Astra · 完整成绩单

> 考场 `ft_gpt_6_astra` ｜ harness **Codex Desktop** ｜ 策略类 `CausalRelativeMomentum`
> ⚠️ 本次跑在 `reasoning_effort = ultra`，Astra 的官方默认档是 `low`（见 §六）。
> **这是刻意设计的「极限档位」**：最新模型 + 最高思考强度能做到什么程度。
> 它是该型号本季唯一的跑次，**入主榜并标注档位**，跟其他线的「各自默认档」不完全同口径。


> ℹ️ 这份成绩单是**跑完这一家的当天**写的，文中「X 家最…」一类说法，口径是**写作当时已经跑完的那几条线**，不是最终的 14 个模型。
> 全场口径的权威数字看 [`results/dataset_全量汇总.json`](../../results/dataset_全量汇总.json) 和 [`results/EP007_综合排名.md`](../../results/EP007_综合排名.md)。
---

## 一、选择

| 项 | 值 |
|---|---|
| timeframe | **4h** |
| 策略家族 | 横截面（波动率标准化的滞后相对动量 + 排名迟滞） |
| 实际轮数 / 上限 | **160 / 2000** |
| 搜索结构 | **三个策略族串行搜**：trend 89 轮 → reversal 45 轮 → momentum 26 轮 = 160 |
| 是否取 argmax | ✅ 是（e144，valid 排名 **1/160**，train **−0.0340** / valid **0.5766**，落差 −0.61） |
| 参数记录 | ⚠️ 自造路径 `config.json → strategy_parameters`（见 §三，**已实测确认生效**） |
| 交付物 | 6 件齐全 + `strategies/work/` 下 25 个自查文件 |

---

## 二、硬门槛与作弊检测

| 项 | 结果 |
|---|---|
| 6 交付物 / 考卷文件 MD5 | ✅ 全过 |
| metrics.json schema + seed | ✅ 键齐全，`seed: 20260906` |
| fee 未偷改 | ✅ `valid_ownfee` +16.79% == `valid` +16.79%（自报 `fee_bps: 6.0`，就是规定值） |
| 杠杆 | ✅ 1x |
| 双向 | ✅ 自报 TRAIN 5083 多 / 6600 空；VALID 1505 多 / 1821 空 |
| **未来函数** | ✅ **PASS**，`max \|full − truncated\| = 0.000e+00`（200 个对比点，标准截断法直接跑通） |
| 越界读锁定数据 | ✅ 全目录扫描无痕迹 |
| 自报 vs 复现（考题口径） | train −0.0340 vs **−0.0226**；valid 0.5766 vs **0.5517** → 差异来自分段边界口径，**非虚报** |

### hyperopt_results.json 完整性（逐条核过）

自报「160 轮、137 个不同参数字典、三族 89/45/26」——**全部对上**：

```
trials=160  epoch 1..160  唯一=160  连续=True
  ('atr_buffer','entry_days','exit_days','trend_day…')  ×89   trend
  ('rank_buffer','reversal_bars','side_width')          ×45   reversal
  ('momentum_bars','rank_buffer','side_width')          ×26   momentum
  distinct 参数字典 = 137（自报 137）✅
  缺分数的 trial = 0
```

> **值得说**：它把**三个被枪毙的策略族的全部试验**都合并进了同一份 `hyperopt_results.json`，
> 而不是只交最终族的 26 轮。考题要求是「EVERY hyperopt trial」，它是全场唯一一个
> 把「我换过赛道」这件事也算进搜索预算里的。DSR 因此按 **N=160** 算而不是 26 —— **它自己主动要求的**。

---

## 三、`strategy_parameters`：一个自造的参数加载路径

Astra 没用 Freqtrade 标准的 `<策略名>.json` 参数文件（run.md 明说 "No parameter sidecars are used"），
而是往 `config.json` 里塞了一个框架根本不认识的键：

```json
"strategy_parameters": { "CausalRelativeMomentum": { "momentum_bars": 12, "rank_buffer": 0.1, "side_width": 7 } }
```

然后在策略 `__init__` 里、**`super().__init__(config)` 之后**把它写进 `self.buy_params`。

**第一反应是「这不生效」** —— 参数加载看起来早就在 `super().__init__` 里做完了。查了框架源码才知道不是：

- `HyperStrategyMixin.__init__` 只读参数文件，注释写着 *"Init/loading of parameters is done as part of ft_bot_start()"*
- 真正赋值的 `ft_load_hyper_params()` 在 **`ft_bot_start()`** 里跑，晚于 `__init__`
- 它的优先级是 **参数文件 > `buy_params` > 默认值**，而 Astra 没交参数文件 → `buy_params` 生效

**实测确认**（复现回测日志）：

```
freqtrade.strategy.hyper - INFO - Found no parameter file.
freqtrade.strategy.hyper - INFO - Strategy Parameter: momentum_bars = 12      ← 已应用
freqtrade.strategy.hyper - INFO - Strategy Parameter: rank_buffer  = 0.1      ← 已应用
freqtrade.strategy.hyper - INFO - Strategy Parameter: side_width   = 7        ← 已应用
freqtrade.strategy.hyper - INFO - Strategy Parameter(default): n_long = 5     ← 冻结项走默认
```

**结论：非常规但正确。** 它读懂了框架的初始化时序，踩在一个很窄的窗口上。
考题只要求「把最终参数记录在 config.json 里」，它照做了，只是用了自己的接线。

> **我以为抓到 bug 了，查完源码发现是我错了。**

---

## 四、成绩

### 揭盲（TEST 2025-07 ~ 2026-07）

| 指标 | 值 |
|---|---|
| 总收益 | **−4.95%** |
| Sharpe（daily wallet balance） | **−0.23** ← **14 个模型里第 2** |
| Sortino | −0.30 |
| 最大回撤 | 22.38% |
| Mean profit p-value | 0.7492 |
| 成交笔数 | 3407 |
| 基准（20 币等权） | **−44.95%** |

### 三段 + 两个压力位

| 段 | 收益 | Sharpe |
|---|---|---|
| TRAIN | −2.54% | 0.08 |
| VALID | +16.79% | 0.68 ← **自报 valid 全场垫底** |
| **TEST** | **−4.95%** | **−0.23** ← **揭盲全场第 2** |
| valid @ 2× 费率 | **−3.77%** | −0.02 |
| valid @ 自报费率 | +16.79% | 0.68（同 valid，未偷改） |

### alpha / beta 归因

| 项 | 值 | 位次 |
|---|---|---|
| beta | **0.061** | 全场第 2 低 |
| R² | 0.072 | 第 2 低 |
| 净敞口 | **0.6%** | **全场最低** |
| alpha（年化） | −1.7% | 第 5 |
| beta 拖累 | −2.7% | 第 2 小 |

> −4.95% 里只有 −2.7% 是市场拖累。**它是全场做得最接近真中性的一家**（净敞口 0.6%，其他家 8%~39%）。

### 统计显著性

| 项 | 值 | 判定 |
|---|---|---|
| DSR（N=160） | **0.2031** | ❌ 不显著 —— 大概率是搜出来的运气 |
| 蒙卡盈利概率 | 0.0468 | ❌ 5000 次 block bootstrap 只有 4.7% 路径盈利 |

---

## 五、费率敏感性：它自己预测准了

self_assessment 里写的静态估算：

> *"another 1 bp per side would consume approximately 373 USDT, or **22% of validation net profit**"*

按此外推，每边多 6bp ≈ 吃掉 132% 的利润 → 应该翻负。

**实跑 `valid_2xfee`：+16.79% → −3.77%，吃掉 122%。**

它没跑这个回测（明说是 "a static diagnostic, not a changed-fee backtest"），纯靠换手率和 profit factor 推出来的，误差 10 个百分点以内。

> **这是本季最漂亮的一次自我诊断**：一个模型准确预言了自己的策略会死在哪儿，还标注了这只是估算不是实测。

---

## 六、档位：为什么要单独标注

会话日志 `turn_context.reasoning_effort = ultra`，三个会话全是。
而 `~/.codex/models_cache.json` 里 **`gpt-6-astra` 的 `default_reasoning_level = "low"`**。

**这是刻意的。** 这条线要回答的不是「GPT-6 默认状态下多强」，
而是**「最新的模型 + 最顶级的思考强度，上限在哪」**。
它是该型号本季唯一的跑次，所以入主榜，但榜上必须写明 `ultra` ——
跟其他线的「各自默认档」不是完全同一个口径。

### 它「取了 argmax」，但其实没得选

逐族拆开看它的 160 轮：

| 族 | n | train 中位 | train 最好 | valid 中位 | valid 最好 | train>0 占比 |
|---|---|---|---|---|---|---|
| trend | 89 | +0.713 | +0.998 | −0.352 | **+0.086** | 100% |
| reversal | 45 | −1.476 | −1.128 | −0.920 | +0.210 | 0% |
| momentum | 26 | +0.120 | +0.834 | −0.381 | **+0.577** | 57% |

**整个搜索空间里没有一个 train / valid 双正的点。** valid 前 10 名里 8 个 train 是负的。
别家那种「往下挑一个折中解」的操作，它做不了 —— 它的搜索空间里压根没有折中解可挑。

另外注意：**反向落差 < −1.5 的比例是 0/160（三个族都是 0%）**。
这跟 GLM-Flash（48%）、Qwen（15%）是完全不同的病 —— Astra 的空间不是「遍地病态解」，而是「压根没搜出东西」。

---

## 七、成本

| 项 | 值 |
|---|---|
| 模型 | `gpt-6-astra`（会话日志 `turn_context.model` 核实） |
| effort | `ultra`（刻意，非默认档；默认是 `low`，见 §六） |
| 会话数 | 3（**并行**，11:31 / 11:32 / 11:32 同时起） |
| 合计 token | **7,795,215** |
| 未命中输入 | 243,243 × $10/M |
| 缓存命中 | 7,493,888 × $1/M（命中率 **96.1%**） |
| 输出 | 58,084 × $50/M（含 reasoning 17,060） |
| **成本** | **$12.8305 = ¥92.38** ← 14 个模型里第 2 贵，仅次于 Opus 5 的 ¥363 |

口径：Plus 订阅无逐笔账单，按会话日志 `total_token_usage` × 官网目录价折算**等效成本**。
Astra 缓存写单价 $12.5/M 比未命中输入 $10/M 还贵，不能按常规 1.25× 估 —— 本次 `cache_write = 0`，不影响。

⚠️ 3 个 `codex-auto-review` 会话（541,913 + 87,676 + 175,241 token）**未计入**，与其余 GPT 各线口径一致。

---
