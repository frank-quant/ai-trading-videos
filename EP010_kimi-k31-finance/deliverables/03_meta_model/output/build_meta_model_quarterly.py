import os, json, hashlib
from datetime import datetime
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

ROOT=os.path.dirname(os.path.abspath(__file__))
RAW=os.path.join(ROOT,'raw')
OUT=os.path.join(ROOT,'meta_model_quarterly.xlsx')
ANNUAL=os.path.join(ROOT,'meta_model.xlsx')
A25=pd.read_csv(os.path.join(RAW,'meta_fy2025_all.csv'))
AW=load_workbook(ANNUAL,data_only=True)

QEND={1:('03','31'),2:('06','30'),3:('09','30'),4:('12','31')}
QPS=[(y,q) for y in range(2024,2031) for q in range(1,5)]
ACT_Q=[(y,q) for y,q in QPS if (y<2026 or (y==2026 and q<=3))]
FC_Q=[(y,q) for y,q in QPS if (y,q) not in ACT_Q]
YEARS=list(range(2024,2031))
QCOL={p:2+i for i,p in enumerate(QPS)}
SPACER=30
ACOL={y:31+i for i,y in enumerate(YEARS)}
NOTE=39
ALLCOLS=list(range(2,30))+list(range(31,38))
ACT_SET=set(ACT_Q)

NAVY='1F3864'; GREY='EDEDED'; LIGHTBLUE='DDEBF7'; AMBER='FFF2CC'; WHITE='FFFFFF'; BLACK='000000'; CITEBLUE='0000CC'; NOTEGREY='777777'
thin=Side(style='thin',color='A6A6A6')

FILES={(y,q):pd.read_csv(os.path.join(RAW,f'meta_q{q}fy{y}_all.csv')) for y,q in ACT_Q if q<4}

C={
'revenue':'us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax','cor':'us-gaap_CostOfRevenue','rd':'us-gaap_ResearchAndDevelopmentExpense','ms':'us-gaap_SellingAndMarketingExpense','ga':'us-gaap_GeneralAndAdministrativeExpense','costs':'us-gaap_CostsAndExpenses','ebit':'us-gaap_OperatingIncomeLoss','nonop':'us-gaap_NonoperatingIncomeExpense','pretax':'us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest','tax':'us-gaap_IncomeTaxExpenseBenefit','ni':'us-gaap_NetIncomeLoss','eps_dil':'us-gaap_EarningsPerShareDiluted','shares_dil':'us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding',
'cash':'us-gaap_CashAndCashEquivalentsAtCarryingValue','marketable':'us-gaap_MarketableSecuritiesCurrent','ar':'us-gaap_AccountsReceivableNetCurrent','prepaid':'us-gaap_PrepaidExpenseAndOtherAssetsCurrent','nonmarketable':'meta_NonmarketableEquitySecuritiesCarryingValue','ppe':'us-gaap_PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization','rou':'us-gaap_OperatingLeaseRightOfUseAsset','goodwill':'us-gaap_Goodwill','other_assets':'us-gaap_OtherAssetsNoncurrent','assets':'us-gaap_Assets','ap':'us-gaap_AccountsPayableTradeCurrent','lease_cur':'us-gaap_OperatingLeaseLiabilityCurrent','accrued':'us-gaap_AccruedLiabilitiesCurrent','lease_noncur':'us-gaap_OperatingLeaseLiabilityNoncurrent','debt':'us-gaap_LongTermDebtNoncurrent','lt_tax':'us-gaap_AccruedIncomeTaxesNoncurrent','other_liab':'us-gaap_OtherLiabilitiesNoncurrent','liabilities':'us-gaap_Liabilities','aoci':'us-gaap_AccumulatedOtherComprehensiveIncomeLossNetOfTax','re':'us-gaap_RetainedEarningsAccumulatedDeficit','equity':'us-gaap_StockholdersEquity','le':'us-gaap_LiabilitiesAndStockholdersEquity',
'da':'us-gaap_DepreciationDepletionAndAmortization','sbc':'us-gaap_ShareBasedCompensation','deferred_tax':'us-gaap_DeferredIncomeTaxExpenseBenefit','cfo':'us-gaap_NetCashProvidedByUsedInOperatingActivities','cash_capex':'us-gaap_PaymentsToAcquirePropertyPlantAndEquipment','cfi':'us-gaap_NetCashProvidedByUsedInInvestingActivities','debt_issued':'us-gaap_ProceedsFromIssuanceOfLongTermDebt','fin_principal':'us-gaap_FinanceLeasePrincipalPayments','buybacks':'us-gaap_PaymentsForRepurchaseOfCommonStock','dividends':'us-gaap_PaymentsOfDividends','tax_withholding':'us-gaap_PaymentsRelatedToTaxWithholdingForShareBasedCompensation','cff':'us-gaap_NetCashProvidedByUsedInFinancingActivities'}
SEG_LABELS={'advertising':'Advertising - Family of Apps','other_rev':'Other revenue - Family of Apps','foa_rev':'Family of Apps','rl_rev':'Reality Labs','foa_ebit':'Family of Apps','rl_ebit':'Reality Labs'}
SEG_CONCEPT={'advertising':C['revenue'],'other_rev':C['revenue'],'foa_rev':C['revenue'],'rl_rev':C['revenue'],'foa_ebit':C['ebit'],'rl_ebit':C['ebit']}
STMT={**{k:'income_statement' for k in ['revenue','advertising','other_rev','foa_rev','rl_rev','cor','rd','ms','ga','costs','ebit','foa_ebit','rl_ebit','nonop','pretax','tax','ni','eps_dil','shares_dil']},**{k:'balance_sheet' for k in ['cash','marketable','ar','prepaid','nonmarketable','ppe','rou','goodwill','other_assets','assets','ap','lease_cur','accrued','lease_noncur','debt','lt_tax','other_liab','liabilities','aoci','re','equity','le']},**{k:'cash_flow' for k in ['da','sbc','deferred_tax','cfo','cash_capex','cfi','debt_issued','fin_principal','buybacks','dividends','tax_withholding','cff']}}

def read_fact(df,statement,concept,col,label=None):
    m=df[(df.statement_type==statement)&(df.concept==concept)&(df.dimension==(label is not None))]
    if label is not None: m=m[m.label==label]
    aliases={'us-gaap_AccountsPayableTradeCurrent':'us-gaap_AccountsPayableCurrent','us-gaap_DeferredIncomeTaxExpenseBenefit':'us-gaap_DeferredIncomeTaxesAndTaxCredits'}
    if m.empty and concept in aliases:
        concept=aliases[concept]
        m=df[(df.statement_type==statement)&(df.concept==concept)&(df.dimension==(label is not None))]
    optional={'us-gaap_ProceedsFromIssuanceOfLongTermDebt','us-gaap_PaymentsForRepurchaseOfCommonStock','us-gaap_PaymentsOfDividends'}
    if m.empty and concept in optional: return 0.0
    if m.empty: raise KeyError((statement,concept,label,col))
    v=m.iloc[0][col]
    if pd.isna(v): return None
    return float(v)/(1 if concept=='us-gaap_EarningsPerShareDiluted' else 1e6)

def annual_fact(key,y):
    return read_fact(A25,STMT[key],SEG_CONCEPT.get(key,C.get(key)),f'{y}-12-31 (FY)',SEG_LABELS.get(key))

def q_fact(key,y,q):
    concept=SEG_CONCEPT.get(key,C.get(key)); label=SEG_LABELS.get(key); stmt=STMT[key]
    if q<4:
        mm,dd=QEND[q]
        if stmt=='cash_flow' and q>1:
            current=read_fact(FILES[(y,q)],stmt,concept,f'{y}-{mm}-{dd} (YTD)',label)
            pm,pd=QEND[q-1]
            prev_label=f'{y}-{pm}-{pd} (YTD)' if q-1>1 else f'{y}-{pm}-{pd} (Q1)'
            previous=read_fact(FILES[(y,q-1)],stmt,concept,prev_label,label)
            return current-previous
        return read_fact(FILES[(y,q)],stmt,concept,f'{y}-{mm}-{dd} (Q{q})',label)
    if key=='shares_dil': return {2024:2599.0,2025:2565.0}[y]
    if key=='eps_dil':
        return q_fact('ni',y,4)/q_fact('shares_dil',y,4)
    mm,dd=QEND[3]
    ytd=read_fact(FILES[(y,3)],stmt,concept,f'{y}-{mm}-{dd} (YTD)',label)
    return annual_fact(key,y)-ytd

def bs_fact(key,y,q):
    if key=='apic':
        stmt='balance_sheet'
        if q==4:
            df=A25; col='2023-12-31' if y==2023 else f'{y}-12-31'
        else:
            df=FILES[(y,q)]; mm,dd=QEND[q]; col=f'{y}-{mm}-{dd}'
        combined=df[(df.statement_type==stmt)&(df.concept=='us-gaap_CommonStocksIncludingAdditionalPaidInCapital')&(df.dimension==False)]
        if not combined.empty: return float(combined.iloc[0][col])/1e6
        a=read_fact(df,stmt,'us-gaap_CommonStockValue',col)
        b=read_fact(df,stmt,'us-gaap_AdditionalPaidInCapital',col)
        return a+b
    if q==4:
        if y==2023:
            df=pd.read_csv(os.path.join(RAW,'meta_fy2024_bs.csv')); col='2023-12-31'
        else:
            df=A25; col=f'{y}-12-31'
    else:
        df=FILES[(y,q)]; mm,dd=QEND[q]; col=f'{y}-{mm}-{dd}'
    return read_fact(df,'balance_sheet',C[key],col)

RAWKEYS=['revenue','advertising','other_rev','foa_rev','rl_rev','cor','rd','ms','ga','costs','ebit','foa_ebit','rl_ebit','nonop','pretax','tax','ni','eps_dil','shares_dil','cash','marketable','ar','prepaid','nonmarketable','ppe','rou','goodwill','other_assets','assets','ap','lease_cur','accrued','lease_noncur','debt','lt_tax','other_liab','liabilities','aoci','re','equity','le','da','sbc','deferred_tax','cfo','cash_capex','cfi','debt_issued','fin_principal','buybacks','dividends','tax_withholding','cff']
BSKEYS=['cash','marketable','ar','prepaid','nonmarketable','ppe','rou','goodwill','other_assets','assets','ap','lease_cur','accrued','lease_noncur','debt','lt_tax','other_liab','liabilities','aoci','re','equity','le','apic']
raw={k:{} for k in RAWKEYS+['apic']}
for key in RAWKEYS:
    for y,q in ACT_Q:
        raw[key][(y,q)]=bs_fact(key,y,q) if key in BSKEYS else q_fact(key,y,q)
    for y in [2024,2025]:
        raw[key][('A',y)]=bs_fact(key,y,4) if key in BSKEYS else annual_fact(key,y)
