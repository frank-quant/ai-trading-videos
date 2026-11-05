"""Build moving_average_analysis.xlsx — a live, Assumptions-driven model.

Formula-first (xlsx skill §5): only the Assumptions block holds hard-coded
inputs (blue font). Every derived cell is a live `=` formula, so editing a
parameter re-runs the whole chain: Prices -> Indicators -> Ledger ->
Ledger_Gross -> Summary -> QA.

Sheet order: Assumptions, Prices, Indicators, Ledger, Ledger_Gross, QA,
Summary, Prices_Bench.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "moving_average_analysis.xlsx"

FONT = "Calibri"
BLACK = Font(name=FONT, size=10, color="000000")
BLUE = Font(name=FONT, size=10, color="0000FF")
GREEN = Font(name=FONT, size=10, color="008000")
BOLD = Font(name=FONT, size=10, bold=True, color="000000")
TITLE = Font(name=FONT, size=14, bold=True, color="000000")
HDR_FILL = PatternFill("solid", fgColor="1F3864")
HDR_FONT = Font(name=FONT, size=10, bold=True, color="FFFFFF")
SUB_FILL = PatternFill("solid", fgColor="D9E2F3")
NOTE_FONT = Font(name=FONT, size=9, italic=True, color="595959")
IN_FILL = PatternFill("solid", fgColor="FFF2CC")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

FMT_MONEY = '#,##0;(#,##0);"-"'
FMT_PCT = '0.00%'
FMT_PX = '0.00'
FMT_NUM4 = '0.0000'
FMT_INT = '#,##0'


def read_csv(name):
    with (ROOT / name).open(encoding="utf-8-sig") as f:
        return list(csv.reader(f))


prices = read_csv("prices.csv")
bench = read_csv("prices_bench.csv")
qa = json.loads((ROOT / "raw" / "qa_results.json").read_text(encoding="utf-8"))

N = len(prices) - 1                 # 822 data rows
FIRST = 3                          # first Excel data row (row1=title, row2=header)
LAST = FIRST + N - 1               # 824

wb = Workbook()

# ==================================================================== Assumptions
ws = wb.active
ws.title = "Assumptions"
ws["A1"] = "赛力斯（601127.SH）均线交叉策略 · Excel 联动模型"
ws["A1"].font = TITLE
ws["A2"] = ("蓝字单元格为可修改输入；其余全部为公式。修改本表参数后，Indicators / Ledger / "
            "Ledger_Gross / Summary / QA 自动重算。")
ws["A2"].font = NOTE_FONT
ws["A3"] = ("数据来源：个股＝恒生行情（adjustment=forward 前复权）；基准＝同花顺 iFinD（沪深300 价格指数）。"
            "生成日期 2026-11-02。")
ws["A3"].font = NOTE_FONT

ASSUMPTIONS = [
    ("初始资金", "InitCapital", 1000000, "元", "教学设定"),
    ("初始持仓股数", "InitShares", 0, "股", "策略起点空仓"),
    ("短期均线", "SmaFast", 5, "日", "快线（金叉/死叉用）"),
    ("长期均线", "SmaSlow", 20, "日", "慢线（金叉/死叉用）"),
    ("中期均线", "SmaMid", 60, "日", "趋势过滤 / 预热基准"),
    ("EMA 快线", "EmaFast", 12, "日", "MACD"),
    ("EMA 慢线", "EmaSlow", 26, "日", "MACD"),
    ("DEA 周期", "DeaLen", 9, "日", "MACD 信号线"),
    ("RSI 周期", "RsiLen", 14, "日", "Wilder 平滑"),
    ("斜率窗口", "SlopeWin", 5, "日", "均线斜率计算窗口"),
    ("单边佣金费率", "FeeRate", 0.00075, "—", "教学设定；不含印花税与过户费"),
    ("印花税（卖出）", "StampDuty", 0, "—", "本次不计"),
    ("过户费", "TransferFee", 0, "—", "本次不计"),
    ("年化交易日", "AnnualDays", 252, "日", "年化换算"),
    ("预热行数", "WarmupRows", 59, "行", "SMA60 成立前不评分、不交易"),
    ("数据起始日", "StartDate", "2023-06-01", "—", "首根K线"),
    ("数据结束日", "EndDate", "2026-10-23", "—", "末根K线"),
    ("标的代码", "SymbolStock", "601127.SH", "—", "赛力斯"),
    ("标的名称", "NameStock", "赛力斯", "—", ""),
    ("基准代码", "SymbolBench", "000300.SH", "—", "沪深300 价格指数"),
    ("基准名称", "NameBench", "沪深300", "—", ""),
]

for c, v in (("A", "参数"), ("B", "值"), ("C", "单位"), ("D", "说明")):
    ws[f"{c}5"] = v
    ws[f"{c}5"].font = HDR_FONT
    ws[f"{c}5"].fill = HDR_FILL
    ws[f"{c}5"].alignment = Alignment(horizontal="center")

for k, (label, name, value, unit, note) in enumerate(ASSUMPTIONS):
    r = 6 + k
    ws[f"A{r}"] = label
    ws[f"A{r}"].font = BLACK
    ws[f"B{r}"] = value
    ws[f"B{r}"].font = BLUE
    ws[f"B{r}"].fill = IN_FILL
    ws[f"B{r}"].border = BOX
    if isinstance(value, float):
        ws[f"B{r}"].number_format = "0.00000" if value < 0.01 else "#,##0.00"
    elif isinstance(value, int):
        ws[f"B{r}"].number_format = FMT_INT
    ws[f"C{r}"] = unit
    ws[f"C{r}"].font = BLACK
    ws[f"D{r}"] = note
    ws[f"D{r}"].font = NOTE_FONT
    wb.defined_names.add(DefinedName(name, attr_text=f"Assumptions!$B${r}"))

ws["A29"] = "口径说明"
ws["A29"].font = BOLD
notes = [
    "1. 信号：快线上穿慢线=金叉，下穿=死叉；信号在当日收盘后成立，次日开盘成交。",
    "2. 预热：前 WarmupRows 行 SMA60 尚未成立，indicators 不评分、ledger 不交易。",
    "3. 成本：单边费率×成交金额，买卖各计一次；期末不强制平仓。",
    "4. 基准：同期买入持有，起始净值 1.00，与策略同区间同日期轴。",
    "5. 所有数字为样本内结果，未经样本外检验，不构成投资建议。",
]
for i, t in enumerate(notes):
    ws[f"A{30 + i}"] = t
    ws[f"A{30 + i}"].font = NOTE_FONT

for col, w in (("A", 18), ("B", 16), ("C", 8), ("D", 34)):
    ws.column_dimensions[col].width = w


# ==================================================================== helpers
def write_table(ws, header, rows, widths, fmts=None, start=1, input_cols=()):
    """Write a static (raw-data) table with a styled header."""
    for j, h in enumerate(header, 1):
        c = ws.cell(row=start, column=j, value=h)
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.alignment = Alignment(horizontal="center")
    for i, row in enumerate(rows):
        for j, v in enumerate(row, 1):
            c = ws.cell(row=start + 1 + i, column=j, value=v)
            c.font = BLUE if (j in input_cols) else BLACK
            c.border = BOX
            if fmts and j in fmts:
                c.number_format = fmts[j]
    for j, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=start + 1, column=1)


# ==================================================================== Prices
ws = wb.create_sheet("Prices")
ws["A1"] = "原始行情：赛力斯 601127.SH（恒生行情 · 前复权 · 蓝色为输入区，改动 Assumptions 不影响本表）"
ws["A1"].font = TITLE
hdr = ["date", "open", "high", "low", "close", "pre_close", "volume", "amount"]
# prices.csv: date,symbol,name,open,high,low,close,pre_close,volume,amount,adjustment
rows = [[r[0], float(r[3]), float(r[4]), float(r[5]), float(r[6]), float(r[7]),
         int(float(r[8])), float(r[9])] for r in prices[1:]]
write_table(ws, hdr, rows,
            [13, 10, 10, 10, 10, 11, 15, 18],
            {2: FMT_PX, 3: FMT_PX, 4: FMT_PX, 5: FMT_PX, 6: FMT_PX, 7: FMT_INT, 8: FMT_MONEY},
            start=2, input_cols=set(range(1, 9)))
for r in range(FIRST, LAST + 1):
    ws.cell(row=r, column=1).number_format = "@"

# ==================================================================== Prices_Bench
wsb = wb.create_sheet("Prices_Bench")
wsb["A1"] = "原始行情：沪深300 000300.SH 价格指数（同花顺 iFinD · 蓝色为输入区）"
wsb["A1"].font = TITLE
hdr_b = ["date", "open", "high", "low", "close", "volume", "amount"]
# prices_bench.csv: date,symbol,name,open,high,low,close,volume,amount,index_type
rows_b = [[r[0], float(r[3]), float(r[4]), float(r[5]), float(r[6]),
           int(float(r[7])), float(r[8])] for r in bench[1:]]
write_table(wsb, hdr_b, rows_b,
            [13, 12, 12, 12, 12, 17, 19],
            {2: FMT_NUM4, 3: FMT_NUM4, 4: FMT_NUM4, 5: FMT_NUM4, 6: FMT_INT, 7: FMT_MONEY},
            start=2, input_cols=set(range(1, 8)))
for r in range(FIRST, LAST + 1):
    wsb.cell(row=r, column=1).number_format = "@"

# ==================================================================== Indicators
wsi = wb.create_sheet("Indicators")
wsi["A1"] = "技术指标（全部为公式，随 Assumptions 联动）"
wsi["A1"].font = TITLE
IH = ["date", "close", "sma_fast", "sma_slow", "sma_mid", "ema_fast", "ema_slow",
      "macd_dif", "macd_dea", "macd_hist", "rsi14",
      "sma_fast_slope", "sma_slow_slope", "sma_mid_slope",
      "ma_alignment", "score", "score_band", "is_warmup",
      "aux_avg_gain", "aux_avg_loss"]
for j, h in enumerate(IH, 1):
    c = wsi.cell(row=2, column=j, value=h)
    c.font = HDR_FONT
    c.fill = HDR_FILL
    c.alignment = Alignment(horizontal="center")

for r in range(FIRST, LAST + 1):
    p = r  # same row layout on Prices
    wsi[f"A{r}"] = f"=Prices!A{p}"
    wsi[f"A{r}"].number_format = "@"
    wsi[f"B{r}"] = f"=Prices!E{p}"
    for col, per in (("C", "SmaFast"), ("D", "SmaSlow"), ("E", "SmaMid")):
        wsi[f"{col}{r}"] = (f'=IF(ROW()-3<{per}-1,"",'
                            f"AVERAGE(OFFSET(Prices!$E$2,ROW()-1-{per},0,{per},1)))")
    for col, per in (("F", "EmaFast"), ("G", "EmaSlow")):
        wsi[f"{col}{r}"] = (f'=IF(ROW()-3<{per}-1,"",'
                            f"IF(ROW()-3={per}-1,AVERAGE(OFFSET(Prices!$E$3,0,0,{per},1)),"
                            f"{col}{r-1}+(2/({per}+1))*(Prices!E{p}-{col}{r-1})))")
    wsi[f"H{r}"] = f'=IF(OR(F{r}="",G{r}=""),"",F{r}-G{r})'
    wsi[f"I{r}"] = (f'=IF(OR(H{r}="",ROW()<EmaSlow+DeaLen+1),"",'
                    f"IF(ROW()=EmaSlow+DeaLen+1,AVERAGE(OFFSET(H$3,EmaSlow-1,0,DeaLen,1)),"
                    f"I{r-1}+(2/(DeaLen+1))*(H{r}-I{r-1})))")
    wsi[f"J{r}"] = f'=IF(OR(H{r}="",I{r}=""),"",2*(H{r}-I{r}))'
    # Wilder RSI with two helper columns
    wsi[f"S{r}"] = (f'=IF(ROW()-3<RsiLen,"",'
                    f"IF(ROW()-3=RsiLen,"
                    f"SUMPRODUCT((INDEX(Prices!$E:$E,4):INDEX(Prices!$E:$E,RsiLen+3)-"
                    f"INDEX(Prices!$E:$E,3):INDEX(Prices!$E:$E,RsiLen+2)>0)*"
                    f"(INDEX(Prices!$E:$E,4):INDEX(Prices!$E:$E,RsiLen+3)-"
                    f"INDEX(Prices!$E:$E,3):INDEX(Prices!$E:$E,RsiLen+2)))/RsiLen,"
                    f"(S{r-1}*(RsiLen-1)+MAX(0,Prices!E{p}-Prices!E{r-1}))/RsiLen))")
    wsi[f"T{r}"] = (f'=IF(ROW()-3<RsiLen,"",'
                    f"IF(ROW()-3=RsiLen,"
                    f"SUMPRODUCT((INDEX(Prices!$E:$E,3):INDEX(Prices!$E:$E,RsiLen+2)-"
                    f"INDEX(Prices!$E:$E,4):INDEX(Prices!$E:$E,RsiLen+3)>0)*"
                    f"(INDEX(Prices!$E:$E,3):INDEX(Prices!$E:$E,RsiLen+2)-"
                    f"INDEX(Prices!$E:$E,4):INDEX(Prices!$E:$E,RsiLen+3)))/RsiLen,"
                    f"(T{r-1}*(RsiLen-1)+MAX(0,Prices!E{r-1}-Prices!E{p}))/RsiLen))")
    wsi[f"K{r}"] = f'=IF(ROW()-3<RsiLen,"",IF(T{r}=0,100,100-100/(1+S{r}/T{r})))'
    for col, src in (("L", "C"), ("M", "D"), ("N", "E")):
        wsi[f"{col}{r}"] = (f'=IF(OR(ROW()-3<SlopeWin,NOT(ISNUMBER({src}{r})),'
                            f'NOT(ISNUMBER(INDEX(${src}:${src},ROW()-SlopeWin)))),"",'
                            f"({src}{r}-INDEX(${src}:${src},ROW()-SlopeWin))/SlopeWin)")
    wsi[f"O{r}"] = (f'=IF(OR(C{r}="",D{r}="",E{r}=""),"",'
                    f'IF(AND(C{r}>D{r},D{r}>E{r}),"多头排列",'
                    f'IF(AND(C{r}<D{r},D{r}<E{r}),"空头排列",'
                    f'IF(AND(C{r}>D{r},D{r}<E{r}),"短多长空",'
                    f'IF(AND(C{r}<D{r},D{r}>E{r}),"短空长多","交汇纠缠")))))')
    wsi[f"P{r}"] = (
        f'=IF(OR(ROW()-3<WarmupRows,C{r}="",D{r}="",E{r}="",K{r}="",H{r}="",I{r}=""),"",'
        f'IF(O{r}="多头排列",30,IF(O{r}="短多长空",18,IF(O{r}="交汇纠缠",10,'
        f'IF(O{r}="短空长多",8,0))))'
        f'+IF(AND(ISNUMBER(M{r}),ISNUMBER(N{r})),'
        f'IF(AND(M{r}>0,N{r}>0),10,IF(OR(M{r}>0,N{r}>0),5,0)),0)'
        f'+IF(AND(K{r}>=45,K{r}<=70),15,IF(OR(AND(K{r}>=30,K{r}<45),AND(K{r}>70,K{r}<=80)),8,'
        f'IF(K{r}>80,3,IF(K{r}<30,5,0))))'
        f'+IF(AND(H{r}>I{r},J{r}>0),15,IF(AND(H{r}>I{r},J{r}<=0),8,'
        f'IF(AND(H{r}<=I{r},J{r}>0),6,0)))'
        f'+IF(B{r}>C{r},10,0)'
        f'+IF(AND(B{r}>D{r},B{r}>E{r}),10,IF(B{r}>D{r},6,IF(B{r}>E{r},4,0))))')
    wsi[f"Q{r}"] = (f'=IF(P{r}="","",IF(P{r}>=75,"强势",IF(P{r}>=60,"中性偏多",'
                    f'IF(P{r}>=45,"中性",IF(P{r}>=30,"中性偏空","弱势")))))')
    wsi[f"R{r}"] = "=IF(ROW()-3<WarmupRows,1,0)"
    for col in "ABCDEFGHIJKLMNOPQRST":
        wsi[f"{col}{r}"].font = BLACK
    wsi[f"B{r}"].number_format = FMT_PX
    for col in "CDE":
        wsi[f"{col}{r}"].number_format = FMT_NUM4
    for col in "FGHIJ":
        wsi[f"{col}{r}"].number_format = FMT_NUM4
    wsi[f"K{r}"].number_format = FMT_NUM4
    for col in "LMN":
        wsi[f"{col}{r}"].number_format = FMT_NUM4
    wsi[f"P{r}"].number_format = "0"

for j, w in enumerate([13, 10, 11, 11, 11, 11, 11, 11, 11, 11, 10, 14, 15, 15, 11, 8, 11, 10, 13, 13], 1):
    wsi.column_dimensions[get_column_letter(j)].width = w
wsi.freeze_panes = "C3"
wsi.column_dimensions["S"].hidden = True
wsi.column_dimensions["T"].hidden = True


# ==================================================================== Ledger builders
LEDGER_HDR = ["date", "open", "close", "signal", "action", "exec_date", "fill_price",
              "shares", "position_value", "cash", "fee", "cum_fee", "nav",
              "daily_return", "cum_return", "peak_nav", "drawdown"]


def build_ledger(name, fee_expr, title):
    ws = wb.create_sheet(name)
    ws["A1"] = title
    ws["A1"].font = TITLE
    for j, h in enumerate(LEDGER_HDR, 1):
        c = ws.cell(row=2, column=j, value=h)
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.alignment = Alignment(horizontal="center")
    for r in range(FIRST, LAST + 1):
        ws[f"A{r}"] = f"=Prices!A{r}"
        ws[f"A{r}"].number_format = "@"
        ws[f"B{r}"] = f"=Prices!B{r}"
        ws[f"C{r}"] = f"=Prices!E{r}"
        ws[f"D{r}"] = (
            f'=IF(ROW()-3<WarmupRows,"none",'
            f'IF(OR(Indicators!C{r}="",Indicators!D{r}=""),"none",'
            f'IF(Indicators!C{r-1}="","none",'
            f'IF(Indicators!D{r-1}="","none",'
            f'IF(AND(Indicators!C{r}>Indicators!D{r},Indicators!C{r-1}<=Indicators!D{r-1}),"golden_cross",'
            f'IF(AND(Indicators!C{r}<Indicators!D{r},Indicators!C{r-1}>=Indicators!D{r-1}),"death_cross","none"))))))')
        ws[f"E{r}"] = (f'=IF(ROW()-3<WarmupRows,"NONE",'
                       f'IF(D{r-1}="golden_cross",IF(H{r-1}>0,"IGNORED","BUY"),'
                       f'IF(D{r-1}="death_cross",IF(H{r-1}<=0,"IGNORED","SELL"),"NONE")))')
        ws[f"F{r}"] = f'=IF(OR(E{r}="BUY",E{r}="SELL",E{r}="IGNORED"),A{r},"")'
        ws[f"G{r}"] = f'=IF(OR(E{r}="BUY",E{r}="SELL",E{r}="IGNORED"),B{r},"")'
        if r == FIRST:
            ws[f"H{r}"] = "=InitShares"
            ws[f"J{r}"] = "=InitCapital"
            ws[f"L{r}"] = f"=K{r}"
            ws[f"N{r}"] = '=""'
        else:
            ws[f"H{r}"] = (f'=IF(E{r}="BUY",J{r-1}/(G{r}*(1+{fee_expr})),'
                           f'IF(E{r}="SELL",0,H{r-1}))')
            ws[f"J{r}"] = (f'=IF(E{r}="BUY",J{r-1}-H{r}*G{r}-K{r},'
                           f'IF(E{r}="SELL",J{r-1}+H{r-1}*G{r}-K{r},J{r-1}))')
            ws[f"L{r}"] = f"=L{r-1}+K{r}"
            ws[f"N{r}"] = f"=M{r}/M{r-1}-1"
        ws[f"I{r}"] = f"=H{r}*C{r}"
        ws[f"K{r}"] = (f'=IF(E{r}="BUY",H{r}*G{r}*{fee_expr},'
                       f'IF(E{r}="SELL",H{r-1}*G{r}*({fee_expr}),0))')
        ws[f"M{r}"] = f"=J{r}+I{r}"
        ws[f"O{r}"] = f"=M{r}/InitCapital-1"
        ws[f"P{r}"] = f"=MAX($M${FIRST}:M{r})"
        ws[f"Q{r}"] = f"=M{r}/P{r}-1"
        for col in "ABCDEFGHIJKLMNOPQ":
            ws[f"{col}{r}"].font = BLACK
        ws[f"B{r}"].number_format = FMT_PX
        ws[f"C{r}"].number_format = FMT_PX
        ws[f"G{r}"].number_format = FMT_NUM4
        ws[f"H{r}"].number_format = FMT_NUM4
        ws[f"I{r}"].number_format = FMT_MONEY
        ws[f"J{r}"].number_format = FMT_MONEY
        ws[f"K{r}"].number_format = FMT_MONEY
        ws[f"L{r}"].number_format = FMT_MONEY
        ws[f"M{r}"].number_format = FMT_MONEY
        ws[f"N{r}"].number_format = "0.00000000"
        ws[f"O{r}"].number_format = FMT_PCT
        ws[f"P{r}"].number_format = FMT_MONEY
        ws[f"Q{r}"].number_format = "0.0000%"
    for j, w in enumerate([13, 9, 9, 13, 9, 13, 11, 13, 15, 15, 11, 14, 15, 14, 12, 15, 11], 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = "B3"
    return ws


wsl = build_ledger("Ledger", "FeeRate+StampDuty+TransferFee",
                   "回测账本（含费）：信号在收盘后成立，次日开盘成交；期末不强制平仓")
wslg = build_ledger("Ledger_Gross", "0",
                     "回测账本（零成本）：同规则、无交易成本，用于与含费口径分离比较")

# ==================================================================== Summary
wss = wb.create_sheet("Summary")
wss["A1"] = "绩效汇总：策略（零成本 / 含费）vs 买入持有 vs 沪深300（全部为公式）"
wss["A1"].font = TITLE
wss["A2"] = "同一区间 2023-06-01 ~ 2026-10-23（822 个交易日），起始净值 1,000,000 元。"
wss["A2"].font = NOTE_FONT
for j, h in enumerate(["指标", "策略（含费）", "策略（零成本）", "赛力斯 买入持有",
                       "沪深300 买入持有"], 1):
    c = wss.cell(row=4, column=j, value=h)
    c.font = HDR_FONT
    c.fill = HDR_FILL
    c.alignment = Alignment(horizontal="center")

RNG = f"${FIRST}:${LAST}"
NROWS = f"COUNTA(Prices!$A${FIRST}:$A${LAST})"
ROWS = {
    "期末净值（元）": {
        "B": f"=Ledger!M{LAST}", "C": f"=Ledger_Gross!M{LAST}",
        "D": f"=Prices!E{LAST}/Prices!$B${FIRST}*InitCapital",
        "E": f"=Prices_Bench!E{LAST}/Prices_Bench!$B${FIRST}*InitCapital", "fmt": FMT_MONEY},
    "累计收益": {
        "B": f"=B5/InitCapital-1", "C": f"=C5/InitCapital-1",
        "D": f"=Prices!E{LAST}/Prices!$B${FIRST}-1",
        "E": f"=Prices_Bench!E{LAST}/Prices_Bench!$B${FIRST}-1", "fmt": FMT_PCT},
    "年化收益": {
        "B": f"=(B5/InitCapital)^(AnnualDays/({NROWS}-1))-1",
        "C": f"=(C5/InitCapital)^(AnnualDays/({NROWS}-1))-1",
        "D": f"=(Prices!E{LAST}/Prices!$B${FIRST})^(AnnualDays/({NROWS}-1))-1",
        "E": f"=(Prices_Bench!E{LAST}/Prices_Bench!$B${FIRST})^(AnnualDays/({NROWS}-1))-1", "fmt": FMT_PCT},
    "最大回撤": {
        "B": f"=MIN($O${FIRST}:$O${LAST})", "C": f"=MIN($R${FIRST}:$R${LAST})",
        "D": f"=MIN($U${FIRST}:$U${LAST})", "E": f"=MIN($X${FIRST}:$X${LAST})", "fmt": FMT_PCT},
    "回撤峰值日": {
        "B": f"=INDEX($N${FIRST}:$N${LAST},MATCH(MIN($O${FIRST}:$O${LAST}),$O${FIRST}:$O${LAST},0))",
        "C": f"=INDEX($Q${FIRST}:$Q${LAST},MATCH(MIN($R${FIRST}:$R${LAST}),$R${FIRST}:$R${LAST},0))",
        "D": f"=INDEX($T${FIRST}:$T${LAST},MATCH(MIN($U${FIRST}:$U${LAST}),$U${FIRST}:$U${LAST},0))",
        "E": f"=INDEX($W${FIRST}:$W${LAST},MATCH(MIN($X${FIRST}:$X${LAST}),$X${FIRST}:$X${LAST},0))",
        "fmt": "@"},
    "回撤谷底日": {
        "B": f"=INDEX($H${FIRST}:$H${LAST},MATCH(MIN($O${FIRST}:$O${LAST}),$O${FIRST}:$O${LAST},0))",
        "C": f"=INDEX($H${FIRST}:$H${LAST},MATCH(MIN($R${FIRST}:$R${LAST}),$R${FIRST}:$R${LAST},0))",
        "D": f"=INDEX($H${FIRST}:$H${LAST},MATCH(MIN($U${FIRST}:$U${LAST}),$U${FIRST}:$U${LAST},0))",
        "E": f"=INDEX($H${FIRST}:$H${LAST},MATCH(MIN($X${FIRST}:$X${LAST}),$X${FIRST}:$X${LAST},0))",
        "fmt": "@"},
    "交易次数（买入腿）": {
        "B": f'=COUNTIF(Ledger!$E${FIRST}:$E${LAST},"BUY")',
        "C": f'=COUNTIF(Ledger_Gross!$E${FIRST}:$E${LAST},"BUY")',
        "D": "买入 1 次，样本末未卖出", "E": "买入 1 次，样本末未卖出", "fmt": "General"},
    "卖出腿次数": {
        "B": f'=COUNTIF(Ledger!$E${FIRST}:$E${LAST},"SELL")',
        "C": f'=COUNTIF(Ledger_Gross!$E${FIRST}:$E${LAST},"SELL")',
        "D": "0", "E": "0", "fmt": "General"},
    "持仓天数": {
        "B": f'=COUNTIF(Ledger!$H${FIRST}:$H${LAST},">0")',
        "C": f'=COUNTIF(Ledger_Gross!$H${FIRST}:$H${LAST},">0")',
        "D": f"={NROWS}", "E": f"={NROWS}", "fmt": FMT_INT},
    "持仓占比": {
        "B": f"=B13/{NROWS}", "C": f"=C13/{NROWS}",
        "D": f"=D13/{NROWS}", "E": f"=E13/{NROWS}", "fmt": FMT_PCT},
    "实际支付费用（元）": {
        "B": f"=Ledger!L{LAST}", "C": f"=Ledger_Gross!L{LAST}", "D": "0", "E": "0", "fmt": FMT_MONEY},
    "费用造成的期末净值差（元）": {
        "B": f"=Ledger_Gross!M{LAST}-Ledger!M{LAST}",
        "C": f"=Ledger_Gross!M{LAST}-Ledger!M{LAST}", "D": "—", "E": "—", "fmt": FMT_MONEY},
}
r = 5
for label, spec in ROWS.items():
    wss[f"A{r}"] = label
    wss[f"A{r}"].font = BOLD
    for col in "BCDE":
        v = spec[col]
        wss[f"{col}{r}"] = v
        wss[f"{col}{r}"].font = BLACK
        wss[f"{col}{r}"].number_format = spec.get("fmt", "General")
        wss[f"{col}{r}"].border = BOX
    r += 1

wss["A18"] = "费用分解（两个口径分开，不可合并）"
wss["A18"].font = BOLD
wss["A18"].fill = SUB_FILL
wss["A19"] = "费用造成的期末净值差"
wss["A19"].font = BLACK
wss["B19"] = f"=Ledger_Gross!M{LAST}-Ledger!M{LAST}"
wss["B19"].font = BLACK
wss["B19"].number_format = FMT_MONEY
wss["C19"] = "零成本期末净值 − 含费期末净值；含费账本相对零成本账本少掉的净值"
wss["C19"].font = NOTE_FONT
wss["A20"] = "实际支付费用合计"
wss["A20"].font = BLACK
wss["B20"] = f"=Ledger!L{LAST}"
wss["B20"].font = BLACK
wss["B20"].number_format = FMT_MONEY
wss["C20"] = "含费账本 40 个成交腿累计计提的手续费；大于上一行，因费用使后续可用资金变小、后续费用按更小基数计提"
wss["C20"].font = NOTE_FONT

wss["A22"] = "结论（公式自动生成，随参数变动更新）"
wss["A22"].font = BOLD
wss["A22"].fill = SUB_FILL
wss["A23"] = (
    '="策略（含费）累计收益 "&TEXT(B6,"0.00%")&"，同期买入持有赛力斯 "&TEXT(D6,"0.00%")'
    '&"，差 "&TEXT(B6-D6,"0.00%")&"；最大回撤 "&TEXT(B8,"0.00%")&" vs 买入持有 "&TEXT(D8,"0.00%")'
    '&"。同期沪深300 "&TEXT(E6,"0.00%")&"。"')
wss["A23"].font = BLACK
wss["A24"] = (
    '="费用造成的期末净值差 "&TEXT(B19,"#,##0")&" 元；实际支付费用合计 "&TEXT(B20,"#,##0")'
    '&" 元（两者口径不同，分开列示）。"')
wss["A24"].font = BLACK
wss["A25"] = (
    '="本模型为样本内结果，未经样本外检验与参数敏感性分析，不构成投资建议，也不证明策略有效。"')
wss["A25"].font = NOTE_FONT

# helper block (hidden)
wss["H1"] = "辅助计算（隐藏）"
wss["H1"].font = NOTE_FONT
HELP = ["date", "策略含费NAV", "策略零成本NAV", "赛力斯B&H", "沪深300B&H",
        "策略含费peak", "策略含费peak日", "策略含费dd",
        "策略零成本peak", "策略零成本peak日", "策略零成本dd",
        "赛力斯B&H peak", "赛力斯B&H peak日", "赛力斯B&H dd",
        "沪深300B&H peak", "沪深300B&H peak日", "沪深300B&H dd"]
for j, h in enumerate(HELP, 8):
    c = wss.cell(row=2, column=j, value=h)
    c.font = NOTE_FONT
for r in range(FIRST, LAST + 1):
    wss[f"H{r}"] = f"=Prices!A{r}"
    wss[f"H{r}"].number_format = "@"
    wss[f"I{r}"] = f"=Ledger!M{r}"
    wss[f"J{r}"] = f"=Ledger_Gross!M{r}"
    wss[f"K{r}"] = f"=Prices!E{r}/Prices!$B${FIRST}"
    wss[f"L{r}"] = f"=Prices_Bench!E{r}/Prices_Bench!$B${FIRST}"
    for nav_col, pk_col, dt_col, dd_col in (("I", "M", "N", "O"), ("J", "P", "Q", "R"),
                                            ("K", "S", "T", "U"), ("L", "V", "W", "X")):
        wss[f"{pk_col}{r}"] = f"=MAX(${nav_col}${FIRST}:{nav_col}{r})"
        if r == FIRST:
            wss[f"{dt_col}{r}"] = f"=H{r}"
        else:
            wss[f"{dt_col}{r}"] = f"=IF({pk_col}{r}>{pk_col}{r-1},H{r},{dt_col}{r-1})"
        wss[f"{dd_col}{r}"] = f"={nav_col}{r}/{pk_col}{r}-1"
    for j in range(8, 25):
        wss.cell(row=r, column=j).font = BLACK
for j in range(8, 25):
    wss.column_dimensions[get_column_letter(j)].hidden = True
for col, w in (("A", 26), ("B", 17), ("C", 17), ("D", 20), ("E", 20)):
    wss.column_dimensions[col].width = w

# ==================================================================== QA
wsq = wb.create_sheet("QA")
wsq["A1"] = "质量校验：活公式自检 + 独立复核留档"
wsq["A1"].font = TITLE
wsq["A2"] = ("上半部为工作簿自身的活公式校验（改参数后自动重检）；下半部为 scripts/qa_check.py 的独立复核留档。")
wsq["A2"].font = NOTE_FONT
for j, h in enumerate(["校验项", "计算值", "期望", "状态", "说明"], 1):
    c = wsq.cell(row=4, column=j, value=h)
    c.font = HDR_FONT
    c.fill = HDR_FILL
    c.alignment = Alignment(horizontal="center")

LIVE = [
    ("预热行数与 WarmupRows 一致",
     f"=COUNTIF(Indicators!$R${FIRST}:$R${LAST},1)", "=WarmupRows",
     "=IF(B5=C5,\"PASS\",\"FAIL\")", "indicators 中 is_warmup=1 的行数"),
    ("零成本账本 nav=cash+shares×close 违例数",
     f"=SUMPRODUCT(--(ABS(Ledger_Gross!$J${FIRST}:$J${LAST}+Ledger_Gross!$I${FIRST}:$I${LAST}-Ledger_Gross!$M${FIRST}:$M${LAST})>0.01))",
     "=0", "=IF(B6=C6,\"PASS\",\"FAIL\")", "恒等式逐行复核"),
    ("含费账本 nav=cash+shares×close 违例数",
     f"=SUMPRODUCT(--(ABS(Ledger!$J${FIRST}:$J${LAST}+Ledger!$I${FIRST}:$I${LAST}-Ledger!$M${FIRST}:$M${LAST})>0.01))",
     "=0", "=IF(B7=C7,\"PASS\",\"FAIL\")", "恒等式逐行复核"),
    ("成交价 ≠ 当日开盘价的笔数",
     f'=SUMPRODUCT((Ledger!$E${FIRST}:$E${LAST}<>"NONE")*(IFERROR(ABS(Ledger!$G${FIRST}:$G${LAST}-Ledger!$B${FIRST}:$B${LAST}),0)>0.005))',
     "=0", "=IF(B8=C8,\"PASS\",\"FAIL\")", "执行价必须是当日开盘价"),
    ("含费账本买入腿费用公式违例数",
     f'=SUMPRODUCT((Ledger!$E${FIRST}:$E${LAST}="BUY")*(IFERROR(ABS(Ledger!$K${FIRST}:$K${LAST}-Ledger!$H${FIRST}:$H${LAST}*Ledger!$G${FIRST}:$G${LAST}*FeeRate),0)>0.02))',
     "=0", "=IF(B9=C9,\"PASS\",\"FAIL\")", "fee = 成交金额 × 费率"),
    ("含费账本卖出腿费用公式违例数",
     f'=SUMPRODUCT((Ledger!$E${FIRST}:$E${LAST}="SELL")*(IFERROR(ABS(Ledger!$K${FIRST}:$K${LAST}-Ledger!$H${FIRST}:$H${LAST}*Ledger!$G${FIRST}:$G${LAST}*(FeeRate+StampDuty+TransferFee)),0)>0.02))',
     "=0", "=IF(B10=C10,\"PASS\",\"FAIL\")", "fee = 成交金额 × (费率+印花税+过户费)"),
    ("零成本账本累计费用",
     f"=SUM(Ledger_Gross!$K${FIRST}:$K${LAST})", "=0", "=IF(B11=C11,\"PASS\",\"FAIL\")", "零成本口径"),
    ("信号数 = 成交数",
     f'=COUNTIF(Ledger!$D${FIRST}:$D${LAST},"golden_cross")+COUNTIF(Ledger!$D${FIRST}:$D${LAST},"death_cross")',
     f'=COUNTIF(Ledger!$E${FIRST}:$E${LAST},"BUY")+COUNTIF(Ledger!$E${FIRST}:$E${LAST},"SELL")',
     "=IF(B12=C12,\"PASS\",\"FAIL\")", "每个信号都对应一次成交"),
    ("预热期内成交笔数",
     f'=SUMPRODUCT((ROW(Ledger!$A${FIRST}:$A${LAST})<=WarmupRows+2)*(Ledger!$E${FIRST}:$E${LAST}<>"NONE"))',
     "=0", "=IF(B13=C13,\"PASS\",\"FAIL\")", "预热期不交易"),
    ("行情行数",
     f"={NROWS}", "=822", "=IF(B14=C14,\"PASS\",\"FAIL\")", "822 个交易日"),
    ("基准与策略同日期轴",
     f"=IF(COUNTA(Prices_Bench!$A${FIRST}:$A${LAST})={NROWS},\"同轴\",\"不一致\")",
     "=\"同轴\"", "=IF(B15=C15,\"PASS\",\"FAIL\")", "沪深300 与个股同区间"),
    ("Summary 最大回撤 = 明细扫描最小回撤（策略含费）",
     f"=Summary!B8", f"=MIN(Summary!$O${FIRST}:$O${LAST})", "=IF(ABS(B16-C16)<0.000001,\"PASS\",\"FAIL\")",
     "汇总表与辅助列一致"),
    ("期末净值差 = 零成本 − 含费",
     "=Summary!B19", f"=Ledger_Gross!M{LAST}-Ledger!M{LAST}",
     "=IF(ABS(B17-C17)<0.01,\"PASS\",\"FAIL\")", "费用分解口径一"),
    ("累计支付费用 = 明细求和",
     "=Summary!B20", f"=SUM(Ledger!$K${FIRST}:$K${LAST})",
     "=IF(ABS(B18-C18)<0.01,\"PASS\",\"FAIL\")", "费用分解口径二"),
    ("含费账本净值 ≤ 零成本账本净值（每根K线）",
     f"=SUMPRODUCT(--(Ledger!$M${FIRST}:$M${LAST}>Ledger_Gross!$M${FIRST}:$M${LAST}+0.01))",
     "=0", "=IF(B19=C19,\"PASS\",\"FAIL\")", "费用只会拖累净值"),
]
for k, (name, calc, exp, status, note) in enumerate(LIVE):
    r = 5 + k
    wsq[f"A{r}"] = name
    wsq[f"A{r}"].font = BLACK
    wsq[f"B{r}"] = calc
    wsq[f"B{r}"].font = BLACK
    wsq[f"C{r}"] = exp
    wsq[f"C{r}"].font = BLACK
    wsq[f"D{r}"] = status
    wsq[f"D{r}"].font = Font(name=FONT, size=10, bold=True, color="006100")
    wsq[f"E{r}"] = note
    wsq[f"E{r}"].font = NOTE_FONT
    for c in "ABCD":
        wsq[f"{c}{r}"].border = BOX

wsa = wb["Assumptions"]
wsa["A33"] = "独立复核留档（scripts/qa_check.py，机读结果见 raw/qa_results.json）"
wsa["A33"].font = BOLD
wsa["A34"] = f"复核时间 2026-11-02 ｜ 检查项 {qa['total_checks']} 项 ｜ 通过 {qa['passed']} ｜ 失败 {qa['failed']}"
wsa["A34"].font = BLACK

qa_start = 21
wsq.cell(row=qa_start, column=1, value="独立复核明细（全部来自 qa_report.md / raw/qa_results.json）").font = BOLD
wsq.cell(row=qa_start, column=1).fill = SUB_FILL
for j, h in enumerate(["检查项", "状态", "说明"], 1):
    c = wsq.cell(row=qa_start + 1, column=j, value=h)
    c.font = HDR_FONT
    c.fill = HDR_FILL
for k, ch in enumerate(qa["checks"]):
    r = qa_start + 2 + k
    wsq[f"A{r}"] = ch["check"]
    wsq[f"A{r}"].font = BLACK
    wsq[f"B{r}"] = ch["status"]
    wsq[f"B{r}"].font = Font(name=FONT, size=10, bold=True,
                              color="006100" if ch["status"] == "PASS" else "9C0006")
    wsq[f"C{r}"] = ch["detail"][:160]
    wsq[f"C{r}"].font = NOTE_FONT
    for c in "ABC":
        wsq[f"{c}{r}"].border = BOX
for col, w in (("A", 52), ("B", 16), ("C", 16), ("D", 10), ("E", 40)):
    wsq.column_dimensions[col].width = w
wsq.freeze_panes = "A5"

# ---------------------------------------------------------------- order & save
order = ["Assumptions", "Prices", "Indicators", "Ledger", "Ledger_Gross", "QA", "Summary", "Prices_Bench"]
wb._sheets = [wb[n] for n in order]
wb.active = 0
wb.save(OUT)
print(f"saved {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
print("sheets:", wb.sheetnames)
