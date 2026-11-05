"""生成离线单文件 HTML 报告 moving_average_report.html。

要求：
  * 样式、数据、脚本全部内联，**无任何外链**（不引 CDN），离线双击可打开。
  * 章节顺序：核心结果 -> 净值与基准 -> 策略规则 -> 含费与零成本对比
              -> 三种复核方法 -> 数据与限制 -> 下载入口
  * 图表支持切换（tab）与放大（点击进入全屏 modal，滚轮缩放 + 拖拽平移）
  * 原始底稿与图表提供下载入口（相对路径，离线可用）

数据来源：prices.csv / prices_bench.csv / indicators.csv / signals.csv /
          Ledger.csv / Ledger_Gross.csv / metrics.csv /
          raw/nav_paths.json / raw/qa_results.json / raw/workbook_verify.json
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "moving_average_report.html"


# --------------------------------------------------------------------------
# 数据读取
# --------------------------------------------------------------------------
def read_csv(name):
    with (ROOT / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fnum(v, default=None):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def main():
    prices = read_csv("prices.csv")
    bench = read_csv("prices_bench.csv")
    ind = read_csv("indicators.csv")
    sig = read_csv("signals.csv")
    led = read_csv("Ledger.csv")
    led_g = read_csv("Ledger_Gross.csv")
    metrics = read_csv("metrics.csv")

    nav_paths = json.loads((ROOT / "raw" / "nav_paths.json").read_text(encoding="utf-8"))
    qa = json.loads((ROOT / "raw" / "qa_results.json").read_text(encoding="utf-8"))
    wb = json.loads((ROOT / "raw" / "workbook_verify.json").read_text(encoding="utf-8"))

    dates = nav_paths["dates"]
    n = len(dates)
    assert n == len(prices) == len(bench) == len(ind) == len(led) == len(led_g)

    # ---- 净值序列 ----
    nav_series = []
    for name, vals in nav_paths["series"].items():
        nav_series.append({"name": name, "data": [round(v, 6) for v in vals]})

    # ---- 回撤序列（由同一组净值显式循环维护运行峰值得到）----
    def drawdown(vals):
        peak = vals[0]
        out = []
        for v in vals:
            if v > peak:
                peak = v
            out.append(round(v / peak - 1.0, 8))
        return out

    dd_series = [{"name": s["name"], "data": drawdown(s["data"])} for s in nav_series]

    # ---- 价格与均线 ----
    close = [fnum(r["close"]) for r in ind]
    sma5 = [fnum(r["sma5"]) for r in ind]
    sma20 = [fnum(r["sma20"]) for r in ind]
    sma60 = [fnum(r["sma60"]) for r in ind]
    date_index = {d: i for i, d in enumerate(dates)}

    # ---- 成交标记（来自含费账本的 action / fill_price）----
    markers = []
    for r in led:
        act = r["action"]
        if act in ("BUY", "SELL"):
            markers.append({
                "i": date_index[r["date"]],
                "date": r["date"],
                "type": "buy" if act == "BUY" else "sell",
                "price": fnum(r["fill_price"]),
            })

    # ---- 逐笔往返（由账本买卖腿配对）----
    trades = []
    open_leg = None
    for r in led:
        if r["action"] == "BUY":
            open_leg = {"buy_date": r["date"], "buy_price": fnum(r["fill_price"])}
        elif r["action"] == "SELL" and open_leg:
            sell_price = fnum(r["fill_price"])
            ret = sell_price / open_leg["buy_price"] - 1.0
            trades.append({
                "buy_date": open_leg["buy_date"],
                "buy_price": open_leg["buy_price"],
                "sell_date": r["date"],
                "sell_price": sell_price,
                "ret": round(ret, 6),
            })
            open_leg = None

    # ---- 费用侵蚀 ----
    gross_nav = [fnum(r["nav"]) for r in led_g]
    net_nav = [fnum(r["nav"]) for r in led]
    fee = {
        "dates": dates,
        "gross": [round(v, 4) for v in gross_nav],
        "net": [round(v, 4) for v in net_nav],
        "gap": [round(g - n, 4) for g, n in zip(gross_nav, net_nav)],
    }

    # ---- 指标表 ----
    mrows = []
    for r in metrics:
        mrows.append({
            "row_type": r["row_type"],
            "series": r["series"],
            "cost_regime": r["cost_regime"],
            "final_nav": r["final_nav"],
            "cumulative_return": r["cumulative_return"],
            "annualized_return": r["annualized_return"],
            "max_drawdown": r["max_drawdown"],
            "dd_peak_date": r["dd_peak_date"],
            "dd_trough_date": r["dd_trough_date"],
            "trade_count": r["trade_count_round_trips"],
            "holding_days": r["holding_days"],
            "holding_ratio": r["holding_ratio"],
            "total_fees_paid": r["total_fees_paid"],
            "value": r["value"],
            "note": r["note"],
        })
    breakdown = [r for r in mrows if r["row_type"] == "fee_breakdown"]
    metric_rows = [r for r in mrows if r["row_type"] != "fee_breakdown"]

    # ---- 信号统计 ----
    fam = {}
    for s in sig:
        k = (s["signal_family"], s["signal_type"])
        fam[k] = fam.get(k, 0) + 1

    # ---- 当日快照 ----
    last = ind[-1]
    snapshot = {
        "date": last["date"],
        "close": fnum(last["close"]),
        "sma5": fnum(last["sma5"]),
        "sma20": fnum(last["sma20"]),
        "sma60": fnum(last["sma60"]),
        "ema12": fnum(last["ema12"]),
        "ema26": fnum(last["ema26"]),
        "dif": fnum(last["macd_dif"]),
        "dea": fnum(last["macd_dea"]),
        "hist": fnum(last["macd_hist"]),
        "rsi14": fnum(last["rsi14"]),
        "slope20": fnum(last["sma20_slope"]),
        "slope60": fnum(last["sma60_slope"]),
        "alignment": last["ma_alignment"],
        "score": fnum(last["score"]),
        "score_band": last["score_band"],
    }

    # ---- 文件清单（用于下载入口）----
    groups = [
        ("报告与文档", [
            ("stock_report.md", "股票表现分析主报告（Markdown）"),
            ("qa_report.md", "独立复核报告：47 项检查过程与未解决问题"),
            ("sources.md", "数据来源、复权核验、校验与复现命令（12 节）"),
            ("technical_snapshot.md", "最近 120 个交易日技术快照与评分"),
        ]),
        ("Excel 联动模型", [
            ("moving_average_analysis.xlsx", "8 个工作表，Assumptions 改参数即全表重算"),
        ]),
        ("图表 PNG", [
            ("charts/chart_price_signals.png", "前复权收盘价 + MA5/MA20/MA60 + 买卖点"),
            ("charts/chart_nav_comparison.png", "四条净值曲线对比"),
            ("charts/chart_drawdown.png", "回撤曲线 + 最大回撤条形对比"),
        ]),
        ("原始底稿 CSV", [
            ("prices.csv", "赛力斯前复权日线 822 行"),
            ("prices_bench.csv", "沪深300 价格指数 822 行"),
            ("indicators.csv", "SMA/EMA/MACD/RSI/斜率/评分 822 行"),
            ("signals.csv", "111 条交叉信号"),
            ("Ledger_Gross.csv", "零成本账本 822 行"),
            ("Ledger.csv", "含费账本 822 行"),
            ("metrics.csv", "四条曲线绩效指标 + 费用分解"),
        ]),
        ("复现脚本", [
            ("scripts/mc.py", "mcode-tools connector call 封装"),
            ("scripts/fetch_index.py", "沪深300 分块抓取与解析"),
            ("scripts/build_csvs.py", "完整性校验与行情 CSV 落盘"),
            ("scripts/indicators.py", "指标与信号计算"),
            ("scripts/make_snapshot.py", "技术快照生成"),
            ("scripts/backtest.py", "SMA5/20 交叉回测（两套账本）"),
            ("scripts/verify_ledgers.py", "账本独立校验"),
            ("scripts/backtest_report.py", "逐笔与基准对照"),
            ("scripts/metrics.py", "绩效指标与费用分解"),
            ("scripts/charts.py", "三张图生成"),
            ("scripts/qa_check.py", "独立复核（47 项）"),
            ("scripts/build_workbook.py", "Excel 工作簿生成"),
            ("scripts/recalc_verify.py", "Excel COM 重算 + 与 CSV 比对"),
            ("scripts/build_html_report.py", "本 HTML 报告生成"),
            ("scripts/make_reproduction_zip.py", "复现包打包"),
        ]),
    ]
    files = []
    for gname, items in groups:
        for path, desc in items:
            p = ROOT / path
            files.append({
                "group": gname,
                "path": path,
                "desc": desc,
                "size": p.stat().st_size if p.exists() else None,
            })
    files.append({
        "group": "复现包",
        "path": "ma_reproduction.zip",
        "desc": "全量复现包：脚本 + CSV + 原始响应 + 报告 + 工作簿 + HTML",
        "size": None,
    })

    payload = {
        "meta": {
            "symbol": "601127.SH",
            "name": "赛力斯",
            "benchSymbol": "000300.SH",
            "benchName": "沪深300",
            "start": dates[0],
            "end": dates[-1],
            "days": n,
            "warmup": 59,
            "warmupEnd": "2023-08-24",
            "firstEval": "2023-08-25",
            "generated": "2026-11-02",
        },
        "metrics": metric_rows,
        "breakdown": breakdown,
        "nav": {"dates": dates, "series": nav_series},
        "dd": {"dates": dates, "series": dd_series},
        "price": {
            "dates": dates, "close": close, "sma5": sma5, "sma20": sma20,
            "sma60": sma60, "markers": markers,
        },
        "fee": fee,
        "trades": trades,
        "signals": {
            "total": len(sig),
            "minRow": min(int(s["row_index"]) for s in sig),
            "families": [
                {"family": "MACD（DIF vs DEA）", "total": fam.get(("macd_dif_dea", "golden_cross"), 0) + fam.get(("macd_dif_dea", "death_cross"), 0),
                 "golden": fam.get(("macd_dif_dea", "golden_cross"), 0),
                 "death": fam.get(("macd_dif_dea", "death_cross"), 0)},
            ],
        },
        "snapshot": snapshot,
        "qa": {
            "total": qa["total_checks"], "passed": qa["passed"], "failed": qa["failed"],
            "seed": qa["seed"], "samples": qa["sample_indices"],
            "boundaries": qa["boundary_indices"], "tolerance": qa["tolerance"],
            "checks": qa["checks"],
        },
        "wb": wb,
        "files": files,
    }

    # ---- 信号族统计（键名可能随实现变动，按实际统计）----
    fam_map = {}
    for s in sig:
        f = s["signal_family"]
        d = fam_map.setdefault(f, {"total": 0, "golden": 0, "death": 0})
        d["total"] += 1
        if s["signal_type"] == "golden_cross":
            d["golden"] += 1
        else:
            d["death"] += 1
    label = {
        "macd": "MACD（DIF vs DEA）",
        "sma5_sma20": "SMA5 vs SMA20（策略用）",
        "sma20_sma60": "SMA20 vs SMA60",
    }
    order = ["sma5_sma20", "macd", "sma20_sma60"]
    payload["signals"]["families"] = [
        {"family": label.get(f, f), "total": fam_map[f]["total"],
         "golden": fam_map[f]["golden"], "death": fam_map[f]["death"]}
        for f in order if f in fam_map
    ] + [
        {"family": label.get(f, f), "total": v["total"], "golden": v["golden"], "death": v["death"]}
        for f, v in fam_map.items() if f not in order
    ]

    html = TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    OUT.write_text(html, encoding="utf-8")
    print(f"written: {OUT}  ({OUT.stat().st_size:,} bytes)  payload={len(json.dumps(payload)):,} chars")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>赛力斯（601127.SH）均线交叉分析报告</title>
<style>
:root{
  --bg:#f6f7f9; --card:#ffffff; --ink:#1b1f24; --ink2:#4a5158; --ink3:#79828d;
  --line:#e3e7ec; --line2:#cfd6de;
  --accent:#c2410c; --accent-soft:#fff2e8;
  --red:#d6336c; --teal:#0b7a6b; --blue:#1864ab; --amber:#b8860b; --violet:#5f3dc4;
  --ok:#0b7a3b; --ok-bg:#e8f6ec; --warn:#a15c00; --warn-bg:#fff6e5;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC","Hiragino Sans GB","Source Han Sans SC",sans-serif;
  font-size:15px; line-height:1.72; -webkit-font-smoothing:antialiased;
}
a{color:var(--blue)}
code,kbd{font-family:Consolas,"SF Mono",Menlo,monospace;font-size:.9em}

/* ---------- header ---------- */
.hero{background:linear-gradient(135deg,#16202b 0%,#26333f 55%,#3a3026 100%);color:#eef2f6;padding:40px 0 32px}
.hero-inner{max-width:1180px;margin:0 auto;padding:0 24px}
.hero h1{margin:0 0 6px;font-size:30px;letter-spacing:.4px;font-weight:700}
.hero .sub{color:#b9c4cf;font-size:15px;margin-bottom:18px}
.hero .meta{display:flex;flex-wrap:wrap;gap:8px}
.hero .chip{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.18);border-radius:999px;
  padding:4px 13px;font-size:13px;color:#dde5ec}
.banner{background:rgba(255,190,90,.13);border:1px solid rgba(255,190,90,.34);border-radius:10px;
  padding:12px 16px;margin-top:20px;font-size:13.5px;color:#ffe6bd}
.banner b{color:#ffd08a}

/* ---------- toc ---------- */
.toc{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.94);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line)}
.toc-inner{max-width:1180px;margin:0 auto;padding:0 24px;display:flex;gap:4px;overflow-x:auto}
.toc a{display:block;padding:12px 13px;color:var(--ink2);text-decoration:none;font-size:13.5px;
  white-space:nowrap;border-bottom:2px solid transparent;transition:.15s}
.toc a:hover{color:var(--accent);border-bottom-color:var(--line2)}
.toc a.on{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}

/* ---------- layout ---------- */
main{max-width:1180px;margin:0 auto;padding:0 24px 80px}
section{padding:44px 0 8px;scroll-margin-top:56px}
section>h2{font-size:22px;margin:0 0 6px;letter-spacing:.3px;display:flex;align-items:center;gap:10px}
section>h2 .num{background:var(--accent);color:#fff;border-radius:7px;width:28px;height:28px;
  display:inline-flex;align-items:center;justify-content:center;font-size:14px;flex:0 0 auto}
section>.lead{color:var(--ink2);margin:0 0 22px;max-width:900px}
h3{font-size:16.5px;margin:26px 0 10px;color:var(--ink)}
h4{font-size:14.5px;margin:18px 0 8px;color:var(--ink2)}
p{margin:10px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin:16px 0;
  box-shadow:0 1px 2px rgba(16,24,40,.04)}
.grid{display:grid;gap:14px}
.g4{grid-template-columns:repeat(4,1fr)}
.g3{grid-template-columns:repeat(3,1fr)}
.g2{grid-template-columns:repeat(2,1fr)}
@media(max-width:900px){.g4{grid-template-columns:repeat(2,1fr)}.g3,.g2{grid-template-columns:1fr}}

/* ---------- KPI ---------- */
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;position:relative}
.kpi .t{font-size:12.5px;color:var(--ink3);letter-spacing:.3px}
.kpi .v{font-size:27px;font-weight:700;line-height:1.25;margin:2px 0 1px;font-variant-numeric:tabular-nums}
.kpi .d{font-size:12.5px;color:var(--ink3)}
.kpi .tag{position:absolute;right:14px;top:14px;font-size:11px;padding:2px 8px;border-radius:999px;
  background:var(--accent-soft);color:var(--accent);font-weight:600}
.pos{color:#c0392b}.neg{color:#0b7a6b}
@media(max-width:520px){.kpi .v{font-size:22px}}

.verdict{background:linear-gradient(90deg,#fff6ec,#fff);border:1px solid #f0cfa8;border-left:4px solid var(--accent);
  border-radius:10px;padding:16px 20px;margin:18px 0}
.verdict h3{margin:0 0 6px;color:var(--accent)}

/* ---------- table ---------- */
table{width:100%;border-collapse:collapse;font-size:13.5px;margin:10px 0}
th,td{padding:9px 11px;border-bottom:1px solid var(--line);text-align:right}
th{background:#f2f4f7;color:var(--ink2);font-weight:600;font-size:12.5px;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
td.l,th.l{text-align:left}
tbody tr:hover{background:#fafbfc}
.tbl-wrap{overflow:auto;max-height:520px;border:1px solid var(--line);border-radius:10px}
.tbl-wrap:not(.short) th{position:sticky;top:0;z-index:2}
.tbl-wrap.short{max-height:none}
.tbl-wrap.short th{position:static}
.num{font-variant-numeric:tabular-nums}

/* ---------- chart ---------- */
.chart-panel{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:16px 0}
.chart-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid var(--line);
  background:#fbfcfd}
.tabs{display:flex;gap:6px;flex:1 1 auto;flex-wrap:wrap}
.tab{border:1px solid var(--line2);background:#fff;color:var(--ink2);border-radius:8px;padding:6px 14px;
  font-size:13.5px;cursor:pointer;font-family:inherit;transition:.15s}
.tab:hover{border-color:var(--accent);color:var(--accent)}
.tab.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.btn{border:1px solid var(--line2);background:#fff;color:var(--ink2);border-radius:8px;padding:6px 12px;
  font-size:13px;cursor:pointer;font-family:inherit;transition:.15s}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.chart-body{position:relative;padding:8px 6px 4px}
.chart-host{width:100%;position:relative}
.chart-host svg{display:block;width:100%;height:auto;cursor:crosshair}
.legend{display:flex;flex-wrap:wrap;gap:14px;padding:8px 16px 12px;font-size:12.5px;color:var(--ink2)}
.legend i{display:inline-block;width:18px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
.legend .sq{width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.tip{position:absolute;pointer-events:none;background:rgba(24,30,38,.95);color:#fff;border-radius:8px;
  padding:8px 11px;font-size:12.5px;line-height:1.6;opacity:0;transition:opacity .1s;z-index:20;
  white-space:nowrap;box-shadow:0 6px 20px rgba(0,0,0,.25);font-variant-numeric:tabular-nums}
.tip .d{color:#9fb0c2;font-size:11.5px}
.tip .row{display:flex;gap:10px;justify-content:space-between}
.tip .row b{font-weight:600}
.zoom-hint{font-size:12px;color:var(--ink3);padding:0 16px 10px}

/* ---------- modal ---------- */
.modal{position:fixed;inset:0;background:rgba(10,14,18,.985);backdrop-filter:blur(3px);z-index:200;display:none;
  flex-direction:column}
.modal.open{display:flex}
.modal-head{display:flex;align-items:center;gap:12px;padding:12px 18px;color:#e7edf3;
  border-bottom:1px solid rgba(255,255,255,.13)}
.modal-head .t{font-weight:600;font-size:15px;flex:1}
.modal-head .x{background:rgba(255,255,255,.12);border:0;color:#fff;border-radius:7px;
  padding:6px 13px;cursor:pointer;font-size:13px;font-family:inherit}
.modal-head .x:hover{background:rgba(255,255,255,.22)}
.modal-body{flex:1;overflow:auto;padding:14px;display:flex;align-items:flex-start;justify-content:center}
.modal-body svg{max-width:none}
.modal-foot{padding:8px 18px;color:#93a3b3;font-size:12.5px;border-top:1px solid rgba(255,255,255,.1);
  display:flex;gap:16px;flex-wrap:wrap}
.modal-foot b{color:#d8e2ec}

/* ---------- misc ---------- */
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.pill.ok{background:var(--ok-bg);color:var(--ok)}
.pill.no{background:#fdeaea;color:#b02a2a}
.pill.mid{background:var(--warn-bg);color:var(--warn)}
.note{background:#f3f6fa;border-left:3px solid #9bb4cd;border-radius:0 8px 8px 0;padding:12px 16px;
  margin:14px 0;font-size:13.5px;color:var(--ink2)}
.note.warn{background:#fff8ec;border-left-color:#e0a44a;color:#7a4d12}
.note strong{color:var(--ink)}
ul.tight{margin:8px 0;padding-left:22px}
ul.tight li{margin:5px 0}
details{border:1px solid var(--line);border-radius:10px;padding:0;margin:12px 0;background:var(--card)}
details>summary{cursor:pointer;padding:11px 16px;font-weight:600;font-size:14px;list-style:none;
  display:flex;align-items:center;gap:8px}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"▸";color:var(--accent);font-size:13px;transition:.15s}
details[open]>summary::before{transform:rotate(90deg)}
details .body{padding:0 16px 14px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13.5px}
.kv dt{color:var(--ink3)}
.kv dd{margin:0;font-variant-numeric:tabular-nums}
.dl{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.dl a{display:flex;flex-direction:column;gap:2px;text-decoration:none;border:1px solid var(--line);
  background:var(--card);border-radius:10px;padding:12px 14px;transition:.15s}
.dl a:hover{border-color:var(--accent);box-shadow:0 2px 10px rgba(194,65,12,.09);transform:translateY(-1px)}
.dl .fn{font-size:13.5px;color:var(--accent);font-weight:600;word-break:break-all}
.dl .fd{font-size:12.5px;color:var(--ink3);line-height:1.55}
.dl .fs{font-size:11.5px;color:#a6adb5}
footer{background:#16202b;color:#96a4b2;font-size:13px;padding:26px 0;margin-top:30px}
footer .fi{max-width:1180px;margin:0 auto;padding:0 24px}
.method{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;position:relative}
.method .n{position:absolute;right:16px;top:14px;font-size:30px;font-weight:800;color:#eef1f4}
.method h3{margin:0 0 8px}
.method .pair{font-size:12.5px;color:var(--ink2);background:#f5f7f9;border-radius:8px;padding:9px 12px;margin:10px 0}
.method .pair b{color:var(--accent)}
.method .res{font-size:13px;color:var(--ok);font-weight:600}
footer a{color:#7fb4e8}
@media print{.toc,.chart-head .btn{display:none}.modal{display:none}}
</style>
</head>
<body>

<div class="hero">
  <div class="hero-inner">
    <h1>赛力斯（601127.SH）均线交叉分析报告</h1>
    <div class="sub">SMA5 × SMA20 交叉策略 · 技术面状态 · 绩效与基准对比 · 三种独立复核</div>
    <div class="meta" id="hero-meta"></div>
    <div class="banner">
      <b>口径声明：</b>本报告中的「评分」与「信号」是对历史数据的量化描述，<b>不是收益预测，不构成买卖建议，也不证明任何策略有效</b>。
      回测为<b>样本内</b>结果，未经样本外检验与参数敏感性分析；使用前复权价成交，绝对金额非实盘口径，
      未建模涨跌停不可成交、集合竞价、停牌与滑点。费用仅计单边 0.075%，未计印花税与过户费。
    </div>
  </div>
</div>

<nav class="toc"><div class="toc-inner" id="toc"></div></nav>

<main>
  <!-- 1 核心结果 -->
  <section id="s1">
    <h2><span class="num">1</span>核心结果</h2>
    <p class="lead">三条曲线在同一区间、同一日期轴、同一初始资金下的对照。策略跑输买入持有，如实呈现。</p>
    <div class="verdict" id="verdict"></div>
    <div class="grid g4" id="kpis"></div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card" id="snap-card"></div>
      <div class="card" id="takeaway-card"></div>
    </div>
  </section>

  <!-- 2 净值与基准 -->
  <section id="s2">
    <h2><span class="num">2</span>净值与基准</h2>
    <p class="lead">三条图表可切换：净值曲线、价格与买卖点、回撤曲线。点击任意图表可进入全屏放大（滚轮缩放、拖拽平移）。</p>
    <div class="chart-panel">
      <div class="chart-head">
        <div class="tabs" id="tabs"></div>
        <button class="btn" id="btn-csv">下载当前图表数据 CSV</button>
        <button class="btn" id="btn-png">下载当前图表 PNG</button>
        <button class="btn" id="btn-zoom">放大</button>
      </div>
      <div class="chart-body"><div class="chart-host" id="chart-host"><div class="tip" id="tip"></div></div></div>
      <div class="legend" id="legend"></div>
      <div class="zoom-hint">提示：鼠标悬停查看逐日数值；点击图表区域进入全屏放大。</div>
    </div>
    <div class="card">
      <h3 style="margin-top:0">绩效指标对照</h3>
      <div class="tbl-wrap short"><table id="metrics-table"></table></div>
      <p class="note"><strong>年化口径：</strong><code>(期末净值 / 初始资金) ^ (252 / (N − 1)) − 1</code>，
      <code>N = 822</code> 个净值观测点对应 <code>N − 1 = 821</code> 个日收益期（首日建仓不产生收益期）。
      Python 侧与 Excel 工作簿 <code>Summary!B7:E7</code> 使用<b>完全相同</b>的口径，两侧逐位对齐。</p>
    </div>
  </section>

  <!-- 3 策略规则 -->
  <section id="s3">
    <h2><span class="num">3</span>策略规则</h2>
    <p class="lead">规则先说清楚，再看结果。所有成交都由<b>上一根K线</b>的信号触发，按<b>当日开盘价</b>成交。</p>
    <div class="grid g2">
      <div class="card">
        <h3 style="margin-top:0">交易规则</h3>
        <table><tbody id="rules-table"></tbody></table>
      </div>
      <div class="card">
        <h3 style="margin-top:0">信号体系（三个独立族）</h3>
        <table><tbody id="sig-table"></tbody></table>
        <p class="note" style="margin-bottom:0">金叉 / 死叉只在<b>实际发生符号翻转的那一根K线</b>记录，不重复发信号；
        全样本连续同向重复 <b>0</b> 次；最小 <code>row_index</code> = <b>61</b>，全部落在预热期之后。</p>
      </div>
    </div>
    <div class="card">
      <h3 style="margin-top:0">为什么不会有前视偏差</h3>
      <p>账本行内的 <code>signal</code> 与 <code>action</code> <b>故意错开一行</b>：第 <i>t</i> 行的成交只能由第 <i>t−1</i> 行的信号触发，
      成交价只能是第 <i>t</i> 行的<b>开盘价</b>。这让「用当日收盘信号、在当日开盘成交」在结构上不可能发生。</p>
      <p>典型因果链（已作为回归用例写入复核脚本）：</p>
      <div class="tbl-wrap short"><table id="chain-table"></table></div>
      <p class="note warn" style="margin-bottom:0">判断前视偏差的正确标准不是「信号行不得有成交」，
      而是「第 <i>i</i> 行的成交只能由第 <i>i−1</i> 行的信号触发，且成交价只能是第 <i>i</i> 行的开盘价」。这两条已独立验证通过。</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0">逐笔往返（20 笔）</h3>
      <p style="margin-top:0">胜率 <b>25%</b>（5 胜 15 负），平均盈利 <b>+39.90%</b>，平均亏损 <b>−7.29%</b>，最佳 <b>+99.26%</b>，最差 <b>−13.63%</b>。
      低胜率仍取得正收益，靠的是少数几笔大盈利——收益分布高度右偏，也意味着<b>对单笔行情极度敏感</b>。</p>
      <div class="tbl-wrap"><table id="trades-table"></table></div>
    </div>
  </section>

  <!-- 4 含费与零成本 -->
  <section id="s4">
    <h2><span class="num">4</span>含费与零成本对比</h2>
    <p class="lead">两个费用口径<b>必须分开看</b>，它们不相等，这是复利计提的自然结果，不是错误。</p>
    <div class="grid g2" id="fee-cards"></div>
    <div class="chart-panel">
      <div class="chart-head">
        <div class="tabs"><button class="tab on" disabled>费用侵蚀：零成本 vs 含费</button></div>
        <button class="btn" id="btn-fee-png">下载 PNG</button>
        <button class="btn" id="btn-fee-zoom">放大</button>
      </div>
      <div class="chart-body"><div class="chart-host" id="fee-host"><div class="tip" id="fee-tip"></div></div></div>
      <div class="legend" id="fee-legend"></div>
      <div class="zoom-hint">两条净值曲线之间的<b>垂直间距</b>即为费用侵蚀；灰色虚线为累计净值差，与净值同轴因而贴近底部——
      这正说明费用侵蚀相对净值不算大，但对一只<b>年化仅 11.91%</b> 的策略来说，4.39% 的初始资金损耗是显著的。</div>
    </div>
    <div class="card">
      <h3 style="margin-top:0">费用明细</h3>
      <div class="tbl-wrap short"><table id="fee-table"></table></div>
      <p class="note" style="margin-bottom:0">在 40 次往返、3 年多、标的大幅波动的样本里，交易成本把累计收益从
      <b>+48.69%</b> 拉低到 <b>+44.30%</b>。若补齐印花税（卖出 0.05%）与过户费，累计收益还要再掉
      <b>3~4 个百分点</b>，跑输幅度进一步扩大。</p>
    </div>
  </section>

  <!-- 5 三种复核方法 -->
  <section id="s5">
    <h2><span class="num">5</span>三种复核方法</h2>
    <p class="lead">复核脚本刻意 <b>不 import</b> 任何生产脚本，从交付 CSV 出发用<b>不同算法路径</b>重算，再逐项比对。</p>
    <div class="grid g3" id="methods"></div>
    <div class="card" style="border-left:4px solid var(--accent)">
      <h3 style="margin-top:0">附加最强证据：从原始价格完整重放策略</h3>
      <p style="margin-top:0">复核脚本从 <code>prices.csv</code> 的原始价格出发，按规则独立重算每一天的持仓与成交，
      得到 <b>40 笔</b>成交，与账本<b>逐笔一致</b>（信号日、执行日、方向、成交价全等），末态均为空仓。
      这同时证明账本不是事后凑出来的。</p>
      <p class="note" style="margin-bottom:0">抽样：<code>seed = <span id="qa-seed"></span></code> 随机抽 20 个交易日
      <span id="qa-samples" class="num"></span>，外加预热/非预热边界行 <span id="qa-bounds" class="num"></span>。
      容差按 CSV 实际存储精度设定（indicators 存 4 位小数 → ±5e-05；prices 存 2 位小数 → ±5e-03）。</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0">复核统计</h3>
      <div class="grid g4" id="qa-stats"></div>
      <details style="margin-top:14px">
        <summary>展开全部 47 项检查明细</summary>
        <div class="body"><div class="tbl-wrap"><table id="qa-table"></table></div></div>
      </details>
    </div>
    <div class="card">
      <h3 style="margin-top:0">Excel 工作簿独立复核</h3>
      <p style="margin-top:0">工作簿用 <b>Excel COM（<code>CalculateFullRebuild</code>）</b> 强制全量重算后回读缓存值，
      再与 CSV 逐项比对——这是与 Python 侧<b>完全独立</b>的第二套实现。</p>
      <div class="tbl-wrap short"><table id="wb-table"></table></div>
    </div>
    <div class="card">
      <h3 style="margin-top:0">未解决的问题（8 项，必须与结果一并披露）</h3>
      <div class="tbl-wrap"><table id="issues-table"></table></div>
    </div>
  </section>

  <!-- 6 数据与限制 -->
  <section id="s6">
    <h2><span class="num">6</span>数据与限制</h2>
    <p class="lead">数据从哪来、怎么校验的、哪里不能过度解读。</p>
    <div class="grid g2">
      <div class="card">
        <h3 style="margin-top:0">数据来源</h3>
        <table><tbody id="src-table"></tbody></table>
      </div>
      <div class="card">
        <h3 style="margin-top:0">关键口径</h3>
        <table><tbody id="spec-table"></tbody></table>
      </div>
    </div>
    <div class="card">
      <h3 style="margin-top:0">数据校验结论</h3>
      <ul class="tight" id="validate-list"></ul>
    </div>
    <div class="card" style="border-left:4px solid #d64545">
      <h3 style="margin-top:0">限制与免责</h3>
      <ol class="tight" id="limits-list"></ol>
    </div>
  </section>

  <!-- 7 下载入口 -->
  <section id="s7">
    <h2><span class="num">7</span>下载入口</h2>
    <p class="lead">全部为相对路径，与本 HTML 同目录，离线双击即可下载。</p>
    <div id="download-groups"></div>
  </section>
</main>

<footer><div class="fi">
  本报告由 MiniMax Code 生成 · 2026-11-02 · 单文件离线 HTML（样式、数据、脚本全部内联，无任何外链）<br>
  全部数字来自同目录交付文件，可用 <code>scripts/</code> 下脚本逐项复现。
  本报告不构成投资建议，亦不证明任何交易策略有效。
</div></footer>

<div class="modal" id="modal">
  <div class="modal-head">
    <span class="t" id="modal-title">图表放大</span>
    <button class="btn" id="modal-png" style="background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.25);color:#fff">下载 PNG</button>
    <button class="x" id="modal-close">关闭 (ESC)</button>
  </div>
  <div class="modal-body" id="modal-body"></div>
  <div class="modal-foot">
    <span><b>滚轮</b> 缩放</span><span><b>拖拽</b> 平移</span><span><b>双击</b> 复位</span><span><b>ESC</b> 关闭</span>
  </div>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("payload").textContent);
const NS = "http://www.w3.org/2000/svg";

/* ============================ 工具 ============================ */
function el(tag, attrs, parent){
  const n = document.createElementNS(NS, tag);
  for(const k in attrs){ if(attrs[k]!==null && attrs[k]!==undefined) n.setAttribute(k, attrs[k]); }
  if(parent) parent.appendChild(n);
  return n;
}
function h(tag, cls, html){
  const n = document.createElement(tag);
  if(cls) n.className = cls;
  if(html!==undefined) n.innerHTML = html;
  return n;
}
function fmt(v, d){ if(v===null||v===undefined||v===isNaN(v)) return "—"; return (v).toLocaleString("zh-CN",{minimumFractionDigits:d,maximumFractionDigits:d}); }
function pct(v, d){ if(v===null||v===undefined||v==="") return "—"; return (v*100).toFixed(d===undefined?2:d)+"%"; }
function sgn(v, d){ if(v===null||v===undefined||v==="") return "—"; const x=(v*100).toFixed(d===undefined?2:d); return (v>0?"+":"")+x+"%"; }
function cls(v){ return v>0?"pos":(v<0?"neg":""); }
function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

/* ============================ 图表引擎 ============================ */
const CHARTS = {};

function buildChart(hostEl, tipEl, spec, opts){
  const host = hostEl;
  const tip = tipEl;
  const W = 1000, H = spec.height || 440;
  const m = {l:64, r:18, t:16, b:40};

  host.querySelectorAll("svg").forEach(n=>n.remove());
  const svg = el("svg", {viewBox:`0 0 ${W} ${H}`, preserveAspectRatio:"xMidYMid meet"}, host);

  // 值域
  let lo = Infinity, hi = -Infinity;
  spec.series.forEach(s=>s.data.forEach(v=>{
    if(v===null||v===undefined||isNaN(v)) return;
    if(v<lo) lo=v; if(v>hi) hi=v;
  }));
  if(spec.markers) spec.markers.forEach(mk=>{
    if(mk.price<lo) lo=mk.price; if(mk.price>hi) hi=mk.price;
  });
  if(spec.yMin!==undefined) lo = Math.min(lo, spec.yMin);
  if(spec.yMax!==undefined) hi = Math.max(hi, spec.yMax);
  if(hi===lo){ hi=lo+1; lo=lo-1; }
  const pad = (hi-lo)*0.08;
  lo -= pad; hi += pad;
  if(spec.yZero){ if(lo>0) lo=0; if(hi<0) hi=0; }

  const n = spec.dates.length;
  const x = i => m.l + (W-m.l-m.r)*(n<=1?0:i/(n-1));
  const y = v => m.t + (H-m.t-m.b)*(hi-v)/(hi-lo);

  // 网格 + Y 轴刻度
  const ticks = 6;
  for(let k=0;k<=ticks;k++){
    const v = lo + (hi-lo)*k/ticks, yy = y(v);
    el("line",{x1:m.l,y1:yy,x2:W-m.r,y2:yy,stroke:"#eceff3","stroke-width":1},svg);
    const t = el("text",{x:m.l-9,y:yy+4,"text-anchor":"end","font-size":11.5,fill:"#79828d","font-family":"inherit"},svg);
    t.textContent = spec.yFmt ? spec.yFmt(v) : fmt(v,2);
  }
  // 参考线
  (spec.refs||[]).forEach(r=>{
    el("line",{x1:m.l,y1:y(r.v),x2:W-m.r,y2:y(r.v),stroke:r.color||"#adb5bd",
      "stroke-width":1.4,"stroke-dasharray":"6 4"},svg);
    if(r.label){
      const t=el("text",{x:W-m.r-4,y:y(r.v)-6,"text-anchor":"end","font-size":11,fill:r.color||"#adb5bd","font-family":"inherit"},svg);
      t.textContent=r.label;
    }
  });

  // X 轴刻度
  const nx = 8;
  for(let k=0;k<=nx;k++){
    const i = Math.round((n-1)*k/nx);
    const t = el("text",{x:x(i),y:H-14,"text-anchor":k===0?"start":(k===nx?"end":"middle"),
      "font-size":11.5,fill:"#79828d","font-family":"inherit"},svg);
    t.textContent = spec.dates[i].slice(0,7);
  }
  el("line",{x1:m.l,y1:H-m.b,x2:W-m.r,y2:H-m.b,stroke:"#cfd6de","stroke-width":1},svg);

  // 数据层
  const g = el("g",{},svg);
  spec.series.forEach(s=>{
    if(s.fill){
      let d="", started=false;
      s.data.forEach((v,i)=>{
        if(v===null||v===undefined||isNaN(v)) return;
        d += (started?"L":"M")+x(i).toFixed(2)+" "+y(v).toFixed(2)+" ";
        started=true;
      });
      if(d){
        const lastI = s.data.reduce((a,v,i)=> (v!==null&&!isNaN(v)?i:a), 0);
        d += `L${x(lastI).toFixed(2)} ${y(spec.baseline===undefined?lo:spec.baseline).toFixed(2)} `;
        d += `L${x(0).toFixed(2)} ${y(spec.baseline===undefined?lo:spec.baseline).toFixed(2)} Z`;
        el("path",{d:d,fill:s.fill,"fill-opacity":s.fillOpacity||0.16,stroke:"none"},g);
      }
    }
    let d="", started=false;
    s.data.forEach((v,i)=>{
      if(v===null||v===undefined||isNaN(v)){ started=false; return; }
      d += (started?"L":"M")+x(i).toFixed(2)+" "+y(v).toFixed(2)+" ";
      started=true;
    });
    if(d && s.width!==0) el("path",{d:d,fill:"none",stroke:s.color,"stroke-width":s.width||1.8,
      "stroke-dasharray":s.dash||"none","stroke-linejoin":"round","stroke-linecap":"round",
      "stroke-opacity":s.opacity===undefined?1:s.opacity},g);
  });

  // 标记点
  if(spec.markers) spec.markers.forEach(mk=>{
    const cx=x(mk.i), cy=y(mk.price);
    const isBuy = mk.type==="buy";
    const color = isBuy?"#d6336c":"#0b7a6b";
    const shape = isBuy?"triangle-up":"triangle-down";
    const tri = el("polygon",{},g);
    const r = 5.4;
    let pts;
    if(isBuy) pts = [[cx,cy-r*1.25],[cx-r,cy+r*0.85],[cx+r,cy+r*0.85]];
    else pts = [[cx,cy+r*1.25],[cx-r,cy-r*0.85],[cx+r,cy-r*0.85]];
    tri.setAttribute("points", pts.map(p=>p.map(q=>q.toFixed(2)).join(",")).join(" "));
    tri.setAttribute("fill", color); tri.setAttribute("stroke","#fff"); tri.setAttribute("stroke-width",0.8);
    tri.setAttribute("data-i", mk.i);
  });

  // 交互层
  const vline = el("line",{x1:0,y1:m.t,x2:0,y2:H-m.b,stroke:"#adb5bd","stroke-width":1,"stroke-dasharray":"3 3",opacity:0},svg);
  const dots = el("g",{opacity:0},svg);
  const hit = el("rect",{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b,fill:"transparent"},svg);

  function idxFromEvent(ev){
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left)/r.width*W;
    let best=0, bd=Infinity;
    for(let i=0;i<n;i++){ const d=Math.abs(x(i)-px); if(d<bd){bd=d;best=i;} }
    return best;
  }
  function showTip(ev){
    const i = idxFromEvent(ev);
    vline.setAttribute("x1",x(i)); vline.setAttribute("x2",x(i)); vline.setAttribute("opacity",1);
    dots.innerHTML="";
    spec.series.forEach(s=>{
      const v=s.data[i]; if(v===null||v===undefined||isNaN(v)) return;
      el("circle",{cx:x(i),cy:y(v),r:3.4,fill:s.color,stroke:"#fff","stroke-width":1.2},dots);
    });
    dots.setAttribute("opacity",1);
    let html = `<div class="d">${spec.dates[i]}</div>`;
    spec.series.forEach(s=>{
      const v=s.data[i];
      html += `<div class="row"><span><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${s.color};margin-right:6px"></span>${esc(s.name)}</span><b>${s.fmt?s.fmt(v):fmt(v,2)}</b></div>`;
    });
    if(spec.markers){
      const mk = spec.markers.find(m=>m.i===i);
      if(mk) html += `<div class="row"><span>${mk.type==="buy"?"▲ 买入":"▼ 卖出"}</span><b>${fmt(mk.price,2)}</b></div>`;
    }
    tip.innerHTML = html;
    tip.style.opacity = 1;
    const hr = host.getBoundingClientRect();
    let px = ev.clientX-hr.left+16, py = ev.clientY-hr.top+12;
    if(px+tip.offsetWidth>hr.width-6) px = ev.clientX-hr.left-tip.offsetWidth-16;
    if(py+tip.offsetHeight>hr.height-6) py = Math.max(4, ev.clientY-hr.top-tip.offsetHeight-12);
    tip.style.left = px+"px"; tip.style.top = py+"px";
  }
  hit.addEventListener("mousemove", showTip);
  hit.addEventListener("mouseleave", ()=>{ tip.style.opacity=0; vline.setAttribute("opacity",0); dots.setAttribute("opacity",0); });
  hit.addEventListener("click", ()=>{ if(!(opts&&opts.noModal)) openModal(spec, spec.title); });

  return {svg:svg, host:host, spec:spec};
}

/* ============================ 图表定义 ============================ */
const COLORS = {
  "策略（零成本）":"#b8860b",
  "策略（含费0.075%）":"#c2410c",
  "赛力斯买入持有":"#1864ab",
  "沪深300买入持有":"#5f3dc4"
};
function navSpec(){
  const s = D.nav.series.map(s=>({
    name:s.name, data:s.data, color:COLORS[s.name]||"#868e96", width:2.0,
    fmt:v=>fmt(v,4)
  }));
  return {title:"净值曲线对比（起始净值 1.00）", dates:D.nav.dates, series:s, height:440,
    yFmt:v=>fmt(v,2)+"×", refs:[{v:1,label:"初始净值 1.00",color:"#adb5bd"}],
    legend:s.map(x=>({name:x.name,color:x.color}))};
}
function priceSpec(){
  const p=D.price;
  const s=[
    {name:"前复权收盘价",data:p.close,color:"#343a40",width:1.7},
    {name:"MA5",data:p.sma5,color:"#e8590c",width:1.4},
    {name:"MA20",data:p.sma20,color:"#1971c2",width:1.5},
    {name:"MA60",data:p.sma60,color:"#2f9e44",width:1.5}
  ];
  return {title:"前复权收盘价 + 均线 + 买卖点", dates:p.dates, series:s, height:440,
    yFmt:v=>fmt(v,0), markers:p.markers,
    legend:s.map(x=>({name:x.name,color:x.color})).concat([
      {name:"▲ 买入（次日开盘）",color:"#d6336c",sq:true},{name:"▼ 卖出（次日开盘）",color:"#0b7a6b",sq:true}])};
}
function ddSpec(){
  const s = D.dd.series.map(x=>({
    name:x.name, data:x.data, color:COLORS[x.name]||"#868e96", width:1.8,
    fill:x.name, fillOpacity:0.07, baseline:0, fmt:v=>pct(v,2)
  }));
  return {title:"回撤曲线（水下图）", dates:D.dd.dates, series:s, height:400,
    yFmt:v=>pct(v,0), yZero:true, yMax:0,
    legend:s.map(x=>({name:x.name,color:x.color}))};
}
function feeSpec(){
  const s=[
    {name:"零成本净值",data:D.fee.gross,color:"#b8860b",width:2.0,fmt:v=>fmt(v,0)},
    {name:"含费净值（0.075%/单边）",data:D.fee.net,color:"#c2410c",width:2.0,fmt:v=>fmt(v,0)},
    {name:"费用造成的累计净值差",data:D.fee.gap,color:"#868e96",width:1.6,dash:"5 4",fmt:v=>fmt(v,0)}
  ];
  return {title:"费用侵蚀：零成本 vs 含费", dates:D.fee.dates, series:s, height:380,
    yFmt:v=>fmt(v,0), legend:[
      {name:"零成本净值（元）",color:"#b8860b"},{name:"含费净值（元）",color:"#c2410c"},
      {name:"费用造成的累计净值差（元，同轴）",color:"#868e96"}]};
}

/* ============================ 渲染各区块 ============================ */
function renderMeta(){
  const m=D.meta;
  const chips=[
    `标的 ${m.name}（${m.symbol}）`, `基准 ${m.benchName}（${m.benchSymbol}）`,
    `区间 ${m.start} ~ ${m.end}`, `${m.days} 个交易日`,
    `预热 ${m.warmup} 行（~ ${m.warmupEnd}）`, `首个可评估日 ${m.firstEval}`,
    `生成 ${m.generated}`
  ];
  document.getElementById("hero-meta").innerHTML = chips.map(c=>`<span class="chip">${esc(c)}</span>`).join("");
}

function renderKpi(){
  const idx={};
  D.metrics.forEach(r=>{ idx[r.series+"|"+r.cost_regime]=r; });
  const sNet=idx["赛力斯 SMA5/20 交叉策略|fee_0.075pct_oneway"];
  const sGross=idx["赛力斯 SMA5/20 交叉策略|zero_cost"];
  const bh=idx["赛力斯 买入持有|zero_cost"];
  const ix=idx["沪深300 价格指数 买入持有|zero_cost"];
  if(!sNet||!bh||!ix){ console.warn("metrics key mismatch", Object.keys(idx)); return; }

  document.getElementById("verdict").innerHTML =
    `<h3>结论：策略跑输买入持有，唯一的相对优势是回撤更浅</h3>
     <div style="font-size:14px;color:var(--ink2)">
       策略（含费）累计收益 <b class="pos">${sgn(+sNet.cumulative_return)}</b>，
       同期买入持有赛力斯 <b class="pos">${sgn(+bh.cumulative_return)}</b>，
       差距 <b class="neg">${sgn(+sNet.cumulative_return - +bh.cumulative_return)}</b>；
       最大回撤 <b class="neg">${pct(+sNet.max_drawdown)}</b> vs 买入持有 <b class="neg">${pct(+bh.max_drawdown)}</b>。
       同期沪深300 <b class="pos">${sgn(+ix.cumulative_return)}</b>——策略跑赢指数主要来自<b>个股 Beta</b>，不是策略本身的 alpha。
       <br><b>该结果如实呈现，没有为让数字好看而更换区间或调参。</b>
     </div>`;

  const cards=[
    {t:"策略（含费 0.075%）",v:sgn(+sNet.cumulative_return),d:`年化 ${sgn(+sNet.annualized_return)} · 回撤 ${pct(+sNet.max_drawdown)}`,tag:"策略",c:cls(+sNet.cumulative_return)},
    {t:"赛力斯 买入持有",v:sgn(+bh.cumulative_return),d:`年化 ${sgn(+bh.annualized_return)} · 回撤 ${pct(+bh.max_drawdown)}`,tag:"基准",c:cls(+bh.cumulative_return)},
    {t:"沪深300 买入持有",v:sgn(+ix.cumulative_return),d:`年化 ${sgn(+ix.annualized_return)} · 回撤 ${pct(+ix.max_drawdown)}`,tag:"基准",c:cls(+ix.cumulative_return)},
    {t:"策略期末净值（含费）",v:fmt(+sNet.final_nav,0)+" 元",d:`零成本 ${fmt(+sGross.final_nav,0)} 元 · 差 ${fmt(+sGross.final_nav-+sNet.final_nav,0)} 元`,tag:"资金",c:""}
  ];
  document.getElementById("kpis").innerHTML = cards.map(c=>
    `<div class="kpi"><span class="tag">${c.tag}</span><div class="t">${esc(c.t)}</div>
     <div class="v ${c.c}">${c.v}</div><div class="d">${c.d}</div></div>`).join("");

  const s=D.snapshot;
  document.getElementById("snap-card").innerHTML=
    `<h3 style="margin-top:0">当日技术快照（${s.date}）</h3>
     <dl class="kv">
       <dt>收盘价</dt><dd>${fmt(s.close,2)} 元</dd>
       <dt>MA5 / MA20 / MA60</dt><dd>${fmt(s.sma5,2)} / ${fmt(s.sma20,2)} / ${fmt(s.sma60,2)}</dd>
       <dt>MACD DIF / DEA / 柱</dt><dd>${fmt(s.dif,4)} / ${fmt(s.dea,4)} / ${fmt(s.hist,4)}</dd>
       <dt>RSI14</dt><dd>${fmt(s.rsi14,2)}</dd>
       <dt>均线排列</dt><dd><b style="color:var(--accent)">${esc(s.alignment)}</b></dd>
       <dt>技术评分</dt><dd><b class="neg">${s.score} / 100（${esc(s.score_band)}）</b></dd>
     </dl>
     <p class="note" style="margin-bottom:0">评分只描述<b>当日</b>技术状态，不预测收益、不证明策略有效。</p>`;

  const wins=D.trades.filter(t=>t.ret>0).length;
  document.getElementById("takeaway-card").innerHTML=
    `<h3 style="margin-top:0">要点速览</h3>
     <ul class="tight">
       <li><b>${D.trades.length}</b> 次往返，胜率 <b>${(wins/D.trades.length*100).toFixed(0)}%</b>（${wins} 胜 ${D.trades.length-wins} 负）；
         收益全靠少数几笔大盈利（最佳 <b class="pos">${sgn(Math.max(...D.trades.map(t=>t.ret)))}</b>）。</li>
       <li>持仓 <b>${sNet.holding_days}</b> 天（占比 <b>${pct(+sNet.holding_ratio)}</b>），其余时间空仓。</li>
       <li>交易成本把累计收益从 <b>${sgn(+sGross.cumulative_return)}</b> 拉到 <b>${sgn(+sNet.cumulative_return)}</b>；
         费用造成的期末净值差 <b>${fmt(+D.breakdown[0].value,2)}</b> 元，实际支付费用 <b>${fmt(+D.breakdown[1].value,2)}</b> 元（两者口径不同）。</li>
       <li>20 笔往返、3 年多、标的大幅波动 —— 费用是决定性因素之一；补齐印花税与过户费还要再掉 3~4 个百分点。</li>
       <li>本区间为<b>样本内</b>结果，未做样本外检验与参数敏感性分析，<b>不证明策略有效</b>。</li>
     </ul>`;
}

function renderMetricsTable(){
  const names={ "赛力斯 SMA5/20 交叉策略":"SMA5/20 交叉策略","赛力斯 买入持有":"赛力斯 买入持有","沪深300 价格指数 买入持有":"沪深300 买入持有"};
  const order=[["赛力斯 SMA5/20 交叉策略","fee_0.075pct_oneway","策略（含费 0.075%）"],
               ["赛力斯 SMA5/20 交叉策略","zero_cost","策略（零成本）"],
               ["赛力斯 买入持有","zero_cost","赛力斯 买入持有"],
               ["沪深300 价格指数 买入持有","zero_cost","沪深300 买入持有"]];
  const idx={}; D.metrics.forEach(r=>{ idx[r.series+"|"+r.cost_regime]=r; });
  let html=`<thead><tr><th class="l">指标</th><th>策略（含费 0.075%）</th><th>策略（零成本）</th><th>赛力斯 买入持有</th><th>沪深300 买入持有</th></tr></thead><tbody>`;
  const rows=[
    ["期末净值（元）", r=>fmt(+r.final_nav,2)],
    ["累计收益", r=>`<span class="${cls(+r.cumulative_return)}">${sgn(+r.cumulative_return)}</span>`],
    ["年化收益", r=>`<span class="${cls(+r.annualized_return)}">${sgn(+r.annualized_return)}</span>`],
    ["最大回撤", r=>`<span class="neg">${pct(+r.max_drawdown)}</span>`],
    ["最大回撤区间", r=>`${r.dd_peak_date} → ${r.dd_trough_date}`],
    ["交易次数（往返）", r=>r.trade_count],
    ["持仓天数", r=>r.holding_days],
    ["持仓占比", r=>pct(+r.holding_ratio)],
    ["实际支付费用（元）", r=>r.total_fees_paid==="0"||+r.total_fees_paid===0?"0.00":fmt(+r.total_fees_paid,2)]
  ];
  rows.forEach(([label,fn])=>{
    html+=`<tr><td class="l">${label}</td>`;
    order.forEach(([s,c])=>{ const r=idx[s+"|"+c]; html+=`<td class="num">${r?fn(r):"—"}</td>`; });
    html+="</tr>";
  });
  html+="</tbody>";
  document.getElementById("metrics-table").innerHTML=html;
}

function renderRules(){
  const rules=[
    ["入场","SMA5 上穿 SMA20（金叉）→ <b>次日开盘</b> 全仓买入"],
    ["出场","SMA5 下穿 SMA20（死叉）→ <b>次日开盘</b> 清仓"],
    ["方向","只做多，不做空"],
    ["预热",`前 ${D.meta.warmup} 根K线（至 ${D.meta.warmupEnd}）不交易、不评分、不发信号`],
    ["样本末","<b>不强制平仓</b>（本例末态恰为空仓）"],
    ["初始资金","1,000,000 元"],
    ["份额","允许小数份额，买入后现金恰为 0"],
    ["成交价","前复权价，按当日<b>开盘价</b>成交"],
    ["费用","单边 0.075%（零成本账本另出，不计印花税与过户费）"]
  ];
  document.getElementById("rules-table").innerHTML =
    rules.map(r=>`<tr><td class="l" style="width:96px;color:var(--ink3)">${r[0]}</td><td class="l">${r[1]}</td></tr>`).join("");

  document.getElementById("sig-table").innerHTML =
    `<thead><tr><th class="l">信号族</th><th>合计</th><th>金叉</th><th>死叉</th></tr></thead><tbody>`+
    D.signals.families.map(f=>`<tr><td class="l">${esc(f.family)}</td><td class="num">${f.total}</td><td class="num">${f.golden}</td><td class="num">${f.death}</td></tr>`).join("")+
    `<tr><td class="l"><b>合计</b></td><td class="num"><b>${D.signals.total}</b></td><td class="num">${D.signals.families.reduce((a,f)=>a+f.golden,0)}</td><td class="num">${D.signals.families.reduce((a,f)=>a+f.death,0)}</td></tr></tbody>`;

  document.getElementById("chain-table").innerHTML=
    `<thead><tr><th class="l">日期</th><th class="l">当日收盘</th><th class="l">事件</th></tr></thead><tbody>
     <tr><td class="l num">2025-01-02</td><td class="l">金叉成立（SMA5 上穿 SMA20）</td><td class="l">当日<b>不</b>成交</td></tr>
     <tr><td class="l num">2025-01-03</td><td class="l">开盘按前一日金叉买入；当日收盘又出死叉</td><td class="l">BUY @ 126.42</td></tr>
     <tr><td class="l num">2025-01-06</td><td class="l">开盘按 01-03 死叉卖出</td><td class="l">SELL @ 122.75</td></tr>
     </tbody>`;
}

function renderTrades(){
  let html=`<thead><tr><th>#</th><th class="l">信号日</th><th class="l">买入日</th><th>买入价</th><th class="l">卖出日</th><th>卖出价</th><th>单笔收益</th></tr></thead><tbody>`;
  D.trades.forEach((t,i)=>{
    html+=`<tr><td class="num">${i+1}</td><td class="l num">—</td><td class="l num">${t.buy_date}</td><td class="num">${fmt(t.buy_price,2)}</td>
    <td class="l num">${t.sell_date}</td><td class="num">${fmt(t.sell_price,2)}</td>
    <td class="num ${cls(t.ret)}">${sgn(t.ret)}</td></tr>`;
  });
  html+="</tbody>";
  document.getElementById("trades-table").innerHTML=html;
}

function renderFee(){
  const g=D.breakdown[0], f=D.breakdown[1];
  document.getElementById("fee-cards").innerHTML=
    `<div class="kpi"><span class="tag">口径一</span><div class="t">费用造成的期末净值差</div>
       <div class="v">${fmt(+g.value,2)} 元</div><div class="d">占初始资金 ${(g.value/1000000*100).toFixed(2)}% · 零成本期末净值 − 含费期末净值</div></div>
     <div class="kpi"><span class="tag">口径二</span><div class="t">实际支付费用合计</div>
       <div class="v">${fmt(+f.value,2)} 元</div><div class="d">占初始资金 ${(f.value/1000000*100).toFixed(2)}% · 含费账本 40 个成交腿累计计提</div></div>`;

  document.getElementById("fee-table").innerHTML=
    `<thead><tr><th class="l">口径</th><th>金额（元）</th><th>占初始资金</th><th class="l">含义</th></tr></thead><tbody>
     <tr><td class="l"><b>费用造成的期末净值差</b></td><td class="num">${fmt(+g.value,2)}</td><td class="num">${(g.value/1000000*100).toFixed(2)}%</td><td class="l">${esc(g.note)}</td></tr>
     <tr><td class="l"><b>实际支付费用合计</b></td><td class="num">${fmt(+f.value,2)}</td><td class="num">${(f.value/1000000*100).toFixed(2)}%</td><td class="l">${esc(f.note)}</td></tr>
     <tr><td class="l">零成本期末净值</td><td class="num">1,486,924.17</td><td class="num">—</td><td class="l">Ledger_Gross.csv 末行 nav</td></tr>
     <tr><td class="l">含费期末净值</td><td class="num">1,442,978.92</td><td class="num">—</td><td class="l">Ledger.csv 末行 nav</td></tr>
     </tbody>`;
}

function renderMethods(){
  const M=[
    {n:"1",t:"均线复核：双算法互校",p:"生产实现用滚动窗口累加；复核改用<b>前缀和差分法</b> + <b>滚动差分法</b>两套算法，各自独立算出 SMA5/20/60，再与 <code>indicators.csv</code> 三方比对。",
     res:"22 个抽样行 × 3 条均线 × 2 种算法<b>全部吻合</b>"},
    {n:"2",t:"EMA 复核：显式标量循环",p:"生产实现是向量化递推；复核用<b>显式标量循环</b>逐日递推 EMA12/26，并额外用「首价种子」口径做了敏感性对照。",
     res:"全样本 822 行最大偏差 <b>5.0e-05</b>（恰为 CSV 存储精度上限）"},
    {n:"3",t:"净值复核：log 收益累加 + 显式峰值循环",p:"净值用 <code>log(r)</code> 累加后再 <code>exp()</code> 还原；最大回撤用<b>显式循环维护运行峰值</b>，不使用任何现成指标函数。",
     res:"净值最大偏差 <b>2.33e-09 元</b>；四条曲线回撤全部吻合到 1e-6"}
  ];
  document.getElementById("methods").innerHTML = M.map(m=>
    `<div class="method"><span class="n">${m.n}</span><h3>${m.t}</h3><p style="font-size:13.5px;color:var(--ink2)">${m.p}</p>
     <div class="res">✅ ${m.res}</div></div>`).join("");

  document.getElementById("qa-seed").textContent=D.qa.seed;
  document.getElementById("qa-samples").textContent="["+D.qa.samples.join(", ")+"]";
  document.getElementById("qa-bounds").textContent="["+D.qa.boundaries.join(", ")+"]";

  document.getElementById("qa-stats").innerHTML=[
    {t:"检查项总数",v:D.qa.total},{t:"通过",v:D.qa.passed},{t:"失败",v:D.qa.failed},
    {t:"工作簿比对项",v:D.wb.checks_total}
  ].map(x=>`<div class="kpi"><div class="t">${x.t}</div><div class="v" style="color:${x.v&&x.v!==0?(x.t==="失败"?"var(--ok)":"var(--ink)"):"var(--ok)"}">${x.v}</div></div>`).join("");

  let html=`<thead><tr><th class="l">检查项</th><th>状态</th><th class="l">说明</th></tr></thead><tbody>`;
  D.qa.checks.forEach(c=>{
    html+=`<tr><td class="l">${esc(c.check)}</td><td><span class="pill ${c.status==="PASS"?"ok":"no"}">${c.status}</span></td><td class="l">${esc(c.detail||"")}</td></tr>`;
  });
  html+="</tbody>";
  document.getElementById("qa-table").innerHTML=html;

  const wb=D.wb;
  document.getElementById("wb-table").innerHTML=
    `<thead><tr><th class="l">项</th><th>值</th></tr></thead><tbody>
     <tr><td class="l">工作表顺序</td><td class="num">${wb.sheets.join(" → ")}</td></tr>
     <tr><td class="l">公式总数</td><td class="num">${wb.total_formulas.toLocaleString()}</td></tr>
     ${Object.entries(wb.formulas_per_sheet).filter(([k,v])=>v>0).map(([k,v])=>`<tr><td class="l">　${k}</td><td class="num">${v.toLocaleString()}</td></tr>`).join("")}
     <tr><td class="l">错误单元格</td><td class="num"><b style="color:var(--ok)">${wb.error_cells}</b></td></tr>
     <tr><td class="l">与 CSV 逐项比对</td><td class="num"><b style="color:var(--ok)">${wb.checks_passed} / ${wb.checks_total} 一致</b></td></tr>
     <tr><td class="l">重算方式</td><td class="num">Excel COM · CalculateFullRebuild（${wb.recalc_seconds}s）</td></tr>
     </tbody>`;

  const ISSUES=[
    ["基准指数为单一供应商","沪深300 全部 822 点只有 iFinD 一个来源。复核只能证明「CSV 与 iFinD 原始响应一致」，<b>不能证明 iFinD 本身正确</b>。","已抽检 2023-06-01 / 2024-12-31 及媒体口径一致；全区间未逐点第三方验证"],
    ["前复权价成交，绝对金额非实盘口径","前复权序列隐含「分红按因子再投资」；账本中的现金、股数、成交价不是真实可交易金额。","收益率序列正确；绝对金额仅供教学，不可实盘复用"],
    ["成交假设偏乐观","假设开盘价全额成交，未建模集合竞价可成交量、涨跌停封板无法成交、停牌、流动性冲击与滑点。","真实成交成本必然更高，策略表现只会更差"],
    ["EMA 初始化口径敏感","本项目采用 SMA 种子（与 iFinD / 通达信一致）。若改用首价种子，全样本最大偏差 <b>1.061</b>，最后 100 根K线收敛为 0。","样本早期 RSI/MACD 对初始化敏感，中期之后无影响"],
    ["费用模型刻意简化","只计 0.075% 单边佣金，<b>未计</b>印花税（卖出 0.05%）、过户费、冲击成本。","若补齐，40 次往返再损失约 3–4 个百分点，跑输幅度进一步扩大"],
    ["无样本外检验、无参数敏感性分析","本次 QA 只证明「计算忠实于既定规则」，<b>不证明规则有效</b>。未测试 SMA 参数邻域稳定性，未做 walk-forward。","策略跑输买入持有 25.48 个百分点这一事实已如实呈现，未做任何区间或参数调整"],
    ["存储精度限制复核精度","indicators.csv 存 4 位小数、prices.csv 存 2 位小数，复核容差只能是 ±5e-5 / ±5e-3。","需逐位复现请用 scripts/ 重算而非读 CSV"],
    ["单一标的、单一市场","只测了赛力斯一只高波动个股，未跨标的、跨市场验证。","结论不可外推"]
  ];
  document.getElementById("issues-table").innerHTML=
    `<thead><tr><th>#</th><th class="l">未解决问题</th><th class="l">具体影响</th><th class="l">现状</th></tr></thead><tbody>`+
    ISSUES.map((r,i)=>`<tr><td class="num">${i+1}</td><td class="l"><b>${r[0]}</b></td><td class="l">${r[1]}</td><td class="l">${r[2]}</td></tr>`).join("")+"</tbody>";
}

function renderData(){
  document.getElementById("src-table").innerHTML=
    `<thead><tr><th class="l">用途</th><th class="l">来源</th><th class="l">关键参数</th></tr></thead><tbody>
     <tr><td class="l">个股行情</td><td class="l">恒生行情 Connector <code>get_daily_bars</code></td><td class="l"><code>adjustment=forward</code>（前复权），822 根，<code>coverageComplete=true</code></td></tr>
     <tr><td class="l">基准指数</td><td class="l">同花顺 iFinD <code>get_security_indicators</code>（market=指数）</td><td class="l">沪深300 价格指数，14 个分块拉取</td></tr>
     <tr><td class="l">指标交叉验证</td><td class="l">同花顺 iFinD 标准指标</td><td class="l">MA / RSI / MACD 对照</td></tr>
     </tbody>`;

  document.getElementById("spec-table").innerHTML=
    `<thead><tr><th class="l">项</th><th class="l">设定</th></tr></thead><tbody>
     <tr><td class="l">区间</td><td class="l">${D.meta.start} ~ ${D.meta.end}（${D.meta.days} 个交易日）</td></tr>
     <tr><td class="l">价格基准</td><td class="l">前复权，锚定区间末日</td></tr>
     <tr><td class="l">预热</td><td class="l">前 ${D.meta.warmup} 行（至 ${D.meta.warmupEnd}）</td></tr>
     <tr><td class="l">首个可评估日</td><td class="l">${D.meta.firstEval}</td></tr>
     <tr><td class="l">初始资金</td><td class="l">1,000,000 元</td></tr>
     <tr><td class="l">费用</td><td class="l">单边 0.075%；不计印花税与过户费</td></tr>
     <tr><td class="l">年化</td><td class="l"><code>(期末/初始)^(252/(N−1))−1</code>，N=822</td></tr>
     <tr><td class="l">最大回撤</td><td class="l">显式循环维护运行峰值</td></tr>
     <tr><td class="l">净值复核</td><td class="l"><code>log(r)</code> 累加后 <code>exp()</code> 还原</td></tr>
     </tbody>`;

  document.getElementById("validate-list").innerHTML=[
    "个股与基准 <b>822 个交易日完全对齐</b>，两侧差集为空，无重复、无缺失、零 OHLC 违例。",
    "前复权序列<b>锚定区间末日</b>（2026-10-23 前复权收盘 42.53 = 原始价）。",
    "4 个除权跳变点 <code>2024-12-13</code> / <code>2025-05-13</code> / <code>2025-10-30</code> / <code>2026-06-03</code> 与未复权序列断点一一对应。",
    "跨源抽检 2023-06-01（25.38 / 前收 25.78）、2024-12-31（133.39 / 134.80）、2026-10-23（42.53 / 40.90），恒生与 iFinD <b>完全一致</b>。",
    "沪深300 2023-06-01 收 3806.87 点 / 成交额 2418.3 亿，与多家财经媒体口径一致。",
    "iFinD 单次查询有 100 行上限且会<b>静默降采样</b>，故拆成 14 个 ≤90 天自然日块，逐块校验行数 = 自然日数（14/14 FULL）。",
    "三处 &gt;10 天断档均为法定休市：<code>2023-09-28→2023-10-09</code>、<code>2024-02-08→2024-02-19</code>、<code>2026-02-13→2026-02-24</code>。",
    "技术指标与 iFinD 标准指标交叉验证：MA5/20/60 <b>完全相同</b>，RSI14 差 0.0014，MACD DIF/DEA/柱 差 ≤0.0007。",
    "全样本连续同向重复信号 <b>0</b> 次；最小信号行号 61，全部在预热期之后。",
    "独立复核 <b>47/47</b> 通过；Excel 工作簿重算后与 CSV <b>57/57</b> 一致，错误单元格 <b>0</b>。"
  ].map(x=>`<li>${x}</li>`).join("");

  document.getElementById("limits-list").innerHTML=[
    "<b>不构成投资建议</b>，不预测收益，也不证明任何交易策略有效。",
    "回测为<b>样本内</b>结果，<b>未经样本外检验、未做参数敏感性分析</b>。",
    "使用<b>前复权价</b>成交，绝对金额口径<b>非实盘口径</b>。",
    "<b>未建模</b>涨跌停不可成交、集合竞价、停牌、滑点与冲击成本，成交假设偏乐观。",
    "费用仅计单边 0.075%，<b>未计</b>印花税 0.05% 与过户费；补齐后再损约 3~4 个百分点。",
    "EMA 初始化口径敏感（SMA 种子 vs 首价种子，全样本最大偏差 1.061，最后 100 根K线收敛为 0）。",
    "基准指数为<b>单一供应商</b>（iFinD），未做全区间逐点第三方验证。",
    "CSV 存储精度（4 位 / 2 位小数）限制复核精度，复核容差相应放宽。",
    "<b>单一标的、单一市场</b>，结论不可外推。",
    "策略在本区间<b>跑输</b>同期买入持有 25.48 个百分点 —— 如实呈现，未做任何区间或参数调整。"
  ].map(x=>`<li>${x}</li>`).join("");
}

function renderDownload(){
  const groups={};
  D.files.forEach(f=>{ (groups[f.group]=groups[f.group]||[]).push(f); });
  const html=Object.keys(groups).map(g=>{
    const items=groups[g].map(f=>{
      const size = f.size===null||f.size===undefined ? "同目录文件" :
        (f.size>1048576 ? (f.size/1048576).toFixed(2)+" MB" : (f.size/1024).toFixed(1)+" KB");
      return `<a href="${encodeURI(f.path)}" download="${f.path.split("/").pop()}">
        <span class="fn">${esc(f.path)}</span>
        <span class="fd">${esc(f.desc)}</span>
        <span class="fs">${size}</span></a>`;
    }).join("");
    return `<h3>${esc(g)}</h3><div class="dl">${items}</div>`;
  }).join("");
  document.getElementById("download-groups").innerHTML=html;
}

/* ============================ 图表切换 + 放大 ============================ */
let current=null, currentSpec=null;
const SPECS={nav:navSpec, price:priceSpec, dd:ddSpec};
const TAB_NAMES={nav:"净值曲线",price:"价格与买卖点",dd:"回撤曲线"};

function switchChart(key){
  current=key;
  currentSpec=SPECS[key]();
  buildChart(document.getElementById("chart-host"), document.getElementById("tip"), currentSpec);
  document.getElementById("legend").innerHTML = currentSpec.legend.map(l=>
    `<span><i class="${l.sq?"sq":""}" style="background:${l.color}"></i>${esc(l.name)}</span>`).join("");
  document.querySelectorAll("#tabs .tab").forEach(b=>b.classList.toggle("on", b.dataset.k===key));
}

function initTabs(){
  const tabs=document.getElementById("tabs");
  tabs.innerHTML=Object.keys(SPECS).map(k=>`<button class="tab${k==="nav"?" on":""}" data-k="${k}">${TAB_NAMES[k]}</button>`).join("");
  tabs.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>switchChart(b.dataset.k)));
}

/* ---- 放大 modal ---- */
const modal=document.getElementById("modal");
let modalSpec=null, zoomK=1, dragging=false, lastPt=null;
function openModal(spec,title){
  modalSpec=spec;
  zoomK=1;
  document.getElementById("modal-title").textContent=title||spec.title;
  const body=document.getElementById("modal-body");
  body.innerHTML="";
  const holder=h("div","","" ); holder.style.cssText="width:100%;display:flex;justify-content:center;";
  body.appendChild(holder);
  const svg=buildChartInto(holder,spec);
  applyZoom();
  modal.classList.add("open");
  document.body.style.overflow="hidden";
}
function buildChartInto(holder,spec){
  const tip=h("div","tip"); tip.id="mtip";
  const host=h("div","chart-host"); host.style.width="100%";
  host.appendChild(tip);
  holder.appendChild(host);
  const c=buildChart(host, tip, spec, {noModal:true});
  return c.svg;
}
function applyZoom(){
  const svg=document.querySelector("#modal-body svg");
  if(!svg) return;
  const baseW=1600;
  const vb=svg.getAttribute("viewBox").split(" ").map(Number);
  svg.style.width=(baseW*zoomK)+"px";
  svg.style.height=Math.round(baseW*zoomK*(vb[3]/vb[2]))+"px";
}
function closeModal(){ modal.classList.remove("open"); document.body.style.overflow=""; }

/* ============================ CSV / PNG 导出 ============================ */
function download(name, blob){
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob); a.download=name;
  document.body.appendChild(a); a.click();
  setTimeout(()=>{ URL.revokeObjectURL(a.href); a.remove(); }, 1500);
}
function specToCsv(spec){
  const head=["date"].concat(spec.series.map(s=>s.name));
  const lines=[head.join(",")];
  for(let i=0;i<spec.dates.length;i++){
    const row=[spec.dates[i]].concat(spec.series.map(s=>{
      const v=s.data[i]; return (v===null||v===undefined||isNaN(v))?"":v;
    }));
    lines.push(row.join(","));
  }
  if(spec.markers){
    lines.push("");
    lines.push("trade_date,type,fill_price");
    spec.markers.forEach(m=>lines.push([m.date,m.type,m.price].join(",")));
  }
  return lines.join("\n");
}
function svgToPng(svg,name){
  const clone=svg.cloneNode(true);
  clone.setAttribute("xmlns",NS);
  const vb=clone.getAttribute("viewBox").split(" ").map(Number);
  const w=vb[2]*2, h=vb[3]*2;
  const str=new XMLSerializer().serializeToString(clone);
  const img=new Image();
  const blob=new Blob([str],{type:"image/svg+xml;charset=utf-8"});
  const url=URL.createObjectURL(blob);
  img.onload=function(){
    const cv=document.createElement("canvas");
    cv.width=w; cv.height=h;
    const ctx=cv.getContext("2d");
    ctx.fillStyle="#fff"; ctx.fillRect(0,0,w,h);
    ctx.drawImage(img,0,0,w,h);
    URL.revokeObjectURL(url);
    cv.toBlob(b=>download(name,b),"image/png");
  };
  img.src=url;
}

/* ============================ TOC ============================ */
function initToc(){
  const secs=[...document.querySelectorAll("main section")];
  const names=secs.map(s=>{
    const h2=s.querySelector("h2");
    return {id:s.id, t:h2.textContent.replace(/^\s*\d+\s*/,"").trim()};
  });
  document.getElementById("toc").innerHTML=names.map(n=>`<a href="#${n.id}">${esc(n.t)}</a>`).join("");
  const links=[...document.querySelectorAll("#toc a")];
  const obs=new IntersectionObserver(es=>{
    es.forEach(e=>{
      if(e.isIntersecting){
        links.forEach(l=>l.classList.toggle("on", l.getAttribute("href")==="#"+e.target.id));
      }
    });
  },{rootMargin:"-60px 0px -70% 0px"});
  secs.forEach(s=>obs.observe(s));
}

/* ============================ 启动 ============================ */
document.addEventListener("DOMContentLoaded",()=>{
  renderMeta(); renderKpi(); renderMetricsTable(); renderRules(); renderTrades();
  renderFee(); renderMethods(); renderData(); renderDownload();
  initTabs(); switchChart("nav");
  initToc();

  document.getElementById("btn-csv").addEventListener("click",()=>{
    download("chart_"+current+".csv", new Blob(["\ufeff"+specToCsv(currentSpec)],{type:"text/csv;charset=utf-8"}));
  });
  document.getElementById("btn-png").addEventListener("click",()=>{
    const svg=document.querySelector("#chart-host svg");
    if(svg) svgToPng(svg,"chart_"+current+".png");
  });
  document.getElementById("btn-zoom").addEventListener("click",()=>openModal(currentSpec,currentSpec.title));

  const feeSpecObj=feeSpec();
  buildChart(document.getElementById("fee-host"), document.getElementById("fee-tip"), feeSpecObj);
  document.getElementById("fee-legend").innerHTML=feeSpecObj.legend.map(l=>
    `<span><i class="${l.sq?"sq":""}" style="background:${l.color}"></i>${esc(l.name)}</span>`).join("");
  document.getElementById("btn-fee-zoom").addEventListener("click",()=>openModal(feeSpecObj,feeSpecObj.title));
  document.getElementById("btn-fee-png").addEventListener("click",()=>{
    const svg=document.querySelector("#fee-host svg");
    if(svg) svgToPng(svg,"chart_fee_erosion.png");
  });

  document.getElementById("modal-close").addEventListener("click",closeModal);
  document.getElementById("modal-png").addEventListener("click",()=>{
    const svg=document.querySelector("#modal-body svg");
    if(svg) svgToPng(svg,"chart_zoom.png");
  });
  modal.addEventListener("click",e=>{ if(e.target===modal) closeModal(); });
  document.addEventListener("keydown",e=>{ if(e.key==="Escape") closeModal(); });
  const body=document.getElementById("modal-body");
  body.addEventListener("wheel",e=>{
    e.preventDefault();
    zoomK=Math.min(5,Math.max(0.6,zoomK*(e.deltaY<0?1.12:0.89)));
    applyZoom();
  },{passive:false});
  body.addEventListener("mousedown",e=>{ dragging=true; lastPt={x:e.clientX,y:e.clientY}; body.style.cursor="grabbing"; });
  window.addEventListener("mouseup",()=>{ dragging=false; body.style.cursor=""; });
  window.addEventListener("mousemove",e=>{
    if(!dragging||!lastPt) return;
    body.scrollLeft -= (e.clientX-lastPt.x);
    body.scrollTop  -= (e.clientY-lastPt.y);
    lastPt={x:e.clientX,y:e.clientY};
  });
  body.addEventListener("dblclick",()=>{ zoomK=1; applyZoom(); });
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