for y,q in ACT_Q: raw['apic'][(y,q)]=bs_fact('apic',y,q)
for y in [2024,2025]: raw['apic'][('A',y)]=bs_fact('apic',y,4)
raw['legal_charge']={(2026,3):9890.0,('A',2025):0.0,('A',2024):0.0}
raw['fin_additions']={}
for y,q in ACT_Q:
    prev_ppe=bs_fact('ppe',y-1,4) if q==1 else raw['ppe'][(y,q-1)]
    if raw['cash_capex'][(y,q)] is None or raw['da'][(y,q)] is None:
        raise ValueError(('Missing PP&E flow',y,q,raw['cash_capex'][(y,q)],raw['da'][(y,q)]))
    raw['fin_additions'][(y,q)]=raw['ppe'][(y,q)]-prev_ppe+raw['cash_capex'][(y,q)]+raw['da'][(y,q)]

# Annual model targets are used only to derive quarterly assumptions; annual outputs in this workbook are always quarter roll-ups.
def av(sheet,cell): return float(AW[sheet][cell].value)
AC26={2026:'E',2027:'F',2028:'G',2029:'H',2030:'I'}
at={}
for y in range(2026,2031):
    c=AC26[y]
    at[y]={
      'foa_rev':av('Segment',f'{c}10'),'other_rev':av('Segment',f'{c}9'),'rl_rev':av('Segment',f'{c}11'),'revenue':av('Segment',f'{c}12'),'foa_ebit':av('Segment',f'{c}16'),'rl_ebit':av('Segment',f'{c}17'),'ebit':av('Segment',f'{c}18'),'costs':av('Segment',f'{c}22'),
      'cor':av('IS',f'{c}9'),'rd':av('IS',f'{c}10'),'ms':av('IS',f'{c}11'),'nonop':av('IS',f'{c}16'),'pretax':av('IS',f'{c}17'),'tax':av('IS',f'{c}18'),'shares_dil':av('IS',f'{c}21'),'da':av('IS',f'{c}25'),'sbc':av('IS',f'{c}26'),
      'marketable':av('BS',f'{c}9'),'ar':av('BS',f'{c}10'),'prepaid':av('BS',f'{c}11'),'nonmarketable':av('BS',f'{c}14'),'rou':av('BS',f'{c}16'),'goodwill':av('BS',f'{c}17'),'other_assets':av('BS',f'{c}18'),'ap':av('BS',f'{c}22'),'lease_cur':av('BS',f'{c}23'),'accrued':av('BS',f'{c}24'),'debt':av('BS',f'{c}28'),'lt_tax':av('BS',f'{c}29'),'other_liab':av('BS',f'{c}30'),'aoci':av('BS',f'{c}35'),
      'cash_capex':av('BS',f'{c}48'),'fin_additions':av('BS',f'{c}49'),'debt_repayment':-av('BS',f'{c}55'),'fin_principal':-av('CF',f'{c}26'),'dividends':-av('CF',f'{c}27'),'tax_withholding':-av('CF',f'{c}29'),'buybacks':-av('CF',f'{c}28')}

def nine(key): return sum(raw[key][(2026,q)] for q in [1,2,3])
def seasonal(key):
    ws=[]
    for q in range(1,5):
        shares=[]
        for y in [2024,2025]:
            total=sum(abs(raw[key][(y,qq)]) for qq in range(1,5))
            shares.append(abs(raw[key][(y,q)])/total)
        ws.append(sum(shares)/2)
    return [w/sum(ws) for w in ws]
SEAS={k:seasonal(k) for k in ['foa_rev','other_rev','rl_rev']}
RAMP=[0.22,0.24,0.26,0.28]

assump=[]
def adda(key,label,note,values): assump.append({'key':key,'label':label,'note':note,'values':values})
V={}
def vals(key): return V.setdefault(key,{})
# 2026 Q4 bridge inputs
q4spec={
'q4_revenue':('Q4 2026 total revenue',at[2026]['revenue']-nine('revenue'),'S4 | Guidance midpoint less 9M actual'),
'q4_rl_rev':('Q4 2026 RL revenue',at[2026]['rl_rev']-nine('rl_rev'),'Author | Annual model bridge'),
'q4_other_rev':('Q4 2026 FoA other revenue',at[2026]['other_rev']-nine('other_rev'),'Author | Annual model bridge'),
'q4_costs':('Q4 2026 total expenses',at[2026]['costs']-nine('costs'),'S4 | FY guidance midpoint less 9M actual'),
'q4_cor':('Q4 2026 cost of revenue',at[2026]['cor']-nine('cor'),'Author | Annual model bridge'),
'q4_rd':('Q4 2026 R&D',at[2026]['rd']-nine('rd'),'Author | Annual model bridge'),
'q4_ms':('Q4 2026 marketing and sales',at[2026]['ms']-nine('ms'),'Author | Annual model bridge'),
'q4_rl_ebit':('Q4 2026 RL operating income / (loss)',at[2026]['rl_ebit']-nine('rl_ebit'),'Author | Annual model bridge'),
'q4_nonop':('Q4 2026 non-operating income / (expense)',at[2026]['nonop']-nine('nonop'),'Author | Annual model bridge')}
for k,(label,val,note) in q4spec.items(): vals(k)[(2026,4)]=val; adda(k,label,note,vals(k))
for key,label,note in [
('foa_growth','FoA revenue YoY growth','Quarterly YoY driver; historical seasonality + annual house view'),('other_growth','FoA other revenue YoY growth','Quarterly allocation view'),('rl_growth','RL revenue YoY growth','Quarterly YoY driver'),('foa_margin','FoA operating margin','Annual margin applied evenly across quarters'),('rl_ebit','RL operating income / (loss)','Annual loss deployed evenly'),('cor_pct','Cost of revenue / revenue','Quarterly cost ratio'),('rd_pct','R&D / revenue','Quarterly AI investment ratio'),('ms_pct','Marketing and sales / revenue','Quarterly marketing ratio'),('da','Depreciation and amortization','Quarterly ramp deployment'),('cash_capex','Purchases of property and equipment','Quarterly capital deployment'),('fin_principal','Finance-lease principal payments','Quarterly capital deployment'),('fin_additions','Finance lease & other PP&E additions','Quarterly non-cash PP&E additions'),('marketable','Marketable securities ending balance','Linear quarterly interpolation to year-end target'),('nonmarketable','Non-marketable investments ending balance','Held flat'),('dso','Accounts receivable days','Applied to LTM revenue'),('prepaid_pct','Prepaid assets / LTM revenue','Quarter-end driver'),('other_assets_pct','Other assets / LTM revenue','Quarter-end driver'),('rou_pct','ROU assets / LTM revenue','Quarter-end driver'),('goodwill','Goodwill ending balance','No acquisitions modeled'),('ap_pct','AP / (LTM costs + LTM cash capex)','Quarter-end driver'),('accrued_pct','Accrued expenses / LTM costs','Quarter-end driver'),('lease_pct','Lease liabilities / ROU assets','Lease schedule'),('lease_current_pct','Current share of lease liabilities','Lease schedule'),('lt_tax','Long-term income taxes','Held flat'),('other_liab_pct','Other liabilities / LTM revenue','Quarter-end driver'),('debt_repayment','Scheduled debt repayment','Contractual maturity placed in Q4'),('min_cash','Minimum cash balance','Quarterly funding-response trigger'),('aoci','AOCI ending balance','Held flat'),('tax_rate','Effective tax rate','Quarterly normalized rate'),('nonop','Non-operating income / (expense)','Annual amount deployed evenly'),('sbc_pct','SBC / revenue','Quarterly compensation ratio'),('withholding_pct','Tax withholding / SBC','Quarterly cash-flow ratio'),('shares_dil','Diluted weighted-average shares','Annual weighted-average convention held within year'),('dps','Dividends per share','Quarterly dividend run-rate'),('buybacks','Share repurchases','No repurchases modeled')]:
    adda(key,label,note,vals(key))

for y in range(2027,2031):
    for q in range(1,5):
        p=(y,q)
        for key,sk in [('foa_growth','foa_rev'),('other_growth','other_rev'),('rl_growth','rl_rev')]:
            target=at[y][sk]*SEAS[sk][q-1]
            prior=(at[y-1][sk]*SEAS[sk][q-1] if y>2027 else (raw[sk][(2026,q)] if q<4 else at[2026][sk]-nine(sk)))
            vals(key)[p]=target/prior-1
        vals('foa_margin')[p]=at[y]['foa_ebit']/at[y]['foa_rev']
        vals('rl_ebit')[p]=at[y]['rl_ebit']/4
        vals('cor_pct')[p]=at[y]['cor']/at[y]['revenue']; vals('rd_pct')[p]=at[y]['rd']/at[y]['revenue']; vals('ms_pct')[p]=at[y]['ms']/at[y]['revenue']
        for key in ['da','cash_capex','fin_principal','fin_additions']: vals(key)[p]=at[y][key]*RAMP[q-1]
        for key in ['marketable','nonmarketable','goodwill','lt_tax','aoci']:
            vals(key)[p]=at[y-1][key]+(at[y][key]-at[y-1][key])*q/4
        vals('dso')[p]=at[y]['ar']/at[y]['revenue']*365; vals('prepaid_pct')[p]=at[y]['prepaid']/at[y]['revenue']; vals('other_assets_pct')[p]=at[y]['other_assets']/at[y]['revenue']; vals('rou_pct')[p]=at[y]['rou']/at[y]['revenue']; vals('ap_pct')[p]=at[y]['ap']/(at[y]['costs']+at[y]['cash_capex']); vals('accrued_pct')[p]=at[y]['accrued']/at[y]['costs']; vals('lease_pct')[p]=(at[y]['lease_cur']+av('BS',f'{AC26[y]}27'))/at[y]['rou']; vals('lease_current_pct')[p]=at[y]['lease_cur']/(at[y]['lease_cur']+av('BS',f'{AC26[y]}27')); vals('other_liab_pct')[p]=at[y]['other_liab']/at[y]['revenue']
        vals('debt_repayment')[p]=at[y]['debt_repayment'] if q==4 else 0; vals('min_cash')[p]=10000; vals('tax_rate')[p]=at[y]['tax']/at[y]['pretax']; vals('nonop')[p]=at[y]['nonop']/4; vals('sbc_pct')[p]=at[y]['sbc']/at[y]['revenue']; vals('withholding_pct')[p]=at[y]['tax_withholding']/at[y]['sbc']; vals('shares_dil')[p]=at[y]['shares_dil']; vals('dps')[p]=at[y]['dividends']/at[y]['shares_dil']/4; vals('buybacks')[p]=0
