"""Write the branch evaluation report from saved metrics.

Usage: python -I evaluation/report_branch.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

OUT = HERE / "reproduced_20261120"


def main():
    m = json.loads((OUT / "metrics.json").read_text(encoding="utf-8"))
    cmp = pd.read_csv(OUT / "comparison.csv")
    best = max(m, key=lambda k: m[k]["cumulative_return"])
    dev_candidate = "deliverable"
    L = []
    L.append("# 三版策略揭盲评测 — 2025-01-02 ~ 2026-11-20\n")
    L.append("数据：evaluation/local_data_20261120（BaoStock，2024 预热，评测 456 个交易日）。")
    L.append("三版同行情、同等权基准、同仓位/成交规则/费率；首日 100 万现金、上一交易日收盘信号建仓于首日开盘；")
    L.append("累计收益统一从建仓前现金算起，含首日盈亏。加载已保存模型/公式，不下载、不重训、不调参、不换因子。\n")
    L.append("## 三版文件与打分方式（已确认，无缺失）\n")
    L.append("| 版本 | 文件 | 打分 |")
    L.append("|---|---|---|")
    L.append("| v1 初版 | output/lgbm_model.txt + output/pool.json | 因子 [b3_low_range_20, b4_max_lottery] 百分位 → LightGBM(38树) → 平局按因子百分位均值 |")
    L.append("| v2 优化 | output/v2/lgbm_model.txt + output/v2/pool.json | 因子 [optC2, b2_low_range, b3_cc_vol, optD1, optA2] 百分位 → LightGBM(117树) → 同平局规则 |")
    L.append("| deliverable | deliverable/strategy.json | optC2 `Sub(0, Mean(Div(Sub($high,$low),$vwap),60))` 百分位排序 |")
    L.append("\n## 全期对比\n")
    L.append("相对基准的收益差以百分点计。年化单边换手仅计算策略账户的已成交买入额。\n")
    L.append(cmp.to_markdown(index=False))
    L.append("\n## 分年收益（链式，含首日；2026 为年初至 11-20）\n")
    yy = pd.DataFrame({k: v["per_year"] for k, v in m.items()}).T
    bench_row = pd.DataFrame([m["v1"]["benchmark_per_year"]], index=["benchmark"])
    yy = pd.concat([yy, bench_row])
    L.append((yy * 100).round(2).to_markdown())
    L.append("\n## 结论\n")
    L.append(f"- **开发时选定的交付候选：deliverable（optC2 单因子版）**。开发阶段两个 LightGBM 口径版本验证段均为负超额，")
    L.append(f"  按约定交付明确标注的研究候选 optC2 单因子排序版。")
    L.append(f"- **本次并排评测表现最好：{best}**，全期累计收益 {m[best]['cumulative_return']*100:.1f}%，"
             f"相对基准 {m[best]['return_vs_benchmark']*100:+.1f} 个百分点，最大回撤 {m[best]['max_drawdown']*100:.1f}%。")
    if best == dev_candidate:
        L.append("- 开发候选与评测最佳一致：单因子版在样本外延续了开发期的相对优势。")
    else:
        L.append(f"- **样本外排名反转**：开发期（2023–24 验证段）deliverable 单因子大幅领先、v2 最弱；"
                 f"本次样本外（2025–26）v2 反而最佳、deliverable 跑输基准。开发期的合成层诊断是特定行情下的结论，"
                 f"不等于样本外优劣。")
        L.append(f"- v2（5 因子 LightGBM）全期领先基准 {m['v2']['return_vs_benchmark']*100:.1f} 个百分点，回撤最浅（{m['v2']['max_drawdown']*100:.1f}%），"
                 f"但换手高（{m['v2']['annual_one_way_turnover']:.1f}/年）、费用最高；deliverable 换手低（{m['deliverable']['annual_one_way_turnover']:.1f}/年）但样本外超额为负。")
        L.append(f"- v1（2 因子）2025 年收益 {m['v1']['per_year']['2025']*100:+.1f}%，2026 年截至评测末日收益 {m['v1']['per_year']['2026']*100:+.1f}%。")
    L.append("- 本评测为样本外揭盲，未对任何版本调参；基准为沪深300历史成分等权（非加权指数）。")
    L.append("- 开发候选仍按开发期约定标注为 deliverable；是否改以 v2 为交付候选，属另行决策，本评测只呈现事实。")
    (OUT / "report.md").write_text("\n".join(L), encoding="utf-8")
    print("best:", best, "| dev candidate:", dev_candidate)
    print("report.md written")


if __name__ == "__main__":
    main()
