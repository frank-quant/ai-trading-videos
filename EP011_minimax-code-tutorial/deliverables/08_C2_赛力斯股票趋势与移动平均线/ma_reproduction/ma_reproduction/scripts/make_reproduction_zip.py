"""打包 ma_reproduction.zip —— 全量复现包。

内容：
  scripts/          全部复现脚本
  raw/              全部原始响应与机读校验结果
  charts/           三张 PNG 图
  根目录            全部 CSV 底稿、Markdown 报告、Excel 工作簿、离线 HTML、技能调用日志
  README.md         包内说明（复现顺序、目录清单、口径声明）

排除：__pycache__、.gitkeep、临时补丁脚本（_patch_*.py）、本 zip 自身。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ma_reproduction.zip"
PREFIX = "ma_reproduction"

EXCLUDE_NAMES = {"__pycache__", ".ipynb_checkpoints", ".git", ".vscode"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".tmp"}
EXCLUDE_STEMS = {"_patch_bw", "_patch_bw2", "_patch_bw3", "_patch_bw4", "_check_html", "_verify_zip"}
SKIP_TOP = {"ma_reproduction.zip"}

README = """# 赛力斯（601127.SH）均线交叉分析 · 复现包

## 这是什么

一个**可完整复现**的教学包：行情数据 → 技术指标 → 交叉信号 → SMA5/SMA20 交叉回测 →
绩效与基准对比 → 三张图 → Excel 联动模型 → 离线 HTML 报告 → 独立复核。

## 目录

```
ma_reproduction/
├── README.md                 本文件
├── scripts/                  全部复现脚本（14 个）
├── raw/                      原始响应与机读校验结果
├── charts/                   三张 PNG 图
├── prices.csv                赛力斯前复权日线 822 行
├── prices_bench.csv          沪深300 价格指数 822 行
├── indicators.csv            SMA/EMA/MACD/RSI/斜率/评分 822 行
├── signals.csv               111 条交叉信号
├── Ledger_Gross.csv          零成本账本 822 行
├── Ledger.csv                含费账本 822 行
├── metrics.csv               四条曲线绩效指标 + 两行费用分解
├── moving_average_analysis.xlsx   Excel 联动模型（8 表，Assumptions 驱动）
├── moving_average_report.html     离线单文件报告（双击即可打开）
├── stock_report.md                 股票表现分析主报告
├── qa_report.md                    独立复核报告（47 项 + 工作簿 57 项）
├── sources.md                      数据来源、复权核验、复现命令（12 节）
├── technical_snapshot.md           最近 120 个交易日技术快照
└── skill_invocations.log           本次会话的技能与工具调用记录
```

## 复现顺序

**无需网络**（用 `raw/` 里已留档的原始响应）：

```powershell
python scripts\\build_csvs.py         # 校验 + 对齐 -> prices.csv / prices_bench.csv
python scripts\\indicators.py         # -> indicators.csv / signals.csv
python scripts\\make_snapshot.py      # -> technical_snapshot.md
python scripts\\backtest.py           # -> Ledger_Gross.csv / Ledger.csv
python scripts\\verify_ledgers.py     # 账本独立校验
python scripts\\backtest_report.py    # -> raw/backtest_report.md
python scripts\\metrics.py            # -> metrics.csv + raw/nav_paths.json
python scripts\\charts.py             # -> charts/*.png
python scripts\\qa_check.py           # 独立复核 47 项 -> raw/qa_results.json
python scripts\\build_workbook.py     # -> moving_average_analysis.xlsx
python scripts\\recalc_verify.py      # Excel COM 重算 + 与 CSV 比对 57 项
python scripts\\build_html_report.py  # -> moving_average_report.html
```

`recalc_verify.py` 需要本机安装 Microsoft Excel；其余步骤仅需 Python 3.11+、
openpyxl、matplotlib、pandas。

**需要网络与 Connector 授权**（重新取数）：

```powershell
python scripts\\fetch_index.py        # 沪深300 分块抓取 -> raw/ifind_csi300_merged.json
```

个股行情已完整留档在 `raw/seres_fwd.json`（前复权）与 `raw/seres_raw.json`（未复权）。

## 关键口径（复现时必须一致）

| 项 | 设定 |
|---|---|
| 区间 | 2023-06-01 ~ 2026-10-23，822 个交易日 |
| 价格基准 | 前复权（恒生 `adjustment=forward`），锚定区间末日 |
| 基准 | 沪深300 价格指数（同花顺 iFinD） |
| 预热 | 前 59 行不评分、不交易、不发信号；首个可评估日 2023-08-25 |
| 信号 | 只在实际发生符号翻转的那一根K线上记录，全样本连续重复 0 次 |
| 入场 / 出场 | 金叉 → 次日开盘全仓买入；死叉 → 次日开盘清仓；不做空；样本末不强制平仓 |
| 成交价 | 前复权价，按当日开盘价成交 |
| 费用 | 单边 0.075%（零成本账本另出），不计印花税与过户费 |
| 年化收益 | `(期末净值/初始资金)^(252/(N−1))−1`，N = 822 个净值观测点 → 821 个收益期 |
| 最大回撤 | 显式循环维护运行峰值 |

## 核心结果（复现后应当完全一致）

| 指标 | 策略（含费 0.075%） | 策略（零成本） | 赛力斯 买入持有 | 沪深300 买入持有 |
|---|---:|---:|---:|---:|
| 期末净值（元） | 1,442,978.92 | 1,486,924.17 | 1,697,804.39 | 1,083,603.24 |
| 累计收益 | +44.30% | +48.69% | +69.78% | +8.36% |
| 年化收益 | +11.91% | +12.95% | +17.64% | +2.50% |
| 最大回撤 | −50.09% | −49.19% | −75.88% | −21.42% |
| 交易次数（往返） | 20 | 20 | 0 | 0 |
| 持仓天数 | 317 | 317 | 822 | 822 |

- 费用造成的期末净值差 **43,945.26 元**（占初始资金 4.39%）
- 实际支付费用合计 **56,521.26 元**（占初始资金 5.65%）
- 两者口径不同、不相等，分行列示。

## 重要提醒

1. **策略跑输同期买入持有 25.48 个百分点**，结果如实呈现，未做任何区间或参数调整。
2. 样本内结果，**未经样本外检验与参数敏感性分析**，**不证明策略有效**，**不构成投资建议**。
3. 使用前复权价成交，绝对金额非实盘口径；未建模涨跌停不可成交、集合竞价、停牌与滑点。
4. 技术评分只描述**当日**技术状态，不预测收益。
5. 完整的 8+1 项未解决问题见 `qa_report.md`。

打包时间：2026-11-02（Asia/Shanghai）
"""


def collect():
    items: list[tuple[Path, str]] = []
    for p in sorted(ROOT.iterdir()):
        if not p.is_file():
            continue
        if p.name in SKIP_TOP:
            continue
        items.append((p, f"{PREFIX}/{p.name}"))

    for sub in ("scripts", "raw", "charts"):
        d = ROOT / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            if any(part in EXCLUDE_NAMES for part in p.parts):
                continue
            if p.suffix.lower() in EXCLUDE_SUFFIX:
                continue
            if p.stem in EXCLUDE_STEMS:
                continue
            rel = p.relative_to(ROOT).as_posix()
            items.append((p, f"{PREFIX}/{rel}"))
    return items


def main():
    items = collect()
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr(f"{PREFIX}/README.md", README.encode("utf-8"))
        for src, arc in items:
            z.write(src, arc)
    n = len(items) + 1
    print(f"written: {OUT}")
    print(f"  files: {n}")
    print(f"  size : {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