# Q4 2026 assumptions
p=(2026,4)
for key in ['marketable','nonmarketable','goodwill','lt_tax','aoci']: vals(key)[p]=at[2026][key]
vals('dso')[p]=at[2026]['ar']/at[2026]['revenue']*365; vals('prepaid_pct')[p]=at[2026]['prepaid']/at[2026]['revenue']; vals('other_assets_pct')[p]=at[2026]['other_assets']/at[2026]['revenue']; vals('rou_pct')[p]=at[2026]['rou']/at[2026]['revenue']; vals('ap_pct')[p]=at[2026]['ap']/(at[2026]['costs']+at[2026]['cash_capex']); vals('accrued_pct')[p]=at[2026]['accrued']/at[2026]['costs']; vals('lease_pct')[p]=(at[2026]['lease_cur']+av('BS','E27'))/at[2026]['rou']; vals('lease_current_pct')[p]=at[2026]['lease_cur']/(at[2026]['lease_cur']+av('BS','E27')); vals('other_liab_pct')[p]=at[2026]['other_liab']/at[2026]['revenue']; vals('debt_repayment')[p]=0; vals('min_cash')[p]=10000; vals('tax_rate')[p]=0.16; vals('sbc_pct')[p]=at[2026]['sbc']/at[2026]['revenue']; vals('withholding_pct')[p]=at[2026]['tax_withholding']/at[2026]['sbc']; vals('shares_dil')[p]=at[2026]['shares_dil']; vals('dps')[p]=(at[2026]['dividends']+nine('dividends'))/at[2026]['shares_dil']; vals('buybacks')[p]=0
for key in ['da','fin_additions']: vals(key)[p]=at[2026][key]-nine(key)
for key in ['cash_capex','fin_principal']: vals(key)[p]=at[2026][key]+nine(key)

# Workbook helpers
wb=Workbook(); wb.remove(wb.active)
for n in ['Cover','Summary','Assumptions','Segment','IS','BS','CF','Checks','DCF','Sensitivity','Scenarios','Market_Implied','Raw_Data','Data_Sources']: wb.create_sheet(n)
wb.calculation.fullCalcOnLoad=True; wb.calculation.forceFullCalc=True; wb.calculation.calcMode='auto'
for ws in wb:
    ws.sheet_view.showGridLines=False; ws.freeze_panes='B7'; ws.column_dimensions['A'].width=42
    for c in range(2,38): ws.column_dimensions[get_column_letter(c)].width=13
    ws.column_dimensions['AD'].width=3; ws.column_dimensions['AM'].width=58

def title(ws,text,subtitle='Meta Platforms, Inc. | Nasdaq: META | US GAAP | USD mn unless stated'):
    ws.merge_cells(start_row=1,start_column=1,end_row=1,end_column=NOTE); ws.cell(1,1,text); ws.cell(1,1).fill=PatternFill('solid',fgColor=NAVY); ws.cell(1,1).font=Font(name='Arial',size=15,bold=True,color=WHITE); ws.row_dimensions[1].height=25
    ws.merge_cells(start_row=2,start_column=1,end_row=2,end_column=NOTE); ws.cell(2,1,subtitle); ws.cell(2,1).font=Font(name='Arial',size=9,color=NOTEGREY)
    ws['A3']='Model date'; ws['B3']=datetime(2026,10,30); ws['B3'].number_format='yyyy-mm-dd'; ws['D3']='Quarterly + derived annual grid'

def section(ws,row,text,end=NOTE):
    ws.cell(row,1,text)
    for c in range(1,end+1):
        if c==SPACER: continue
        ws.cell(row,c).fill=PatternFill('solid',fgColor=GREY); ws.cell(row,c).font=Font(name='Arial',size=10,bold=True)

def periods(ws,rawmode=False):
    ws.cell(5,1,'Line item')
    for (y,q),c in QCOL.items():
        actual=(y,q) in ACT_SET
        ws.cell(5,c,f'{y}Q{q}{"A" if actual else "E"}'); ws.cell(6,c,f'{y}-{QEND[q][0]}-{QEND[q][1]}')
    for y,c in ACOL.items():
        ws.cell(5,c,f'FY{y}{"A" if y<=2025 else "E"}'); ws.cell(6,c,f'{y}-12-31')
    ws.cell(5,NOTE,'Source / rationale')
    for c in [1]+ALLCOLS+[NOTE]:
        ws.cell(5,c).fill=PatternFill('solid',fgColor=NAVY); ws.cell(5,c).font=Font(name='Arial',size=10,bold=True,color=WHITE); ws.cell(5,c).alignment=Alignment(horizontal='center')
    for c in ALLCOLS: ws.cell(6,c).alignment=Alignment(horizontal='center'); ws.cell(6,c).font=Font(name='Arial',size=9,color=NOTEGREY)

def cite(cell,fmt=None): cell.font=Font(name='Arial',size=10,color=CITEBLUE); cell.number_format=fmt or '#,##0;(#,##0);-'
def inp(cell,fmt=None): cell.fill=PatternFill('solid',fgColor=AMBER); cell.font=Font(name='Arial',size=10,color=BLACK); cell.number_format=fmt or '#,##0;(#,##0);-'
def subtotal(ws,row,cols=None):
    for c in [1]+(cols or ALLCOLS): ws.cell(row,c).font=Font(name='Arial',size=10,bold=True); ws.cell(row,c).border=Border(top=thin)
def style_rows(ws,rows,pct=(),eps=()):
    for r in rows:
        for c in ALLCOLS:
            ws.cell(r,c).font=Font(name='Arial',size=10,color=ws.cell(r,c).font.color if ws.cell(r,c).font.color else BLACK)
            ws.cell(r,c).number_format='0.0%' if r in pct else ('0.00' if r in eps else '#,##0;(#,##0);-')
        ws.cell(r,NOTE).font=Font(name='Arial',size=9,color=NOTEGREY)
def qcols_for_year(y): return [QCOL[(y,q)] for q in range(1,5)]
def flow_annual(ws,row,y):
    cs=qcols_for_year(y); ws.cell(row,ACOL[y],f'=SUM({get_column_letter(cs[0])}{row}:{get_column_letter(cs[-1])}{row})')
def stock_annual(ws,row,y): ws.cell(row,ACOL[y],f'={get_column_letter(QCOL[(y,4)])}{row}')
def rawref(key,y,q): return f'Raw_Data!{get_column_letter(QCOL[(y,q)])}{rawmap[key]}'
def aref(key,y,q): return f'Assumptions!{get_column_letter(QCOL[(y,q)])}{amap[key]}'

# Raw data
ws=wb['Raw_Data']; title(ws,'Raw Data | 季度官方事实层','Quarterly flows are single-quarter; Q4 = FY − 9M. BS uses quarter-end point-in-time values. No forecast data on this tab.'); periods(ws,True)
labels={'revenue':'Revenue','advertising':'Advertising — FoA','other_rev':'Other revenue — FoA','foa_rev':'Family of Apps revenue','rl_rev':'Reality Labs revenue','cor':'Cost of revenue','rd':'Research and development','ms':'Marketing and sales','ga':'General and administrative','costs':'Total costs and expenses','ebit':'Operating income','foa_ebit':'FoA operating income','rl_ebit':'RL operating income (loss)','nonop':'Non-operating income / (expense)','pretax':'Pre-tax income','tax':'Income taxes','ni':'Net income','eps_dil':'Diluted EPS','shares_dil':'Diluted shares','cash':'Cash and cash equivalents','marketable':'Marketable securities','ar':'Accounts receivable','prepaid':'Prepaid and other current assets','nonmarketable':'Non-marketable investments','ppe':'PP&E, net','rou':'Operating lease ROU assets','goodwill':'Goodwill','other_assets':'Other assets','assets':'Total assets','ap':'Accounts payable','lease_cur':'Lease liabilities, current','accrued':'Accrued expenses','lease_noncur':'Lease liabilities, non-current','debt':'Long-term debt','lt_tax':'Long-term income taxes','other_liab':'Other liabilities','liabilities':'Total liabilities','aoci':'AOCI','re':'Retained earnings','equity':'Total equity','le':'Total liabilities and equity','da':'D&A','sbc':'Share-based compensation','deferred_tax':'Deferred income taxes','cfo':'Operating cash flow','cash_capex':'Purchases of PP&E','cfi':'Investing cash flow','debt_issued':'Debt issuance','fin_principal':'Finance-lease principal','buybacks':'Share repurchases','dividends':'Dividends','tax_withholding':'SBC tax withholding','cff':'Financing cash flow','apic':'Common stock and APIC','legal_charge':'Q3 2026 legal charge'}
rawmap={}
ordered=RAWKEYS+['apic','legal_charge','fin_additions']
for i,key in enumerate(ordered,8):
    rawmap[key]=i; ws.cell(i,1,labels.get(key,key))
    for y,q in ACT_Q:
        v=raw[key].get((y,q))
        if v is not None:
            c=QCOL[(y,q)]; ws.cell(i,c,v); ws.cell(i,c).fill=PatternFill('solid',fgColor=LIGHTBLUE); ws.cell(i,c).number_format='0.00' if key=='eps_dil' else '#,##0;(#,##0);-'
    for y in [2024,2025]:
        v=raw[key].get(('A',y))
        if v is not None:
            c=ACOL[y]; ws.cell(i,c,v); ws.cell(i,c).fill=PatternFill('solid',fgColor=LIGHTBLUE); ws.cell(i,c).number_format='0.00' if key=='eps_dil' else '#,##0;(#,##0);-'
    ws.cell(i,NOTE,'SEC 10-Q / 10-K; Q4 flow derived as annual minus 9M; EPS recomputed from Q4 NI / Q4 shares' if key!='legal_charge' else 'S4 | Meta Q3 2026 earnings release')
ws.auto_filter.ref=f'A7:AM{7+len(ordered)}'

