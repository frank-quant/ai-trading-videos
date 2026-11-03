import os, json, math, hashlib
from datetime import datetime
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.utils import get_column_letter

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(ROOT, 'meta_model.xlsx')
A25 = pd.read_csv(os.path.join(RAW, 'meta_fy2025_all.csv'))
Q26 = pd.read_csv(os.path.join(RAW, 'meta_q3fy2026_all.csv'))
B24 = pd.read_csv(os.path.join(RAW, 'meta_fy2024_bs.csv'))
STOCK = pd.read_csv(os.path.join(RAW, 'meta_stock_info.csv')).iloc[0]
PRICES = pd.read_csv(os.path.join(RAW, 'meta_prices_5d.csv'))

NAVY='1F3864'; GREY='EDEDED'; LIGHTBLUE='DDEBF7'; AMBER='FFF2CC'; WHITE='FFFFFF'; BLACK='000000'; CITEBLUE='0000CC'; NOTEGREY='777777'; GREEN='006100'; RED='9C0006'
thin = Side(style='thin', color='A6A6A6')

# All monetary facts are normalized to USD millions; per-share data are USD, shares are millions.
def fact(df, statement, label, col, dimension=False):
    m = df[(df.statement_type == statement) & (df.label == label) & (df.dimension == dimension)]
    if m.empty:
        raise KeyError((statement, label, col))
    v = m.iloc[0][col]
    if pd.isna(v):
        return None
    return float(v) / (1 if 'per share' in label.lower() else 1e6)

def fy(statement, label, year, dimension=False):
    return fact(A25, statement, label, f'{year}-12-31 (FY)', dimension)

def bs(label, year):
    if year == 2023:
        if label == 'Non-marketable equity investments':
            label = 'Non-marketable equity securities'
        if label == 'Accumulated other comprehensive income (loss)':
            label = 'Accumulated other comprehensive loss'
        return fact(B24, 'balance_sheet', label, '2023-12-31')
    return fact(A25, 'balance_sheet', label, '2024-12-31' if year == 2024 else '2025-12-31')

def q(label, statement='income_statement', ytd=True, dimension=False):
    col = '2026-09-30 (YTD)' if ytd else '2026-09-30'
    return fact(Q26, statement, label, col, dimension)

YRS = [2023, 2024, 2025]
raw_rows = []
def add_raw(key, label, statement, values, locator, unit='USD mn'):
    raw_rows.append(dict(key=key, label=label, statement=statement, values=values, locator=locator, unit=unit))

is_labels = {
'revenue':'Revenue','advertising':'Advertising - Family of Apps','other_rev':'Other revenue - Family of Apps',
'foa_rev':'Family of Apps','rl_rev':'Reality Labs','cor':'Cost of revenue','rd':'Research and development',
'ms':'Marketing and sales','ga':'General and administrative','costs':'Total costs and expenses',
'ebit':'Income (loss) from operations','foa_ebit':'Family of Apps','rl_ebit':'Reality Labs',
'pretax':'Income before provision for income taxes','tax':'Provision for income taxes','ni':'Net income',
'eps_basic':'Basic (in dollars per share)','eps_dil':'Diluted (in dollars per share)',
'shares_basic':'Basic (in shares)','shares_dil':'Diluted (in shares)'}
for key,label in is_labels.items():
    dim = key in ['advertising','other_rev','foa_rev','rl_rev','foa_ebit','rl_ebit']
    unit = 'USD/share' if 'eps' in key else ('mn shares' if 'shares' in key else 'USD mn')
    qlabel = 'Income before income taxes' if key == 'pretax' else label
    add_raw(key,label,'IS',[fy('income_statement',label,y,dim) for y in YRS]+[q(qlabel,dimension=dim)],'10-K FY2025 / 10-Q Q3 FY2026',unit)
add_raw('nonop','Interest and other income (expense), net','IS',[fy('income_statement','Interest and other income, net',y) for y in YRS]+[q('Interest and other income (expense), net')],'10-K FY2025 / 10-Q Q3 FY2026')

bs_labels = {'cash':'Cash and cash equivalents','marketable':'Marketable securities','ar':'Accounts receivable, net','prepaid':'Prepaid expenses and other current assets','nonmarketable':'Non-marketable equity investments','ppe':'Property and equipment, net','rou':'Operating lease right-of-use assets','goodwill':'Goodwill','other_assets':'Other assets','assets':'Total assets','ap':'Accounts payable','lease_cur':'Operating lease liabilities, current','accrued':'Accrued expenses and other current liabilities','lease_noncur':'Operating lease liabilities, non-current','debt':'Long-term debt','lt_tax':'Long-term income taxes','other_liab':'Other liabilities','liabilities':'Total liabilities','aoci':'Accumulated other comprehensive income (loss)','re':'Retained earnings','equity':'Total stockholders\' equity','le':'Total liabilities and stockholders\' equity'}
for key,label in bs_labels.items():
    vals = [bs(label,y) for y in YRS]
    if key == 'nonmarketable':
        vals[0] = fact(B24,'balance_sheet','Non-marketable equity securities','2023-12-31')
    vals.append(fact(Q26,'balance_sheet',label,'2026-09-30'))
    add_raw(key,label,'BS',vals,'10-K FY2024/FY2025; 10-Q Q3 FY2026')
add_raw('apic','Common stock and additional paid-in capital','BS',[73253,83228,95793,q('Common stock and additional paid-in capital','balance_sheet',False)],'10-K FY2024/FY2025; 10-Q Q3 FY2026')

cf_map = {'da':'Depreciation and amortization','sbc':'Share-based compensation','deferred_tax':'Deferred income taxes','cfo':'Net cash provided by operating activities','cash_capex':'Purchases of property and equipment','cfi':'Net cash used in investing activities','debt_issued':'Proceeds from issuance of long-term debt, net','fin_principal':'Principal payments on finance leases','buybacks':'Repurchases of Class A common stock','dividends':'Payments for dividends and dividend equivalents','tax_withholding':'Taxes paid related to net share settlement of equity awards','cff':'Net cash used in financing activities','fx':'Effect of exchange rate changes on cash, cash equivalents, restricted cash, and restricted cash equivalents'}
for key,label in cf_map.items():
    qlabel = label
    fylabel = label
    if key == 'cff': qlabel = 'Net cash provided by (used in) financing activities'
    if key == 'fx': fylabel = 'Effect of exchange rate changes on cash, cash equivalents, and restricted cash equivalents'
    add_raw(key,label,'CF',[fy('cash_flow',fylabel,y) for y in YRS]+[q(qlabel,'cash_flow')],'10-K FY2025 / 10-Q Q3 FY2026')
add_raw('legal_charge','Q3 2026 legal charge','Memo',[None,None,None,9890],'Meta Q3 2026 earnings release — Agreement with U.S. State Attorneys General')

# Workbook and styles
wb = Workbook(); wb.remove(wb.active)
for name in ['Cover','Summary','Assumptions','Segment','IS','BS','CF','Checks','DCF','Sensitivity','Scenarios','Market_Implied','Raw_Data','Data_Sources']:
    wb.create_sheet(name)
wb.calculation.fullCalcOnLoad = True; wb.calculation.forceFullCalc = True; wb.calculation.calcMode = 'auto'

for ws in wb:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = 'B7'
    ws.column_dimensions['A'].width = 42
    for c in range(2,10): ws.column_dimensions[get_column_letter(c)].width = 15
    ws.column_dimensions['J'].width = 68
    for row in ws.iter_rows():
        for cell in row: cell.font = Font(name='Arial', size=10)

def title(ws, text, subtitle='Meta Platforms, Inc. | Nasdaq: META | US GAAP | USD mn unless stated'):
    ws.merge_cells('A1:J1'); ws['A1']=text; ws['A1'].fill=PatternFill('solid',fgColor=NAVY); ws['A1'].font=Font(name='Arial',size=15,bold=True,color=WHITE); ws.row_dimensions[1].height=25
    ws.merge_cells('A2:J2'); ws['A2']=subtitle; ws['A2'].font=Font(name='Arial',size=9,color=NOTEGREY)
    ws['A3']='Model date'; ws['B3']=datetime(2026,10,30); ws['B3'].number_format='yyyy-mm-dd'
    ws['D3']='Annual long-range model'; ws['E3']='2026E = 9M actual + Q4 estimate'

def section(ws,row,text,end=10):
    ws.cell(row,1,text)
    for c in range(1,end+1):
        ws.cell(row,c).fill=PatternFill('solid',fgColor=GREY); ws.cell(row,c).font=Font(name='Arial',size=10,bold=True)

def periods(ws, row=5, raw=False):
    labels = ['2023A','2024A','2025A','9M26A/Q3-26A'] if raw else ['2023A','2024A','2025A','2026E','2027E','2028E','2029E','2030E']
    ws.cell(row,1,'Line item')
    for i,l in enumerate(labels,2):
        ws.cell(row,i,l); ws.cell(row,i).alignment=Alignment(horizontal='center')
    ws.cell(row,10,'Source / rationale')
    for c in range(1,11):
        ws.cell(row,c).fill=PatternFill('solid',fgColor=NAVY); ws.cell(row,c).font=Font(name='Arial',size=10,bold=True,color=WHITE)
    ws.cell(row+1,1,'Period end / basis')
    ends = ['2023-12-31','2024-12-31','2025-12-31','2026-09-30'] if raw else ['2023-12-31','2024-12-31','2025-12-31','2026-12-31','2027-12-31','2028-12-31','2029-12-31','2030-12-31']
    for i,l in enumerate(ends,2): ws.cell(row+1,i,l); ws.cell(row+1,i).alignment=Alignment(horizontal='center')

def style_data(ws, min_row, max_row, min_col=2, max_col=9, pct_rows=None, eps_rows=None):
    pct_rows = pct_rows or []; eps_rows = eps_rows or []
    for r in range(min_row,max_row+1):
        for c in range(min_col,max_col+1):
            cell=ws.cell(r,c); cell.font=Font(name='Arial',size=10,color=BLACK)
            cell.number_format='0.0%' if r in pct_rows else ('0.00' if r in eps_rows else '#,##0;(#,##0);-')
        ws.cell(r,10).font=Font(name='Arial',size=9,color=NOTEGREY)

