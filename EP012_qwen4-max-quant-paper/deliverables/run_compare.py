"""Compare v1 / v2 / research-candidate and write output/optimization_report.md.

Usage: python -I run_compare.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from coa.data import ROOT


def load(tag):
    base = ROOT / "output"
    d = base / tag if tag else base
    m = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    tr = pd.read_csv(d / "trades.csv", parse_dates=["date"])
    fills = tr[tr["status"] == "filled"].copy()
    fills["notional"] = fills["price"] * fills["shares"]
    buys = fills[fills["side"] == "buy"]["notional"].sum()
    nav = pd.read_csv(d / "nav.csv", parse_dates=["date"])
    years = len(nav) / 252
    avg_nav = nav["strategy_nav"].mean()
    turnover = buys / avg_nav / years  # annual one-way turnover
    return m, turnover


def main():
    base = ROOT / "output"
    versions = [("v1 初版 (LightGBM 2因子)", ""), ("v2 优化 (LightGBM 5因子)", "v2"),
                ("研究候选 rc_single (optC2 单因子)", "rc_single")]
    rows = []
    for name, tag in versions:
        m, to = load(tag)
        s, ex, acc = m["strategy"], m["excess"], m["strategy_account"]
        rows.append({"版本": name, "期末净值(万)": round(s["final_nav"] / 1e4, 1),
                     "区间收益%": round(s["total_return"] * 100, 1),
                     "年化超额%": round(ex["annualized_excess_arithmetic"] * 100, 2),
                     "IR": round(ex["information_ratio"], 2),
                     "最大回撤%": round(s["max_drawdown"] * 100, 1),
                     "年化波动%": round(s["annualized_vol"] * 100, 1),
                     "年换手(单边)": round(to, 2),
                     "费用(元)": round(acc["fees_paid"]),
                     "买/卖笔数": f"{acc['buys']}/{acc['sells']}"})
    cmp = pd.DataFrame(rows)
    cmp.to_csv(base / "version_comparison.csv", index=False, encoding="utf-8-sig")

    lineage = (base / "lineage.md").read_text(encoding="utf-8")
    pool2 = json.loads((base / "v2" / "pool.json").read_text(encoding="utf-8"))
    L = []
    L.append("# Chain-of-Alpha 因子优化链 — 第二轮研究报告\n")
    L.append("## 1. 优化链设置\n")
    L.append("从初版实际结果挑 4 个有根据的种子：b3_low_range_20（冠军）、b4_max_lottery（入池第二）、"
             "b3_cc_vol（强但被相关闸挡）、b4_pv_diverge_amount（ICIR 差一步）。")
    L.append("按论文优化链：每次先写「为什么改/想改善什么」再跑数，读反馈再决定下一次。"
             "共 2 轮 8 个变体（≤20，每种子≤5）；父子公式、指标、淘汰原因全入 output/optimization_ledger.jsonl。\n")
    L.append("## 2. 代表性血缘（并排）\n")
    L.append("MAX 彩票链 b4_max_lottery → optD1 → optD2：\n")
    L.append("| | b4_max_lottery | optD1 | optD2 |")
    L.append("|---|---|---|---|")
    L.append("| 公式 | `Sub(0, Max($change,20))` | `Sub(0, Max($change,60))` | `Sub(0, Mean(Max($change,5),60))` |")
    L.append("| 为什么改 | 种子 | 回看20→60日，捕捉更完整炒作记忆 | 滚动5日最大值再60日均值，平滑极值 |")
    L.append("| val IC | 0.0872 | 0.0962 | **0.1104** |")
    L.append("| ICIR | 0.4269 | 0.4096 | **0.4618** |")
    L.append("| 换手 | 0.233 | 0.072 | 0.072 |")
    L.append("| 结果 | 过闸 | 过闸 | 过闸 |\n")
    L.append("完整 4 种子血缘见 lineage.md。关键修正：optA2 把量价背离 ICIR 从 0.193 抬到 0.2086（相关窗口10→20），"
             "补上量能轴；optB2 下行半偏差与冠军相关 0.736（去相关成功）；optC2 冠军 IC 0.1146→0.1212。\n")
    L.append("## 3. 重新入池（同口径）\n")
    L.append("合并初版+优化候选，同闸門（训练IC>0、验证IC≥0.015/ICIR≥0.20/覆盖≥70%/换手≤1.5、相关≤0.80、上限10）。")
    L.append(f"v2 入池 {len(pool2)} 个：" + ", ".join(p["id"] for p in pool2) + "。")
    L.append("optD2（IC 0.1104）因与 optC2 相关 0.891 被贪心序挡下；b2_low_range/b3_cc_vol 因与 optC2 相关≤0.80 反而入池。\n")
    L.append("## 4. 三版组合对比（验证段 2023–2024，同交易规则/基准/费率）\n")
    L.append(cmp.to_markdown(index=False))
    L.append("\n## 5. 因子改善有没有传导到组合？——没有（经 LightGBM）\n")
    L.append("- 因子层确实改善：optC2 IC 0.1212 > 初版冠军 0.1146；池子从 2 同族因子扩到 5 个含正交量能轴；LightGBM 早停 38→117 轮。")
    L.append("- 但 v2 组合年化超额 **-9.9%**，比 v1 的 -7.0% 更差。v2 合成分与冠军因子日截面 Spearman **-0.006**（几乎零）。")
    L.append("- 机制：LightGBM 按叶分裂拟合 R²≈1% 的弱信号，最高预测叶落在因子中段，单调排序被毁；因子越多噪声拟合容量越大，反而更差。")
    L.append("- 反证：把优化后的 optC2 直接做百分位排序（不经 LightGBM），同一交易规则下年化超额 **+19.5%**、IR 1.53、回撤 -8.7%，"
             "优于初版冠军单因子的 +14.4%。**因子改善经因子排序传导了，经 LightGBM 没有。**\n")
    L.append("## 6. 保留哪版 / 交付决定\n")
    L.append("- 两个固定口径 LightGBM 版本都弱（v1 -7.0%、v2 -9.9%），v2 不优于 v1 → 固定口径里保留 v1。")
    L.append("- 按用户许可，两版皆弱时交一版**明确标注为研究候选**的可运行策略：rc_single（optC2 单因子百分位排序）。")
    L.append("- 交付物在 deliverable/：strategy.json（公式+口径+参数）、scores_saved.parquet、nav/trades/metrics、"
             "自包含运行脚本 run_strategy.py。模型重载验证：从保存公式重建打分与保存分值 max diff = 0（PASS），净值精确复现。")
    L.append("- 研究候选不是论文口径交付物：它改了合成器（单因子排序替代 LightGBM），其余数据/股票池/交易/费率/基准与初版完全一致。")
    L.append("- 2025+ 行情未触碰；验证段兼作早停/选因子，研究候选结果偏乐观，真正样本外留待最后。\n")
    L.append("## 7. 如何运行交付策略\n")
    L.append("在项目根目录（含 coa/ 与 data/）执行：`python -I deliverable/run_strategy.py`。")
    L.append("脚本从 strategy.json 重载公式 → 重建百分位打分 → 校验与 scores_saved.parquet 一致 → 跑同口径回测，输出 deliverable/run_output/。")
    L.append("换同口径行情：替换 data/daily_bars.parquet 与 data/hs300_members.parquet（字段/复权/快照口径见 config.json），重跑即可。")
    (base / "optimization_report.md").write_text("\n".join(L), encoding="utf-8")
    print(cmp.to_string(index=False))
    print("\noptimization_report.md written")


if __name__ == "__main__":
    main()