# Assumptions
ws=wb['Assumptions']; title(ws,'Assumptions | 季度预测驱动','Amber = quarterly forecast inputs. Annual columns are not independent input columns.'); periods(ws)
amap={}
for i,rec in enumerate(assump,8):
    key=rec['key']; amap[key]=i; ws.cell(i,1,rec['label']); ws.cell(i,NOTE,rec['note'])
    for (y,q),v in rec['values'].items():
        c=QCOL[(y,q)]
        pct=any(x in key for x in ['growth','margin','pct','rate'])
        ws.cell(i,c,v); inp(ws.cell(i,c),'0.0%' if pct else ('0.00' if key in ['dps'] else '#,##0;(#,##0);-'))
    if key in ['foa_growth','other_growth','rl_growth']:
        segrow={'foa_growth':10,'other_growth':9,'rl_growth':11}[key]
        for y in range(2025,2031): ws.cell(i,ACOL[y],f'=Segment!{get_column_letter(ACOL[y])}{segrow}/Segment!{get_column_letter(ACOL[y-1])}{segrow}-1'); ws.cell(i,ACOL[y]).number_format='0.0%'
    elif key=='foa_margin':
        for y in YEARS: ws.cell(i,ACOL[y],f'=Segment!{get_column_letter(ACOL[y])}19'); ws.cell(i,ACOL[y]).number_format='0.0%'
    elif key in ['rl_ebit','da','cash_capex','fin_principal','fin_additions','nonop','buybacks']:
        for y in range(2026,2031):
            if y>=2027: flow_annual(ws,i,y)
    elif key in ['marketable','nonmarketable','goodwill','lt_tax','aoci']:
        for y in range(2026,2031): stock_annual(ws,i,y)
    elif key=='dps':
        for y in range(2026,2031): ws.cell(i,ACOL[y],f'=SUM({get_column_letter(QCOL[(y,1)])}{i}:{get_column_letter(QCOL[(y,4)])}{i})'); ws.cell(i,ACOL[y]).number_format='0.00'

# Segment
ws=wb['Segment']; title(ws,'Segment | 季度分部预测','FoA and RL quarterly drivers; annual flows = sum of quarters; annual margins recomputed.'); periods(ws)
sr={'advertising':8,'other_rev':9,'foa_rev':10,'rl_rev':11,'revenue':12,'rev_growth':13,'foa_ebit':16,'rl_ebit':17,'ebit':18,'foa_margin':19,'rl_margin':20,'costs':22,'legal_charge':24,'adj_ebit':25}
section(ws,7,'Revenue build'); section(ws,15,'Operating profit build'); section(ws,21,'Total expenses'); section(ws,23,'Memo — legal charge exclusion')
for k,r in sr.items(): ws.cell(r,1,labels.get(k,{'rev_growth':'Revenue growth','foa_margin':'FoA operating margin','rl_margin':'RL operating margin','adj_ebit':'Operating income excl. legal charge'}.get(k,k)))
for y,q in ACT_Q:
    c=QCOL[(y,q)]
    for k in ['advertising','other_rev','foa_rev','rl_rev','revenue','foa_ebit','rl_ebit','ebit','costs']:
        ws.cell(sr[k],c,f'={rawref(k,y,q)}'); cite(ws.cell(sr[k],c))
    ws.cell(sr['legal_charge'],c,raw['legal_charge'].get((y,q),0)); ws.cell(sr['adj_ebit'],c,f'={get_column_letter(c)}18+{get_column_letter(c)}24')
for y,q in FC_Q:
    c=QCOL[(y,q)]; L=get_column_letter(c)
    if (y,q)==(2026,4):
        ws.cell(sr['revenue'],c,f'={aref("q4_revenue",y,q)}'); ws.cell(sr['rl_rev'],c,f'={aref("q4_rl_rev",y,q)}'); ws.cell(sr['other_rev'],c,f'={aref("q4_other_rev",y,q)}'); ws.cell(sr['foa_rev'],c,f'={L}12-{L}11'); ws.cell(sr['costs'],c,f'={aref("q4_costs",y,q)}'); ws.cell(sr['rl_ebit'],c,f'={aref("q4_rl_ebit",y,q)}'); ws.cell(sr['ebit'],c,f'={L}12-{L}22'); ws.cell(sr['foa_ebit'],c,f'={L}18-{L}17'); ws.cell(sr['legal_charge'],c,0)
    else:
        pc=QCOL[(y-1,q)]; P=get_column_letter(pc)
        ws.cell(sr['foa_rev'],c,f'={P}10*(1+{aref("foa_growth",y,q)})'); ws.cell(sr['other_rev'],c,f'={P}9*(1+{aref("other_growth",y,q)})'); ws.cell(sr['rl_rev'],c,f'={P}11*(1+{aref("rl_growth",y,q)})'); ws.cell(sr['revenue'],c,f'={L}10+{L}11'); ws.cell(sr['foa_ebit'],c,f'={L}10*{aref("foa_margin",y,q)}'); ws.cell(sr['rl_ebit'],c,f'={aref("rl_ebit",y,q)}'); ws.cell(sr['ebit'],c,f'={L}16+{L}17'); ws.cell(sr['costs'],c,f'={L}12-{L}18'); ws.cell(sr['legal_charge'],c,0)
    ws.cell(sr['advertising'],c,f'={L}10-{L}9'); ws.cell(sr['adj_ebit'],c,f'={L}18+{L}24')
for c in ALLCOLS:
    L=get_column_letter(c)
    ws.cell(sr['foa_margin'],c,f'={L}16/{L}10'); ws.cell(sr['rl_margin'],c,f'={L}17/{L}11')
for y in YEARS:
    for k in ['advertising','other_rev','foa_rev','rl_rev','revenue','foa_ebit','rl_ebit','ebit','costs','legal_charge','adj_ebit']: flow_annual(ws,sr[k],y)
    if y>2024: ws.cell(sr['rev_growth'],ACOL[y],f'={get_column_letter(ACOL[y])}12/{get_column_letter(ACOL[y-1])}12-1')
for i,(y,q) in enumerate(QPS[1:],1):
    c=QCOL[(y,q)]; p=QCOL[QPS[i-1]]
    if q==1: continue
    ws.cell(sr['rev_growth'],c,f'={get_column_letter(c)}12/{get_column_letter(p)}12-1')
style_rows(ws,list(sr.values()),pct=[13,19,20]); subtotal(ws,12); subtotal(ws,18); subtotal(ws,25)

# Income statement
ws=wb['IS']; title(ws,'Income Statement | 季度利润表','Annual flows = sum of quarters; annual diluted shares = average; annual EPS = annual NI / annual shares.'); periods(ws)
ir={'revenue':8,'cor':9,'rd':10,'ms':11,'ga':12,'costs':13,'ebit':15,'nonop':16,'pretax':17,'tax':18,'ni':19,'shares_dil':21,'eps_dil':22,'da':25,'sbc':26,'adj_ebit':28,'op_margin':30,'net_margin':31,'revenue_growth':32}
section(ws,7,'GAAP income statement'); section(ws,20,'Per-share data'); section(ws,24,'Memo items'); section(ws,27,'Legal-charge exclusion'); section(ws,29,'Margins and growth')
for k,r in ir.items(): ws.cell(r,1,labels.get(k,{'adj_ebit':'Operating income excl. legal charge','op_margin':'Operating margin','net_margin':'Net margin','revenue_growth':'Revenue growth'}.get(k,k)))
for y,q in ACT_Q:
    c=QCOL[(y,q)]; L=get_column_letter(c)
    for k in ['cor','rd','ms','ga','nonop','tax','da','sbc','shares_dil','eps_dil']:
        ws.cell(ir[k],c,f'={rawref(k,y,q)}'); cite(ws.cell(ir[k],c),'0.00' if k=='eps_dil' else None)
    ws.cell(ir['revenue'],c,f'=Segment!{L}12'); ws.cell(ir['costs'],c,f'=SUM({L}9:{L}12)'); ws.cell(ir['ebit'],c,f'={L}8-{L}13'); ws.cell(ir['pretax'],c,f'={L}15+{L}16'); ws.cell(ir['ni'],c,f'={L}17-{L}18')
for y,q in FC_Q:
    c=QCOL[(y,q)]; L=get_column_letter(c)
    ws.cell(ir['revenue'],c,f'=Segment!{L}12'); ws.cell(ir['costs'],c,f'=Segment!{L}22'); ws.cell(ir['ebit'],c,f'={L}8-{L}13'); ws.cell(ir['pretax'],c,f'={L}15+{L}16'); ws.cell(ir['ni'],c,f'={L}17-{L}18'); ws.cell(ir['eps_dil'],c,f'={L}19/{L}21')
    if (y,q)==(2026,4):
        ws.cell(ir['cor'],c,f'={aref("q4_cor",y,q)}'); ws.cell(ir['rd'],c,f'={aref("q4_rd",y,q)}'); ws.cell(ir['ms'],c,f'={aref("q4_ms",y,q)}'); ws.cell(ir['nonop'],c,f'={aref("q4_nonop",y,q)}'); ws.cell(ir['da'],c,f'={aref("da",y,q)}')
    else:
        ws.cell(ir['cor'],c,f'={L}8*{aref("cor_pct",y,q)}'); ws.cell(ir['rd'],c,f'={L}8*{aref("rd_pct",y,q)}'); ws.cell(ir['ms'],c,f'={L}8*{aref("ms_pct",y,q)}'); ws.cell(ir['nonop'],c,f'={aref("nonop",y,q)}'); ws.cell(ir['da'],c,f'={aref("da",y,q)}')
    ws.cell(ir['ga'],c,f'={L}13-SUM({L}9:{L}11)'); ws.cell(ir['tax'],c,f'={L}17*{aref("tax_rate",y,q)}'); ws.cell(ir['shares_dil'],c,f'={aref("shares_dil",y,q)}'); ws.cell(ir['sbc'],c,f'={L}8*{aref("sbc_pct",y,q)}')
for c in ALLCOLS:
    L=get_column_letter(c); ws.cell(ir['adj_ebit'],c,f'=Segment!{L}25'); ws.cell(ir['op_margin'],c,f'={L}15/{L}8'); ws.cell(ir['net_margin'],c,f'={L}19/{L}8')
for y in YEARS:
    for k in ['revenue','cor','rd','ms','ga','costs','ebit','nonop','pretax','tax','ni','da','sbc']: flow_annual(ws,ir[k],y)
    cs=qcols_for_year(y); ws.cell(ir['shares_dil'],ACOL[y],f'=AVERAGE({get_column_letter(cs[0])}21:{get_column_letter(cs[-1])}21)'); ws.cell(ir['eps_dil'],ACOL[y],f'={get_column_letter(ACOL[y])}19/{get_column_letter(ACOL[y])}21')
    if y>2024: ws.cell(ir['revenue_growth'],ACOL[y],f'={get_column_letter(ACOL[y])}8/{get_column_letter(ACOL[y-1])}8-1')