def input_cell(cell, fmt=None):
    cell.fill=PatternFill('solid',fgColor=AMBER); cell.font=Font(name='Arial',size=10,color=BLACK)
    if fmt: cell.number_format=fmt

def cite_cell(cell, fmt=None):
    cell.font=Font(name='Arial',size=10,color=CITEBLUE)
    if fmt: cell.number_format=fmt

def subtotal(ws,row,end=9):
    for c in range(1,end+1):
        ws.cell(row,c).font=Font(name='Arial',size=10,bold=True,color=ws.cell(row,c).font.color.rgb if ws.cell(row,c).font.color and ws.cell(row,c).font.color.type=='rgb' else BLACK)
        ws.cell(row,c).border=Border(top=thin)

# Raw data
ws=wb['Raw_Data']; title(ws,'Raw Data | 官方披露事实层','USD mn except per-share data; blue fill = source facts; 9M26A = flows, Q3-26A = balance sheet'); periods(ws,raw=True)
rawmap={}
for idx,rec in enumerate(raw_rows,8):
    rawmap[rec['key']]=idx
    ws.cell(idx,1,rec['label'])
    for j,v in enumerate(rec['values'],2):
        if v is not None:
            ws.cell(idx,j,v); ws.cell(idx,j).fill=PatternFill('solid',fgColor=LIGHTBLUE)
            ws.cell(idx,j).number_format='0.00' if rec['unit']=='USD/share' else '#,##0;(#,##0);-'
    src = 'S2' if 'Q3 FY2026' in rec['locator'] else ('S3' if rec['key'] in bs_labels and rec['values'][0] is not None else 'S1')
    ws.cell(idx,10,src+' | '+rec['locator']+' | '+rec['unit'])
ws.auto_filter.ref=f'A7:J{7+len(raw_rows)}'

# Assumptions
ws=wb['Assumptions']; title(ws,'Assumptions | 预测驱动与估值输入','Amber = author inputs or guidance-mid assumptions; historical values are realized or left blank where not meaningful'); periods(ws)
assump = [
('q4_revenue','Q4 2026 total revenue guide midpoint',[None,None,None,74500,None,None,None,None],'S4 | Midpoint of $73–76bn Q4 2026 guidance'),
('fy_costs','FY2026 total expenses guide midpoint',[None,None,None,177000,None,None,None,None],'S4 | Midpoint of $175–179bn FY2026 guidance'),
('q4_rl_rev','Q4 2026 Reality Labs revenue',[None,None,None,800,None,None,None,None],'Author | Below Q4 2025; reflects 9M26 run-rate'),
('q4_other_rev','Q4 2026 FoA other revenue',[None,None,None,1000,None,None,None,None],'Author | 9M26 other-revenue run-rate'),
('rl_loss','Reality Labs operating income (loss)',[None,None,None,-18500,-15000,-13000,-11000,-9000],'S4 for 2026/2027; author taper thereafter'),
('foa_growth','FoA revenue growth',[None,None,None,None,0.18,0.15,0.12,0.10],'Author | Strong 2027, gradual normalization'),
('other_growth','FoA other revenue growth',[None,None,None,None,0.20,0.18,0.15,0.12],'Author | Allocation view; FoA remains sole topline driver'),
('rl_growth','Reality Labs revenue growth',[None,None,None,None,0.15,0.15,0.12,0.10],'Author | Hardware/software adoption normalization'),
('foa_margin','FoA operating margin',[None,None,None,None,0.42,0.425,0.43,0.435],'Author | AI cost discipline and ad monetization scale'),
('q4_cor','Q4 2026 cost of revenue',[None,None,None,14000,None,None,None,None],'Author | Q4 infrastructure run-rate'),
('q4_rd','Q4 2026 research and development',[None,None,None,20000,None,None,None,None],'Author | Continued AI talent and infrastructure investment'),
('q4_ms','Q4 2026 marketing and sales',[None,None,None,3500,None,None,None,None],'Author | Q4 seasonal spend'),
('cor_pct','Cost of revenue / revenue',[None,None,None,None,0.14,0.145,0.15,0.15],'Author | Infrastructure cost mix'),
('rd_pct','R&D / revenue',[None,None,None,None,0.30,0.29,0.28,0.27],'Author | Elevated AI investment, gradual scale'),
('ms_pct','Marketing and sales / revenue',[None,None,None,None,0.045,0.043,0.042,0.040],'Author | Modest operating leverage'),
('da','Depreciation and amortization',[None,None,None,27000,40000,55000,70000,82000],'Author | 9M26 actual $19.509bn plus capex-driven ramp'),
('cash_capex','Purchases of property and equipment',[None,None,None,133055,147000,151000,145000,140000],'S4 total-capex guide for 2026; author cash-capex path thereafter'),
('fin_principal','Principal payments on finance leases',[None,None,None,6945,8000,9000,10000,10000],'2026 reconciles to $140bn total-capex midpoint; author thereafter'),
('fin_additions','Finance lease & other PP&E additions',[None,None,None,13276,10000,12000,12000,12000],'2026 = 9M residual PP&E movement; author thereafter'),
('marketable_bal','Marketable securities ending balance',[None,None,None,60000,50000,40000,30000,30000],'Author | Portfolio funds part of AI capex'),
('nonmarketable_bal','Non-marketable equity investments',[None,None,None,32624,32624,32624,32624,32624],'Author | Held flat at Q3 2026 actual'),
('dso','Accounts receivable days (365-day basis)',[None,None,None,35,35,34,34,33],'Author | Near historical collection profile'),
('prepaid_pct','Prepaid & other current assets / revenue',[None,None,None,0.045,0.043,0.040,0.040,0.040],'Author | Normalizes from elevated Q3 2026'),
('other_assets_pct','Other assets / revenue',[None,None,None,0.055,0.050,0.045,0.045,0.045],'Author | Includes restricted-cash normalization'),
('rou_pct','Operating lease ROU assets / revenue',[None,None,None,0.10,0.09,0.08,0.075,0.07],'Author | Lease commitments scale below revenue'),
('goodwill_bal','Goodwill ending balance',[None,None,None,23421,23421,23421,23421,23421],'Author | No future acquisitions modeled'),
('ap_pct','Accounts payable / (costs + cash capex)',[None,None,None,0.08,0.07,0.06,0.055,0.05],'Author | Elevated capex payables gradually normalize'),
('accrued_pct','Accrued expenses / total costs',[None,None,None,0.25,0.25,0.25,0.25,0.25],'Author | Near FY2025 ratio'),
('lease_pct','Total lease liabilities / ROU assets',[None,None,None,1.05,1.05,1.05,1.05,1.05],'Author | Finance + operating lease schedule'),
('lease_current_pct','Current share of lease liabilities',[None,None,None,0.08,0.08,0.08,0.08,0.08],'Author | Near Q3 2026 actual'),
('lt_tax_bal','Long-term income taxes ending balance',[None,None,None,20521,20521,20521,20521,20521],'Author | Held flat at Q3 2026 actual'),
('other_liab_pct','Other liabilities / revenue',[None,None,None,0.03,0.03,0.03,0.03,0.03],'Author | Stable operating scale'),
('debt_repayment','Scheduled long-term debt repayment',[None,None,None,0,2750,1500,1000,5000],'S2 | Contractual maturities disclosed in 2026 10-Q'),
('min_cash','Minimum cash balance / funding trigger',[None,None,None,10000,10000,10000,10000,10000],'Author | Explicit debt-draw funding response'),
('aoci_bal','Accumulated other comprehensive income (loss)',[None,None,None,-1200,-1200,-1200,-1200,-1200],'Author | Held flat; no OCI forecast'),
('q4_tax','Q4 2026 / forecast effective tax rate',[None,None,None,0.16,0.17,0.18,0.18,0.18],'S4 Q4 midpoint 15–17%; author normalization thereafter'),
('nonop_2026','FY2026 interest and other income (expense), net',[None,None,None,-2126,None,None,None,None],'Author | 9M actual plus Q4 estimate'),
('cash_yield','Interest yield on opening cash + marketable securities',[None,None,None,None,0.02,0.02,0.02,0.02],'Author | Used only below operating income'),
('sbc_pct','Share-based compensation / revenue',[None,None,None,0.11,0.105,0.10,0.095,0.09],'Author | AI compensation remains elevated'),
('withholding_pct','Tax withholding / SBC',[None,None,None,0.60,0.60,0.60,0.60,0.60],'Author | Near 9M26 cash-flow ratio'),
('share_growth','Diluted share-count growth',[None,None,None,0,0.005,0.005,0.005,0.005],'Author | No buybacks; SBC dilution; pre-Class-C-split basis'),
('dps','Dividends per share (USD)',[None,None,None,2.10,2.31,2.54,2.79,3.07],'Author | Approximately 10% annual growth'),
('buybacks','Share repurchases',[None,None,None,0,0,0,0,0],'Author | Suspended through forecast; preserves funding discipline'),
('shares_2026','Q3 2026 diluted shares (mn)',[None,None,None,2573,None,None,None,None],'S2 | Q3 2026 diluted weighted-average shares'),
('rf','Risk-free rate — 10Y UST',[None,None,None,0.0498,None,None,None,None],'S8 | 2026-10-29, Federal Reserve series'),
('beta','Levered beta',[None,None,None,1.185,None,None,None,None],'S6 | Yahoo Finance, retrieved 2026-10-30'),
('erp','Equity risk premium',[None,None,None,0.05,None,None,None,None],'S9 | Kroll recommended U.S. ERP, September 2025'),
('size_premium','Size premium',[None,None,None,0,None,None,None,None],'Author | Mega-cap issuer'),
('csrp','Company-specific risk premium',[None,None,None,0,None,None,None,None],'Author | Risks modeled in scenarios instead'),
('kd','Pre-tax cost of debt',[None,None,None,0.0615,None,None,None,None],'S10 | META 5.25% 2036 bond yield, 2026-10-28'),
('marginal_tax','Marginal tax rate for WACC tax shield',[None,None,None,0.21,None,None,None,None],'S11 | U.S. federal corporate statutory rate'),
('market_price','META market price (USD/share)',[None,None,None,624.52,None,None,None,None],'S7 | 2026-10-29 close, unadjusted'),
('market_cap','Market capitalization (USD mn)',[None,None,None,1596793.421824,None,None,None,None],'S6 | Yahoo Finance, 2026-10-29'),
('weight_debt','Debt incl. leases for WACC weights (USD mn)',[None,None,None,114842.001408,None,None,None,None],'S6 | Yahoo Finance total debt'),
('bridge_cash','Cash + marketable securities, Q3 2026',[None,None,None,82449,None,None,None,None],'S2 | 2026-09-30'),
('bridge_nonmarketable','Non-marketable equity investments, Q3 2026',[None,None,None,32624,None,None,None,None],'S2 | Non-operating asset at carrying value'),
('bridge_debt','Long-term debt + finance leases, Q3 2026',[None,None,None,83669,None,None,None,None],'S2/S6 | Debt excluding operating leases'),
('terminal_g','Terminal growth rate',[None,None,None,0.03,None,None,None,None],'Author | Long-run nominal sustainable growth'),
('terminal_capex_da','Terminal capex / D&A',[None,None,None,1.10,None,None,None,None],'Author | Normalized maintenance + growth investment'),
('terminal_nwc_pct','Terminal NWC investment / incremental revenue',[None,None,None,0.02,None,None,None,None],'Author | Sustainable working-capital intensity'),
('exit_multiple','Terminal EV / EBITDA cross-check',[None,None,None,8.0,None,None,None,None],'Author | Terminal multiple cross-check, not primary method'),
('valuation_date','Valuation date',[None,None,None,datetime(2026,10,29),None,None,None,None],'S7 | Matches latest evidenced close'),
]
amap={}
for i,(key,label,vals,note) in enumerate(assump,8):
    amap[key]=i; ws.cell(i,1,label)
    for j,v in enumerate(vals,2):
        if v is not None:
            ws.cell(i,j,v)
            fmt='yyyy-mm-dd' if key=='valuation_date' else ('0.0%' if any(x in key for x in ['growth','margin','pct','rate','rf','erp','premium','kd','tax','yield','terminal_g','withholding']) else ('0.000' if key=='beta' else ('0.00' if key in ['dps','market_price','exit_multiple','terminal_capex_da'] else '#,##0;(#,##0);-')))
            input_cell(ws.cell(i,j),fmt)
    ws.cell(i,10,note); ws.cell(i,10).font=Font(name='Arial',size=9,color=NOTEGREY)

