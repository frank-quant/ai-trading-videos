# EP003 · Kimi K3 写量化策略

让 Kimi Code 写一个能做多也能做空的 ETH 永续合约策略,并且**严守样本内外纪律**——
TEST 段(最后一年)全程不许它碰,拿来当最终考卷。

结果:样本外 TEST 段 ETH 买入持有跌 36.7%,策略 +3.15%,**跑赢大盘约 40 个百分点**,
最大回撤 24.4%(大盘约 69%,只有三分之一)。但这一年样本 p-value=0.88——
**硬故事是"跑赢大盘 + 回撤砍到三分之一",不是"稳定赚钱"**。这期讲的就是这个诚实分寸。

## 三段数据划分(纪律的核心)

| 段 | 区间 | 用途 | ETH 买入持有 |
|---|---|---|---|
| TRAIN | 2020-01 ~ 2024-06 | hyperopt 在这里优化 | +2569% |
| VALID | 2024-07 ~ 2025-06 | 只回测、不优化,用来选参数 | −27% |
| **TEST** | 2025-07 之后 | **最终考卷,Kimi 不许访问** | **−36.9%** |

## 环境

- Freqtrade 2026.6(Docker),`lookahead-analysis` / `recursive-analysis` 可用
- 交易对 ETH/USDT:USDT(U 本位永续,可做空,杠杆固定 1x),周期 30m
- config:futures / isolated / fee 0.0005 / 30m
- 数据:30m OHLCV + mark + funding_rate,2020-01 → 2026-07

## 怎么复现

1. 把 [`prompts/kimi-code-提示词.md`](prompts/kimi-code-提示词.md) 里「提示词正文」整段喂给 Kimi Code CLI。
   里面写死了三段划分、硬约束(必须真用 hyperopt、止损不得紧于 -10%、三种损失函数用 VALID 选)、
   以及未来函数禁令和自检步骤。
2. 等它交出策略 + 参数对比表 + 三种损失函数对比 + 平台判断。
3. 自己在 TEST 段跑一次 backtesting 验收(命令见提示词末尾)。

### 两张证据图(脚本在 `scripts/`)

- [`scripts/plot_convergence.py`](scripts/plot_convergence.py) — **hyperopt 收敛曲线**,回答"800 轮够不够"。曲线早早走平就是够了的硬证据。
- [`scripts/mc_blockbootstrap.py`](scripts/mc_blockbootstrap.py) — **Block Bootstrap 蒙特卡洛**,按 10 天一块重采样重拼几百条资金曲线,测路径稳健性。

> 注意:两个脚本读的是容器内路径,先复制到 `user_data/` 下再跑;容器无中文字体,中文标题渲染不出,建议剪辑里盖中文标题。`mc_blockbootstrap.py` 内置的是演示用 EMA100 近似策略,换成你真实策略的日收益序列才是成品。

## 讲解时的诚实分寸

- ✅ 可以说:跌市里靠**做空**(+121.66)扛起收益,多单是拖累(−90.12);而且这一年数据它从没见过。
- ⚠️ 必须补:p-value=0.88(盈利在统计上跟 0 区分不开,有运气成分)、profit factor=1.04(勉强站在盈亏平衡线)、VALID 是亏的(−24.6%)、三组损失函数在 VALID 上全亏。

## ⚠️ 合规提醒

仅教学演示,不构成投资建议,不是荐股。历史回测不代表未来收益,据此操作风险自负。