style_rows(ws,list(ir.values()),pct=[30,31,32],eps=[22]); subtotal(ws,13); subtotal(ws,15); subtotal(ws,19); subtotal(ws,22)

# Balance sheet and schedules
ws=wb['BS']; title(ws,'Balance Sheet & Schedules | 季度资产负债表','Annual balances = Q4 quarter-end. Cash is CF-derived; quarterly debt draws respond to minimum-cash trigger.'); periods(ws)
br={'cash':8,'marketable':9,'ar':10,'prepaid':11,'current_assets':12,'nonmarketable':14,'ppe':15,'rou':16,'goodwill':17,'other_assets':18,'assets':19,'ap':22,'lease_cur':23,'accrued':24,'current_liab':25,'lease_noncur':27,'debt':28,'lt_tax':29,'other_liab':30,'liabilities':31,'apic':34,'aoci':35,'re':36,'equity':37,'le':38,'balance_check':40,'nwc':42,'lease_total':44,'ppe_begin':47,'capex':48,'fin_additions':49,'da':50,'ppe_end':51,'debt_begin':54,'debt_sched':55,'debt_draw':56,'debt_end':57}
section(ws,7,'Assets'); section(ws,21,'Liabilities'); section(ws,33,'Stockholders equity'); section(ws,39,'Integrity check'); section(ws,41,'Operating working capital'); section(ws,43,'Lease schedule'); section(ws,46,'PP&E roll-forward'); section(ws,53,'Debt roll-forward')
blabels={'current_assets':'Total current assets','assets':'Total assets','current_liab':'Total current liabilities','liabilities':'Total liabilities','equity':'Total equity','le':'Total liabilities and equity','balance_check':'Assets − liabilities − equity','nwc':'Operating NWC','lease_total':'Total lease liabilities','ppe_begin':'Beginning PP&E','capex':'Cash capital expenditures','fin_additions':'Finance lease & other additions','da':'D&A','ppe_end':'Ending PP&E','debt_begin':'Beginning debt','debt_sched':'Scheduled issuance / (repayment)','debt_draw':'Funding-response debt draw','debt_end':'Ending debt'}
for k,r in br.items(): ws.cell(r,1,blabels.get(k,labels.get(k,k)))
for y,q in ACT_Q:
    c=QCOL[(y,q)]; L=get_column_letter(c)
    for k in ['cash','marketable','ar','prepaid','nonmarketable','ppe','rou','goodwill','other_assets','ap','lease_cur','accrued','lease_noncur','debt','lt_tax','other_liab','apic','aoci','re']:
        ws.cell(br[k],c,f'={rawref(k,y,q)}'); cite(ws.cell(br[k],c))
    ws.cell(br['current_assets'],c,f'=SUM({L}8:{L}11)'); ws.cell(br['assets'],c,f'={L}12+SUM({L}14:{L}18)'); ws.cell(br['current_liab'],c,f'=SUM({L}22:{L}24)'); ws.cell(br['liabilities'],c,f'={L}25+SUM({L}27:{L}30)'); ws.cell(br['equity'],c,f'=SUM({L}34:{L}36)'); ws.cell(br['le'],c,f'={L}31+{L}37'); ws.cell(br['lease_total'],c,f'={L}23+{L}27')
    ws.cell(br['capex'],c,f'=-{rawref("cash_capex",y,q)}'); ws.cell(br['fin_additions'],c,f'={rawref("fin_additions",y,q)}'); ws.cell(br['da'],c,f'={rawref("da",y,q)}'); ws.cell(br['ppe_begin'],c,f'={L}15-{L}48-{L}49+{L}50'); ws.cell(br['ppe_end'],c,f'={L}47+{L}48+{L}49-{L}50')
for y,q in FC_Q:
    c=QCOL[(y,q)]; L=get_column_letter(c); prev=QCOL[QPS[QPS.index((y,q))-1]]; P=get_column_letter(prev)
    ltm_start=QCOL[QPS[QPS.index((y,q))-3]]; LS=get_column_letter(ltm_start)
    ws.cell(br['cash'],c,f'=CF!{L}35'); ws.cell(br['marketable'],c,f'={aref("marketable",y,q)}'); ws.cell(br['ar'],c,f'=SUM(IS!{LS}8:{L}8)*{aref("dso",y,q)}/365'); ws.cell(br['prepaid'],c,f'=SUM(IS!{LS}8:{L}8)*{aref("prepaid_pct",y,q)}'); ws.cell(br['current_assets'],c,f'=SUM({L}8:{L}11)')
    ws.cell(br['nonmarketable'],c,f'={aref("nonmarketable",y,q)}'); ws.cell(br['ppe'],c,f'={L}51'); ws.cell(br['rou'],c,f'=SUM(IS!{LS}8:{L}8)*{aref("rou_pct",y,q)}'); ws.cell(br['goodwill'],c,f'={aref("goodwill",y,q)}'); ws.cell(br['other_assets'],c,f'=SUM(IS!{LS}8:{L}8)*{aref("other_assets_pct",y,q)}'); ws.cell(br['assets'],c,f'={L}12+SUM({L}14:{L}18)')
    ws.cell(br['ap'],c,f'=(SUM(IS!{LS}13:{L}13)+SUM({LS}48:{L}48))*{aref("ap_pct",y,q)}'); ws.cell(br['lease_total'],c,f'={L}16*{aref("lease_pct",y,q)}'); ws.cell(br['lease_cur'],c,f'={L}44*{aref("lease_current_pct",y,q)}'); ws.cell(br['accrued'],c,f'=SUM(IS!{LS}13:{L}13)*{aref("accrued_pct",y,q)}'); ws.cell(br['current_liab'],c,f'=SUM({L}22:{L}24)'); ws.cell(br['lease_noncur'],c,f'={L}44-{L}23')
    ws.cell(br['debt'],c,f'={L}57'); ws.cell(br['lt_tax'],c,f'={aref("lt_tax",y,q)}'); ws.cell(br['other_liab'],c,f'=SUM(IS!{LS}8:{L}8)*{aref("other_liab_pct",y,q)}'); ws.cell(br['liabilities'],c,f'={L}25+SUM({L}27:{L}30)')
    ws.cell(br['apic'],c,f'={P}34+CF!{L}10+CF!{L}29'); ws.cell(br['aoci'],c,f'={aref("aoci",y,q)}'); ws.cell(br['re'],c,f'={P}36+IS!{L}19+CF!{L}27+CF!{L}28'); ws.cell(br['equity'],c,f'=SUM({L}34:{L}36)'); ws.cell(br['le'],c,f'={L}31+{L}37')
    ws.cell(br['ppe_begin'],c,f'={P}15'); ws.cell(br['capex'],c,f'={aref("cash_capex",y,q)}'); ws.cell(br['fin_additions'],c,f'={aref("fin_additions",y,q)}'); ws.cell(br['da'],c,f'=IS!{L}25'); ws.cell(br['ppe_end'],c,f'={L}47+{L}48+{L}49-{L}50')
    ws.cell(br['debt_begin'],c,f'={P}28'); ws.cell(br['debt_sched'],c,f'=-{aref("debt_repayment",y,q)}'); ws.cell(br['debt_draw'],c,f'=CF!{L}33'); ws.cell(br['debt_end'],c,f'={L}54+{L}55+{L}56')
for c in ALLCOLS:
    L=get_column_letter(c); ws.cell(br['balance_check'],c,f'={L}19-{L}38'); ws.cell(br['nwc'],c,f'={L}10+{L}11+{L}18-{L}22-{L}24-{L}30')
for y in YEARS:
    for k in ['cash','marketable','ar','prepaid','current_assets','nonmarketable','ppe','rou','goodwill','other_assets','assets','ap','lease_cur','accrued','current_liab','lease_noncur','debt','lt_tax','other_liab','liabilities','apic','aoci','re','equity','le','lease_total','ppe_end','debt_end']: stock_annual(ws,br[k],y)
    for k in ['capex','fin_additions','da','debt_sched','debt_draw']: flow_annual(ws,br[k],y)
    stock_annual(ws,br['balance_check'],y); stock_annual(ws,br['nwc'],y)
style_rows(ws,list(br.values())); subtotal(ws,12); subtotal(ws,19); subtotal(ws,25); subtotal(ws,31); subtotal(ws,37); subtotal(ws,38); subtotal(ws,51); subtotal(ws,57)

# Cash flow
ws=wb['CF']; title(ws,'Cash Flow Statement | 季度现金流量表','Annual flows = sum of quarters; ending cash = Q4. Forecast cash is fully articulated with BS movements.'); periods(ws)
fr={'ni':8,'da':9,'sbc':10,'deferred':11,'nwc':12,'lease_adj':13,'cfo':15,'cash_capex':18,'marketable_flow':19,'nonmarketable_flow':20,'goodwill_flow':21,'cfi':22,'debt_sched':25,'fin_principal':26,'dividends':27,'buybacks':28,'tax_withholding':29,'cff_before':30,'pre_funding_cash':31,'min_cash':32,'debt_draw':33,'cff':34,'ending_cash':35,'fcf':38,'capex_total':39}
section(ws,7,'Operating activities'); section(ws,17,'Investing activities'); section(ws,24,'Financing activities'); section(ws,37,'Company-defined free cash flow')
flabels={'deferred':'Deferred taxes / AOCI movement','nwc':'Change in operating NWC','lease_adj':'Lease amortization net of payments and additions','cfo':'Operating cash flow','marketable_flow':'Net marketable securities purchases / sales','nonmarketable_flow':'Net non-marketable investment purchases','goodwill_flow':'Acquisitions / goodwill movement','cfi':'Investing cash flow','debt_sched':'Scheduled debt issuance / (repayment)','cff_before':'Financing cash flow before funding response','pre_funding_cash':'Cash before funding-response draw','min_cash':'Minimum cash balance','debt_draw':'Funding-response debt draw','cff':'Financing cash flow','ending_cash':'Ending cash and cash equivalents','fcf':'Free cash flow — company definition','capex_total':'Total capex incl. finance-lease principal'}
for k,r in fr.items(): ws.cell(r,1,flabels.get(k,labels.get(k,k)))
for y,q in ACT_Q:
    c=QCOL[(y,q)]; L=get_column_letter(c)
    for k in ['ni','da','sbc','deferred_tax','cfo','cash_capex','cfi','fin_principal','dividends','buybacks','tax_withholding','cff']:
        target='deferred' if k=='deferred_tax' else k
        ws.cell(fr[target],c,f'={rawref(k,y,q)}'); cite(ws.cell(fr[target],c))
    ws.cell(fr['debt_sched'],c,f'={rawref("debt_issued",y,q)}'); cite(ws.cell(fr['debt_sched'],c)); ws.cell(fr['ending_cash'],c,f'={rawref("cash",y,q)}'); cite(ws.cell(fr['ending_cash'],c)); ws.cell(fr['fcf'],c,f'={L}15+{L}18+{L}26'); ws.cell(fr['capex_total'],c,f'=-{L}18-{L}26')