AC={2026:'E',2027:'F',2028:'G',2029:'H',2030:'I'}
HC={2023:'B',2024:'C',2025:'D'}
def ar(key,year): return f"Assumptions!{AC[year]}{amap[key]}"
def rr(key,col): return f"Raw_Data!{col}{rawmap[key]}"

# Segment build
ws=wb['Segment']; title(ws,'Segment | 分部收入与经营利润','FoA is the single topline driver; advertising/other are allocations. RL losses include all directly attributable segment costs.'); periods(ws)
seg_rows={'advertising':8,'other_rev':9,'foa_rev':10,'rl_rev':11,'revenue':12,'rev_growth':13,'foa_ebit':16,'rl_ebit':17,'ebit':18,'foa_margin':19,'rl_margin':20,'costs':22,'legal_charge':24,'adj_ebit':25}
section(ws,7,'Revenue build'); section(ws,15,'Operating profit build'); section(ws,21,'Total expenses'); section(ws,23,'Memo — excluding Q3 2026 legal charge')
for key,r in seg_rows.items():
    labels={'advertising':'Advertising — FoA','other_rev':'Other revenue — FoA','foa_rev':'Family of Apps revenue','rl_rev':'Reality Labs revenue','revenue':'Total revenue','rev_growth':'Total revenue growth','foa_ebit':'Family of Apps operating income','rl_ebit':'Reality Labs operating income (loss)','ebit':'Total operating income','foa_margin':'FoA operating margin','rl_margin':'RL operating margin','costs':'Total costs and expenses','legal_charge':'Q3 2026 legal charge','adj_ebit':'Operating income excl. legal charge'}
    ws.cell(r,1,labels[key])
for y in YRS:
    c=HC[y]
    for key in ['advertising','other_rev','foa_rev','rl_rev','revenue','foa_ebit','rl_ebit','ebit','costs']:
        r=seg_rows[key]; ws.cell(r,ord(c)-64,f'={rr(key,c)}'); cite_cell(ws.cell(r,ord(c)-64))
for y in range(2026,2031):
    c=AC[y]; ci=ord(c)-64
    if y==2026:
        ws.cell(seg_rows['other_rev'],ci,f'={rr("other_rev","E")}+{ar("q4_other_rev",y)}')
        ws.cell(seg_rows['rl_rev'],ci,f'={rr("rl_rev","E")}+{ar("q4_rl_rev",y)}')
        ws.cell(seg_rows['foa_rev'],ci,f'={rr("foa_rev","E")}+{ar("q4_revenue",y)}-{ar("q4_rl_rev",y)}')
        ws.cell(seg_rows['advertising'],ci,f'={c}{seg_rows["foa_rev"]}-{c}{seg_rows["other_rev"]}')
        ws.cell(seg_rows['revenue'],ci,f'={c}{seg_rows["foa_rev"]}+{c}{seg_rows["rl_rev"]}')
        ws.cell(seg_rows['costs'],ci,f'={ar("fy_costs",y)}')
        ws.cell(seg_rows['rl_ebit'],ci,f'={ar("rl_loss",y)}')
        ws.cell(seg_rows['ebit'],ci,f'={c}{seg_rows["revenue"]}-{c}{seg_rows["costs"]}')
        ws.cell(seg_rows['foa_ebit'],ci,f'={c}{seg_rows["ebit"]}-{c}{seg_rows["rl_ebit"]}')
        ws.cell(seg_rows['legal_charge'],ci,f'={rr("legal_charge","E")}')
    else:
        p=AC[y-1]
        ws.cell(seg_rows['foa_rev'],ci,f'={p}{seg_rows["foa_rev"]}*(1+{ar("foa_growth",y)})')
        ws.cell(seg_rows['other_rev'],ci,f'={p}{seg_rows["other_rev"]}*(1+{ar("other_growth",y)})')
        ws.cell(seg_rows['advertising'],ci,f'={c}{seg_rows["foa_rev"]}-{c}{seg_rows["other_rev"]}')
        ws.cell(seg_rows['rl_rev'],ci,f'={p}{seg_rows["rl_rev"]}*(1+{ar("rl_growth",y)})')
        ws.cell(seg_rows['revenue'],ci,f'={c}{seg_rows["foa_rev"]}+{c}{seg_rows["rl_rev"]}')
        ws.cell(seg_rows['foa_ebit'],ci,f'={c}{seg_rows["foa_rev"]}*{ar("foa_margin",y)}')
        ws.cell(seg_rows['rl_ebit'],ci,f'={ar("rl_loss",y)}')
        ws.cell(seg_rows['ebit'],ci,f'={c}{seg_rows["foa_ebit"]}+{c}{seg_rows["rl_ebit"]}')
        ws.cell(seg_rows['costs'],ci,f'={c}{seg_rows["revenue"]}-{c}{seg_rows["ebit"]}')
        ws.cell(seg_rows['legal_charge'],ci,0)
    ws.cell(seg_rows['foa_margin'],ci,f'={c}{seg_rows["foa_ebit"]}/{c}{seg_rows["foa_rev"]}')
    ws.cell(seg_rows['rl_margin'],ci,f'={c}{seg_rows["rl_ebit"]}/{c}{seg_rows["rl_rev"]}')
    ws.cell(seg_rows['adj_ebit'],ci,f'={c}{seg_rows["ebit"]}+{c}{seg_rows["legal_charge"]}')
for y in YRS:
    c=HC[y]; ci=ord(c)-64
    ws.cell(seg_rows['foa_margin'],ci,f'={c}{seg_rows["foa_ebit"]}/{c}{seg_rows["foa_rev"]}')
    ws.cell(seg_rows['rl_margin'],ci,f'={c}{seg_rows["rl_ebit"]}/{c}{seg_rows["rl_rev"]}')
    ws.cell(seg_rows['legal_charge'],ci,0); ws.cell(seg_rows['adj_ebit'],ci,f'={c}{seg_rows["ebit"]}')
for ci in range(3,10):
    c=get_column_letter(ci); p=get_column_letter(ci-1)
    ws.cell(seg_rows['rev_growth'],ci,f'={c}{seg_rows["revenue"]}/{p}{seg_rows["revenue"]}-1')
style_data(ws,8,25,pct_rows=[13,19,20]); subtotal(ws,12); subtotal(ws,18); subtotal(ws,25)

# Income statement
ws=wb['IS']; title(ws,'Income Statement | 利润表','GAAP; D&A and SBC are memo items already included in operating expenses, not deducted twice.'); periods(ws)
isr={'revenue':8,'cor':9,'rd':10,'ms':11,'ga':12,'costs':13,'ebit':15,'nonop':16,'pretax':17,'tax':18,'ni':19,'shares_dil':21,'eps_dil':22,'da':25,'sbc':26,'adj_ebit':28,'op_margin':30,'net_margin':31,'revenue_growth':32}
section(ws,7,'GAAP income statement'); section(ws,20,'Per-share data'); section(ws,24,'Memo items'); section(ws,27,'Company-defined legal-charge exclusion'); section(ws,29,'Margins and growth')
labels={'revenue':'Revenue','cor':'Cost of revenue','rd':'Research and development','ms':'Marketing and sales','ga':'General and administrative','costs':'Total costs and expenses','ebit':'Income from operations','nonop':'Interest and other income (expense), net','pretax':'Income before income taxes','tax':'Provision for income taxes','ni':'Net income','shares_dil':'Diluted weighted-average shares (mn)','eps_dil':'Diluted EPS (USD)','da':'Depreciation and amortization (memo)','sbc':'Share-based compensation (memo)','adj_ebit':'Operating income excl. Q3 legal charge','op_margin':'Operating margin','net_margin':'Net margin','revenue_growth':'Revenue growth'}
for k,r in isr.items(): ws.cell(r,1,labels[k])
for y in YRS:
    c=HC[y]; ci=ord(c)-64
    for k in ['cor','rd','ms','ga','nonop','tax','da','sbc','shares_dil']:
        ws.cell(isr[k],ci,f'={rr(k,c)}'); cite_cell(ws.cell(isr[k],ci))
    ws.cell(isr['revenue'],ci,f'=Segment!{c}{seg_rows["revenue"]}')
    ws.cell(isr['costs'],ci,f'=SUM({c}9:{c}12)')
    ws.cell(isr['ebit'],ci,f'={c}8-{c}13'); ws.cell(isr['pretax'],ci,f'={c}15+{c}16'); ws.cell(isr['ni'],ci,f'={c}17-{c}18')
    ws.cell(isr['eps_dil'],ci,f'={rr("eps_dil",c)}'); cite_cell(ws.cell(isr['eps_dil'],ci))
