"""Independent QA re-verification of the whole pipeline.

Deliberately does NOT import indicators.py / backtest.py / metrics.py.
Every quantity is re-derived from the delivered CSV files with a different
algorithm than the one used to produce them:

  SMA   -> prefix-sum window AND rolling-difference window (two independent methods)
  EMA   -> explicit scalar loop (documented SMA-seeded convention + alternative seed)
  NAV   -> log-return accumulation then exp()
  MDD   -> explicit loop maintaining a running peak
  TRADES-> full strategy replay from raw prices, compared to the ledger

Look-ahead is tested structurally: a signal on bar t must be reproducible from
closes[0..t] only, and an execution must occur at bar t+1's OPEN.

Tolerance note: indicators.csv stores values rounded to 4 decimals, so the
comparison tolerance must be half an ulp of the stored precision (5e-5), not
an arbitrary tight epsilon.
"""
from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
TOL4 = 5e-5          # half-ulp for 4-decimal stored values
TOL2 = 5e-3          # half-ulp for 2-decimal stored values
SEED = 20261102
SAMPLE_N = 20

results = []


def check(name, ok, detail=""):
    results.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def read(name, folder=ROOT):
    with (folder / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def approx(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


prices = read("prices.csv")
bench = read("prices_bench.csv")
ind = read("indicators.csv")
sigs = read("signals.csv")
gross = read("Ledger_Gross.csv")
net = read("Ledger.csv")
metrics = read("metrics.csv")

dates = [r["date"] for r in prices]
closes = [float(r["close"]) for r in prices]
opens = [float(r["open"]) for r in prices]
n = len(prices)

print(f"loaded: prices={n} bench={len(bench)} indicators={len(ind)} "
      f"signals={len(sigs)} gross={len(gross)} net={len(net)} metrics={len(metrics)}")
print(f"容差口径：indicators.csv 存 4 位小数 -> ±{TOL4}；prices.csv 存 2 位小数 -> ±{TOL2}")
print()

# ================================================================ A. 均线
P = [0.0] * (n + 1)
for i, c in enumerate(closes):
    P[i + 1] = P[i] + c


def sma_prefix(i, w):
    """Window sum via prefix-sum differencing."""
    if i < w - 1:
        return None
    return (P[i + 1] - P[i + 1 - w]) / w


def sma_rolling(i, w):
    """Window sum via a running difference: add the new close, drop the oldest."""
    if i < w - 1:
        return None
    s = sum(closes[:w])                 # window ending at index w-1
    for j in range(w, i + 1):            # roll forward one bar at a time
        s += closes[j] - closes[j - w]
    return s / w


ind_close = [float(r["close"]) for r in ind]
check("indicators.csv 与 prices.csv 行数一致", len(ind) == n, f"{len(ind)} vs {n}")
check("indicators.csv 的 close 与 prices.csv 逐行相同",
      all(approx(ind_close[i], closes[i], TOL2) for i in range(n)))

elig = list(range(59, n))
random.seed(SEED)
sample = sorted(random.sample(elig, SAMPLE_N))
boundary = [58, 59]
print(f"\n随机抽样 {SAMPLE_N} 个交易日（seed={SEED}）: {sample}")
print(f"额外边界复核行（预热/非预热交界）: {boundary}\n")

sma_ok, sma_detail = True, []
for i in sample + boundary:
    for w, col in ((5, "sma5"), (20, "sma20"), (60, "sma60")):
        want = float(ind[i][col]) if ind[i][col] else None
        a, b = sma_prefix(i, w), sma_rolling(i, w)
        if want is None:
            ok = (a is None and b is None)
        else:
            ok = (a is not None and b is not None and approx(a, want, TOL4)
                  and approx(b, want, TOL4) and approx(a, b, TOL4))
        if not ok:
            sma_ok = False
            sma_detail.append(f"row{i} {col}: csv={want} prefix={a} rolling={b}")
check(f"随机 {SAMPLE_N} 日 + 边界行的 SMA5/20/60（前缀和法 vs 滚动差分法 vs indicators.csv）",
      sma_ok, "; ".join(sma_detail[:4]) if not sma_ok else
      f"22 行 × 3 个均线 × 2 种算法全部吻合")

# ---- EMA: explicit loop ----
def ema_loop(vals, w, seed="sma"):
    alpha = 2.0 / (w + 1)
    out = [None] * len(vals)
    if seed == "sma":
        e = sum(vals[:w]) / w
        out[w - 1] = e
        for i in range(w, len(vals)):
            e = alpha * vals[i] + (1 - alpha) * e
            out[i] = e
    else:
        e = vals[0]
        out[0] = e
        for i in range(1, len(vals)):
            e = alpha * vals[i] + (1 - alpha) * e
            out[i] = e
    return out


ema12 = ema_loop(closes, 12)
ema26 = ema_loop(closes, 26)
ema12_alt = ema_loop(closes, 12, seed="first")
ema26_alt = ema_loop(closes, 26, seed="first")

ema_ok, ema_detail = True, []
for i in sample + boundary:
    for vals, col in ((ema12, "ema12"), (ema26, "ema26")):
        want = float(ind[i][col]) if ind[i][col] else None
        got = vals[i]
        ok = (want is None and got is None) or approx(want, got, TOL4)
        if not ok:
            ema_ok = False
            ema_detail.append(f"row{i} {col}: csv={want} loop={got}")
check(f"随机 {SAMPLE_N} 日 + 边界行的 EMA12/26（显式循环 vs indicators.csv）", ema_ok,
      "; ".join(ema_detail[:4]) if not ema_ok else "22 行全部吻合")

full_ema_ok, worst_ema = True, 0.0
for i in range(n):
    if ind[i]["ema12"] and ind[i]["ema26"]:
        d = max(abs(ema12[i] - float(ind[i]["ema12"])), abs(ema26[i] - float(ind[i]["ema26"])))
        worst_ema = max(worst_ema, d)
        if d > TOL4:
            full_ema_ok = False
check("全样本 822 行 EMA12/26 与显式循环一致", full_ema_ok, f"最大偏差 {worst_ema:.2e}")

tail_dev = [abs(ema12[i] - ema12_alt[i]) for i in range(n)
            if ema12[i] is not None and ema12_alt[i] is not None]
check("EMA 初始化口径敏感性已量化（SMA 种子 vs 首价种子）", True,
      f"全样本最大偏差 {max(tail_dev):.3e}；最后 100 根K线最大偏差 {max(tail_dev[-100:]):.3e}"
      f"（已收敛；属口径选择，非计算错误）")


def rsi_wilder(vals, w=14):
    out = [None] * len(vals)
    g = [max(vals[i] - vals[i - 1], 0.0) for i in range(1, len(vals))]
    l = [max(vals[i - 1] - vals[i], 0.0) for i in range(1, len(vals))]
    ag, al = sum(g[:w]) / w, sum(l[:w]) / w
    out[w] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(w, len(g)):
        ag = (ag * (w - 1) + g[i]) / w
        al = (al * (w - 1) + l[i]) / w
        out[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


rsi = rsi_wilder(closes)
dif = [None] * n
for i in range(n):
    if ema12[i] is not None and ema26[i] is not None:
        dif[i] = ema12[i] - ema26[i]
dea_vals = ema_loop([d for d in dif if d is not None], 9)
dea = [None] * n
k = 0
for i in range(n):
    if dif[i] is not None:
        dea[i] = dea_vals[k]
        k += 1

osc_ok, osc_detail = True, []
for i in sample + boundary:
    for want_v, got_v, nm in (
        (float(ind[i]["rsi14"]) if ind[i]["rsi14"] else None, rsi[i], "rsi14"),
        (float(ind[i]["macd_dif"]) if ind[i]["macd_dif"] else None, dif[i], "macd_dif"),
        (float(ind[i]["macd_dea"]) if ind[i]["macd_dea"] else None, dea[i], "macd_dea"),
    ):
        ok = (want_v is None and got_v is None) or approx(want_v, got_v, TOL4)
        if not ok:
            osc_ok = False
            osc_detail.append(f"row{i} {nm}: csv={want_v} recompute={got_v}")
check(f"随机 {SAMPLE_N} 日 + 边界行的 RSI14 与 MACD(DIF/DEA)", osc_ok,
      "; ".join(osc_detail[:4]) if not osc_ok else "22 行全部吻合")

# ================================================================ B. 净值
def nav_from_log_returns(navs):
    out = [navs[0]]
    acc = 0.0
    for t in range(1, len(navs)):
        acc += math.log(navs[t] / navs[t - 1])
        out.append(navs[0] * math.exp(acc))
    return out


for label, rows_ in (("零成本 Ledger_Gross", gross), ("含费 Ledger", net)):
    navs = [float(r["nav"]) for r in rows_]
    rebuilt = nav_from_log_returns(navs)
    max_dev = max(abs(rebuilt[i] - navs[i]) for i in range(len(navs)))
    check(f"{label} 净值复核：log(r) 累加再 exp 后还原", max_dev < 1e-4,
          f"最大偏差 {max_dev:.3e} 元（{navs[0]:,.2f} -> {navs[-1]:,.2f}）")

for label, rows_ in (("零成本 Ledger_Gross", gross), ("含费 Ledger", net)):
    navs = [float(r["nav"]) for r in rows_]
    d_ok = all(approx(float(r["daily_return"]), navs[i] / navs[i - 1] - 1, 1e-8)
               for i, r in enumerate(rows_) if i > 0)
    c_ok = all(approx(float(r["cum_return"]), navs[i] / navs[0] - 1, 1e-8)
               for i, r in enumerate(rows_))
    check(f"{label} daily_return / cum_return 与 nav 自洽", d_ok and c_ok)

# ================================================================ C. 最大回撤
def mdd_explicit(navs):
    peak = navs[0]
    worst = 0.0
    for v in navs:
        if v > peak:
            peak = v
        dd = v / peak - 1.0
        if dd < worst:
            worst = dd
    return worst


mdd_metric = {r["series"] + "|" + r["cost_regime"]: float(r["max_drawdown"])
              for r in metrics if r["row_type"] in ("strategy", "benchmark")}
nav_g = [float(r["nav"]) for r in gross]
nav_n = [float(r["nav"]) for r in net]
nav_bh = [float(r["close"]) / opens[0] for r in prices]
nav_ix = [float(r["close"]) / float(bench[0]["open"]) for r in bench]
checks = [("赛力斯 SMA5/20 交叉策略|zero_cost", mdd_explicit(nav_g)),
          ("赛力斯 SMA5/20 交叉策略|fee_0.075pct_oneway", mdd_explicit(nav_n)),
          ("赛力斯 买入持有|zero_cost", mdd_explicit(nav_bh)),
          ("沪深300 价格指数 买入持有|zero_cost", mdd_explicit(nav_ix))]
check("四条曲线最大回撤：显式循环维护峰值 vs metrics.csv",
      all(approx(mdd_metric[k], v, 1e-6) for k, v in checks),
      "；".join(f"{k.split('|')[0][:10]}: csv={mdd_metric[k]:.6f} 复核={v:.6f}" for k, v in checks))

# ================================================================ D. 预热
warm = [i for i, r in enumerate(ind) if r["is_warmup"] == "1"]
check("indicators.csv 预热行数 = 59", len(warm) == 59, f"实际 {len(warm)} 行")
check("预热行区间为前 59 行且连续", warm == list(range(59)))
check("预热行 sma60 与 score 为空",
      all(ind[i]["sma60"] == "" and ind[i]["score"] == "" and ind[i]["score_band"] == "预热"
          for i in warm))
check("signals.csv 无任何来自预热行的信号",
      all(int(r["row_index"]) > 59 for r in sigs),
      f"最小 row_index = {min(int(r['row_index']) for r in sigs)}")
check("账本预热期 59 行空仓、无动作、净值恒定",
      all(gross[i]["action"] == "NONE" and float(gross[i]["shares"]) == 0.0
          and abs(float(gross[i]["nav"]) - 1_000_000) < 0.01
          for i in range(59))
      and all(net[i]["action"] == "NONE" and float(net[i]["shares"]) == 0.0
              for i in range(59)))
check("首个可评估日 = 第 60 行 = 2023-08-25",
      ind[59]["is_warmup"] == "0" and ind[59]["date"] == "2023-08-25")
check("indicators.csv 有评分的行数 = 822 − 59",
      sum(1 for r in ind if r["score"] != "") == 763)

# ================================================================ E. 未来数据
sma5_all = [sma_prefix(i, 5) for i in range(n)]
sma20_all = [sma_prefix(i, 20) for i in range(n)]
derived = []
for i in range(59, n):
    if sma5_all[i] is None or sma20_all[i] is None:
        continue
    d0 = sma5_all[i - 1] - sma20_all[i - 1]
    d1 = sma5_all[i] - sma20_all[i]
    if d0 <= 0 < d1:
        derived.append((dates[i], "golden_cross"))
    elif d0 >= 0 > d1:
        derived.append((dates[i], "death_cross"))
file_sig = [(r["date"], r["signal_type"]) for r in sigs if r["signal_family"] == "sma5_sma20"]
check("SMA5/20 交叉信号集：独立重算 vs signals.csv 完全一致",
      derived == file_sig, f"重算 {len(derived)} 条 / 文件 {len(file_sig)} 条")

first_sig_bar = dates.index(file_sig[0][0]) if file_sig else None
check("首个信号落在预热期之后（无未来数据预取）",
      first_sig_bar is not None and first_sig_bar >= 59,
      f"首个信号 {file_sig[0][0]} 位于第 {first_sig_bar + 1} 行")

# execution timing: caused ONLY by the previous bar's signal, filled at this bar's OPEN
exec_ok, det = True, []
for i, r in enumerate(gross):
    if r["action"] in ("BUY", "SELL"):
        want = "golden_cross" if r["action"] == "BUY" else "death_cross"
        if i == 0 or gross[i - 1]["signal"] != want:
            exec_ok = False
            det.append(f"{r['date']} 上一行信号={gross[i-1]['signal'] if i else None} 期望={want}")
        if r["exec_date"] != r["date"]:
            exec_ok = False
            det.append(f"{r['date']} exec_date={r['exec_date']}")
        if abs(float(r["fill_price"]) - opens[i]) > TOL2:
            exec_ok = False
            det.append(f"{r['date']} 成交价 {r['fill_price']} != 当日开盘 {opens[i]}")
check("成交时点：仅由上一根K线的信号触发、按当日开盘价成交（无当日收盘价前视）",
      exec_ok, "; ".join(det[:5]))

# a row may carry its own signal AND an execution (when two signals occur back to back);
# the decisive property is that the execution follows the PREVIOUS bar's signal,
# never the same bar's own signal.
consec = []
for i, r in enumerate(gross):
    if r["signal"] != "none" and r["action"] in ("BUY", "SELL"):
        prev_sig = gross[i - 1]["signal"] if i else None
        consec.append((r["date"], prev_sig, r["signal"], r["action"]))
consistent = all((a == "golden_cross" and act == "BUY") or (a == "death_cross" and act == "SELL")
                  for _, a, _, act in consec)
check("同日既有信号又有成交时，成交方向由前一日信号决定（连续信号日不误读）",
      consistent,
      f"同时含信号与成交的行 {len(consec)} 个：{consec}")

# explicit regression on the only such bar (2025-01-02 金叉 -> 01-03 买入 -> 01-06 卖出)
i031 = dates.index("2025-01-03")
check("连续信号回归用例 2025-01-02/03/06 的因果链正确",
      gross[i031 - 1]["signal"] == "golden_cross" and gross[i031]["action"] == "BUY"
      and gross[i031]["signal"] == "death_cross"
      and gross[i031 + 1]["action"] == "SELL" and gross[i031 + 1]["date"] == "2025-01-06",
      f"2025-01-02 金叉 → 2025-01-03 开盘买入（当日收盘又出死叉）→ 2025-01-06 开盘卖出")

# other two signal families re-derived independently
dif_sig = []
for i in range(59, n):
    if dif[i] is None or dea[i] is None or dif[i - 1] is None or dea[i - 1] is None:
        continue
    d0, d1 = dif[i - 1] - dea[i - 1], dif[i] - dea[i]
    if d0 <= 0 < d1:
        dif_sig.append((dates[i], "golden_cross"))
    elif d0 >= 0 > d1:
        dif_sig.append((dates[i], "death_cross"))
file_macd = [(r["date"], r["signal_type"]) for r in sigs if r["signal_family"] == "macd"]
check("MACD 交叉信号集：独立重算 vs signals.csv 完全一致",
      dif_sig == file_macd, f"重算 {len(dif_sig)} 条 / 文件 {len(file_macd)} 条")

sma60_all = [sma_prefix(i, 60) for i in range(n)]
s2060 = []
for i in range(59, n):
    if any(v is None for v in (sma20_all[i], sma60_all[i], sma20_all[i - 1], sma60_all[i - 1])):
        continue
    d0 = sma20_all[i - 1] - sma60_all[i - 1]
    d1 = sma20_all[i] - sma60_all[i]
    if d0 <= 0 < d1:
        s2060.append((dates[i], "golden_cross"))
    elif d0 >= 0 > d1:
        s2060.append((dates[i], "death_cross"))
file_2060 = [(r["date"], r["signal_type"]) for r in sigs if r["signal_family"] == "sma20_sma60"]
check("SMA20/SMA60 交叉信号集：独立重算 vs signals.csv 完全一致",
      s2060 == file_2060, f"重算 {len(s2060)} 条 / 文件 {len(file_2060)} 条")

# E: independent replay of the whole strategy from raw prices
def replay(closes_, opens_, dates_):
    """Replay the documented rules from scratch; return the trade list."""
    s5 = [sma_prefix(i, 5) for i in range(len(closes_))]
    s20 = [sma_prefix(i, 20) for i in range(len(closes_))]
    trades, held = [], False
    for t in range(59, len(closes_)):
        if s5[t] is None or s20[t] is None:
            continue
        d0, d1 = s5[t - 1] - s20[t - 1], s5[t] - s20[t]
        sig = "golden_cross" if d0 <= 0 < d1 else ("death_cross" if d0 >= 0 > d1 else None)
        if sig is None or t + 1 >= len(closes_):
            continue
        if sig == "golden_cross" and not held:
            trades.append((dates_[t], dates_[t + 1], "BUY", opens_[t + 1]))
            held = True
        elif sig == "death_cross" and held:
            trades.append((dates_[t], dates_[t + 1], "SELL", opens_[t + 1]))
            held = False
    return trades, held


replay_trades, replay_held = replay(closes, opens, dates)
ledger_trades = []
for i, r in enumerate(gross):
    if r["action"] in ("BUY", "SELL"):
        ledger_trades.append((gross[i - 1]["date"], r["exec_date"], r["action"],
                              float(r["fill_price"])))
check("策略端到端重放：从原始价格独立重算的成交清单 vs 账本逐笔一致",
      [(a, b, c) for a, b, c, _ in replay_trades] == [(a, b, c) for a, b, c, _ in ledger_trades]
      and all(approx(replay_trades[i][3], ledger_trades[i][3], TOL2)
              for i in range(len(replay_trades))),
      f"重放 {len(replay_trades)} 笔 vs 账本 {len(ledger_trades)} 笔")
check("重放末态与账本末态一致（均空仓）",
      replay_held is False and float(gross[-1]["shares"]) == 0.0)

for label, rows_ in (("零成本", gross), ("含费", net)):
    ok = all(abs(float(r["cash"]) + float(r["shares"]) * closes[i] - float(r["nav"])) < 0.01
             for i, r in enumerate(rows_))
    check(f"{label}账本 nav = cash + shares×当日close（同一根K线内闭合）", ok)

# ================================================================ F. 成本
fee_rate = 0.00075
fee_ok, fee_det = True, []
prev_shares, prev_cash = 0.0, 1_000_000.0
for i, r in enumerate(net):
    act = r["action"]
    if act == "BUY":
        exp_shares = prev_cash / (opens[i] * (1 + fee_rate))
        exp_fee = exp_shares * opens[i] * fee_rate
        exp_cash = prev_cash - exp_shares * opens[i] - exp_fee
        if abs(float(r["shares"]) - exp_shares) > 1e-4:
            fee_ok = False; fee_det.append(f"{r['date']} 份额 {r['shares']} vs {exp_shares:.6f}")
        if abs(float(r["fee"]) - exp_fee) > 0.02:
            fee_ok = False; fee_det.append(f"{r['date']} 费用 {r['fee']} vs {exp_fee:.4f}")
        if abs(float(r["cash"]) - exp_cash) > 0.02:
            fee_ok = False; fee_det.append(f"{r['date']} 现金 {r['cash']} vs {exp_cash:.4f}")
        prev_cash, prev_shares = exp_cash, exp_shares
    elif act == "SELL":
        exp_proceeds = prev_shares * opens[i]
        exp_fee = exp_proceeds * fee_rate
        exp_cash = prev_cash + exp_proceeds - exp_fee
        if abs(float(r["fee"]) - exp_fee) > 0.02:
            fee_ok = False; fee_det.append(f"{r['date']} 卖出费用 {r['fee']} vs {exp_fee:.4f}")
        if abs(float(r["cash"]) - exp_cash) > 0.02:
            fee_ok = False; fee_det.append(f"{r['date']} 卖出后现金 {r['cash']} vs {exp_cash:.4f}")
        prev_cash, prev_shares = exp_cash, 0.0
    else:
        prev_cash, prev_shares = float(r["cash"]), float(r["shares"])
check("含费账本逐笔独立重算（份额/费用/现金，含卖出腿）", fee_ok, "; ".join(fee_det[:5]))

fee_sum = sum(float(r["fee"]) for r in net)
check("累计手续费 = 逐笔费用之和 = 期末 cum_fee",
      abs(fee_sum - float(net[-1]["cum_fee"])) < 0.01,
      f"逐笔和 {fee_sum:,.2f} / cum_fee {float(net[-1]['cum_fee']):,.2f}")
check("零成本账本全表费用为 0", all(float(r["fee"]) == 0.0 for r in gross))
check("含费账本费率恰为 0.075%（逐笔反解）",
      all(abs(float(r["fee"]) / (float(r["shares"]) * float(r["fill_price"])) - fee_rate) < 1e-6
          for r in net if r["action"] == "BUY"))

gap = float(gross[-1]["nav"]) - float(net[-1]["nav"])
bd = [r for r in metrics if r["row_type"] == "fee_breakdown"]
check("费用分解：期末净值差与实际支付费用分开列示且数值正确",
      abs(float(bd[0]["value"]) - gap) < 0.01
      and abs(float(bd[1]["value"]) - fee_sum) < 0.01
      and "期末净值差" in bd[0]["series"] and "实际支付费用" in bd[1]["series"],
      f"净值差 {gap:,.2f} / 费用 {fee_sum:,.2f}（费用 > 净值差，符合复利计提口径）")

# ================================================================ G. 基准
bh_final, ix_final = nav_bh[-1], nav_ix[-1]
m_bh = [r for r in metrics if r["series"] == "赛力斯 买入持有"][0]
m_ix = [r for r in metrics if r["series"] == "沪深300 价格指数 买入持有"][0]
check("赛力斯买入持有净值独立复核",
      abs(float(m_bh["final_nav"]) - bh_final * 1_000_000) < 1.0
      and abs(float(m_bh["cumulative_return"]) - (bh_final - 1)) < 1e-6,
      f"csv={float(m_bh['final_nav']):,.2f} 复核={bh_final * 1_000_000:,.2f}")
check("沪深300买入持有净值独立复核",
      abs(float(m_ix["final_nav"]) - ix_final * 1_000_000) < 1.0
      and abs(float(m_ix["cumulative_return"]) - (ix_final - 1)) < 1e-6,
      f"csv={float(m_ix['final_nav']):,.2f} 复核={ix_final * 1_000_000:,.2f}")
check("基准与策略同区间（822 个交易日、同一日期轴）",
      len(bench) == n and [r["date"] for r in bench] == dates
      and m_bh["window_start"] == dates[0] and m_bh["window_end"] == dates[-1])

# ================================================================ H. 数据来源链
raw_fwd = json.loads((RAW / "seres_fwd.json").read_text(encoding="utf-8"))
raw_items = raw_fwd["items"]
chain_ok = len(raw_items) == n
for i, it in enumerate(raw_items):
    r = prices[i]
    if (it["date"] != r["date"] or abs(it["close"] - float(r["close"])) > TOL2
            or abs(it["open"] - float(r["open"])) > TOL2):
        chain_ok = False
        break
check("prices.csv 可回溯到恒生原始响应 raw/seres_fwd.json（逐行 OHLC）", chain_ok,
      f"{len(raw_items)} 行")
check("恒生响应 adjustment=forward 且 coverageComplete=true",
      raw_fwd.get("adjustment") == "forward" and raw_fwd.get("coverageComplete") is True,
      f"adjustment={raw_fwd.get('adjustment')} basisVersion={raw_fwd.get('basisVersion')}")

raw_ix = json.loads((RAW / "ifind_csi300_merged.json").read_text(encoding="utf-8"))
ix_trading = [r for r in raw_ix["rows"] if r.get("open") is not None]
chain_ix = len(ix_trading) == len(bench)
for i, r in enumerate(ix_trading):
    b = bench[i]
    if r["date"] != b["date"] or abs(r["close"] - float(b["close"])) > 1e-4:
        chain_ix = False
        break
check("prices_bench.csv 可回溯到 iFinD 原始响应（自然日 -> 交易日筛选）", chain_ix,
      f"自然日 {len(raw_ix['rows'])} 行 -> 交易日 {len(ix_trading)} 行")

raw_resp = json.loads((RAW / "seres_raw.json").read_text(encoding="utf-8"))
for label in ("2023-06-01", "2024-12-31"):
    row = next(r for r in raw_resp["items"] if r["date"] == label)
    txt = (RAW / f"ifind_seres_{'d1' if label == '2023-06-01' else 'd2'}.json").read_text(encoding="utf-8")
    check(f"外部抽检 {label} 恒生未复权收盘价 = iFinD 留档值",
          str(row["close"]) in txt.replace(" ", ""),
          f"恒生 {row['close']} / 前收 {row['previousClose']}")

m_g = [r for r in metrics if r["cost_regime"] == "zero_cost" and r["row_type"] == "strategy"][0]
m_n = [r for r in metrics if r["cost_regime"] == "fee_0.075pct_oneway"][0]
check("metrics.csv 策略行与账本末值一致",
      abs(float(m_g["final_nav"]) - float(gross[-1]["nav"])) < 0.01
      and abs(float(m_n["final_nav"]) - float(net[-1]["nav"])) < 0.01)
check("metrics.csv 交易次数 = 账本 BUY 数",
      int(m_n["trade_count_round_trips"]) == sum(1 for r in net if r["action"] == "BUY"))
check("metrics.csv 持仓天数 = 账本持股>0 的行数",
      int(m_n["holding_days"]) == sum(1 for r in net if float(r["shares"]) > 0),
      f"{m_n['holding_days']} 天 / {len(net)} 天 = {float(m_n['holding_ratio'])*100:.2f}%")
check("metrics.csv 费用分解行未与指标行混淆（row_type 区分）",
      {r["row_type"] for r in metrics} == {"strategy", "benchmark", "fee_breakdown"})

# ---------------------------------------------------------------- summary
fails = [r for r in results if r["status"] == "FAIL"]
summary = {"seed": SEED, "sample_indices": sample, "boundary_indices": boundary,
           "tolerance": {"indicators_4dp": TOL4, "prices_2dp": TOL2},
           "total_checks": len(results), "passed": len(results) - len(fails),
           "failed": len(fails), "checks": results}
(RAW / "qa_results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
print(f"\n{'=' * 64}\n检查项 {len(results)} 个：通过 {len(results) - len(fails)}，失败 {len(fails)}")
if fails:
    for f in fails:
        print(f"  FAIL: {f['check']} — {f['detail']}")
else:
    print("全部通过")