for y,q in FC_Q:
    c=QCOL[(y,q)]; L=get_column_letter(c); prev=QCOL[QPS[QPS.index((y,q))-1]]; P=get_column_letter(prev)
    ws.cell(fr['ni'],c,f'=IS!{L}19'); ws.cell(fr['da'],c,f'=IS!{L}25'); ws.cell(fr['sbc'],c,f'=IS!{L}26'); ws.cell(fr['deferred'],c,f'=(BS!{L}29-BS!{P}29)+(BS!{L}35-BS!{P}35)'); ws.cell(fr['nwc'],c,f'=-(BS!{L}42-BS!{P}42)'); ws.cell(fr['lease_adj'],c,f'=(BS!{L}44-BS!{P}44)-(BS!{L}16-BS!{P}16)-BS!{L}49-{L}26'); ws.cell(fr['cfo'],c,f'=SUM({L}8:{L}13)')
    ws.cell(fr['cash_capex'],c,f'=-BS!{L}48'); ws.cell(fr['marketable_flow'],c,f'=-(BS!{L}9-BS!{P}9)'); ws.cell(fr['nonmarketable_flow'],c,f'=-(BS!{L}14-BS!{P}14)'); ws.cell(fr['goodwill_flow'],c,f'=-(BS!{L}17-BS!{P}17)'); ws.cell(fr['cfi'],c,f'=SUM({L}18:{L}21)')
    ws.cell(fr['debt_sched'],c,f'=BS!{L}55'); ws.cell(fr['fin_principal'],c,f'=-{aref("fin_principal",y,q)}'); ws.cell(fr['dividends'],c,f'=-IS!{L}21*{aref("dps",y,q)}'); ws.cell(fr['buybacks'],c,f'=-{aref("buybacks",y,q)}'); ws.cell(fr['tax_withholding'],c,f'=-{L}10*{aref("withholding_pct",y,q)}'); ws.cell(fr['cff_before'],c,f'=SUM({L}25:{L}29)'); ws.cell(fr['pre_funding_cash'],c,f'=BS!{P}8+{L}15+{L}22+{L}30'); ws.cell(fr['min_cash'],c,f'={aref("min_cash",y,q)}'); ws.cell(fr['debt_draw'],c,f'=MAX(0,{L}32-{L}31)'); ws.cell(fr['cff'],c,f'={L}30+{L}33'); ws.cell(fr['ending_cash'],c,f'={L}31+{L}33'); ws.cell(fr['fcf'],c,f'={L}15+{L}18+{L}26'); ws.cell(fr['capex_total'],c,f'=-{L}18-{L}26')
for y in YEARS:
    for k in ['ni','da','sbc','cfo','cash_capex','cfi','debt_sched','fin_principal','dividends','buybacks','tax_withholding','cff','fcf','capex_total']: flow_annual(ws,fr[k],y)
    stock_annual(ws,fr['ending_cash'],y)
style_rows(ws,list(fr.values())); subtotal(ws,15); subtotal(ws,22); subtotal(ws,30); subtotal(ws,34); subtotal(ws,35); subtotal(ws,38)

# DCF uses the same annual house view, now sourced from derived annual columns.
ws=wb['DCF']; title(ws,'DCF | FCFF Intrinsic Valuation','Annual DCF linked to quarterly roll-ups. Q4 2026 stub; mid-year discounting; pre-Class-C-split basis.')
for c in range(2,8): ws.column_dimensions[get_column_letter(c)].width=16
ws['A5']='Line item'; dys=[2026,2027,2028,2029,2030]
for i,y in enumerate(dys,2): ws.cell(5,i,'Q4 2026E' if y==2026 else f'{y}E')
ws['G5']='Terminal'
for c in range(1,8): ws.cell(5,c).fill=PatternFill('solid',fgColor=NAVY); ws.cell(5,c).font=Font(name='Arial',size=10,bold=True,color=WHITE)
dr={'revenue':7,'ebit':8,'tax':9,'nopat':10,'da':11,'cash_capex':12,'fin_principal':13,'nwc_change':14,'fcff':15,'period':16,'df':17,'pv_fcff':18,'tnopat':21,'tda':22,'tcapex_ratio':23,'tcapex':24,'tnwc':25,'tfcff':26,'tg':27,'gtv':28,'pvg':29,'exit_multiple':30,'etv':31,'pve':32,'ev_g':35,'ev_e':36,'bridge_cash':37,'bridge_nonmarketable':38,'bridge_debt':39,'eq_g':40,'eq_e':41,'shares':42,'price_g':43,'price_e':44,'market_price':45,'upside_g':46,'upside_e':47,'tv_share_g':48,'tv_share_e':49,'review':50}
section(ws,6,'Unlevered free cash flow',7); section(ws,20,'Normalized terminal cash flow',7); section(ws,34,'Enterprise value to per-share bridge',7)
dlabels={'revenue':'Revenue','ebit':'Operating income / EBIT','tax':'Normalized operating tax rate','nopat':'NOPAT','da':'D&A','cash_capex':'Cash capital expenditures','fin_principal':'Finance-lease principal','nwc_change':'Increase / (decrease) in operating NWC','fcff':'Unlevered free cash flow / FCFF','period':'Discount period (years)','df':'Discount factor','pv_fcff':'PV of FCFF','tnopat':'Terminal NOPAT','tda':'Terminal D&A','tcapex_ratio':'Terminal capex / D&A','tcapex':'Terminal capex','tnwc':'Terminal NWC investment','tfcff':'Normalized terminal FCFF','tg':'Terminal growth','gtv':'Gordon terminal value','pvg':'PV of Gordon terminal value','exit_multiple':'Terminal EV / EBITDA','etv':'Exit-multiple terminal value','pve':'PV of exit-multiple terminal value','ev_g':'Enterprise value — Gordon','ev_e':'Enterprise value — exit multiple','bridge_cash':'Plus: cash + marketable securities','bridge_nonmarketable':'Plus: non-marketable equity investments','bridge_debt':'Less: long-term debt + finance leases','eq_g':'Equity value — Gordon','eq_e':'Equity value — exit multiple','shares':'Diluted shares (mn)','price_g':'Implied value / share — Gordon','price_e':'Implied value / share — exit multiple','market_price':'Market price (2026-10-29)','upside_g':'Upside / (downside) — Gordon','upside_e':'Upside / (downside) — exit multiple','tv_share_g':'Terminal PV / EV — Gordon','tv_share_e':'Terminal PV / EV — exit multiple','review':'Valuation review status'}
for k,r in dr.items(): ws.cell(r,1,dlabels[k])
for idx,y in enumerate(dys,2):
    c=get_column_letter(idx); ac=get_column_letter(ACOL[y]); qc=get_column_letter(QCOL[(y,4)])
    if y==2026:
        ws.cell(dr['revenue'],idx,f'=IS!{qc}8'); ws.cell(dr['ebit'],idx,f'=IS!{qc}15'); ws.cell(dr['da'],idx,f'=IS!{qc}25'); ws.cell(dr['cash_capex'],idx,f'=-BS!{qc}48'); ws.cell(dr['fin_principal'],idx,f'=CF!{qc}26'); ws.cell(dr['nwc_change'],idx,f'=BS!{qc}42-BS!L42'); ws.cell(dr['period'],idx,'=(DATE(2026,11,15)-DATE(2026,10,29))/365'); ws.cell(dr['tax'],idx,'=0.16')
    else:
        ws.cell(dr['revenue'],idx,f'=IS!{ac}8'); ws.cell(dr['ebit'],idx,f'=IS!{ac}15'); ws.cell(dr['da'],idx,f'=IS!{ac}25'); ws.cell(dr['cash_capex'],idx,f'=-BS!{ac}48'); ws.cell(dr['fin_principal'],idx,f'=CF!{ac}26'); ws.cell(dr['nwc_change'],idx,f'=BS!{ac}42-BS!{get_column_letter(ACOL[y-1])}42'); ws.cell(dr['period'],idx,f'=(DATE({y},6,30)-DATE(2026,10,29))/365'); ws.cell(dr['tax'],idx,f'=IS!{ac}18/IS!{ac}17')
    ws.cell(dr['nopat'],idx,f'={c}8*(1-{c}9)'); ws.cell(dr['fcff'],idx,f'={c}10+{c}11+{c}12+{c}13-{c}14'); ws.cell(dr['df'],idx,f'=1/(1+$B$66)^{c}16'); ws.cell(dr['pv_fcff'],idx,f'={c}15*{c}17')
ws['G21']='=F10*(1+$B$67)'; ws['G22']='=F11*(1+$B$67)'; ws['G23']=1.10; ws['G24']='=-G22*G23'; ws['G25']='=F7*$B$67*0.02'; ws['G26']='=G21+G22+G24-G25'; ws['G27']='=$B$67'; ws['G28']='=G26/($B$66-G27)'; ws['G29']='=G28/(1+$B$66)^$B$68'; ws['G30']=8.0; ws['G31']='=(F8+F11)*(1+$B$67)*G30'; ws['G32']='=G31/(1+$B$66)^$B$68'
ws['B35']='=SUM(B18:F18)+G29'; ws['B36']='=SUM(B18:F18)+G32'; ws['B37']=82449; ws['B38']=32624; ws['B39']=-83669; ws['B40']='=B35+B37+B38+B39'; ws['B41']='=B36+B37+B38+B39'; ws['B42']=2573; ws['B43']='=B40/B42'; ws['B44']='=B41/B42'; ws['B45']=624.52; ws['B46']='=B43/B45-1'; ws['B47']='=B44/B45-1'; ws['B48']='=G29/B35'; ws['B49']='=G32/B36'; ws['B50']='=IF(OR(B48>0.8,B46<-0.5,B40/B45/B42<0.5),"VALUATION_REVIEW_REQUIRED",IF(OR(B48>0.5,B40/B45/B42<0.75),"REVIEW","OK"))'
section(ws,53,'WACC build-up',7)
wlabels={54:'Risk-free rate',55:'Levered beta',56:'Equity risk premium',57:'Size premium',58:'Company-specific risk premium',59:'Cost of equity',60:'Pre-tax cost of debt',61:'Marginal tax rate',62:'After-tax cost of debt',63:'Equity weight',64:'Debt weight',65:'Suggested WACC',66:'Chosen WACC',67:'Terminal growth',68:'Terminal discount period',69:'Market price date'}
for r,l in wlabels.items(): ws.cell(r,1,l)
ws['B54']=0.0498; ws['B55']=1.185; ws['B56']=0.05; ws['B57']=0; ws['B58']=0; ws['B59']='=B54+B55*B56+B57+B58'; ws['B60']=0.0615; ws['B61']=0.21; ws['B62']='=B60*(1-B61)'; ws['B63']='=1596793.421824/(1596793.421824+114842.001408)'; ws['B64']='=1-B63'; ws['B65']='=B63*B59+B64*B62'; ws['B66']='=B65'; ws['B67']=0.03; ws['B68']='=(DATE(2030,12,31)-DATE(2026,10,29))/365'; ws['B69']=datetime(2026,10,29); ws['B69'].number_format='yyyy-mm-dd'
for r in [54,56,57,58,59,60,61,62,63,64,65,66,67]: ws.cell(r,2).number_format='0.0%'
for r in [9,46,47,48,49]:
    for c in range(2,7): ws.cell(r,c).number_format='0.0%'