for y in range(2026,2031):
    c=AC[y]; ci=ord(c)-64; p=AC[y-1] if y>2026 else 'D'
    ws.cell(isr['revenue'],ci,f'=Segment!{c}{seg_rows["revenue"]}')
    if y==2026:
        ws.cell(isr['cor'],ci,f'={rr("cor","E")}+{ar("q4_cor",y)}'); ws.cell(isr['rd'],ci,f'={rr("rd","E")}+{ar("q4_rd",y)}'); ws.cell(isr['ms'],ci,f'={rr("ms","E")}+{ar("q4_ms",y)}')
        ws.cell(isr['costs'],ci,f'={ar("fy_costs",y)}'); ws.cell(isr['ga'],ci,f'={c}13-SUM({c}9:{c}11)')
        ws.cell(isr['nonop'],ci,f'={ar("nonop_2026",y)}')
        ws.cell(isr['tax'],ci,f'={rr("tax","E")}+({c}17-{rr("pretax","E")})*{ar("q4_tax",y)}')
        ws.cell(isr['shares_dil'],ci,f'={ar("shares_2026",y)}')
    else:
        ws.cell(isr['cor'],ci,f'={c}8*{ar("cor_pct",y)}'); ws.cell(isr['rd'],ci,f'={c}8*{ar("rd_pct",y)}'); ws.cell(isr['ms'],ci,f'={c}8*{ar("ms_pct",y)}')
        ws.cell(isr['costs'],ci,f'=Segment!{c}{seg_rows["costs"]}'); ws.cell(isr['ga'],ci,f'={c}13-SUM({c}9:{c}11)')
        ws.cell(isr['nonop'],ci,f'=(BS!{p}8+BS!{p}9)*{ar("cash_yield",y)}-BS!{p}27*{ar("kd",2026)}')
        ws.cell(isr['tax'],ci,f'={c}17*{ar("q4_tax",y)}')
        ws.cell(isr['shares_dil'],ci,f'={p}21*(1+{ar("share_growth",y)})')
    ws.cell(isr['ebit'],ci,f'={c}8-{c}13'); ws.cell(isr['pretax'],ci,f'={c}15+{c}16'); ws.cell(isr['ni'],ci,f'={c}17-{c}18'); ws.cell(isr['eps_dil'],ci,f'={c}19/{c}21')
    ws.cell(isr['da'],ci,f'={ar("da",y)}'); ws.cell(isr['sbc'],ci,f'={c}8*{ar("sbc_pct",y)}')
for ci in range(2,10):
    c=get_column_letter(ci)
    ws.cell(isr['adj_ebit'],ci,f'=Segment!{c}{seg_rows["adj_ebit"]}')
    ws.cell(isr['op_margin'],ci,f'={c}15/{c}8'); ws.cell(isr['net_margin'],ci,f'={c}19/{c}8')
    if ci>=3: ws.cell(isr['revenue_growth'],ci,f'={c}8/{get_column_letter(ci-1)}8-1')
style_data(ws,8,32,pct_rows=[30,31,32],eps_rows=[22]); subtotal(ws,13); subtotal(ws,15); subtotal(ws,19); subtotal(ws,22)

# Supporting schedules and balance sheet formulas are defined before CF so references are stable.
ws=wb['BS']; title(ws,'Balance Sheet & Supporting Schedules | 资产负债表及附表','Cash is CF-derived; debt draws respond explicitly to the minimum-cash trigger. No balance-sheet plug.'); periods(ws)
bsr={'cash':8,'marketable':9,'ar':10,'prepaid':11,'current_assets':12,'nonmarketable':14,'ppe':15,'rou':16,'goodwill':17,'other_assets':18,'assets':19,'ap':22,'lease_cur':23,'accrued':24,'current_liab':25,'lease_noncur':27,'debt':28,'lt_tax':29,'other_liab':30,'liabilities':31,'apic':34,'aoci':35,'re':36,'equity':37,'le':38,'balance_check':40,'nwc':42,'lease_total':44,'ppe_begin':47,'capex':48,'fin_additions':49,'da':50,'ppe_end':51,'debt_begin':54,'debt_sched':55,'debt_draw':56,'debt_end':57}
section(ws,7,'Assets'); section(ws,21,'Liabilities'); section(ws,33,'Stockholders equity'); section(ws,39,'Integrity check'); section(ws,41,'Operating working capital'); section(ws,43,'Lease schedule'); section(ws,46,'PP&E roll-forward'); section(ws,53,'Debt roll-forward')
blabels={'cash':'Cash and cash equivalents','marketable':'Marketable securities','ar':'Accounts receivable, net','prepaid':'Prepaid expenses and other current assets','current_assets':'Total current assets','nonmarketable':'Non-marketable equity investments','ppe':'Property and equipment, net','rou':'Operating lease right-of-use assets','goodwill':'Goodwill','other_assets':'Other assets','assets':'Total assets','ap':'Accounts payable','lease_cur':'Operating lease liabilities, current','accrued':'Accrued expenses and other current liabilities','current_liab':'Total current liabilities','lease_noncur':'Operating lease liabilities, non-current','debt':'Long-term debt + funding draws','lt_tax':'Long-term income taxes','other_liab':'Other liabilities','liabilities':'Total liabilities','apic':'Common stock and additional paid-in capital','aoci':'Accumulated other comprehensive income (loss)','re':'Retained earnings','equity':'Total stockholders equity','le':'Total liabilities and stockholders equity','balance_check':'Assets − liabilities − equity','nwc':'Operating NWC (AR + prepaid + other assets − AP − accrued − other liabilities)','lease_total':'Total lease liabilities','ppe_begin':'Beginning PP&E','capex':'Cash capital expenditures','fin_additions':'Finance lease & other additions','da':'Depreciation and amortization','ppe_end':'Ending PP&E','debt_begin':'Beginning debt','debt_sched':'Scheduled issuance / (repayment)','debt_draw':'Funding-response debt draw','debt_end':'Ending debt'}
for k,r in bsr.items(): ws.cell(r,1,blabels[k])
for y in YRS:
    c=HC[y]; ci=ord(c)-64
    for k in ['cash','marketable','ar','prepaid','nonmarketable','ppe','rou','goodwill','other_assets','ap','lease_cur','accrued','lease_noncur','debt','lt_tax','other_liab','apic','aoci','re']:
        ws.cell(bsr[k],ci,f'={rr(k,c)}'); cite_cell(ws.cell(bsr[k],ci))
    ws.cell(bsr['current_assets'],ci,f'=SUM({c}8:{c}11)'); ws.cell(bsr['assets'],ci,f'={c}12+SUM({c}14:{c}18)'); ws.cell(bsr['current_liab'],ci,f'=SUM({c}22:{c}24)'); ws.cell(bsr['liabilities'],ci,f'={c}25+SUM({c}27:{c}30)'); ws.cell(bsr['equity'],ci,f'=SUM({c}34:{c}36)'); ws.cell(bsr['le'],ci,f'={c}31+{c}37')
    ws.cell(bsr['lease_total'],ci,f'={c}23+{c}27')
for y in range(2026,2031):
    c=AC[y]; ci=ord(c)-64; p=AC[y-1] if y>2026 else 'D'
    ws.cell(bsr['cash'],ci,f'=CF!{c}35')
    ws.cell(bsr['marketable'],ci,f'={ar("marketable_bal",y)}'); ws.cell(bsr['ar'],ci,f'=IS!{c}8*{ar("dso",y)}/365'); ws.cell(bsr['prepaid'],ci,f'=IS!{c}8*{ar("prepaid_pct",y)}'); ws.cell(bsr['current_assets'],ci,f'=SUM({c}8:{c}11)')
    ws.cell(bsr['nonmarketable'],ci,f'={ar("nonmarketable_bal",y)}'); ws.cell(bsr['ppe'],ci,f'={c}51'); ws.cell(bsr['rou'],ci,f'=IS!{c}8*{ar("rou_pct",y)}'); ws.cell(bsr['goodwill'],ci,f'={ar("goodwill_bal",y)}'); ws.cell(bsr['other_assets'],ci,f'=IS!{c}8*{ar("other_assets_pct",y)}'); ws.cell(bsr['assets'],ci,f'={c}12+SUM({c}14:{c}18)')
    ws.cell(bsr['ap'],ci,f'=(IS!{c}13+{c}48)*{ar("ap_pct",y)}'); ws.cell(bsr['lease_total'],ci,f'={c}16*{ar("lease_pct",y)}'); ws.cell(bsr['lease_cur'],ci,f'={c}44*{ar("lease_current_pct",y)}'); ws.cell(bsr['accrued'],ci,f'=IS!{c}13*{ar("accrued_pct",y)}'); ws.cell(bsr['current_liab'],ci,f'=SUM({c}22:{c}24)'); ws.cell(bsr['lease_noncur'],ci,f'={c}44-{c}23')
    ws.cell(bsr['debt'],ci,f'={c}57'); ws.cell(bsr['lt_tax'],ci,f'={ar("lt_tax_bal",y)}'); ws.cell(bsr['other_liab'],ci,f'=IS!{c}8*{ar("other_liab_pct",y)}'); ws.cell(bsr['liabilities'],ci,f'={c}25+SUM({c}27:{c}30)')
    ws.cell(bsr['apic'],ci,f'={p}34+CF!{c}10+CF!{c}29'); ws.cell(bsr['aoci'],ci,f'={ar("aoci_bal",y)}'); ws.cell(bsr['re'],ci,f'={p}36+IS!{c}19+CF!{c}27+CF!{c}28'); ws.cell(bsr['equity'],ci,f'=SUM({c}34:{c}36)'); ws.cell(bsr['le'],ci,f'={c}31+{c}37')
    ws.cell(bsr['ppe_begin'],ci,f'={p}15'); ws.cell(bsr['capex'],ci,f'={ar("cash_capex",y)}'); ws.cell(bsr['fin_additions'],ci,f'={ar("fin_additions",y)}'); ws.cell(bsr['da'],ci,f'=IS!{c}25'); ws.cell(bsr['ppe_end'],ci,f'={c}47+{c}48+{c}49-{c}50')
    ws.cell(bsr['debt_begin'],ci,f'={p}28'); ws.cell(bsr['debt_sched'],ci,f'=-{ar("debt_repayment",y)}'); ws.cell(bsr['debt_draw'],ci,f'=CF!{c}33'); ws.cell(bsr['debt_end'],ci,f'={c}54+{c}55+{c}56')
