# EP001 · Claude Code 实操提示词

> 录屏/复现时照着贴,命令由 Claude Code 自己执行。默认在 `user_data` 所在目录下操作。

## 1. 改配置

> 读一下 user_data/config.json,帮我做三个改动:max_open_trades 改成 5;pair_whitelist 里加上 ETH/USDT;timeframe 改成 5m。改之前先用 diff 把要改的地方列给我看,我确认了你再写。

## 2. 写策略

> 在 user_data/strategies/ 下新建一个策略,类名 MyMeanReversion,继承 IStrategy。思路:布林带判断偏离(触下轨超卖进场、回中轨出场),再用 RSI 过滤(RSI 低于 30 才允许进场),带一个 3% 固定止损,timeframe 用 5m。把 populate_indicators、populate_entry_trend、populate_exit_trend 三个方法都填好,代码要能直接被 freqtrade 回测。

## 3. 回测

> 帮我给 MyMeanReversion 跑个回测。第一步,用 docker 下载 BTC/USDT、ETH/USDT 最近 180 天的 5 分钟数据。第二步,用 backtesting 回测 2026 年 1 月到 6 月这段,timeframe 5m。跑完把总收益、最大回撤、胜率、交易笔数提取出来,一句话总结好不好。

(Claude Code 会自动执行 `freqtrade download-data …` 和 `freqtrade backtesting …`,弹权限点允许)

## 4. 迭代

> 刚才这版最大回撤有点大。帮我加一个基于 ATR 的移动止损,别的逻辑不动。改完直接再跑一遍同样区间的回测,把新旧两次的收益和最大回撤放一起对比给我。

---

## 录制前三个坑

1. **timeframe 三处一致**:config、策略 timeframe 属性、下载数据/回测周期,统一 5m,否则报错或对不上。
2. **download-data 要联网且慢**:建议提前把数据下好,录的时候直接回测更顺。
3. **叙事要真实**:先私下跑一遍,确认"第一版回撤偏大 → 加 ATR 后改善"成立;不成立就换个能体现改进的调整,别硬编假改善。