for r in [43,44,45]:
    for c in range(2,7): ws.cell(r,c).number_format='0.00'
for r in range(7,51):
    for c in range(2,7):
        if r not in [9,43,44,45,46,47,48,49]: ws.cell(r,c).number_format='#,##0;(#,##0);-'
subtotal(ws,15,list(range(2,7))); subtotal(ws,18,list(range(2,7))); subtotal(ws,26,list(range(2,8))); subtotal(ws,43,[2]); subtotal(ws,44,[2])

# Sensitivity
ws=wb['Sensitivity']; title(ws,'Sensitivity | WACC × Terminal Growth','Live formulas using quarterly-derived annual FCFF. USD/share.')
ws['A5']='WACC / g'; gvals=[0.02,0.025,0.03,0.035,0.04]; wvals=[0.085,0.095,0.105,0.115,0.125]
for j,g in enumerate(gvals,2): ws.cell(5,j,g); ws.cell(5,j).number_format='0.0%'
for i,w in enumerate(wvals,6):
    ws.cell(i,1,w); ws.cell(i,1).number_format='0.0%'
    for j,g in enumerate(gvals,2):
        terms=[f'DCF!{c}$15/(1+$A{i})^DCF!{c}$16' for c in ['B','C','D','E','F']]
        terms.append(f'(DCF!$G$26/($A{i}-{get_column_letter(j)}$5))/(1+$A{i})^DCF!$B$68')
        ws.cell(i,j,f'=(({"+".join(terms)})+DCF!$B$37+DCF!$B$38+DCF!$B$39)/DCF!$B$42'); ws.cell(i,j).number_format='0.00'
for c in range(1,7): ws.cell(5,c).fill=PatternFill('solid',fgColor=NAVY); ws.cell(5,c).font=Font(name='Arial',size=10,bold=True,color=WHITE)
ws['A13']='Direction check'; ws['B13']='=IF(AND(B6>B10,F6>B6),"PASS","REVIEW")'

# Scenarios
ws=wb['Scenarios']; title(ws,'Scenarios | 基准、乐观、悲观','Scenario deltas apply to quarterly-derived annual forecasts; D&A and capex paths remain unchanged.')
scenario_defs=[('Base',0,0,0,0,0),('Upside',0.02,0.02,-0.01,0.005,-0.05),('Downside',-0.02,-0.02,0.01,-0.005,0.10)]
scenario_outputs={}; start=6
for sidx,(name,gdelta,mdelta,wdelta,tgdelta,cratio_delta) in enumerate(scenario_defs):
    r0=start+sidx*26; section(ws,r0,f'{name} case',7)
    ws.cell(r0+1,1,'Case inputs'); ws.cell(r0+1,2,'FoA annual growth delta'); ws.cell(r0+1,3,gdelta); ws.cell(r0+1,4,'FoA margin delta'); ws.cell(r0+1,5,mdelta); ws.cell(r0+1,6,'WACC'); ws.cell(r0+1,7,f'=DCF!$B$66+{wdelta}')
    ws.cell(r0+2,1,'Terminal inputs'); ws.cell(r0+2,2,'Terminal g'); ws.cell(r0+2,3,f'=DCF!$B$67+{tgdelta}'); ws.cell(r0+2,4,'Terminal capex / D&A'); ws.cell(r0+2,5,f'=DCF!$G$23+{cratio_delta}')
    for idx,y in enumerate(dys,2): ws.cell(r0+4,idx,'Q4 2026E' if y==2026 else f'{y}E')
    for k,l in enumerate(['Revenue','EBIT','NOPAT','D&A','Cash capex + finance principal','NWC change','FCFF','Discount factor','PV FCFF']): ws.cell(r0+5+k,1,l)
    for idx,y in enumerate(dys,2):
        c=get_column_letter(idx); ac=get_column_letter(ACOL[y]); exponent=y-2026
        ws.cell(r0+5,idx,f'=DCF!{c}7*(1+$C${r0+1})^{exponent}'); ws.cell(r0+6,idx,f'=DCF!{c}8+({c}{r0+5}-DCF!{c}7)*(DCF!{c}8/DCF!{c}7)+Segment!{ac}10*(1+$C${r0+1})^{exponent}*$E${r0+1}'); ws.cell(r0+7,idx,f'={c}{r0+6}*(1-DCF!{c}9)'); ws.cell(r0+8,idx,f'=DCF!{c}11'); ws.cell(r0+9,idx,f'=DCF!{c}12+DCF!{c}13'); ws.cell(r0+10,idx,f'=DCF!{c}14+({c}{r0+5}-DCF!{c}7)*0.02'); ws.cell(r0+11,idx,f'={c}{r0+7}+{c}{r0+8}+{c}{r0+9}-{c}{r0+10}'); ws.cell(r0+12,idx,f'=1/(1+$G${r0+1})^DCF!{c}16'); ws.cell(r0+13,idx,f'={c}{r0+11}*{c}{r0+12}')
    ws.cell(r0+15,1,'Terminal FCFF'); ws.cell(r0+15,2,f'=F{r0+7}*(1+$C${r0+2})+F{r0+8}*(1+$C${r0+2})-F{r0+8}*(1+$C${r0+2})*$E${r0+2}-F{r0+5}*$C${r0+2}*0.02'); ws.cell(r0+16,1,'PV terminal value'); ws.cell(r0+16,2,f'=B{r0+15}/($G${r0+1}-$C${r0+2})/(1+$G${r0+1})^DCF!$B$68'); ws.cell(r0+17,1,'Enterprise value'); ws.cell(r0+17,2,f'=SUM(B{r0+13}:F{r0+13})+B{r0+16}'); ws.cell(r0+18,1,'Equity value'); ws.cell(r0+18,2,f'=B{r0+17}+DCF!$B$37+DCF!$B$38+DCF!$B$39'); ws.cell(r0+19,1,'Implied value / share'); ws.cell(r0+19,2,f'=B{r0+18}/DCF!$B$42'); ws.cell(r0+19,2).number_format='0.00'; ws.cell(r0+20,1,'Upside / (downside)'); ws.cell(r0+20,2,f'=B{r0+19}/DCF!$B$45-1'); ws.cell(r0+20,2).number_format='0.0%'; scenario_outputs[name]=r0+19

# Market implied
ws=wb['Market_Implied']; title(ws,'Market Implied | 市场定价反推','No automatic fitting to market; reverse-DCF uses quarterly-derived base-case cash flows.')
mi=['Market capitalization','Equity bridge items','Market-implied enterprise value','PV of explicit base-case FCFF','Required terminal value at market price','Required terminal FCFF at base WACC and g','Base normalized terminal FCFF','Required / base terminal FCFF','Market-implied terminal growth','Unexplained market premium / (discount)']
for i,l in enumerate(mi,7): ws.cell(i,1,l)
ws['B7']=1596793.421824; ws['B8']='=DCF!B37+DCF!B38+DCF!B39'; ws['B9']='=B7-B8'; ws['B10']='=SUM(DCF!B18:F18)'; ws['B11']='=(B9-B10)*(1+DCF!B66)^DCF!B68'; ws['B12']='=B11*(DCF!B66-DCF!B67)'; ws['B13']='=DCF!G26'; ws['B14']='=B12/B13'; ws['B15']='=IFERROR((B11*DCF!B66-B13)/(B11+B13),"NM")'; ws['B16']='=B9-DCF!B35'; ws['B14'].number_format='0.00x'; ws['B15'].number_format='0.0%'

# Checks across every quarter and annual column
ws=wb['Checks']; title(ws,'Checks | 季度与年度模型检查','Model tolerance = 0.1 USD mn; annual reported tie tolerance = 2 USD mn for comparative-vintage rounding.'); periods(ws)
checkrows=[('BS balance','balance'),('Cash tie','cash'),('Net income link','ni'),('Segment revenue tie','segrev'),('Segment EBIT tie','segebit'),('PP&E roll-forward','ppe'),('Debt roll-forward','debt')]
for i,(label,kind) in enumerate(checkrows,8):
    ws.cell(i,1,label)
    for c in ALLCOLS:
        L=get_column_letter(c)
        if kind=='balance': f=f'=BS!{L}40'
        elif kind=='cash': f=f'=CF!{L}35-BS!{L}8'
        elif kind=='ni': f=f'=CF!{L}8-IS!{L}19'
        elif kind=='segrev': f=f'=Segment!{L}12-IS!{L}8'
        elif kind=='segebit': f=f'=Segment!{L}18-IS!{L}15'
        elif kind=='ppe': f=f'=BS!{L}15-BS!{L}51' if c>=QCOL[(2026,4)] and c<QCOL[(2030,4)]+1 else '=0'
        elif kind=='debt': f=f'=BS!{L}28-BS!{L}57' if c>=QCOL[(2026,4)] and c<QCOL[(2030,4)]+1 else '=0'
        ws.cell(i,c,f); ws.cell(i,c).number_format='0.0'
for i,y in enumerate([2024,2025],17):
    c=get_column_letter(ACOL[y]); ws.cell(i,1,f'FY{y} reported revenue tie'); ws.cell(i,2,f'=IS!{c}8-Raw_Data!{c}{rawmap["revenue"]}'); ws.cell(i,3,f'FY{y} reported NI tie'); ws.cell(i,4,f'=IS!{c}19-Raw_Data!{c}{rawmap["ni"]}'); ws.cell(i,5,f'FY{y} reported assets tie'); ws.cell(i,6,f'=BS!{c}19-Raw_Data!{c}{rawmap["assets"]}')