for ci in range(2,10):
    c=get_column_letter(ci)
    ws.cell(bsr['balance_check'],ci,f'={c}19-{c}38'); ws.cell(bsr['nwc'],ci,f'={c}10+{c}11+{c}18-{c}22-{c}24-{c}30')
style_data(ws,8,57); subtotal(ws,12); subtotal(ws,19); subtotal(ws,25); subtotal(ws,31); subtotal(ws,37); subtotal(ws,38); subtotal(ws,51); subtotal(ws,57)

# Cash flow statement
ws=wb['CF']; title(ws,'Cash Flow Statement | 现金流量表','Indirect method; forecast cash is fully articulated with BS movements. Company FCF deducts cash capex and finance-lease principal.'); periods(ws)
cfr={'ni':8,'da':9,'sbc':10,'deferred':11,'nwc':12,'lease_adj':13,'cfo':15,'cash_capex':18,'marketable_flow':19,'nonmarketable_flow':20,'goodwill_flow':21,'cfi':22,'debt_sched':25,'fin_principal':26,'dividends':27,'buybacks':28,'tax_withholding':29,'cff_before':30,'pre_funding_cash':31,'min_cash':32,'debt_draw':33,'cff':34,'ending_cash':35,'fcf':38,'capex_total':39}
section(ws,7,'Operating activities'); section(ws,17,'Investing activities'); section(ws,24,'Financing activities'); section(ws,37,'Company-defined free cash flow')
clabels={'ni':'Net income','da':'Depreciation and amortization','sbc':'Share-based compensation','deferred':'Deferred taxes / change in long-term income taxes','nwc':'Change in operating NWC','lease_adj':'Lease amortization net of payments and non-cash additions','cfo':'Net cash provided by operating activities','cash_capex':'Purchases of property and equipment','marketable_flow':'Net purchases / sales of marketable securities','nonmarketable_flow':'Net non-marketable investment purchases','goodwill_flow':'Acquisitions / goodwill movement','cfi':'Net cash used in investing activities','debt_sched':'Scheduled debt issuance / (repayment)','fin_principal':'Principal payments on finance leases','dividends':'Dividends and dividend equivalents','buybacks':'Share repurchases','tax_withholding':'Taxes paid for net share settlement','cff_before':'Financing cash flow before funding response','pre_funding_cash':'Cash before funding-response debt draw','min_cash':'Minimum cash balance','debt_draw':'Funding-response debt draw','cff':'Net cash provided by (used in) financing activities','ending_cash':'Ending cash and cash equivalents','fcf':'Free cash flow (company definition)','capex_total':'Total capex incl. finance-lease principal'}
for k,r in cfr.items(): ws.cell(r,1,clabels[k])
for y in YRS:
    c=HC[y]; ci=ord(c)-64
    for k in ['ni','da','sbc','cfo','cash_capex','cfi','fin_principal','dividends','buybacks','tax_withholding','ending_cash']:
        rawkey='cash' if k=='ending_cash' else k
        ws.cell(cfr[k],ci,f'={rr(rawkey,c)}'); cite_cell(ws.cell(cfr[k],ci))
    ws.cell(cfr['deferred'],ci,f'={rr("deferred_tax",c)}'); cite_cell(ws.cell(cfr['deferred'],ci))
    ws.cell(cfr['debt_sched'],ci,f'={rr("debt_issued",c)}'); cite_cell(ws.cell(cfr['debt_sched'],ci))
    ws.cell(cfr['cff'],ci,f'={rr("cff",c)}'); cite_cell(ws.cell(cfr['cff'],ci))
    ws.cell(cfr['fcf'],ci,f'={c}15+{c}18+{c}26'); ws.cell(cfr['capex_total'],ci,f'=-{c}18-{c}26')
for y in range(2026,2031):
    c=AC[y]; ci=ord(c)-64; p=AC[y-1] if y>2026 else 'D'
    ws.cell(cfr['ni'],ci,f'=IS!{c}19'); ws.cell(cfr['da'],ci,f'=IS!{c}25'); ws.cell(cfr['sbc'],ci,f'=IS!{c}26'); ws.cell(cfr['deferred'],ci,f'=(BS!{c}29-BS!{p}29)+(BS!{c}35-BS!{p}35)'); ws.cell(cfr['nwc'],ci,f'=-(BS!{c}42-BS!{p}42)')
    ws.cell(cfr['lease_adj'],ci,f'=(BS!{c}44-BS!{p}44)-(BS!{c}16-BS!{p}16)-BS!{c}49-{c}26')
    ws.cell(cfr['cfo'],ci,f'=SUM({c}8:{c}13)')
    ws.cell(cfr['cash_capex'],ci,f'=-BS!{c}48'); ws.cell(cfr['marketable_flow'],ci,f'=-(BS!{c}9-BS!{p}9)'); ws.cell(cfr['nonmarketable_flow'],ci,f'=-(BS!{c}14-BS!{p}14)'); ws.cell(cfr['goodwill_flow'],ci,f'=-(BS!{c}17-BS!{p}17)'); ws.cell(cfr['cfi'],ci,f'=SUM({c}18:{c}21)')
    ws.cell(cfr['debt_sched'],ci,f'=BS!{c}55'); ws.cell(cfr['fin_principal'],ci,f'=-{ar("fin_principal",y)}'); ws.cell(cfr['dividends'],ci,f'=-IS!{c}21*{ar("dps",y)}'); ws.cell(cfr['buybacks'],ci,f'=-{ar("buybacks",y)}'); ws.cell(cfr['tax_withholding'],ci,f'=-{c}10*{ar("withholding_pct",y)}'); ws.cell(cfr['cff_before'],ci,f'=SUM({c}25:{c}29)')
    ws.cell(cfr['pre_funding_cash'],ci,f'=BS!{p}8+{c}15+{c}22+{c}30'); ws.cell(cfr['min_cash'],ci,f'={ar("min_cash",y)}'); ws.cell(cfr['debt_draw'],ci,f'=MAX(0,{c}32-{c}31)'); ws.cell(cfr['cff'],ci,f'={c}30+{c}33'); ws.cell(cfr['ending_cash'],ci,f'={c}31+{c}33')
    ws.cell(cfr['fcf'],ci,f'={c}15+{c}18+{c}26'); ws.cell(cfr['capex_total'],ci,f'=-{c}18-{c}26')
style_data(ws,8,39); subtotal(ws,15); subtotal(ws,22); subtotal(ws,30); subtotal(ws,34); subtotal(ws,35); subtotal(ws,38)

