# EP003 · Kimi K3 写量化策略

📺 看视频:[B站](https://www.bilibili.com/video/BV1Np3j6QEQc/) · [YouTube](https://www.youtube.com/watch?v=vNC-_rIajrw)

让 Kimi Code 写一个能做多也能做空的 ETH 永续合约策略,并且**严守样本内外纪律**——
TEST 段(最后一年)全程不许它碰,拿来当最终考卷。

结果:样本外 TEST 段 ETH 买入持有跌 36.7%,策略 +3.15%,**跑赢大盘约 40 个百分点**,
最大回撤 24.4%(大盘约 69%,只有三分之一)。但这一年样本 p-value=0.88——
**硬故事是"跑赢大盘 + 回撤砍到三分之一",不是"稳定赚钱"**。这期讲的就是这个分寸。

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

1. 按 [`prompts/kimi-code-prompt.md`](prompts/kimi-code-prompt.md) 先下好数据,再把「提示词正文」整段喂给 Kimi Code CLI。
   提示词里写死了三段划分、硬约束(必须真用 hyperopt、止损不得紧于 -10%、三种损失函数用 VALID 选)、
   未来函数禁令和自检步骤。
2. 等它交出策略 + 参数对比表 + 三种损失函数对比 + 平台判断。
3. 自己在 TEST 段跑一次 backtesting 验收:

   ```bash
   # 策略先放进 user_data/strategies/
   cp strategy/KimiK3StrategyV2.py <你的 freqtrade 目录>/user_data/strategies/

   docker compose run --rm freqtrade backtesting \
     --strategy KimiK3StrategyV2 --config user_data/config_eth30m.json \
     --timerange 20250701-20260701 --cache none
   ```

   > `--cache none` 必须带,否则改了代码结果也不变。
   > 看夏普用报告里 **Sharpe (daily wallet balance)** 那一行。

## 策略文件(结果)

[`strategy/KimiK3StrategyV2.py`](strategy/KimiK3StrategyV2.py) 是最终采用版,丢进 `user_data/strategies/` 就能回测:
趋势(EMA20/50 + ADX)+ 震荡过滤(Choppiness + EMA 间距/ATR),双向交易,宽止损,`leverage()` 固定 1x。TEST +3.15%。

> 其实还跑过一个基线版(TEST +4.71%,略好),但没用它——因为"看到两个结果再挑好看的那个",
> 本身就是在测试集上做选择,正是这期要批判的做法。所以采用完整跑完全流程的 V2。

## 两张证据图(脚本在 `scripts/`)

- [`scripts/plot_convergence.py`](scripts/plot_convergence.py) — **hyperopt 收敛曲线**,回答"800 轮够不够"。曲线早早走平就是够了的硬证据。
- [`scripts/mc_blockbootstrap.py`](scripts/mc_blockbootstrap.py) — **Block Bootstrap 蒙特卡洛**,按 10 天一块重采样重拼几百条资金曲线,测路径稳健性。

两个脚本都在**容器里**跑(读的是 `/freqtrade/user_data/...` 路径),先复制进去:

```bash
cp scripts/*.py <你的 freqtrade 目录>/user_data/

# hyperopt 收敛曲线 —— 读 user_data/hyperopt_results/,出 hyperopt_convergence.png
docker compose run --rm --entrypoint bash freqtrade -c \
  "pip install -q matplotlib; python /freqtrade/user_data/plot_convergence.py"

# Block Bootstrap 蒙特卡洛 —— 读 30m 的 feather 行情,出 mc_demo.png
docker compose run --rm --entrypoint bash freqtrade -c \
  "pip install -q matplotlib; python /freqtrade/user_data/mc_blockbootstrap.py"
```

宿主机不用装任何 Python 包;`numpy`/`pandas` 镜像里自带,只有 `matplotlib` 要临时补。

> 容器无中文字体,中文标题可能渲染不出。
> `mc_blockbootstrap.py` 内置的是演示用 EMA100 近似策略,换成你真实策略的日收益序列才是成品。

## 怎么诚实地看这个结果

- 真优点:跌市里靠**做空**(+121.66)扛起收益,多单是拖累(−90.12);而且这一年数据它从没见过。
- 别夸大:p-value=0.88(盈利在统计上跟 0 区分不开,有运气成分);profit factor=1.04(勉强站在盈亏平衡线);VALID 是亏的(−24.6%),三组损失函数在 VALID 上全亏。

## ⚠️ 合规提醒

仅教学演示,不构成投资建议,不是荐股。历史回测不代表未来收益,据此操作风险自负。
