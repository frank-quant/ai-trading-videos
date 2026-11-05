"""Recalculate the workbook with Excel COM and verify the results against the CSVs.

openpyxl writes formulas but never evaluates them, so recalculation is
mandatory before delivery (xlsx skill §4). Excel COM is used here because the
skill's recalc.py installs a LibreOffice macro to a Linux path that does not
exist on Windows; Excel is installed here (16.0) and recalculates natively.
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import win32com.client as win32
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "moving_average_analysis.xlsx"

ERRORS = ("#REF!", "#VALUE!", "#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#SPILL!", "#CALC!")


def read_csv(name):
    with (ROOT / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def recalc(path: Path, timeout=900):
    t0 = time.time()
    app = win32.Dispatch("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    try:
        wb = app.Workbooks.Open(str(path))
        app.Calculation = -4105          # xlCalculationAutomatic
        app.CalculateFullRebuild()
        wb.Save()
        wb.Close(SaveChanges=True)
    finally:
        app.Quit()
    return time.time() - t0


def main():
    print("recalculating with Excel COM ...")
    secs = recalc(XLSX)
    print(f"  recalc done in {secs:.1f}s")

    wbf = load_workbook(XLSX, data_only=False)
    wbv = load_workbook(XLSX, data_only=True)
    print("  sheets:", wbv.sheetnames)

    # ---- formula census ----
    total_formulas = 0
    per_sheet = {}
    for ws in wbf.worksheets:
        cnt = 0
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    cnt += 1
        per_sheet[ws.title] = cnt
        total_formulas += cnt
    print(f"  formulas: {total_formulas}  {per_sheet}")

    # ---- error scan on cached values ----
    err_hits = []
    for ws in wbv.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and any(e in c.value for e in ERRORS):
                    err_hits.append(f"{ws.title}!{c.coordinate}={c.value}")
    print(f"  error cells: {len(err_hits)}")
    for h in err_hits[:10]:
        print("   ", h)

    # ---- verification against the CSV ground truth ----
    prices = read_csv("prices.csv")
    ind = read_csv("indicators.csv")
    gross = read_csv("Ledger_Gross.csv")
    net = read_csv("Ledger.csv")
    metrics = read_csv("metrics.csv")

    sm = wbv["Summary"]
    qa = wbv["QA"]
    checks = []

    def chk(name, got, want, tol=0.01):
        try:
            ok = got is not None and want is not None and abs(float(got) - float(want)) <= tol
        except (TypeError, ValueError):
            ok = False
        checks.append((name, ok, got, want))
        return ok

    m = {r["series"] + "|" + r["cost_regime"]: r for r in metrics if r["row_type"] != "fee_breakdown"}
    chk("Summary 策略含费 期末净值", sm["B5"].value, float(m["赛力斯 SMA5/20 交叉策略|fee_0.075pct_oneway"]["final_nav"]))
    chk("Summary 策略零成本 期末净值", sm["C5"].value, float(m["赛力斯 SMA5/20 交叉策略|zero_cost"]["final_nav"]))
    chk("Summary 赛力斯B&H 期末净值", sm["D5"].value, float(m["赛力斯 买入持有|zero_cost"]["final_nav"]))
    chk("Summary 沪深300 期末净值", sm["E5"].value, float(m["沪深300 价格指数 买入持有|zero_cost"]["final_nav"]))
    chk("Summary 策略含费 累计收益", sm["B6"].value, float(m["赛力斯 SMA5/20 交叉策略|fee_0.075pct_oneway"]["cumulative_return"]), 1e-6)
    chk("Summary 策略含费 年化收益", sm["B7"].value, float(m["赛力斯 SMA5/20 交叉策略|fee_0.075pct_oneway"]["annualized_return"]), 1e-6)
    chk("Summary 策略含费 最大回撤", sm["B8"].value, float(m["赛力斯 SMA5/20 交叉策略|fee_0.075pct_oneway"]["max_drawdown"]), 1e-6)
    chk("Summary 策略零成本 最大回撤", sm["C8"].value, float(m["赛力斯 SMA5/20 交叉策略|zero_cost"]["max_drawdown"]), 1e-6)
    chk("Summary 赛力斯B&H 最大回撤", sm["D8"].value, float(m["赛力斯 买入持有|zero_cost"]["max_drawdown"]), 1e-6)
    chk("Summary 沪深300 最大回撤", sm["E8"].value, float(m["沪深300 价格指数 买入持有|zero_cost"]["max_drawdown"]), 1e-6)
    chk("Summary 策略含费 持仓天数", sm["B13"].value, float(m["赛力斯 SMA5/20 交叉策略|fee_0.075pct_oneway"]["holding_days"]), 0.5)
    chk("Summary 策略含费 实际支付费用", sm["B15"].value, float(m["赛力斯 SMA5/20 交叉策略|fee_0.075pct_oneway"]["total_fees_paid"]))
    chk("Summary 费用造成的期末净值差", sm["B19"].value, 43945.2587)
    chk("Summary 实际支付费用合计", sm["B20"].value, 56521.2644)

    # spot-check Indicators rows against indicators.csv (rows 60, 400, 823)
    wsi = wbv["Indicators"]
    for excel_row in (62, 400, 824):
        src = ind[excel_row - 3]
        chk(f"Indicators row{excel_row} close", wsi[f"B{excel_row}"].value, float(src["close"]), 0.005)
        chk(f"Indicators row{excel_row} sma_fast", wsi[f"C{excel_row}"].value, float(src["sma5"]), 5e-5)
        chk(f"Indicators row{excel_row} sma_slow", wsi[f"D{excel_row}"].value, float(src["sma20"]), 5e-5)
        chk(f"Indicators row{excel_row} sma_mid", wsi[f"E{excel_row}"].value, float(src["sma60"]), 5e-5)
        chk(f"Indicators row{excel_row} rsi14", wsi[f"K{excel_row}"].value, float(src["rsi14"]), 5e-5)
        chk(f"Indicators row{excel_row} macd_dif", wsi[f"H{excel_row}"].value, float(src["macd_dif"]), 5e-5)
        chk(f"Indicators row{excel_row} macd_dea", wsi[f"I{excel_row}"].value, float(src["macd_dea"]), 5e-5)
        chk(f"Indicators row{excel_row} score", wsi[f"P{excel_row}"].value, float(src["score"]), 0.5)
        if wsi[f"O{excel_row}"].value != src["ma_alignment"]:
            checks.append((f"Indicators row{excel_row} alignment", False,
                           wsi[f"O{excel_row}"].value, src["ma_alignment"]))

    # spot-check Ledger rows against Ledger.csv
    for sheet, src_rows, label in (("Ledger", net, "含费"), ("Ledger_Gross", gross, "零成本")):
        wsl = wbv[sheet]
        for excel_row in (62, 400, 824):
            src = src_rows[excel_row - 3]
            chk(f"{label}账本 row{excel_row} nav", wsl[f"M{excel_row}"].value, float(src["nav"]), 0.01)
            chk(f"{label}账本 row{excel_row} cash", wsl[f"J{excel_row}"].value, float(src["cash"]), 0.01)
            chk(f"{label}账本 row{excel_row} fee", wsl[f"K{excel_row}"].value, float(src["fee"]), 0.01)
            if wsl[f"D{excel_row}"].value != src["signal"]:
                checks.append((f"{label}账本 row{excel_row} signal", False,
                               wsl[f"D{excel_row}"].value, src["signal"]))
            if wsl[f"E{excel_row}"].value != src["action"]:
                checks.append((f"{label}账本 row{excel_row} action", False,
                               wsl[f"E{excel_row}"].value, src["action"]))

    # QA live-check statuses
    qa_fail = []
    for r in range(5, 20):
        st = qa[f"D{r}"].value
        nm = qa[f"A{r}"].value
        if st != "PASS":
            qa_fail.append(f"row{r} {nm}: {st}")
    checks.append(("QA 页 15 项活公式自检全部 PASS", not qa_fail,
                   "; ".join(qa_fail) or "全部 PASS", "全部 PASS"))

    print("\n--- verification ---")
    failed = [c for c in checks if not c[1]]
    for name, ok, got, want in checks:
        if not ok:
            print(f"  FAIL {name}: workbook={got} csv={want}")
    print(f"  {len(checks) - len(failed)}/{len(checks)} 项一致")

    result = {
        "recalc_seconds": round(secs, 1),
        "sheets": wbv.sheetnames,
        "total_formulas": total_formulas,
        "formulas_per_sheet": per_sheet,
        "error_cells": len(err_hits),
        "error_examples": err_hits[:10],
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed),
        "checks_failed": [c[0] for c in failed],
    }
    (ROOT / "raw" / "workbook_verify.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