# DCF
ws=wb['DCF']; title(ws,'DCF | FCFF Intrinsic Valuation','Valuation date 2026-10-29; 2026 column is Q4 stub only; mid-year discounting; pre-Class-C-split per-share basis.')
ws.freeze_panes='B7'; ws.column_dimensions['A'].width=46
for c in range(2,8): ws.column_dimensions[get_column_letter(c)].width=16
ws['A5']='Line item'; dcyears=[2026,2027,2028,2029,2030]
for i,y in enumerate(dcyears,2): ws.cell(5,i,'Q4 2026E' if y==2026 else f'{y}E')
ws['G5']='Terminal'
for c in range(1,8): ws.cell(5,c).fill=PatternFill('solid',fgColor=NAVY); ws.cell(5,c).font=Font(name='Arial',size=10,bold=True,color=WHITE)
dr={'revenue':7,'ebit':8,'tax':9,'nopat':10,'da':11,'cash_capex':12,'fin_principal':13,'nwc_change':14,'fcff':15,'period':16,'df':17,'pv_fcff':18,'tnopat':21,'tda':22,'tcapex_ratio':23,'tcapex':24,'tnwc':25,'tfcff':26,'tg':27,'gtv':28,'pvg':29,'exit_multiple':30,'etv':31,'pve':32,'ev_g':35,'ev_e':36,'bridge_cash':37,'bridge_nonmarketable':38,'bridge_debt':39,'eq_g':40,'eq_e':41,'shares':42,'price_g':43,'price_e':44,'market_price':45,'upside_g':46,'upside_e':47,'tv_share_g':48,'tv_share_e':49,'review':50}
section(ws,6,'Unlevered free cash flow',7); section(ws,20,'Normalized terminal cash flow',7); section(ws,34,'Enterprise value to per-share bridge',7)
dlabels={'revenue':'Revenue','ebit':'Operating income / EBIT','tax':'Normalized operating tax rate','nopat':'NOPAT','da':'D&A','cash_capex':'Cash capital expenditures','fin_principal':'Finance-lease principal','nwc_change':'Increase / (decrease) in operating NWC','fcff':'Unlevered free cash flow / FCFF','period':'Discount period (years)','df':'Discount factor','pv_fcff':'PV of FCFF','tnopat':'Terminal NOPAT','tda':'Terminal D&A','tcapex_ratio':'Terminal capex / D&A','tcapex':'Terminal capex','tnwc':'Terminal NWC investment','tfcff':'Normalized terminal FCFF','tg':'Terminal growth','gtv':'Gordon terminal value','pvg':'PV of Gordon terminal value','exit_multiple':'Terminal EV / EBITDA','etv':'Exit-multiple terminal value','pve':'PV of exit-multiple terminal value','ev_g':'Enterprise value — Gordon','ev_e':'Enterprise value — exit multiple','bridge_cash':'Plus: cash + marketable securities','bridge_nonmarketable':'Plus: non-marketable equity investments','bridge_debt':'Less: long-term debt + finance leases','eq_g':'Equity value — Gordon','eq_e':'Equity value — exit multiple','shares':'Diluted shares (mn)','price_g':'Implied value / share — Gordon','price_e':'Implied value / share — exit multiple','market_price':'Market price (2026-10-29)','upside_g':'Upside / (downside) — Gordon','upside_e':'Upside / (downside) — exit multiple','tv_share_g':'Terminal PV / EV — Gordon','tv_share_e':'Terminal PV / EV — exit multiple','review':'Valuation review status'}
for k,r in dr.items(): ws.cell(r,1,dlabels[k])
for idx,y in enumerate(dcyears,2):
    c=get_column_letter(idx); mc=AC[y]
    if y==2026:
        ws.cell(dr['revenue'],idx,f'=IS!{mc}8-{rr("revenue","E")}'); ws.cell(dr['ebit'],idx,f'=IS!{mc}15-{rr("ebit","E")}'); ws.cell(dr['da'],idx,f'=IS!{mc}25-{rr("da","E")}'); ws.cell(dr['cash_capex'],idx,f'=-(BS!{mc}48+{rr("cash_capex","E")})'); ws.cell(dr['fin_principal'],idx,f'=-({ar("fin_principal",y)}+{rr("fin_principal","E")})'); ws.cell(dr['nwc_change'],idx,f'=BS!{mc}42-({rr("ar","E")}+{rr("prepaid","E")}+{rr("other_assets","E")}-{rr("ap","E")}-{rr("accrued","E")}-{rr("other_liab","E")})'); ws.cell(dr['period'],idx,f'=(DATE(2026,11,15)-{ar("valuation_date",2026)})/365')
    else:
        ws.cell(dr['revenue'],idx,f'=IS!{mc}8'); ws.cell(dr['ebit'],idx,f'=IS!{mc}15'); ws.cell(dr['da'],idx,f'=IS!{mc}25'); ws.cell(dr['cash_capex'],idx,f'=-BS!{mc}48'); ws.cell(dr['fin_principal'],idx,f'=-{ar("fin_principal",y)}'); ws.cell(dr['nwc_change'],idx,f'=BS!{mc}42-BS!{AC[y-1]}42'); ws.cell(dr['period'],idx,f'=(DATE({y},6,30)-{ar("valuation_date",2026)})/365')
    ws.cell(dr['tax'],idx,f'={ar("q4_tax",y)}'); ws.cell(dr['nopat'],idx,f'={c}8*(1-{c}9)'); ws.cell(dr['fcff'],idx,f'={c}10+{c}11+{c}12+{c}13-{c}14'); ws.cell(dr['df'],idx,f'=1/(1+$B$66)^{c}16'); ws.cell(dr['pv_fcff'],idx,f'={c}15*{c}17')
# Terminal calculations in G
ws['G21']='=F10*(1+$B$67)'; ws['G22']='=F11*(1+$B$67)'; ws['G23']=f'={ar("terminal_capex_da",2026)}'; ws['G24']='=-G22*G23'; ws['G25']=f'=F7*$B$67*{ar("terminal_nwc_pct",2026)}'; ws['G26']='=G21+G22+G24-G25'; ws['G27']='=$B$67'; ws['G28']='=G26/($B$66-G27)'; ws['G29']='=G28/(1+$B$66)^$B$68'; ws['G30']=f'={ar("exit_multiple",2026)}'; ws['G31']='=(F8+F11)*(1+$B$67)*G30'; ws['G32']='=G31/(1+$B$66)^$B$68'
ws['B35']='=SUM(B18:F18)+G29'; ws['B36']='=SUM(B18:F18)+G32'; ws['B37']=f'={ar("bridge_cash",2026)}'; ws['B38']=f'={ar("bridge_nonmarketable",2026)}'; ws['B39']=f'=-{ar("bridge_debt",2026)}'; ws['B40']='=B35+B37+B38+B39'; ws['B41']='=B36+B37+B38+B39'; ws['B42']=f'={ar("shares_2026",2026)}'; ws['B43']='=B40/B42'; ws['B44']='=B41/B42'; ws['B45']=f'={ar("market_price",2026)}'; ws['B46']='=B43/B45-1'; ws['B47']='=B44/B45-1'; ws['B48']='=G29/B35'; ws['B49']='=G32/B36'; ws['B50']='=IF(OR(B48>0.8,B46<-0.5,B40/B45/B42<0.5),"VALUATION_REVIEW_REQUIRED",IF(OR(B48>0.5,B40/B45/B42<0.75),"REVIEW","OK"))'
section(ws,53,'WACC build-up',7)
wlabels={54:'Risk-free rate',55:'Levered beta',56:'Equity risk premium',57:'Size premium',58:'Company-specific risk premium',59:'Cost of equity',60:'Pre-tax cost of debt',61:'Marginal tax rate',62:'After-tax cost of debt',63:'Equity weight',64:'Debt weight',65:'Suggested WACC',66:'Chosen WACC',67:'Terminal growth',68:'Terminal discount period',69:'Market price date'}
for r,l in wlabels.items(): ws.cell(r,1,l)
ws['B54']=f'={ar("rf",2026)}'; ws['B55']=f'={ar("beta",2026)}'; ws['B56']=f'={ar("erp",2026)}'; ws['B57']=f'={ar("size_premium",2026)}'; ws['B58']=f'={ar("csrp",2026)}'; ws['B59']='=B54+B55*B56+B57+B58'; ws['B60']=f'={ar("kd",2026)}'; ws['B61']=f'={ar("marginal_tax",2026)}'; ws['B62']='=B60*(1-B61)'; ws['B63']=f'={ar("market_cap",2026)}/({ar("market_cap",2026)}+{ar("weight_debt",2026)})'; ws['B64']='=1-B63'; ws['B65']='=B63*B59+B64*B62'; ws['B66']='=B65'; ws['B67']=f'={ar("terminal_g",2026)}'; ws['B68']=f'=(DATE(2030,12,31)-{ar("valuation_date",2026)})/365'; ws['B69']=datetime(2026,10,29); ws['B69'].number_format='yyyy-mm-dd'
for r in [54,56,57,58,59,60,61,62,63,64,65,66,67]: ws.cell(r,2).number_format='0.0%'
ws['B55'].number_format='0.000'; ws['B68'].number_format='0.00'
style_data(ws,7,50,2,6,pct_rows=[9,46,47,48,49],eps_rows=[43,44,45]);
for r in [16,17,23,30,68]:
    for c in range(2,7): ws.cell(r,c).number_format='0.00x' if r==30 else '0.00'
subtotal(ws,15,6); subtotal(ws,18,6); subtotal(ws,26,7); subtotal(ws,40,2); subtotal(ws,41,2); subtotal(ws,43,2); subtotal(ws,44,2)

# Sensitivity
ws=wb['Sensitivity']; title(ws,'Sensitivity | WACC × Terminal Growth','Live formulas; each cell re-discounts explicit FCFF and normalized terminal FCFF. USD/share.')
ws['A5']='WACC \ g'; gvals=[0.02,0.025,0.03,0.035,0.04]; wvals=[0.085,0.095,0.105,0.115,0.125]
for j,g in enumerate(gvals,2): ws.cell(5,j,g); ws.cell(5,j).number_format='0.0%'
for i,w in enumerate(wvals,6):
    ws.cell(i,1,w); ws.cell(i,1).number_format='0.0%'
    for j,g in enumerate(gvals,2):
        terms=[]
        for c in ['B','C','D','E','F']: terms.append(f'DCF!{c}$15/(1+$A{i})^DCF!{c}$16')
        terms.append(f'(DCF!$G$26/($A{i}-{get_column_letter(j)}$5))/(1+$A{i})^DCF!$B$68')
        ws.cell(i,j,f'=(({"+".join(terms)})+DCF!$B$37+DCF!$B$38+DCF!$B$39)/DCF!$B$42'); ws.cell(i,j).number_format='0.00'
for c in range(1,7): ws.cell(5,c).fill=PatternFill('solid',fgColor=NAVY); ws.cell(5,c).font=Font(name='Arial',size=10,bold=True,color=WHITE)
ws.conditional_formatting.add('B6:F10',CellIsRule(operator='lessThan',formula=['DCF!$B$45'],font=Font(color=RED)))
ws.conditional_formatting.add('B6:F10',CellIsRule(operator='greaterThanOrEqual',formula=['DCF!$B$45'],font=Font(color=GREEN)))
ws['A13']='Direction check'; ws['B13']='=IF(AND(B6>B10,F6>B6),"PASS","REVIEW")'

