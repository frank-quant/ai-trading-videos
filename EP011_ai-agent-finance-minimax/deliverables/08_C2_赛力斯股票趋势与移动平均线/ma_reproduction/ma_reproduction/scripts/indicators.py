"""Technical indicators + signal generation for the Seres / CSI300 demo scenario.

Conventions (all documented in technical_snapshot.md):
  SMA_n      : simple moving average over n closes
  EMA_n      : seeded with the SMA of the first n values, then alpha = 2/(n+1)
  MACD       : DIF = EMA12 - EMA26; DEA = EMA9(DIF); HIST = 2 * (DIF - DEA)   [通达信/同花顺 convention]
  RSI14      : Wilder's smoothing, seeded with the mean of the first 14 periods
  slope_n    : (MA_n[t] - MA_n[t-5]) / 5  (CNY per trading day, 5-day window)
  slope_n_pct: ((MA_n[t] / MA_n[t-5]) - 1) / 5 * 100  (% per trading day, 5-day window)
  warmup     : the first 59 rows (index 0..58) carry no tradable signal
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WARMUP_ROWS = 59          # first 59 rows = warmup, no signals
SLOPE_WINDOW = 5
SNAPSHOT_DAYS = 120


# ---------------------------------------------------------------- indicators
def sma(values, n):
    out = [None] * len(values)
    if len(values) < n:
        return out
    s = sum(values[:n])
    out[n - 1] = s / n
    for i in range(n, len(values)):
        s += values[i] - values[i - n]
        out[i] = s / n
    return out


def ema(values, n):
    """EMA seeded with the SMA of the first n values."""
    out = [None] * len(values)
    if len(values) < n:
        return out
    alpha = 2.0 / (n + 1)
    e = sum(values[:n]) / n
    out[n - 1] = e
    for i in range(n, len(values)):
        e = alpha * values[i] + (1 - alpha) * e
        out[i] = e
    return out


def rsi_wilder(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    out[n] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        out[i + 1] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def alignment(s5, s20, s60):
    if s5 is None or s20 is None or s60 is None:
        return ""
    if s5 > s20 > s60:
        return "多头排列"
    if s5 < s20 < s60:
        return "空头排列"
    if s5 > s20 and s20 < s60:
        return "短多长空"
    if s5 < s20 and s20 > s60:
        return "短空长多"
    return "交汇纠缠"


def slope(series, t, window=SLOPE_WINDOW):
    """(series[t] - series[t-window]) / window ; None if not enough history."""
    if t < window or series[t] is None or series[t - window] is None:
        return None
    return (series[t] - series[t - window]) / window


def slope_pct(series, t, window=SLOPE_WINDOW):
    if t < window or series[t] is None or series[t - window] in (None, 0):
        return None
    return (series[t] / series[t - window] - 1.0) / window * 100.0


# ---------------------------------------------------------------- scoring
def score_day(row):
    """Transparent 100-point technical snapshot. Returns (score, [reason strings])."""
    reasons = []
    s = 0

    # A. trend structure (40)
    align = row["ma_alignment"]
    align_pts = {"多头排列": 30, "短多长空": 18, "交汇纠缠": 10, "短空长多": 8, "空头排列": 0}
    s += align_pts.get(align, 0)
    reasons.append(f"均线排列「{align}」{align_pts.get(align, 0)}/30")

    if row["sma20_slope"] is not None and row["sma60_slope"] is not None:
        up20 = row["sma20_slope"] > 0
        up60 = row["sma60_slope"] > 0
        if up20 and up60:
            s += 10
            reasons.append("SMA20 与 SMA60 斜率同为向上 +10/10")
        elif up20 or up60:
            s += 5
            reasons.append("SMA20/SMA60 斜率一正一负 +5/10")
        else:
            reasons.append("SMA20 与 SMA60 斜率同为向下 +0/10")

    # B. momentum (30)
    r = row["rsi14"]
    if r is not None:
        if 45 <= r <= 70:
            s += 15
            reasons.append(f"RSI14={r:.1f}，位于健康多头区间 +15/15")
        elif 30 <= r < 45:
            s += 8
            reasons.append(f"RSI14={r:.1f}，弱势区 +8/15")
        elif 70 < r <= 80:
            s += 8
            reasons.append(f"RSI14={r:.1f}，偏热 +8/15")
        elif r > 80:
            s += 3
            reasons.append(f"RSI14={r:.1f}，严重超买 +3/15")
        else:
            s += 5
            reasons.append(f"RSI14={r:.1f}，超卖 +5/15")

    if row["macd_dif"] is not None and row["macd_dea"] is not None:
        dif, dea, hist = row["macd_dif"], row["macd_dea"], row["macd_hist"]
        if dif > dea and hist > 0:
            s += 15
            reasons.append(f"MACD 处于金叉状态（DIF {dif:.3f} > DEA {dea:.3f}）且红柱为正 +15/15")
        elif dif > dea and hist <= 0:
            s += 8
            reasons.append(f"MACD DIF>DEA 但柱体转弱（DIF {dif:.3f} > DEA {dea:.3f}） +8/15")
        elif dif <= dea and hist > 0:
            s += 6
            reasons.append(f"MACD 仍为死叉但柱体收敛（DIF {dif:.3f} ≤ DEA {dea:.3f}） +6/15")
        else:
            reasons.append(f"MACD 死叉且柱体为负（DIF {dif:.3f} ≤ DEA {dea:.3f}） +0/15")

    # C. price position (30)
    close = row["close"]
    if close > row["sma5"]:
        s += 10
        reasons.append(f"收盘价 {close:.2f} 站上 SMA5({row['sma5']:.2f}) +10/10")
    else:
        reasons.append(f"收盘价 {close:.2f} 位于 SMA5({row['sma5']:.2f}) 下方 +0/10")

    if close > row["sma20"] and close > row["sma60"]:
        s += 10
        reasons.append(f"收盘价同时站上 SMA20({row['sma20']:.2f}) 与 SMA60({row['sma60']:.2f}) +10/10")
    elif close > row["sma20"]:
        s += 6
        reasons.append(f"收盘价站上 SMA20({row['sma20']:.2f}) 但未站上 SMA60({row['sma60']:.2f}) +6/10")
    elif close > row["sma60"]:
        s += 4
        reasons.append(f"收盘价低于 SMA20({row['sma20']:.2f}) 但仍高于 SMA60({row['sma60']:.2f}) +4/10")
    else:
        reasons.append(f"收盘价跌破 SMA20({row['sma20']:.2f}) 与 SMA60({row['sma60']:.2f}) +0/10")

    return s, reasons


def band(s):
    if s >= 75:
        return "强势"
    if s >= 60:
        return "中性偏多"
    if s >= 45:
        return "中性"
    if s >= 30:
        return "中性偏空"
    return "弱势"


# ---------------------------------------------------------------- main
def main():
    with (ROOT / "prices.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    dates = [r["date"] for r in rows]
    closes = [float(r["close"]) for r in rows]

    s5, s20, s60 = sma(closes, 5), sma(closes, 20), sma(closes, 60)
    e12, e26 = ema(closes, 12), ema(closes, 26)

    dif = [None] * len(closes)
    for i in range(len(closes)):
        if e12[i] is not None and e26[i] is not None:
            dif[i] = e12[i] - e26[i]
    dif_vals = [d for d in dif if d is not None]
    dea_full = ema(dif_vals, 9)
    dea = [None] * len(closes)
    k = 0
    for i in range(len(closes)):
        if dif[i] is not None:
            dea[i] = dea_full[k]
            k += 1
    hist = [None if (dif[i] is None or dea[i] is None) else 2.0 * (dif[i] - dea[i])
            for i in range(len(closes))]
    rsi = rsi_wilder(closes, 14)

    ind = []
    for i, r in enumerate(rows):
        rec = {
            "date": dates[i],
            "close": closes[i],
            "sma5": s5[i], "sma20": s20[i], "sma60": s60[i],
            "ema12": e12[i], "ema26": e26[i],
            "macd_dif": dif[i], "macd_dea": dea[i], "macd_hist": hist[i],
            "rsi14": rsi[i],
            "sma5_slope": slope(s5, i), "sma20_slope": slope(s20, i), "sma60_slope": slope(s60, i),
            "sma5_slope_pct": slope_pct(s5, i), "sma20_slope_pct": slope_pct(s20, i),
            "sma60_slope_pct": slope_pct(s60, i),
            "ma_alignment": alignment(s5[i], s20[i], s60[i]),
            "is_warmup": i < WARMUP_ROWS,
        }
        needs = ("sma5", "sma20", "sma60", "rsi14", "macd_dif", "macd_dea", "macd_hist")
        if rec["is_warmup"] or any(rec[k] is None for k in needs):
            rec["score"] = None
            rec["score_band"] = "预热"
            rec["score_reasons"] = [f"预热期（第 {i + 1} 行，不足 60 根K线），不评分、不产生交易信号"]
        else:
            sc, reasons = score_day(rec)
            rec["score"] = sc
            rec["score_band"] = band(sc)
            rec["score_reasons"] = reasons
        ind.append(rec)
    # ---------------- indicators.csv ----------------
    cols = ["date", "close", "sma5", "sma20", "sma60", "ema12", "ema26",
            "macd_dif", "macd_dea", "macd_hist", "rsi14",
            "sma5_slope", "sma20_slope", "sma60_slope",
            "sma5_slope_pct", "sma20_slope_pct", "sma60_slope_pct",
            "ma_alignment", "is_warmup", "score", "score_band"]

    def fmt(v, nd=4):
        if v is None:
            return ""
        return f"{v:.{nd}f}"

    with (ROOT / "indicators.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for rec in ind:
            w.writerow([
                rec["date"], fmt(rec["close"], 2), fmt(rec["sma5"], 4), fmt(rec["sma20"], 4),
                fmt(rec["sma60"], 4), fmt(rec["ema12"], 4), fmt(rec["ema26"], 4),
                fmt(rec["macd_dif"], 4), fmt(rec["macd_dea"], 4), fmt(rec["macd_hist"], 4),
                fmt(rec["rsi14"], 4),
                fmt(rec["sma5_slope"], 4), fmt(rec["sma20_slope"], 4), fmt(rec["sma60_slope"], 4),
                fmt(rec["sma5_slope_pct"], 4), fmt(rec["sma20_slope_pct"], 4), fmt(rec["sma60_slope_pct"], 4),
                rec["ma_alignment"], "1" if rec["is_warmup"] else "0",
                rec["score"], rec["score_band"],
            ])

    # ---------------- signals.csv ----------------
    def cross_events(series_a, series_b, t):
        """Strict crossing at bar t only (no repeat on following bars)."""
        if t < 1:
            return None
        a0, b0 = series_a[t - 1], series_b[t - 1]
        a1, b1 = series_a[t], series_b[t]
        if None in (a0, b0, a1, b1):
            return None
        d0, d1 = a0 - b0, a1 - b1
        if d0 <= 0 < d1:
            return "golden_cross"
        if d0 >= 0 > d1:
            return "death_cross"
        return None

    PAIRS = [
        ("macd", "DIF", "DEA", dif, dea),
        ("sma5_sma20", "SMA5", "SMA20", s5, s20),
        ("sma20_sma60", "SMA20", "SMA60", s20, s60),
    ]
    signals = []
    for t in range(WARMUP_ROWS, len(ind)):
        for key, na, nb, sa, sb in PAIRS:
            ev = cross_events(sa, sb, t)
            if not ev:
                continue
            d0 = sa[t - 1] - sb[t - 1]
            d1 = sa[t] - sb[t]
            signals.append({
                "date": dates[t],
                "signal_type": ev,
                "signal_family": key,
                "indicator_a": na, "indicator_b": nb,
                "value_a_prev": sa[t - 1], "value_b_prev": sb[t - 1],
                "value_a": sa[t], "value_b": sb[t],
                "spread_prev": d0, "spread_now": d1,
                "close": closes[t],
                "is_warmup": 0,
                "row_index": t + 1,
            })

    with (ROOT / "signals.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "signal_type", "signal_family", "indicator_a", "indicator_b",
                    "value_a_prev", "value_b_prev", "value_a", "value_b",
                    "spread_prev", "spread_now", "close", "is_warmup", "row_index"])
        for s in signals:
            w.writerow([
                s["date"], s["signal_type"], s["signal_family"], s["indicator_a"], s["indicator_b"],
                fmt(s["value_a_prev"], 4), fmt(s["value_b_prev"], 4),
                fmt(s["value_a"], 4), fmt(s["value_b"], 4),
                fmt(s["spread_prev"], 4), fmt(s["spread_now"], 4),
                fmt(s["close"], 2), s["is_warmup"], s["row_index"],
            ])

    # sanity: no two consecutive signals of the same family+type
    consec = 0
    for i in range(1, len(signals)):
        if signals[i]["signal_family"] == signals[i - 1]["signal_family"] and \
           signals[i]["signal_type"] == signals[i - 1]["signal_type"] and \
           signals[i]["row_index"] - signals[i - 1]["row_index"] == 1:
            consec += 1

    stats = {
        "n_rows": len(ind),
        "warmup_rows": sum(1 for r in ind if r["is_warmup"]),
        "first_non_warmup_date": next(r["date"] for r in ind if not r["is_warmup"]),
        "signals_total": len(signals),
        "signals_by_family_type": {},
        "consecutive_repeat_signals": consec,
        "snapshot_days": SNAPSHOT_DAYS,
        "snapshot_start": dates[-SNAPSHOT_DAYS],
        "snapshot_end": dates[-1],
        "last_day": {
            "date": dates[-1], "close": closes[-1],
            "sma5": s5[-1], "sma20": s20[-1], "sma60": s60[-1],
            "ema12": e12[-1], "ema26": e26[-1],
            "macd_dif": dif[-1], "macd_dea": dea[-1], "macd_hist": hist[-1],
            "rsi14": rsi[-1],
            "score": ind[-1]["score"], "band": ind[-1]["score_band"],
            "reasons": ind[-1]["score_reasons"],
        },
    }
    for s in signals:
        k = f"{s['signal_family']}:{s['signal_type']}"
        stats["signals_by_family_type"][k] = stats["signals_by_family_type"].get(k, 0) + 1

    (ROOT / "raw").mkdir(exist_ok=True)
    (ROOT / "raw" / "indicator_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "raw" / "indicators_full.json").write_text(
        json.dumps(ind, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