ws['A21']='WACC > terminal growth'; ws['B21']='=DCF!B66-DCF!B67'; ws['C21']='=IF(B21>0,"PASS","REVIEW")'
ws['A22']='Base scenario vs DCF per-share'; ws['B22']='=Scenarios!B25-DCF!B43'; ws['C22']='=IF(ABS(B22)<0.1,"PASS","REVIEW")'
ws['A23']='Overall formula integrity'; ws['B23']='=IF(SUMPRODUCT(ABS(B8:AK14))<0.1,"PASS","REVIEW")'
ws['A24']='Annual reported integrity'; ws['B24']='=IF(SUM(ABS(B17),ABS(B18),ABS(D17),ABS(D18),ABS(F17),ABS(F18))<=2,"PASS","REVIEW")'
ws['A26']='Valuation status'; ws['B26']='=DCF!B50'; ws['A27']='Model status'; ws['B27']='=IF(AND(B23="PASS",B24="PASS",C21="PASS",C22="PASS"),"PASS","REVIEW")'

# Summary and cover
ws=wb['Summary']; title(ws,'Summary | 季度预测与估值摘要','Quarterly columns are the build; annual columns are formula roll-ups.'); periods(ws)
for i,(label,sheet,row) in enumerate([('Revenue','IS',8),('Revenue growth','IS',32),('Operating income','IS',15),('Operating margin','IS',30),('Net income','IS',19),('Diluted EPS','IS',22),('Free cash flow','CF',38)],8):
    ws.cell(i,1,label)
    for c in ALLCOLS:
        L=get_column_letter(c); ws.cell(i,c,f'={sheet}!{L}{row}'); ws.cell(i,c).number_format='0.0%' if 'growth' in label or 'margin' in label else ('0.00' if 'EPS' in label else '#,##0;(#,##0);-')
section(ws,17,'Valuation summary')
for i,(label,formula) in enumerate([('Gordon enterprise value','=DCF!B35'),('Gordon equity value','=DCF!B40'),('Gordon implied value / share','=DCF!B43'),('Exit-multiple implied value / share','=DCF!B44'),('Market price','=DCF!B45'),('Gordon upside / (downside)','=DCF!B46'),('WACC','=DCF!B66'),('Terminal growth','=DCF!B67'),('Terminal PV / EV','=DCF!B48'),('Valuation status','=DCF!B50')],18): ws.cell(i,1,label); ws.cell(i,2,formula); ws.cell(i,2).number_format='0.0%' if any(x in label for x in ['upside','WACC','growth','PV / EV']) else ('0.00' if 'share' in label or 'price' in label else '#,##0')
section(ws,30,'Scenario value / share')
for i,name in enumerate(['Base','Upside','Downside'],31): ws.cell(i,1,name); ws.cell(i,2,f'=Scenarios!B{scenario_outputs[name]}'); ws.cell(i,2).number_format='0.00'; ws.cell(i,3,f'=B{i}/DCF!B45-1'); ws.cell(i,3).number_format='0.0%'

ws=wb['Cover']; ws.freeze_panes=None; ws.merge_cells('A1:J1'); ws['A1']='META | Quarterly Financial Model'; ws['A1'].fill=PatternFill('solid',fgColor=NAVY); ws['A1'].font=Font(name='Arial',size=24,bold=True,color=WHITE); ws.row_dimensions[1].height=36
ws.merge_cells('A2:J2'); ws['A2']='2024Q1—2030Q4 | Quarterly build with derived annual statements and DCF'; ws['A2'].font=Font(name='Arial',size=13,bold=True)
for i,(a,b) in enumerate([('Listing','Nasdaq: META | US GAAP | USD mn'),('Actual periods','2024Q1—2026Q3; Q4 flows derived as FY − 9M'),('Forecast periods','2026Q4—2030Q4 quarterly drivers'),('Annual convention','Flows = sum; stocks = Q4; shares = average; ratios/EPS recomputed'),('Annual model','meta_model.xlsx preserved unchanged'),('Run ID','META-20261030-QUARTERLY-V1')],4): ws.cell(i,1,a); ws.cell(i,1).font=Font(name='Arial',size=10,bold=True); ws.cell(i,2,b)
section(ws,12,'Key outputs',10)
for i,(label,formula,fmt) in enumerate([('FY2030 revenue',f'=IS!{get_column_letter(ACOL[2030])}8','#,##0'),('FY2030 operating income',f'=IS!{get_column_letter(ACOL[2030])}15','#,##0'),('FY2030 diluted EPS',f'=IS!{get_column_letter(ACOL[2030])}22','0.00'),('Gordon implied value / share','=DCF!B43','0.00'),('Market price','=DCF!B45','0.00'),('Gordon upside / (downside)','=DCF!B46','0.0%'),('WACC','=DCF!B66','0.0%'),('Terminal PV / EV','=DCF!B48','0.0%'),('Model status','=Checks!B27','General'),('Valuation status','=DCF!B50','General')],13): ws.cell(i,1,label); ws.cell(i,2,formula); ws.cell(i,2).number_format=fmt
section(ws,26,'Formatting conventions',10)
for i,n in enumerate(['Blue font = direct Raw_Data citation; amber fill = quarterly forecast input; black = formula.','Quarterly block → blank spacer column → annual roll-up block → source/rationale.','2026 GAAP includes the Q3 $9.89bn legal charge only where reported; no charge is forecast beyond Q3.','Five-year DCF retains high terminal-value concentration; read scenarios and reverse-DCF together.'],27): ws.merge_cells(start_row=i,start_column=1,end_row=i,end_column=10); ws.cell(i,1,n); ws.cell(i,1).font=Font(name='Arial',size=9,color=NOTEGREY)

# Sources
ws=wb['Data_Sources']; title(ws,'Data Sources | 季度数据来源','T1 = SEC filing; T2 = issuer release; T3 = market/external research; internal annual model used only for quarterly assumption calibration.')
headers=['Source ID','Tier','Document / dataset','Period / as-of','URL','Local evidence','SHA-256']
for i,h in enumerate(headers,1): ws.cell(5,i,h); ws.cell(5,i).fill=PatternFill('solid',fgColor=NAVY); ws.cell(5,i).font=Font(name='Arial',size=10,bold=True,color=WHITE)
for col,width in {'C':36,'D':20,'E':68,'F':38,'G':66}.items(): ws.column_dimensions[col].width=width
sources=[('S1','T1','Meta FY2025 Form 10-K','FY2023–FY2025','https://www.sec.gov/Archives/edgar/data/1326801/0001628280-26-003942-index.html','raw/meta_fy2025_all.csv'),('S2','T1','Meta quarterly Forms 10-Q','2024Q1—2026Q3','https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001326801&type=10-Q&dateb=&owner=include&count=40','raw/meta_q1fy2024_all.csv and subsequent quarterly CSV files'),('S3','T1','Meta FY2024 Form 10-K','2023 balance sheet','https://www.sec.gov/Archives/edgar/data/1326801/0001326801-25-000017-index.html','raw/meta_fy2024_bs.csv'),('S4','T2','Meta Q3 2026 earnings release','2026-10-21','https://www.sec.gov/Archives/edgar/data/1326801/000162828026066700/meta-09302026xexhibit991.htm','evidence/q3_2026_release_excerpt.md'),('S6','T3','Yahoo Finance stock info','2026-10-29','https://finance.yahoo.com/quote/META/','raw/meta_stock_info.csv'),('S7','T3','Yahoo Finance historical close','2026-10-29','https://finance.yahoo.com/quote/META/history/','raw/meta_prices_5d.csv'),('S8','T3','Federal Reserve 10Y UST via finance-data envelope','2026-10-29','https://www.federalreserve.gov/datadownload/','evidence/us_rates_excerpt.json'),('S9','T3','Kroll recommended U.S. ERP reported by BVR','2025-09-10','https://www.bvresources.com/articles/bvwire/kroll-lowers-recommended-us-erp-to-50','evidence/erp_excerpt.md'),('S10','T3','META 5.25% 2036 bond yield — Public/Moment','2026-10-28','https://public.com/bonds/corporate/meta-platforms-inc/meta-5.25-05-15-2036-30303mah5','evidence/bond_yield_excerpt.md'),('S11','T1','IRS corporate statutory tax rate','Current federal rate','https://www.irs.gov/irb/2018-18_IRB','evidence/irs_tax_excerpt.md'),('S12','Internal','Annual META model — assumption calibration only','2026-10-30','','meta_model.xlsx')]
for r,(sid,tier,doc,period,url,path) in enumerate(sources,6):
    full=os.path.join(ROOT,path); sha=''
    if os.path.isfile(full): sha=hashlib.sha256(open(full,'rb').read()).hexdigest()
    for c,v in enumerate([sid,tier,doc,period,url,path,sha],1): ws.cell(r,c,v); ws.cell(r,c).font=Font(name='Arial',size=9)

# Global style and save
for ws in wb:
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None and cell.font.name!='Arial': cell.font=Font(name='Arial',size=cell.font.sz or 10,bold=cell.font.bold,color=cell.font.color)
    ws.sheet_properties.pageSetUpPr.fitToPage=True; ws.page_setup.fitToWidth=1; ws.page_setup.fitToHeight=0
wb.save(OUT)
manifest={'schema_version':'1.0','run_id':'META-20261030-QUARTERLY-V1','status':'in_progress','metadata':{'company':'Meta Platforms, Inc.','ticker':'META','gaap':'US GAAP','fiscal_year_end':'12-31','currency':'USD','unit':'USD millions','period_type':'quarterly+annual','historical_quarters':'2024Q1–2026Q3','forecast_quarters':'2026Q4–2030Q4'},'canonical_workbook':'meta_model_quarterly.xlsx','cash_policy':'CF-derived with quarterly funding-response debt draw','bs_plug_policy':'forbidden','annual_policy':'Flows sum quarters; stocks Q4; shares average; ratios and EPS recomputed','annual_model_preserved':'meta_model.xlsx','dcf_market':{'price_cell':'DCF!B45','price_date_cell':'DCF!B69','price_date':'2026-10-29','evidence_id':'S7'},'dcf_terminal':{'explicit_forecast_years':5,'tv_pv_cell':'DCF!G29','ev_cell':'DCF!B35'}}
json.dump(manifest,open(os.path.join(ROOT,'manifest_quarterly.json'),'w',encoding='utf-8'),ensure_ascii=False,indent=2)
print(OUT)
print('actual_quarters',len(ACT_Q),'forecast_quarters',len(FC_Q),'assumptions',len(assump),'raw_rows',len(ordered))