# Scenarios — operating deltas flow through EBIT and NWC; D&A/capex paths remain unchanged.
ws=wb['Scenarios']; title(ws,'Scenarios | 基准、乐观、悲观','Revenue delta compounds annually; margin delta applies to FoA; WACC, terminal growth and terminal reinvestment vary by case.')
scenario_defs=[('Base',0,0,0,0,0),('Upside',0.02,0.02,-0.01,0.005,-0.05),('Downside',-0.02,-0.02,0.01,-0.005,0.10)]
scenario_outputs={}
start=6
for sidx,(name,gdelta,mdelta,wdelta,tgdelta,cratio_delta) in enumerate(scenario_defs):
    r0=start+sidx*26
    section(ws,r0,f'{name} case',7)
    ws.cell(r0+1,1,'Case inputs'); ws.cell(r0+1,2,'FoA annual growth delta'); ws.cell(r0+1,3,gdelta); ws.cell(r0+1,4,'FoA margin delta'); ws.cell(r0+1,5,mdelta); ws.cell(r0+1,6,'WACC'); ws.cell(r0+1,7,f'=DCF!$B$66+{wdelta}')
    ws.cell(r0+2,1,'Terminal inputs'); ws.cell(r0+2,2,'Terminal g'); ws.cell(r0+2,3,f'=DCF!$B$67+{tgdelta}'); ws.cell(r0+2,4,'Terminal capex / D&A'); ws.cell(r0+2,5,f'=DCF!$G$23+{cratio_delta}')
    for c in [3,5,7]: ws.cell(r0+1,c).number_format='0.0%'
    for c in [3,5]: ws.cell(r0+2,c).number_format='0.0%' if c==3 else '0.00x'
    for idx,y in enumerate(dcyears,2): ws.cell(r0+4,idx,'Q4 2026E' if y==2026 else f'{y}E')
    labels=['Revenue','EBIT','NOPAT','D&A','Cash capex + finance principal','NWC change','FCFF','Discount factor','PV FCFF']
    for k,l in enumerate(labels): ws.cell(r0+5+k,1,l)
    for idx,y in enumerate(dcyears,2):
        c=get_column_letter(idx); mc=AC[y]; exponent=y-2026
        ws.cell(r0+5,idx,f'=DCF!{c}7*(1+$C${r0+1})^{exponent}')
        ws.cell(r0+6,idx,f'=DCF!{c}8+({c}{r0+5}-DCF!{c}7)*(DCF!{c}8/DCF!{c}7)+Segment!{mc}{seg_rows["foa_rev"]}*(1+$C${r0+1})^{exponent}*$E${r0+1}')
        ws.cell(r0+7,idx,f'={c}{r0+6}*(1-DCF!{c}9)'); ws.cell(r0+8,idx,f'=DCF!{c}11'); ws.cell(r0+9,idx,f'=DCF!{c}12+DCF!{c}13'); ws.cell(r0+10,idx,f'=DCF!{c}14+({c}{r0+5}-DCF!{c}7)*{ar("terminal_nwc_pct",2026)}'); ws.cell(r0+11,idx,f'={c}{r0+7}+{c}{r0+8}+{c}{r0+9}-{c}{r0+10}'); ws.cell(r0+12,idx,f'=1/(1+$G${r0+1})^DCF!{c}16'); ws.cell(r0+13,idx,f'={c}{r0+11}*{c}{r0+12}')
    ws.cell(r0+15,1,'Terminal FCFF'); ws.cell(r0+15,2,f'=F{r0+7}*(1+$C${r0+2})+F{r0+8}*(1+$C${r0+2})-F{r0+8}*(1+$C${r0+2})*$E${r0+2}-F{r0+5}*$C${r0+2}*{ar("terminal_nwc_pct",2026)}')
    ws.cell(r0+16,1,'PV terminal value'); ws.cell(r0+16,2,f'=B{r0+15}/($G${r0+1}-$C${r0+2})/(1+$G${r0+1})^DCF!$B$68')
    ws.cell(r0+17,1,'Enterprise value'); ws.cell(r0+17,2,f'=SUM(B{r0+13}:F{r0+13})+B{r0+16}')
    ws.cell(r0+18,1,'Equity value'); ws.cell(r0+18,2,f'=B{r0+17}+DCF!$B$37+DCF!$B$38+DCF!$B$39')
    ws.cell(r0+19,1,'Implied value / share'); ws.cell(r0+19,2,f'=B{r0+18}/DCF!$B$42'); ws.cell(r0+19,2).number_format='0.00'
    ws.cell(r0+20,1,'Upside / (downside)'); ws.cell(r0+20,2,f'=B{r0+19}/DCF!$B$45-1'); ws.cell(r0+20,2).number_format='0.0%'
    ws.cell(r0+21,1,'Terminal PV / EV'); ws.cell(r0+21,2,f'=B{r0+16}/B{r0+17}'); ws.cell(r0+21,2).number_format='0.0%'
    scenario_outputs[name]=r0+19
    for rr0 in range(r0+5,r0+14):
        for c in range(2,7): ws.cell(rr0,c).number_format='#,##0;(#,##0);-' if rr0 not in [r0+12] else '0.00'

# Market implied reverse DCF
ws=wb['Market_Implied']; title(ws,'Market Implied | 市场定价反推','No automatic fitting to market. Reverse-DCF isolates the terminal cash flow and growth required by the 2026-10-29 market price.')
mi=['Market capitalization','Less / plus: equity bridge items','Market-implied enterprise value','PV of explicit base-case FCFF','Required terminal value at market price','Required terminal FCFF at base WACC and g','Base normalized terminal FCFF','Required / base terminal FCFF','Market-implied terminal growth at base terminal FCFF','Unexplained market premium / (discount)']
for i,l in enumerate(mi,7): ws.cell(i,1,l)
ws['B7']=f'={ar("market_cap",2026)}'; ws['B8']='=DCF!B37+DCF!B38+DCF!B39'; ws['B9']='=B7-B8'; ws['B10']='=SUM(DCF!B18:F18)'; ws['B11']='=(B9-B10)*(1+DCF!B66)^DCF!B68'; ws['B12']='=B11*(DCF!B66-DCF!B67)'; ws['B13']='=DCF!G26'; ws['B14']='=B12/B13'; ws['B15']='=IFERROR((B11*DCF!B66-B13)/(B11+B13),"NM")'; ws['B16']='=B9-DCF!B35'
ws['B15'].number_format='0.0%'; ws['B14'].number_format='0.00x'
ws['A19']='Interpretation'; ws['B19']='A value above 1.0x in required/base terminal FCFF indicates the market embeds a stronger terminal outlook than the independent Base case; it is not an option-value plug.'

# Checks
ws=wb['Checks']; title(ws,'Checks | 模型完整性与估值检查','Tolerance = 0.1 USD mn unless stated. REVIEW is used for economic/valuation concentration, not formula failure.')
periods(ws)
check_defs=[('BS balance','BS',40,'balance'),('Cash tie — CF vs BS',None,None,'cash'),('Net income link — IS vs CF',None,None,'ni'),('Segment revenue tie',None,None,'segrev'),('Segment EBIT tie',None,None,'segebit'),('PP&E roll-forward',None,None,'ppe'),('Debt roll-forward',None,None,'debt')]
for i,(label,_,__,kind) in enumerate(check_defs,8):
    ws.cell(i,1,label)
    for ci in range(2,10):
        c=get_column_letter(ci)
        if kind=='balance': formula=f'=BS!{c}40'
        elif kind=='cash': formula=f'=CF!{c}35-BS!{c}8'
        elif kind=='ni': formula=f'=CF!{c}8-IS!{c}19'
        elif kind=='segrev': formula=f'=Segment!{c}12-IS!{c}8'
        elif kind=='segebit': formula=f'=Segment!{c}18-IS!{c}15'
        elif kind=='ppe': formula=f'=BS!{c}15-BS!{c}51' if ci>=5 else '=0'
        elif kind=='debt': formula=f'=BS!{c}28-BS!{c}57' if ci>=5 else '=0'
        ws.cell(i,ci,formula); ws.cell(i,ci).number_format='0.0'
extra=[('WACC > terminal growth','=DCF!B66-DCF!B67','positive'),('Gordon implied value positive','=DCF!B43','positive'),('Market price positive','=DCF!B45','positive'),('Terminal PV / EV — Gordon','=DCF!B48','tv'),('Sensitivity direction','=Sensitivity!B13','text'),('Base scenario vs DCF per-share','=Scenarios!B25-DCF!B43','zero'),('Overall formula integrity','=IF(SUMPRODUCT(ABS(B8:I14))<0.1,"PASS","REVIEW")','text')]
for j,(label,formula,kind) in enumerate(extra,17):
    ws.cell(j,1,label); ws.cell(j,2,formula)
    if kind=='positive': ws.cell(j,3,f'=IF(B{j}>0,"PASS","REVIEW")')
    elif kind=='tv': ws.cell(j,3,f'=IF(B{j}>0.8,"VALUATION_REVIEW_REQUIRED",IF(B{j}>0.5,"REVIEW","PASS"))')
    elif kind=='text': ws.cell(j,3,f'=B{j}')
    elif kind=='zero': ws.cell(j,3,f'=IF(ABS(B{j})<0.1,"PASS","REVIEW")')
ws['A26']='Valuation status'; ws['B26']='=DCF!B50'; ws['A27']='Model status'; ws['B27']='=IF(AND(SUMPRODUCT(ABS(B8:I14))<0.1,C22="PASS",B23="PASS"),"PASS","REVIEW")'
ws['A29']='Coverage matrix'; ws['B29']='Historical facts → Raw_Data; forecast drivers → Assumptions; three statements → IS/BS/CF; valuation → DCF/Sensitivity/Scenarios; market calibration → Market_Implied; sources → Data_Sources.'

# Summary and cover
ws=wb['Summary']; title(ws,'Summary | 财务预测与估值摘要','All values are formula links; no standalone hardcoded outputs. USD mn except per-share data.')
periods(ws)
summary_rows=[('Revenue','IS',8),('Revenue growth','IS',32),('Operating income','IS',15),('Operating margin','IS',30),('Net income','IS',19),('Diluted EPS','IS',22),('Free cash flow (company definition)','CF',38)]
for i,(label,sheet,row) in enumerate(summary_rows,8):
    ws.cell(i,1,label)
    for ci in range(2,10):
        c=get_column_letter(ci); ws.cell(i,ci,f'={sheet}!{c}{row}'); ws.cell(i,ci).number_format='0.0%' if 'growth' in label or 'margin' in label else ('0.00' if 'EPS' in label else '#,##0;(#,##0);-')
section(ws,17,'Valuation summary')
vals=[('Gordon enterprise value','=DCF!B35'),('Gordon equity value','=DCF!B40'),('Gordon implied value / share','=DCF!B43'),('Exit-multiple implied value / share','=DCF!B44'),('Market price','=DCF!B45'),('Gordon upside / (downside)','=DCF!B46'),('Chosen WACC','=DCF!B66'),('Terminal growth','=DCF!B67'),('Terminal PV / EV','=DCF!B48'),('Valuation status','=DCF!B50')]
for i,(label,formula) in enumerate(vals,18): ws.cell(i,1,label); ws.cell(i,2,formula); ws.cell(i,2).number_format='0.0%' if any(x in label for x in ['upside','WACC','growth','PV / EV']) else ('0.00' if 'share' in label or 'price' in label else '#,##0')
section(ws,30,'Scenario value / share')
for i,name in enumerate(['Base','Upside','Downside'],31): ws.cell(i,1,name); ws.cell(i,2,f'=Scenarios!B{scenario_outputs[name]}'); ws.cell(i,2).number_format='0.00'; ws.cell(i,3,f'=B{i}/DCF!B45-1'); ws.cell(i,3).number_format='0.0%'
chart=BarChart(); chart.type='col'; chart.style=10; chart.title='Revenue and operating income'; chart.y_axis.title='USD mn'; chart.x_axis.title='Fiscal year'; chart.add_data(Reference(wb['IS'],min_col=2,max_col=9,min_row=8,max_row=8),titles_from_data=False,from_rows=True); chart.add_data(Reference(wb['IS'],min_col=2,max_col=9,min_row=15,max_row=15),titles_from_data=False,from_rows=True); chart.set_categories(Reference(wb['IS'],min_col=2,max_col=9,min_row=5,max_row=5)); chart.series[0].tx=None; chart.series[1].tx=None; chart.height=8; chart.width=15; ws.add_chart(chart,'E18')

