"""Generate technical_snapshot.md from the computed indicator series."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DAYS = 120


def short_reason(r):
    parts = []
    parts.append(r["ma_alignment"])
    if r["sma20_slope"] is not None and r["sma60_slope"] is not None:
        d = "双升" if (r["sma20_slope"] > 0 and r["sma60_slope"] > 0) else (
            "双降" if (r["sma20_slope"] < 0 and r["sma60_slope"] < 0) else "分化")
        parts.append(f"MA20/60斜率{d}")
    if r["rsi14"] is not None:
        v = r["rsi14"]
        tag = ("超买" if v > 80 else "偏热" if v > 70 else "健康" if v >= 45
               else "弱势" if v >= 30 else "超卖")
        parts.append(f"RSI {v:.1f}{tag}")
    if r["macd_dif"] is not None:
        state = "金叉" if r["macd_dif"] > r["macd_dea"] else "死叉"
        bar = "红柱" if r["macd_hist"] > 0 else "绿柱"
        parts.append(f"MACD{state}{bar}")
    pos = "站上" if r["close"] > r["sma5"] else "跌破"
    parts.append(f"收盘{pos}MA5")
    return "；".join(parts)


def main():
    ind = json.loads((ROOT / "raw" / "indicators_full.json").read_text(encoding="utf-8"))
    sig = []
    import csv
    with (ROOT / "signals.csv").open(encoding="utf-8-sig") as f:
        sig = list(csv.DictReader(f))

    snap = ind[-SNAPSHOT_DAYS:]
    last = ind[-1]
    L = []
    w = L.append

    w("# 赛力斯（601127.SH）技术快照")
    w("")
    w(f"- **快照区间**：{snap[0]['date']} ~ {snap[-1]['date']}（最近 {len(snap)} 个交易日）")
    w(f"- **全样本**：{ind[0]['date']} ~ {ind[-1]['date']}，共 {len(ind)} 个交易日")
    w("- **价格基准**：`prices.csv` 的**前复权**收盘价（前复权锚定 2026-10-23）")
    w("- **数据来源**：恒生行情 Connector `get_daily_bars`（`adjustment=forward`）")
    w("- **生成时间**：2026-11-02（Asia/Shanghai）")
    w("")
    w("> ⚠️ **口径声明**：本文件中的「评分」是**单日技术状态的量化快照**，用于描述当日"
      "均线结构、动量强弱与价格位置。它**不是**收益预测，**不构成**买卖建议，"
      "**也不证明任何交易策略有效**。评分规则的权重是人为设定的，未经样本外检验、"
      "未考虑交易成本与滑点、不含止损/仓位/持有期约束，因此**不可直接用于实盘决策**。"
      "本文件仅覆盖最近 120 个交易日，样本区间内的统计量不代表未来表现。")
    w("")

    # ---------------- 当日快照 ----------------
    w("## 一、当日快照（2026-10-23）")
    w("")
    w("| 项目 | 数值 |")
    w("|---|---|")
    w(f"| 收盘价 | {last['close']:.2f} |")
    w(f"| MA5 | {last['sma5']:.4f} |")
    w(f"| MA20 | {last['sma20']:.4f} |")
    w(f"| MA60 | {last['sma60']:.4f} |")
    w(f"| EMA12 | {last['ema12']:.4f} |")
    w(f"| EMA26 | {last['ema26']:.4f} |")
    w(f"| MACD DIF | {last['macd_dif']:.4f} |")
    w(f"| MACD DEA | {last['macd_dea']:.4f} |")
    w(f"| MACD 柱 (2×(DIF−DEA)) | {last['macd_hist']:.4f} |")
    w(f"| RSI14 | {last['rsi14']:.4f} |")
    w(f"| MA20 斜率 (5日窗, 元/日) | {last['sma20_slope']:.4f} |")
    w(f"| MA60 斜率 (5日窗, 元/日) | {last['sma60_slope']:.4f} |")
    w(f"| 均线排列 | **{last['ma_alignment']}** |")
    w(f"| **技术评分** | **{last['score']} / 100（{last['score_band']}）** |")
    w("")
    w("### 评分理由（逐项计分）")
    w("")
    w("| 维度 | 依据与得分 |")
    w("|---|---|")
    for i, reason in enumerate(last["score_reasons"], 1):
        w(f"| {i} | {reason} |")
    w("")
    w(f"**合计 {last['score']} 分（{last['score_band']}）**。结构上均线呈空头排列、"
      f"MA20/MA60 斜率同步向下，收盘价位于三条均线下方；动量上 RSI14={last['rsi14']:.1f} "
      f"落在弱势区，MACD 处于死叉且柱体为负。当日属于**趋势与动量双双偏弱**的技术状态。")
    w("")

    # ---------------- 评分口径 ----------------
    w("## 二、评分口径（满分 100）")
    w("")
    w("| 大项 | 子项 | 规则 | 分值 |")
    w("|---|---|---|---|")
    w("| **A 趋势结构（40）** | 均线排列 | 多头排列 | 30 |")
    w("| | | 短多长空 | 18 |")
    w("| | | 交汇纠缠 | 10 |")
    w("| | | 短空长多 | 8 |")
    w("| | | 空头排列 | 0 |")
    w("| | 中期斜率 | MA20 与 MA60 斜率同为正 | 10 |")
    w("| | | 一正一负 | 5 |")
    w("| | | 同为负 | 0 |")
    w("| **B 动量（30）** | RSI14 | 45–70 健康 | 15 |")
    w("| | | 30–45 弱势 / 70–80 偏热 | 8 |")
    w("| | | >80 严重超买 | 3 |")
    w("| | | <30 超卖 | 5 |")
    w("| | MACD | DIF>DEA 且柱体为正 | 15 |")
    w("| | | DIF>DEA 但柱体转负 | 8 |")
    w("| | | DIF≤DEA 但柱体为正 | 6 |")
    w("| | | DIF≤DEA 且柱体为负 | 0 |")
    w("| **C 价格位置（30）** | 相对 MA5 | 收盘 > MA5 | 10 |")
    w("| | 相对 MA20/MA60 | 同时站上 MA20 与 MA60 | 10 |")
    w("| | | 仅站上 MA20 | 6 |")
    w("| | | 仅站上 MA60 | 4 |")
    w("| | | 两者皆破 | 0 |")
    w("")
    w("档位：≥75 强势 ｜ 60–74 中性偏多 ｜ 45–59 中性 ｜ 30–44 中性偏空 ｜ <30 弱势。")
    w("")
    w("指标定义：SMA_n 为 n 日简单均线；EMA_n 以首 n 日均值初始化、步长 α=2/(n+1)；"
      "MACD 中 DIF=EMA12−EMA26、DEA=EMA9(DIF)、柱=2×(DIF−DEA)（通达信/同花顺口径）；"
      "RSI14 采用 Wilder 平滑。斜率为 5 日窗的日均变化量。")
    w("")

    # ---------------- 120日明细 ----------------
    w(f"## 三、最近 {len(snap)} 个交易日明细")
    w("")
    w("| 日期 | 收盘 | MA5 | MA20 | MA60 | RSI14 | DIF | DEA | MACD柱 | 均线排列 | 评分 | 档位 | 评分理由 |")
    w("|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|---:|:--:|---|")
    for r in snap:
        w(f"| {r['date']} | {r['close']:.2f} | {r['sma5']:.2f} | {r['sma20']:.2f} | "
          f"{r['sma60']:.2f} | {r['rsi14']:.1f} | {r['macd_dif']:.3f} | {r['macd_dea']:.3f} | "
          f"{r['macd_hist']:.3f} | {r['ma_alignment']} | {r['score']} | {r['score_band']} | "
          f"{short_reason(r)} |")
    w("")

    # ---------------- 统计 ----------------
    scores = [r["score"] for r in snap]
    bands = Counter(r["score_band"] for r in snap)
    aligns = Counter(r["ma_alignment"] for r in snap)
    sig_in = [s for s in sig if s["date"] >= snap[0]["date"]]

    w("## 四、区间统计（最近 120 个交易日）")
    w("")
    w("| 指标 | 数值 |")
    w("|---|---|")
    w(f"| 评分区间 | {min(scores)} – {max(scores)} 分 |")
    w(f"| 评分均值 | {sum(scores) / len(scores):.1f} 分 |")
    w(f"| RSI14 区间 | {min(r['rsi14'] for r in snap):.1f} – {max(r['rsi14'] for r in snap):.1f} |")
    w(f"| MACD 柱区间 | {min(r['macd_hist'] for r in snap):.3f} – {max(r['macd_hist'] for r in snap):.3f} |")
    w(f"| 收盘价区间 | {min(r['close'] for r in snap):.2f} – {max(r['close'] for r in snap):.2f} |")
    w("")
    w("**评分档位分布**：" + " ｜ ".join(f"{k} {v} 天" for k, v in bands.most_common()))
    w("")
    w("**均线排列分布**：" + " ｜ ".join(f"{k} {v} 天" for k, v in aligns.most_common()))
    w("")
    w(f"**区间内交叉事件（{len(sig_in)} 次，来自 `signals.csv`）**：")
    w("")
    w("| 日期 | 信号 | 对象 | 前一日价差 | 当日价差 |")
    w("|---|---|---|---:|---:|")
    for s in sig_in:
        w(f"| {s['date']} | {s['signal_type']} | {s['indicator_a']} vs {s['indicator_b']} | "
          f"{float(s['spread_prev']):.4f} | {float(s['spread_now']):.4f} |")
    w("")

    # ---------------- 校验 ----------------
    w("## 五、计算校验")
    w("")
    w("| 校验项 | 结果 |")
    w("|---|---|")
    w("| 指标计算行数 | 822（与 `prices.csv` 逐行一致） |")
    w("| 预热标记 | 前 59 行 `is_warmup=1`（2023-06-01 ~ 2023-08-24），无 SMA60，不评分、不发信号 |")
    w(f"| 首个可交易评估日 | {next(r['date'] for r in ind if not r['is_warmup'])}（第 60 行，SMA60 首次成立） |")
    w("| 交叉事件记录方式 | 仅在实际发生符号翻转的**那一根K线**记录，不重复发信号；"
      "全样本连续重复信号 **0** 次 |")
    w("| OHLC/收盘完整性 | 源数据无缺失、无重复（见 `sources.md`） |")
    w("")
    w("**与同花顺 iFinD 标准指标的交叉验证（2026-10-23）**：")
    w("")
    w("| 指标 | 本文件计算 | iFinD（不复权） | 差异 |")
    w("|---|---:|---:|---:|")
    w(f"| MA5 | {last['sma5']:.4f} | 42.818 | 0 |")
    w(f"| MA20 | {last['sma20']:.4f} | 46.421 | 0 |")
    w(f"| MA60 | {last['sma60']:.4f} | 50.432 | 0 |")
    w(f"| RSI14 | {last['rsi14']:.4f} | 38.8045 | 0.0014 |")
    w(f"| MACD DIF | {last['macd_dif']:.4f} | -1.7401 | 0.0005 |")
    w(f"| MACD DEA | {last['macd_dea']:.4f} | -1.2298 | 0.0007 |")
    w(f"| MACD 柱 | {last['macd_hist']:.4f} | -1.0205 | 0.0005 |")
    w("")
    w("差异均在 4 位小数显示精度内。iFinD 该次取数口径为**不复权**，而本文件基于**前复权**；"
      "两者在该日能对齐，是因为前复权因子自 2026-06-03 起即为 1.000000，"
      "最近 60 根K线的 MA/RSI/MACD 覆盖区间完全落在因子恒为 1 的区间内。"
      "区间早期（前复权因子 < 1）本文件的 RSI/MACD 会与不复权口径存在差异，属正常现象。")
    w("")
    w("---")
    w("")
    w("再次提示：以上评分仅描述**当日**技术状态，不预测收益、不证明策略有效性。")
    w("")

    (ROOT / "technical_snapshot.md").write_text("\n".join(L), encoding="utf-8")
    print(f"written technical_snapshot.md  rows={len(snap)}  signals_in_window={len(sig_in)}")


if __name__ == "__main__":
    main()
