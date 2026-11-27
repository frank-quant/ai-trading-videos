"""Assemble output/candidates.csv and output/report.md from ledger + results.

Usage: python -I run_report.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from coa.data import ROOT


def main():
    out = ROOT / "output"
    entries = [json.loads(l) for l in open(out / "ledger.jsonl", encoding="utf-8") if l.strip()]
    subs = {e["id"]: e for e in entries if e["type"] == "submission"}
    evals = {e["id"]: e for e in entries if e["type"] == "evaluation"}
    decisions = {}
    for e in entries:
        if e["type"] == "pool_decision":
            decisions[e["id"]] = e

    rows = []
    for fid, s in subs.items():
        ev = evals.get(fid, {})
        m = ev.get("metrics", {})
        dec = decisions.get(fid, {})
        rows.append({
            "id": fid, "batch": s["batch"], "name": s["name"],
            "expression": s["expression"], "hypothesis": s["hypothesis"],
            "status": dec.get("status", ev.get("status", "missing")),
            "train_rankic": m.get("train_rankic"), "val_rankic": m.get("validation_rankic"),
            "val_rankicir": m.get("validation_rankicir"), "val_coverage": m.get("val_coverage"),
            "val_top30_turnover": m.get("val_top30_turnover"),
            "failed_gates": ",".join(k for k, v in m.get("gates", {}).items() if not v),
            "error": ev.get("error", ""),
        })
    cand = pd.DataFrame(rows)
    cand.to_csv(out / "candidates.csv", index=False, encoding="utf-8-sig")

    pool = json.loads((out / "pool.json").read_text(encoding="utf-8"))
    combine = json.loads((out / "combine_info.json").read_text(encoding="utf-8"))
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    cfg = json.loads((out / "config_snapshot.json").read_text(encoding="utf-8"))
    nav = pd.read_csv(out / "nav.csv", parse_dates=["date"])
    s, b, ex = metrics["strategy"], metrics["benchmark"], metrics["excess"]

    def fmt(x, n=4):
        return f"{x:.{n}f}" if isinstance(x, (int, float)) else str(x)

    lines = []
    lines.append("# Chain-of-Alpha 复现 — 初版研究报告\n")
    lines.append(f"生成时间：{pd.Timestamp.now():%Y-%m-%d %H:%M}　数据：BaoStock 日线 + 沪深300历史月末成分（data/manifest.json）\n")
    lines.append("> **值得看的候选：b3_low_range_20（低日内波幅20日版）** `Sub(0, Mean(Div(Sub($high, $low), $close), 20))`。")
    lines.append("> 验证 RankIC 0.1146 / ICIR 0.456，截断检验稳定；单因子 Top30 同规则诊断回测年化超额 +14.4%、IR 1.20。")
    lines.append("> 固定口径初版组合（2 因子 LightGBM 合成）年化超额 -7.0%——合成层在 2 特征下破坏排序，详见第 4 节诊断。\n")
    lines.append("## 1. 数据与分段\n")
    lines.append(f"- 行情 {cfg['data']['bars']}：2013-01-04 ~ 2024-12-31，680 只历史成分股，2914 个交易日。")
    lines.append(f"- 预热 2013；训练 {cfg['data']['train']}；验证 {cfg['data']['validation']}；2025+ 不在档案内，留作最终测试。")
    lines.append("- 标签：t+1 开盘 → t+11 开盘（后复权），两端须同段且为有效交易开盘。")
    lines.append("- 信号日合格股：最近月末快照成分 ∧ 非停牌 ∧ 非ST ∧ 价格有效。\n")
    lines.append("## 2. 因子生成协议\n")
    lines.append("本会话提出公式，4 批 × 5 个；先记假设与公式再评估，读完整批反馈再出下一批。")
    lines.append("白名单算子；窗口 2–60 日、延迟 1–60 日、总回看 ≤120 日、运算节点 ≤15、字段 ≤3。")
    lines.append("全部 20 个提交（含拒绝）见 candidates.csv 与 ledger.jsonl。\n")
    lines.append("### 批次结果\n")
    show = cand[["id", "batch", "status", "train_rankic", "val_rankic", "val_rankicir", "val_coverage", "val_top30_turnover"]].copy()
    for c in show.columns[3:]:
        show[c] = show[c].map(lambda x: fmt(x))
    lines.append(show.to_markdown(index=False))
    lines.append("\n### 关键反馈链\n")
    lines.append("- 批1：量价正相关稳定负 IC（-0.031/-0.028）→ 批2 翻转；Amihud 水平项训练/验证变号 → 弃用。")
    lines.append("- 批2：低日内波幅 b2_low_range 全过（val IC 0.107）→ 批3 做窗口/测度变体。")
    lines.append("- 批3：low_range_20 与 cc_vol 过线；量价背离系 ICIR 始终差一步（0.13–0.19 < 0.20）。")
    lines.append("- 批4：MAX 彩票效应过线；原始乘积交互因符号象限混淆产生负 IC（教训：交互应在百分位/秩上做）。\n")
    lines.append("## 3. 入池与截断检验\n")
    lines.append("闸门：训练 RankIC>0；验证 RankIC≥0.015、RankICIR≥0.20、覆盖率≥70%、Top30 换手≤1.5；")
    lines.append("按验证 RankIC 降序纳入，与已入池因子验证期日均截面 Spearman |相关|≤0.80，上限 10 个。")
    lines.append("相关闸淘汰：b2_low_range（0.867）、b3_cc_vol（0.899），均相对 b3_low_range_20。\n")
    for p in pool:
        t = p["truncation"]
        lines.append(f"- **{p['id']}**（{p['name']}）：`{p['expression']}`")
        lines.append(f"  - val RankIC {fmt(p['val_rankic'])} / ICIR {fmt(p['val_rankicir'])}；截断（1/99 缩尾）后 RankIC {fmt(t['val_rankic_after'])}，通过。")
        lines.append(f"  - 假设：{p['hypothesis']}")
    lines.append("")
    lines.append("## 4. 合成模型\n")
    lines.append(f"LightGBM（论文参数）：训练 {combine['train_rows']} 行、验证 {combine['val_rows']} 行，早停最佳迭代 {combine['best_iteration']}。")
    lines.append(f"特征重要度：{combine['feature_importance']}。因子按当日合格股截面转百分位，齐全才预测。\n")
    diag = json.loads((out / "diagnostics.json").read_text(encoding="utf-8"))
    fo = json.loads((out / "diag_factor_only_metrics.json").read_text(encoding="utf-8"))
    arb = json.loads((out / "metrics_arbitrary_ties.json").read_text(encoding="utf-8"))
    lines.append("### 合成层诊断（本次复现最重要的发现）\n")
    lines.append(f"- 合成分与冠军因子的验证期日均截面 Spearman 仅 **0.030**；合成分 Top30 的冠军因子百分位均值仅 **0.348**（因子自身 Top30 应≈0.95），两者持仓重合 **0%**。")
    lines.append(f"- 分数分层非单调：D10（最高分组）10日前向收益均值 {diag['score_decile_mean_fwd_bp']['10']:.1f}bp，低于全样本 {diag['universe_mean_fwd_bp']:.1f}bp；D6/D8 因大量并列分成为空桶。")
    lines.append(f"- 300 只合格股每日仅 ~35 个不同分值，最大并列组 121–132 只。初版用列序任意打破平局，Top30 实质随机；改为按入池因子百分位均值确定性打破平局后，年化超额从 {arb['excess']['annualized_excess_arithmetic']*100:.1f}% 改善到 {ex['annualized_excess_arithmetic']*100:.1f}%，仍为负。")
    lines.append(f"- 单因子（冠军因子百分位）走同一套交易规则的诊断回测：期末净值 {fo['strategy']['final_nav']:,.0f}，年化超额 **+{fo['excess']['annualized_excess_arithmetic']*100:.1f}%**，IR **{fo['excess']['information_ratio']:.2f}**，最大回撤 {fo['strategy']['max_drawdown']*100:.1f}%。交易规则本身没有问题。")
    lines.append("- 根因：20 个候选 → 4 个过闸 → 相关闸（≤0.80）只留下 2 个同族因子。2 特征、38 棵树的 LightGBM 在 R²≈1% 的弱信号上按叶分裂拟合噪声，最高预测叶落在因子中段，单调排序被破坏。论文用 Top-100 因子喂模型，梯度信号足够；2 因子不够。")
    lines.append("- 诊断文件：diagnostics.json、diag_factor_only_metrics.json、diag_factor_only_nav.csv、metrics_arbitrary_ties.json（平局修复前对照）。\n")
    lines.append("## 5. 验证段回测（2023-01-03 ~ 2024-12-31，次日开盘成交）\n")
    lines.append("| 指标 | 策略 | 基准（历史成分等权） |")
    lines.append("|---|---|---|")
    lines.append(f"| 期末净值（100万起） | {s['final_nav']:,.0f} | {b['final_nav']:,.0f} |")
    lines.append(f"| 区间总收益 | {fmt(s['total_return']*100,2)}% | {fmt(b['total_return']*100,2)}% |")
    lines.append(f"| 年化收益（算术×252） | {fmt(s['annualized_return_arithmetic']*100,2)}% | {fmt(b['annualized_return_arithmetic']*100,2)}% |")
    lines.append(f"| 年化收益（几何） | {fmt(s['cagr_geometric']*100,2)}% | {fmt(b['cagr_geometric']*100,2)}% |")
    lines.append(f"| 年化波动 | {fmt(s['annualized_vol']*100,2)}% | {fmt(b['annualized_vol']*100,2)}% |")
    lines.append(f"| 夏普（无风险利率=0） | {fmt(s['sharpe_no_rf'],2)} | {fmt(b['sharpe_no_rf'],2)} |")
    lines.append(f"| 最大回撤 | {fmt(s['max_drawdown']*100,2)}% | {fmt(b['max_drawdown']*100,2)}% |")
    lines.append(f"| 年化超额（算术） | {fmt(ex['annualized_excess_arithmetic']*100,2)}% | — |")
    lines.append(f"| 信息比率 IR | {fmt(ex['information_ratio'],2)} | — |")
    lines.append(f"| 日胜率 vs 基准 | {fmt(ex['win_rate_vs_benchmark']*100,1)}% | — |")
    sa, ba = metrics["strategy_account"], metrics["benchmark_account"]
    lines.append(f"\n策略账户：买 {sa['buys']} / 卖 {sa['sells']} / 阻塞 {sa['blocked_attempts']}，费用 {sa['fees_paid']:,.0f} 元。")
    lines.append(f"基准账户：买 {ba['buys']} / 卖 {ba['sells']} / 阻塞 {ba['blocked_attempts']}，费用 {ba['fees_paid']:,.0f} 元。")
    lines.append(f"回测交易日 {s['trading_days']} 天，净值曲线见 nav.png / nav.csv，逐笔成交见 trades.csv。\n")
    lines.append("## 6. 口径与局限（必读）\n")
    lines.append("- 与论文差异：股票池沪深300（论文 CSI500/CSI1000/S&P500）；次日开盘成交（论文当日收盘）；本会话人工出公式（论文 LLM 双链）。")
    lines.append("- 验证段同时用于 LightGBM 早停，验证净值偏乐观；真正样本外是 2025+（未触碰）。")
    lines.append("- 入池仅 2 因子且同属低波/彩票族，行业/风格暴露集中；2023–24 小盘微盘风格剧烈切换，低波溢价含风格成分。")
    lines.append("- 涨跌停按未复权前收×板块规则四舍五入到分估算（主板10%、创业板2020-08-24起20%、科创板20%），非交易所精确规则（未含新股首日等特例）。")
    lines.append("- 基准为历史成分等权、月度调仓，非沪深300指数本身（加权方式不同）。")
    lines.append("- 基准调仓无每日3笔限制（月度全量调仓），费用与阻塞规则与策略一致。")
    lines.append("- 初版组合为固定口径（LightGBM 合成）的如实结果；单因子诊断回测仅作归因，不是交付组合。")
    lines.append("- 下一步可选（需改口径，另行确认）：扩大候选批次/放宽相关闸以凑足因子数；或改用秩平均/线性合成替代 2 特征树模型；冠军因子 b3_low_range_20 单因子已显示强多头边际。")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("report written:", out / "report.md")
    print(cand[["id", "status"]].to_string(index=False))


if __name__ == "__main__":
    main()