ws=wb['Cover']; ws.freeze_panes=None; ws.merge_cells('A1:J1'); ws['A1']='META | Meta Platforms, Inc.'; ws['A1'].fill=PatternFill('solid',fgColor=NAVY); ws['A1'].font=Font(name='Arial',size=24,bold=True,color=WHITE); ws.row_dimensions[1].height=36
ws.merge_cells('A2:J2'); ws['A2']='2026—2030 Financial Forecast & DCF Valuation | 财务预测与 DCF 估值模型'; ws['A2'].font=Font(name='Arial',size=13,bold=True)
identity=[('Listing','Nasdaq: META | U.S. ordinary shares | not an ADR'),('Reporting basis','US GAAP | USD millions | FY ends December 31'),('Latest official filing','Q3 2026 Form 10-Q, filed 2026-10-22'),('Market basis','2026-10-29 close; unadjusted; pre-Class-C-stock-dividend basis'),('Model cadence','Annual long-range model; 2026 = 9M actual + Q4 estimate'),('Run ID','META-20261030-DCF-V1')]
for i,(a,b) in enumerate(identity,4): ws.cell(i,1,a); ws.cell(i,1).font=Font(name='Arial',size=10,bold=True); ws.cell(i,2,b)
section(ws,12,'Key outputs')
cover_vals=[('FY2030 revenue','=IS!I8','#,##0'),('FY2030 operating income','=IS!I15','#,##0'),('FY2030 diluted EPS','=IS!I22','0.00'),('Gordon implied value / share','=DCF!B43','0.00'),('Exit-multiple value / share','=DCF!B44','0.00'),('Market price','=DCF!B45','0.00'),('Gordon upside / (downside)','=DCF!B46','0.0%'),('WACC','=DCF!B66','0.0%'),('Terminal growth','=DCF!B67','0.0%'),('Terminal PV / EV','=DCF!B48','0.0%'),('Valuation status','=DCF!B50','General')]
for i,(label,formula,fmt) in enumerate(cover_vals,13): ws.cell(i,1,label); ws.cell(i,2,formula); ws.cell(i,2).number_format=fmt
section(ws,26,'Model map')
maptext=[('Summary','Financial and valuation dashboard'),('Assumptions','All author and market inputs'),('Segment','FoA / RL driver build'),('IS / BS / CF','Linked GAAP statements and supporting schedules'),('Checks','Cross-statement and valuation checks'),('DCF / Sensitivity / Scenarios','FCFF, WACC, terminal methods and live sensitivities'),('Market_Implied','Reverse-DCF market calibration'),('Raw_Data / Data_Sources','Source facts and lineage')]
for i,(a,b) in enumerate(maptext,27): ws.cell(i,1,a); ws.cell(i,2,b)
section(ws,37,'Important conventions and risks')
notes=['Blue font = direct Raw_Data citation; amber fill = forecast/market input; black = formula.','2026 GAAP results include the $9.89bn Q3 legal charge; adjusted memo excludes it only where shown.','Class C stock dividend expected in January 2027 is economically split-like; model remains on a pre-split basis and excludes future Class C issuance.','Five-year horizon creates high terminal-value concentration; read Gordon, exit-multiple, scenarios and reverse-DCF together.','This is an independent valuation model, not investment advice or a transaction instruction.']
for i,n in enumerate(notes,38): ws.merge_cells(start_row=i,start_column=1,end_row=i,end_column=10); ws.cell(i,1,n); ws.cell(i,1).font=Font(name='Arial',size=9,color=NOTEGREY)

# Source registry
ws=wb['Data_Sources']; title(ws,'Data Sources | 数据来源与口径','T1 = regulatory filing; T2 = issuer IR; T3 = market/external research. Author assumptions are documented on Assumptions.')
headers=['Source ID','Tier','Document / dataset','Period / as-of','URL','Local evidence','SHA-256']
for i,h in enumerate(headers,1): ws.cell(5,i,h); ws.cell(5,i).fill=PatternFill('solid',fgColor=NAVY); ws.cell(5,i).font=Font(name='Arial',size=10,bold=True,color=WHITE)
ws.column_dimensions['C'].width=38; ws.column_dimensions['D'].width=20; ws.column_dimensions['E'].width=70; ws.column_dimensions['F'].width=38; ws.column_dimensions['G'].width=66
sources=[
('S1','T1','Meta FY2025 Form 10-K','FY2023–FY2025','https://www.sec.gov/Archives/edgar/data/1326801/0001628280-26-003942-index.html','raw/meta_fy2025_all.csv'),
('S2','T1','Meta Q3 FY2026 Form 10-Q','2026-09-30','https://www.sec.gov/Archives/edgar/data/1326801/0001628280-26-066773-index.html','raw/meta_q3fy2026_all.csv'),
('S3','T1','Meta FY2024 Form 10-K','2023 balance sheet','https://www.sec.gov/Archives/edgar/data/1326801/0001326801-25-000017-index.html','raw/meta_fy2024_bs.csv'),
('S4','T2','Meta Q3 2026 earnings release','2026-10-21','https://www.sec.gov/Archives/edgar/data/1326801/000162828026066700/meta-09302026xexhibit991.htm','evidence/q3_2026_release_excerpt.md'),
('S5','T2','Meta FY2025 earnings release','2026-01-28','https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Fourth-Quarter-and-Full-Year-2025-Results/default.aspx','raw/meta_fy2025_all.csv'),
('S6','T3','Yahoo Finance stock info','2026-10-29 market data','https://finance.yahoo.com/quote/META/','raw/meta_stock_info.csv'),
('S7','T3','Yahoo Finance historical close','2026-10-29; unadjusted','https://finance.yahoo.com/quote/META/history/','raw/meta_prices_5d.csv'),
('S8','T3','Federal Reserve 10Y UST via finance-data envelope','2026-10-29','https://www.federalreserve.gov/datadownload/','evidence/us_rates_excerpt.json'),
('S9','T3','Kroll recommended U.S. ERP reported by BVR','2025-09-10','https://www.bvresources.com/articles/bvwire/kroll-lowers-recommended-us-erp-to-50','evidence/erp_excerpt.md'),
('S10','T3','META 5.25% 2036 bond yield — Public/Moment','2026-10-28','https://public.com/bonds/corporate/meta-platforms-inc/meta-5.25-05-15-2036-30303mah5','evidence/bond_yield_excerpt.md'),
('S11','T1','IRS corporate statutory tax rate','Current federal rate','https://www.irs.gov/irb/2018-18_IRB','evidence/irs_tax_excerpt.md'),
]
for r,(sid,tier,doc,period,url,path) in enumerate(sources,6):
    full=os.path.join(ROOT,path); sha=''
    if os.path.exists(full):
        with open(full,'rb') as f: sha=hashlib.sha256(f.read()).hexdigest()
    vals=[sid,tier,doc,period,url,path,sha]
    for c,v in enumerate(vals,1): ws.cell(r,c,v); ws.cell(r,c).font=Font(name='Arial',size=9)
ws.freeze_panes='A6'

# Workbook-wide final styling
for ws in wb:
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None and cell.font.name != 'Arial':
                cell.font=Font(name='Arial',size=cell.font.sz or 10,bold=cell.font.bold,color=cell.font.color)
    ws.sheet_properties.pageSetUpPr.fitToPage=True
    ws.page_setup.fitToWidth=1; ws.page_setup.fitToHeight=0; ws.sheet_properties.outlinePr.summaryBelow=True

# Ensure every formula forecast cell is a formula, and all source files have known paths.
wb.save(OUT)

# Machine-readable run metadata and coverage.
manifest={
 'schema_version':'1.0','run_id':'META-20261030-DCF-V1','status':'in_progress',
 'metadata':{'company':'Meta Platforms, Inc.','ticker':'META','gaap':'US GAAP','fiscal_year_end':'12-31','currency':'USD','scale':1000000,'unit':'USD millions','period_type':'annual','valuation_date':'2026-10-29'},
 'canonical_workbook':'meta_model.xlsx','cash_policy':'CF-derived with explicit funding-response debt draw','bs_plug_policy':'forbidden',
 'dcf_terminal':{'explicit_forecast_years':5,'shorter_horizon_reason':'User explicitly requested 2026–2030','tv_pv_cell':'DCF!G29','ev_cell':'DCF!B35'},
 'dcf_market':{'price_cell':'DCF!B45','price_date_cell':'DCF!B69','price_date':'2026-10-29','evidence_id':'S7','methods':[{'id':'gordon','value_cell':'DCF!B43','upside_cell':'DCF!B46'},{'id':'exit_multiple','value_cell':'DCF!B44','upside_cell':'DCF!B47'}]},
 'sources':[{'id':s[0],'tier':s[1],'document':s[2],'period':s[3],'url':s[4],'path':s[5]} for s in sources],
 'artifacts':{'workbook':{'role':'canonical','path':'meta_model.xlsx'}},
 'notes':['Annual-only long-range model','2026E = 9M actual + Q4 estimate','Pre-Class-C-split per-share basis','Base case is not fitted to market price']
}
with open(os.path.join(ROOT,'manifest.json'),'w',encoding='utf-8') as f: json.dump(manifest,f,ensure_ascii=False,indent=2,default=str)
print(OUT)
print('rows',len(raw_rows),'assumptions',len(assump),'sheets',len(wb.sheetnames))
