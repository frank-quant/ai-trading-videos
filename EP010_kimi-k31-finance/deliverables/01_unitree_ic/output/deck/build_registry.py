from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
OUT = Path(__file__).resolve().parent / "data-registry.json"
RETRIEVED = "2026-10-30T11:30:00+08:00"
Q3 = RESEARCH / "20261029_宇树科技_2026年第三季度报告.txt"
IPO = RESEARCH / "20260525_宇树科技_招股说明书上会稿.txt"
QA1 = RESEARCH / "20260320_宇树科技_首轮问询函回复.txt"
QA2 = RESEARCH / "20260320_宇树科技_第二轮问询函回复.txt"
DW_AUG = RESEARCH / "20260809_东吴证券_人形机器人产业化奇点已至.txt"
DW_OCT = RESEARCH / "20261030_东吴证券_2026年三季报点评.txt"
HX = RESEARCH / "20260919_华鑫证券_茁壮成长的中国树.txt"
HJ = RESEARCH / "20260812_华金证券_新股覆盖研究.txt"
TPY = RESEARCH / "20261022_太平洋证券_宇树科技深度报告.txt"
QUOTE = RESEARCH / "quote.json"
CONS = RESEARCH / "consensus.json"
KLINE = RESEARCH / "kline.json"
JPM = RESEARCH / "snapshots/20261026_JPM_宇树评级与预测.txt"
PHYSAI = RESEARCH / "snapshots/20261022_物理AI大会_公司公开演讲.txt"
UNLOCK = RESEARCH / "snapshots/20261026_解禁与估值风险_财新.txt"

points = []
def add(id, value, label, tier, source_type, sources, as_of, category, unit,
        used_in, locator_file=None, raw=None, currency=None, derived=False,
        formula=None, inputs=None, cross_check=None, notes=None, estimate=None):
    display = None
    if derived and unit == "%":
        try:
            display = f"{float(value)}%"
            if isinstance(formula, str):
                formula = formula.replace(" * 100", "")
        except (ValueError, TypeError):
            pass
    p = {
        "id": id, "value": value, "label": label, "tier": tier,
        "source_type": source_type, "sources": sources, "as_of": as_of,
        "retrieved_at": RETRIEVED, "category": category,
        "caliber": {"unit": unit}, "derived": derived,
        "used_in": used_in, "status": "recorded" if locator_file else "skip"
    }
    if display:
        p["display"] = display
    if currency:
        p["caliber"]["currency"] = currency
    elif unit.startswith("人民币") or unit.startswith("CNY"):
        p["caliber"]["currency"] = "CNY"
    if category == "stock_price":
        p["caliber"]["adjust"] = "none"
    elif category == "historical_price_series":
        p["caliber"]["adjust"] = "forward"
    if estimate:
        p["caliber"]["estimate"] = estimate
    if derived:
        p["formula"] = formula
        p["inputs"] = inputs or []
    if locator_file and raw is not None:
        path = Path(locator_file)
        p["locator"] = {
            "kind": "text_span", "file": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16], "raw": raw
        }
    if cross_check:
        p["cross_check"] = cross_check
    if notes:
        p["notes"] = notes
    elif derived and not cross_check:
        p["notes"] = "派生值可核性来自 formula 与 inputs 血缘，无独立第二信源。"
    points.append(p)

# 行情与估值快照
add("price_snapshot", "667.10", "2026-10-30 盘中股价（元/股）", "T2", "api", ["[行情] Wind 盘中快照"], "2026-10-30", "stock_price", "CNY/股", ["page-02", "page-03", "page-22", "page-23"], QUOTE, "667.10", "CNY", estimate="actual")
add("shares_outstanding", "404464340", "最新总股本（股）", "T1", "filing", ["[公告原文] 2026年三季报 合并资产负债表"], "2026-09-30", "share_count", "股", ["page-03", "page-22", "page-23"], Q3, "404,464,340.00", estimate="actual")
add("free_float_shares", "30090000", "流通 A 股约数（股）", "T3", "vendor", ["[研报] 东吴证券 2026年三季报点评 市场数据", "[交叉核验] Wind 流通市值与盘中价"], "2026-10-29", "share_count", "股", ["page-03"], DW_OCT, "流通 A 股(百万股) 30.09", cross_check={"source": "Wind quote.json 流通市值与价格反推", "url": "output/research/quote.json"}, notes="券商披露约数，Wind 流通市值/价格交叉核验")
add("pe_ttm", "482.188", "TTM 市盈率", "T2", "api", ["[行情] Wind 市盈率 TTM"], "2026-10-30", "trailing_pe", "x", ["page-02", "page-03"], QUOTE, "482.188", estimate="actual")
add("consensus_eps_fy2026", "1.68", "FY2026 一致预期 EPS（元/股）", "T3", "api", ["[一致预期] 同花顺 6 家均值", "[交叉核验] 东吴证券与华鑫证券个股预测"], "2026-10-30", "consensus_estimate", "CNY/股", ["page-03"], CONS, '"eps": 1.68', "CNY", cross_check={"source": "东吴证券 2026-10-29 与华鑫证券 2026-09-19 预测", "url": "output/research/20261030_东吴证券_2026年三季报点评.txt"}, estimate="forecast")
add("market_cap", "2698.18161214", "盘中总市值（亿元）", "T2", "derived", ["[计算] 盘中价×最新总股本"], "2026-10-30", "market_cap", "人民币亿元", ["page-03", "page-21", "page-22"], derived=True, formula="price_snapshot * shares_outstanding / 100000000", inputs=["price_snapshot", "shares_outstanding"], estimate="actual")
add("free_float_pct", "7.439469200177203", "自由流通股占总股本比例（%）", "T3", "derived", ["[计算] 流通 A 股/总股本"], "2026-10-29", "share_count", "%", ["page-03"], derived=True, formula="free_float_shares / shares_outstanding * 100", inputs=["free_float_shares", "shares_outstanding"], estimate="actual")
add("pe_fy2026_consensus", "397.08333333333337", "FY2026 一致预期 PE", "T3", "derived", ["[计算] 盘中价/FY2026 共识 EPS"], "2026-10-30", "forward_pe", "x", ["page-03"], derived=True, formula="price_snapshot / consensus_eps_fy2026", inputs=["price_snapshot", "consensus_eps_fy2026"], estimate="forecast")

# 历史财务与经营
add("revenue_history", "1.23 / 1.59 / 3.93 / 16.99", "2022—2025 营业收入（亿元）", "T3", "filing", ["[公告原文] 招股说明书 2023—2025 营收", "[研报] 东吴证券 2022 年营收"], "2025-12-31", "revenue_actual", "人民币亿元", ["page-16"], IPO, "营业收入 169,926.93 39,277.07 15,913.44", "CNY", cross_check={"source": "东吴证券 2026-08-09 图8", "url": "output/research/20260809_东吴证券_人形机器人产业化奇点已至.txt"}, estimate="actual")
add("revenue_cagr_2022_2025", "139.94", "2022—2025 营收 CAGR（%）", "T3", "derived", ["[研报] 东吴证券 CAGR", "[计算复核] 2022—2025 营收序列"], "2025-12-31", "revenue_actual", "%", ["page-16"], DW_AUG, "CAGR 达", derived=True, formula="(16.99 / 1.23) ** (1 / 3) - 1", inputs=["revenue_history"], estimate="actual")
add("segment_revenue_2025", "人形 8.678319 / 四足 6.976256 / 组件 1.037367", "2025 分产品收入（亿元）", "T1", "filing", ["[公告原文] 招股说明书 主营业务收入构成"], "2025-12-31", "revenue_actual", "人民币亿元", ["page-06", "page-16"], IPO, "人形机器人 86,783.19 51.78%", "CNY", estimate="actual")
add("segment_mix_2025", "人形 51.78 / 四足 41.62 / 组件 6.19", "2025 主营收入结构（%）", "T1", "filing", ["[公告原文] 招股说明书 主营业务收入构成"], "2025-12-31", "revenue_actual", "%", ["page-05", "page-06", "page-16"], IPO, "四足机器人 69,762.56 41.62%", estimate="actual")
add("human_quad_share", "93.40", "人形与四足合计主营收入占比（%）", "T1", "derived", ["[计算] 人形占比+四足占比"], "2025-12-31", "revenue_actual", "%", ["page-06"], derived=True, formula="0.5178 + 0.4162", inputs=["segment_mix_2025"], estimate="actual")
add("segment_margin_2025", "人形 63.18 / 四足 56.72 / 组件 59.36", "2025 分产品毛利率（%）", "T1", "filing", ["[公告原文] 招股说明书 主营业务毛利率分析"], "2025-12-31", "margin_actual", "%", ["page-06", "page-12"], IPO, "人形机器人 63.18%", estimate="actual")
add("human_asp", "59.34 / 26.04 / 16.64", "2023—2025 人形平均售价（万元/台）", "T1", "filing", ["[公告原文] 招股说明书 主要产品价格变动"], "2025-12-31", "equipment_price", "万元/台", ["page-12"], IPO, "单价（万元/台）  16.64  26.04 59.34", "CNY", estimate="actual")
add("human_volume", "5 / 412 / 5215", "2023—2025 人形销量（台）", "T1", "filing", ["[公告原文] 招股说明书 主要产品生产情况"], "2025-12-31", "kpi_actual", "无量纲", ["page-09", "page-12"], IPO, "销量 5,215 412 5", estimate="actual")
add("human_shipments_2025", "5511", "2025 人形出货量（台）", "T1", "filing", ["[公告原文] 招股说明书 主要产品生产情况"], "2025-12-31", "kpi_actual", "无量纲", ["page-02", "page-09"], IPO, "出货量 5,511 537 9", estimate="actual")
add("human_asp_decline", "-71.95820694304011", "2023—2025 人形均价降幅（%）", "T1", "derived", ["[计算] 2025 均价/2023 均价-1"], "2025-12-31", "equipment_price", "%", ["page-12"], derived=True, formula="(16.64 / 59.34 - 1) * 100", inputs=["human_asp"], estimate="actual")
add("net_profit_2025", "2.782105", "2025 归母净利润（亿元）", "T1", "filing", ["[公告原文] 招股说明书 主要财务数据"], "2025-12-31", "net_income_actual", "人民币亿元", ["page-16", "page-17"], IPO, "归属于母公司所有者净利润 27,821.05", "CNY", estimate="actual")
add("deduct_profit_2025", "5.907528", "2025 扣非归母净利润（亿元）", "T1", "filing", ["[公告原文] 招股说明书 主要财务数据"], "2025-12-31", "net_income_actual", "人民币亿元", ["page-02", "page-16", "page-17"], IPO, "利润 59,075.28 7,847.65 -1,801.91", "CNY", estimate="actual")
add("profit_gap_2025", "3.125423", "2025 扣非与归母净利差额（亿元）", "T1", "derived", ["[计算] 扣非净利润-归母净利润"], "2025-12-31", "net_income_actual", "人民币亿元", ["page-17"], derived=True, formula="deduct_profit_2025 - net_profit_2025", inputs=["deduct_profit_2025", "net_profit_2025"], estimate="actual")
add("deduct_margin_2025", "34.76519493271846", "2025 扣非净利率（%）", "T3", "derived", ["[计算] 扣非净利润/营业收入"], "2025-12-31", "margin_actual", "%", ["page-17"], derived=True, formula="5.907528 / 16.992693 * 100", inputs=["deduct_profit_2025", "revenue_history"], estimate="actual")
add("share_based_payment_2025", "3.490655", "2025 股份支付费用（亿元）", "T1", "filing", ["[公告原文] 招股说明书 非经常性损益说明"], "2025-12-31", "cost_actual", "人民币亿元", ["page-17"], IPO, "34,906.55 万元", "CNY", estimate="actual")
add("gross_margin_2025", "60.44", "2025 综合毛利率（%）", "T1", "filing", ["[公告原文] 招股说明书 同行业毛利率比较"], "2025-12-31", "margin_actual", "%", ["page-17"], IPO, "公司 169,926.93 60.44%", estimate="actual")
add("peer_gross_margin_2025", "44.44", "2025 可比公司平均毛利率（%）", "T1", "filing", ["[公告原文] 招股说明书 同行业毛利率比较"], "2025-12-31", "margin_actual", "%", ["page-17"], IPO, "平均值 77,254.01 44.44%", estimate="actual")

# 行业、竞争与应用
add("industry_shipments", "0.26 / 1.66 / 8.17", "2024/2025/2026E 全球人形出货（万台）", "T3", "web", ["[研报] 东吴证券引 Yano Research", "[交叉核验] 太平洋证券引高工机器人产业研究所"], "2026-12-31", "industry_growth_rate", "无量纲", ["page-08"], DW_AUG, "2026 年进一步增至 8.17 万台", cross_check={"source": "太平洋证券 2026-10-19 行业预测", "url": "output/research/20261022_太平洋证券_宇树科技深度报告.txt"}, notes="第三方预测，机构间产品定义与出货口径不同", estimate="forecast")
add("industry_2030", "60.57 万台 / 1022 亿元", "2030E 全球人形销量与市场空间", "T3", "web", ["[研报] 东吴证券引 GGII", "[研报] 华金证券引 GGII"], "2030-12-31", "annual_industry_data", "无量纲", ["page-08"], DW_AUG, "60.57 万台", cross_check={"source": "华金证券 2026-08-12 第7页", "url": "output/research/20260812_华金证券_新股覆盖研究.txt"}, estimate="forecast")
add("market_share_2025", "宇树 37.54 / 智元 35.21 / 优必选 6.81", "2025 全球人形出货份额（%）", "T3", "web", ["[研报] 太平洋证券引 Omdia", "[公告原文] 第二轮问询回复讨论 Omdia 口径"], "2025-12-31", "market_share", "%", ["page-09"], TPY, "宇树科技 537 26.36% 5511 37.54%", cross_check={"source": "宇树科技第二轮问询回复", "url": "output/research/20260320_宇树科技_第二轮问询函回复.txt"}, notes="Omdia 口径可能包含部分双臂轮式产品，机构统计存在差异", estimate="actual")
add("top2_share", "72.75", "2025 前两名合计份额（%）", "T3", "derived", ["[计算] 宇树份额+智元份额"], "2025-12-31", "market_share", "%", ["page-09"], derived=True, formula="0.3754 + 0.3521", inputs=["market_share_2025"], estimate="actual")
add("human_application_mix", "科研教育 73.60 / 商业消费 17.39 / 行业应用 9.01", "2025Q1—Q3 人形收入应用结构（%）", "T1", "filing", ["[公告原文] 首轮问询函回复 应用收入结构"], "2025-09-30", "kpi_actual", "%", ["page-10"], QA1, "科研教育 43,806.74 73.60%", estimate="actual")
add("human_true_industrial_share", "2.64", "人形智能制造/巡检/物流合计收入占比（%）", "T3", "web", ["[媒体] 36氪引第二轮问询回复", "[媒体] 虎嗅引第二轮问询回复"], "2025-09-30", "kpi_actual", "%", ["page-10"], QA1, "其中企业导览的占比较高，约为 50-70%", cross_check={"source": "36氪与虎嗅对第二轮问询回复的摘录", "url": "https://www.36kr.com/p/3929173534260608"}, notes="官方回复披露行业应用中企业导览约占50%—70%；2.64%为媒体据明细计算", estimate="actual")
add("quad_application_amounts", "科研 15411.94 / 商业 20642.28 / 行业 12744.33 / 合计 48798.55", "2025Q1—Q3 四足应用收入（万元）", "T1", "filing", ["[公告原文] 首轮问询函回复 应用收入结构"], "2025-09-30", "revenue_actual", "人民币万元", ["page-10"], QA1, "行业应用 12,744.33 224.81%", "CNY", estimate="actual")
add("quad_application_mix", "科研教育 31.58 / 商业消费 42.30 / 行业应用 26.11", "2025Q1—Q3 四足收入应用结构（%）", "T1", "derived", ["[计算] 各应用收入/四足合计收入"], "2025-09-30", "kpi_actual", "%", ["page-10"], derived=True, formula="各项应用收入分别除以四足合计收入", inputs=["quad_application_amounts"], estimate="actual")

# 技术、募投与产能
add("company_founded", "2016", "公司成立年份", "T1", "filing", ["[公告原文] 招股说明书 公司发展历程"], "2016-08-01", "historical_anchor", "无量纲", ["page-07", "page-13"], IPO, "2016 年成立之初", estimate="actual")
add("human_launch", "2023", "首款人形 H1 发布年份", "T1", "filing", ["[公告原文] 招股说明书 公司发展历程"], "2023-08-01", "historical_anchor", "无量纲", ["page-07"], IPO, "2023 年自研推出首款人形机器人 H1", estimate="actual")
add("model_rnd_start", "2024", "加强具身大模型研发的起始年份", "T1", "filing", ["[公告原文] 招股说明书 研发投入风险说明"], "2024-01-01", "historical_anchor", "无量纲", ["page-13"], IPO, "自2024 年起开始逐步加强对具身大模型", estimate="actual")
add("model_fund", "20.224593 / 48.13", "模型研发募投金额（亿元）与占比（%）", "T1", "filing", ["[公告原文] 招股说明书 募集资金运用"], "2026-05-25", "capex", "人民币亿元", ["page-14"], IPO, "202,245.93 202,245.93 48.13%", "CNY", estimate="actual")
add("body_fund_share", "26.41", "本体研发募投占比（%）", "T1", "filing", ["[公告原文] 招股说明书 募集资金运用"], "2026-05-25", "capex", "%", ["page-14"], IPO, "110,973.80 110,973.80 26.41%", estimate="actual")
add("capacity_plan", "人形 7.50 万台 / 四足 11.50 万台（年产）", "制造基地设计产能", "T1", "filing", ["[公告原文] 第二轮问询函回复 制造基地规划"], "2026-03-20", "capex", "无量纲", ["page-14"], QA2, "7.50 万台人形机器人及11.50 万台四足", estimate="forecast")
add("physical_ai_direction", "自进化 V1.0 + 超大算力集群", "2026 物理 AI 大会新投入方向", "T3", "news", ["[媒体] 中国证券报 2026-10-22", "[研报] 东吴证券 2026-10-29"], "2026-10-22", "latest_available_reading", "无量纲", ["page-14"], PHYSAI, "物理AI机器人自进化V1.0大模型", cross_check={"source": "东吴证券 2026年三季报点评", "url": "output/research/20261030_东吴证券_2026年三季报点评.txt"}, estimate="actual")

# 2026Q3 与营运资金
add("q3_single", "收入 6.650445 / 归母 1.126920 / 扣非 1.050413", "2026Q3 单季财务（亿元）", "T1", "filing", ["[公告原文] 2026年第三季度报告 主要会计数据"], "2026-09-30", "revenue_actual", "人民币亿元", ["page-18"], Q3, "营业收入 665,044,497.90 69.93", "CNY", estimate="actual")
add("q3_yoy", "收入 +69.93 / 归母 -17.37 / 扣非 -17.42", "2026Q3 单季同比（%）", "T1", "filing", ["[公告原文] 2026年第三季度报告 主要会计数据"], "2026-09-30", "revenue_actual", "%", ["page-18"], Q3, "归属于上市公司股东的扣", estimate="actual")
add("ytd_q3", "收入 18.172900 / 归母 3.866919 / 扣非 3.489716 / 经营现金流 1.937073", "2026 前三季度财务（亿元）", "T1", "filing", ["[公告原文] 2026年第三季度报告 主要会计数据"], "2026-09-30", "revenue_actual", "人民币亿元", ["page-15", "page-18", "page-19"], Q3, "1,817,290,048.48 55.71", "CNY", estimate="actual")
add("ytd_yoy", "收入 +55.71 / 归母 +270.54 / 扣非 -18.78 / 经营现金流 -54.69", "2026 前三季度同比（%）", "T1", "filing", ["[公告原文] 2026年第三季度报告 主要会计数据"], "2026-09-30", "revenue_actual", "%", ["page-02", "page-15", "page-18", "page-19"], Q3, "净额 不适用 不适用 193,707,344.45 -54.69", estimate="actual")
add("q3_rd", "1.270399 / +249.58 / 19.10", "2026Q3 研发投入（亿元）、同比与费用率（%）", "T1", "filing", ["[公告原文] 2026年第三季度报告 研发投入"], "2026-09-30", "cost_actual", "人民币亿元", ["page-18"], Q3, "研发投入合计 127,039,943.97 249.58", "CNY", estimate="actual")
add("ytd_revenue_cost", "收入 18.172900 / 营业成本 8.355660", "2026 前三季度收入与成本（亿元）", "T1", "filing", ["[公告原文] 2026年第三季度报告 合并利润表"], "2026-09-30", "cost_actual", "人民币亿元", ["page-18"], Q3, "营业成本 835,566,029.34 469,789,810.42", "CNY", estimate="actual")
add("ytd_gross_margin", "54.0166", "2026 前三季度毛利率（%）", "T1", "derived", ["[计算] 1-营业成本/营业收入"], "2026-09-30", "margin_actual", "%", ["page-18"], derived=True, formula="(1 - 8.3556602934 / 18.1729004848) * 100", inputs=["ytd_revenue_cost"], estimate="actual")
add("inventory_q3", "10.193593 / 3.677534", "2026Q3 末与 2025 年末存货（亿元）", "T1", "filing", ["[公告原文] 2026年第三季度报告 合并资产负债表"], "2026-09-30", "net_debt", "人民币亿元", ["page-19"], Q3, "存货 1,019,359,265.40 367,753,386.46", "CNY", estimate="actual")
add("inventory_growth", "177.14", "存货较年初增幅（%）", "T1", "derived", ["[计算] 期末存货/年初存货-1"], "2026-09-30", "kpi_actual", "%", ["page-19"], derived=True, formula="(10.1935926540 / 3.6775338646 - 1) * 100", inputs=["inventory_q3"], estimate="actual")
add("receivables_q3", "1.430242 / 0.587336", "2026Q3 末与 2025 年末应收账款（亿元）", "T1", "filing", ["[公告原文] 2026年第三季度报告 合并资产负债表"], "2026-09-30", "net_debt", "人民币亿元", ["page-19"], Q3, "应收账款 143,024,198.48 58,733,610.53", "CNY", estimate="actual")
add("receivables_growth", "143.51", "应收账款较年初增幅（%）", "T1", "derived", ["[计算] 期末应收账款/年初应收账款-1"], "2026-09-30", "kpi_actual", "%", ["page-19"], derived=True, formula="(1.4302419848 / 0.5873361053 - 1) * 100", inputs=["receivables_q3"], estimate="actual")
add("contract_liab_q3", "2.331000 / 1.369598", "2026Q3 末与 2025 年末合同负债（亿元）", "T1", "filing", ["[公告原文] 2026年第三季度报告 合并资产负债表"], "2026-09-30", "net_debt", "人民币亿元", ["page-19"], Q3, "合同负债 233,100,006.26 136,959,810.00", "CNY", estimate="actual")
add("contract_liab_growth", "70.20", "合同负债较年初增幅（%）", "T1", "derived", ["[计算] 期末合同负债/年初合同负债-1"], "2026-09-30", "kpi_actual", "%", ["page-19"], derived=True, formula="(2.3310000626 / 1.3695981000 - 1) * 100", inputs=["contract_liab_q3"], estimate="actual")
add("cash_q3", "73.540244", "2026Q3 末货币资金（亿元）", "T1", "filing", ["[公告原文] 2026年第三季度报告 合并资产负债表"], "2026-09-30", "net_debt", "人民币亿元", ["page-19"], Q3, "货币资金 7,354,024,357.98", "CNY", estimate="actual")

# 卖方预测（单源预测均标 T4）
add("forecast_dw_aug", "2026—2028 营收 30.97/49.60/76.83；归母 6.62/12.56/22.37", "东吴 2026-08-09 预测（亿元）", "T4", "web", ["[研报] 东吴证券 2026-08-09 新股研究"], "2026-08-09", "eps_forecast", "人民币亿元", ["page-20", "page-22", "page-23"], DW_AUG, "2026/2027/2028 年 归母净利润为 6.6/12.6/22.4 亿 元", "CNY", cross_check={"source": "东吴证券 2026-10-29 最新修订", "url": "output/research/20261030_东吴证券_2026年三季报点评.txt"}, notes="单家券商历史预测，最新报告已下修", estimate="forecast")
add("forecast_hx", "2026—2028 营收 27.56/45.43/68.74；归母 6.32/9.43/12.68", "华鑫 2026-09-19 预测（亿元）", "T4", "web", ["[研报] 华鑫证券 2026-09-19 公司动态研究"], "2026-09-19", "eps_forecast", "人民币亿元", ["page-20", "page-22", "page-23"], HX, "归母净利润 278 632 943 1268", "CNY", cross_check={"source": "太平洋证券 2026-10-19 预测", "url": "output/research/20261022_太平洋证券_宇树科技深度报告.txt"}, notes="单家券商预测", estimate="forecast")
add("forecast_tpy", "2026—2028 营收 27.91/43.13/64.82；归母 6.39/10.02/15.10", "太平洋 2026-10-19 预测（亿元）", "T4", "web", ["[研报] 太平洋证券 2026-10-19 公司深度"], "2026-10-19", "eps_forecast", "人民币亿元", ["page-20", "page-22"], TPY, "归母净利（百万元） 278 639 1002 1510", "CNY", cross_check={"source": "华鑫证券 2026-09-19 预测", "url": "output/research/20260919_华鑫证券_茁壮成长的中国树.txt"}, notes="单家券商预测", estimate="forecast")
add("forecast_dw_oct", "2026—2028 营收 26.27/43.13/59.53；归母 5.52/9.16/15.08", "东吴 2026-10-29 最新预测（亿元）", "T4", "web", ["[研报] 东吴证券 2026-10-29 三季报点评"], "2026-10-29", "eps_forecast", "人民币亿元", ["page-20"], DW_OCT, "归母净利润（百万元） 95.47 278.21 551.95 916.45 1,508.41", "CNY", cross_check={"source": "东吴证券 2026-08-09 前版预测", "url": "output/research/20260809_东吴证券_人形机器人产业化奇点已至.txt"}, notes="单家券商最新预测，较 8 月版下修", estimate="forecast")
add("forecast_high_low", "1.7643375394321767", "四份预测 2028 净利高低比（x）", "T4", "derived", ["[计算] 最高预测/最低预测"], "2026-10-29", "eps_forecast", "x", ["page-20"], derived=True, formula="22.3718 / 12.68", inputs=["forecast_dw_aug", "forecast_hx"], notes="四份卖方模型预测离散度", estimate="forecast")
add("forecast_jpm_bull", "2028 营收 133.83 / 归母 32.02", "摩根大通 2028 乐观预测（亿元）", "T4", "news", ["[媒体] 华尔街见闻转载 2026-10-26", "[媒体] 财新与腾讯新闻评级报道"], "2026-10-26", "eps_forecast", "人民币亿元", ["page-23"], JPM, "调整后净利润预计分别为6.16亿元、11.25亿元和32.02亿元", "CNY", cross_check={"source": "财新 2026-10-26 与腾讯新闻 2026-10-26", "url": "https://finance.caixin.com/2026-10-26/102497594.html"}, notes="媒体转述的外资券商预测，非公司披露；仅用于乐观情景", estimate="forecast")

# 内部反向估值与情景
add("discount_assumption", "12% / 2 年", "要求回报率与折现期", "T4", "house_model", ["[内部假设] 投委会讨论用风险回报要求"], "2026-10-30", "forward_pe", "%", ["page-22", "page-23"], cross_check={"source": "四份券商预测与当前高估值对照", "url": "output/deck/calculated_metrics.json"}, notes="内部估值假设，非市场一致预期", estimate="forecast")
add("exit_pe_assumption", "60x—100x；情景 45x/60x/100x", "2028 退出 PE 假设", "T4", "house_model", ["[内部假设] 高成长硬件与平台情景倍数"], "2028-12-31", "forward_pe", "x", ["page-22", "page-23"], cross_check={"source": "东吴证券 2026-08-09 可比公司估值表", "url": "output/research/20260809_东吴证券_人形机器人产业化奇点已至.txt"}, notes="内部估值假设，乐观档反映稀缺平台溢价", estimate="forecast")
add("required_np_100", "33.845990142684165", "100x 退出 PE 所需 2028 净利（亿元）", "T4", "house_model", ["[内部测算] 市值×1.12²/100"], "2028-12-31", "eps_forecast", "人民币亿元", ["page-22"], derived=True, formula="market_cap * 1.12 ** 2 / 100", inputs=["market_cap", "discount_assumption", "exit_pe_assumption"], cross_check={"source": "摩根大通 2028 净利 32.02 亿元预测", "url": "output/research/snapshots/20261026_JPM_宇树评级与预测.txt"}, notes="内部反向估值", estimate="forecast")
add("required_np_60", "56.40998357114028", "60x 退出 PE 所需 2028 净利（亿元）", "T4", "house_model", ["[内部测算] 市值×1.12²/60"], "2028-12-31", "eps_forecast", "人民币亿元", ["page-22"], derived=True, formula="market_cap * 1.12 ** 2 / 60", inputs=["market_cap", "discount_assumption", "exit_pe_assumption"], cross_check={"source": "四份卖方 2028 净利预测区间", "url": "output/deck/calculated_metrics.json"}, notes="内部反向估值", estimate="forecast")
add("required_vs_forecasts", "+51.29% / +344.87%", "所需净利相对主流预测的溢价", "T4", "derived", ["[内部测算] 所需净利与最高/最低卖方预测比较"], "2028-12-31", "eps_forecast", "%", ["page-22"], derived=True, formula="required_np_100 / 22.3718 - 1；required_np_60 / 12.68 - 1", inputs=["required_np_100", "required_np_60", "forecast_dw_aug", "forecast_hx"], notes="分别相对最高与最低主流预测", estimate="forecast")
add("scenario_probabilities", "下行 30% / 基准 50% / 乐观 20%", "情景主观概率", "T4", "house_model", ["[内部假设] 投委会讨论用主观概率"], "2026-10-30", "forward_pe", "%", ["page-23"], cross_check={"source": "三情景净利润与退出倍数敏感性", "url": "output/deck/calculated_metrics.json"}, notes="仅用于风险收益比较，不是统计预测", estimate="forecast")
add("scenario_profits", "下行 12.68 / 基准 22.37 / 乐观 32.02", "三情景 2028 净利润（亿元）", "T4", "house_model", ["[内部情景] 华鑫低值/东吴前版高值/摩根大通乐观值"], "2028-12-31", "eps_forecast", "人民币亿元", ["page-23"], derived=True, formula="分别引用卖方预测作为内部情景输入", inputs=["forecast_hx", "forecast_dw_aug", "forecast_jpm_bull"], cross_check={"source": "对应机构预测原文", "url": "output/deck/calculated_metrics.json"}, notes="内部情景选择，不是新增盈利预测", estimate="forecast")
add("scenario_prices", "112.46450713816012 / 264.54584907262273 / 631.1099752127387", "三情景折现每股价值（元）", "T4", "house_model", ["[内部测算] 净利×退出 PE÷1.12²÷总股本"], "2026-10-30", "forward_pe", "CNY/股", ["page-23"], derived=True, formula="三情景分别按净利润×退出PE÷1.12²÷总股本计算", inputs=["scenario_profits", "exit_pe_assumption", "discount_assumption", "shares_outstanding"], cross_check={"source": "calculate_metrics.py 复算结果", "url": "output/deck/calculated_metrics.json"}, notes="未考虑分红与净现金调整", estimate="forecast")
add("weighted_price", "292.2342717203071", "概率加权折现每股价值（元）", "T4", "house_model", ["[内部测算] 三情景价值概率加权"], "2026-10-30", "forward_pe", "CNY/股", ["page-23"], derived=True, formula="112.46450713816012 * 0.30 + 264.54584907262273 * 0.50 + 631.1099752127387 * 0.20", inputs=["scenario_prices", "scenario_probabilities"], cross_check={"source": "calculate_metrics.py 复算结果", "url": "output/deck/calculated_metrics.json"}, notes="仅用于投委会风险收益比较", estimate="forecast")

# 风险跟踪
add("listing_low", "404.03", "上市以来最低收盘价（元/股）", "T2", "api", ["[行情] iFinD 前复权日线"], "2026-10-15", "historical_price_series", "CNY/股", ["page-24"], KLINE, "408.55,418.49,404.03,405.1", "CNY", estimate="actual")
add("unlock_window", "2027-08-19", "首发限售股首轮解禁窗口", "T4", "news", ["[媒体] 财新 2026-10-26 解禁与锁定期报道"], "2027-08-19", "historical_anchor", "无量纲", ["page-24"], UNLOCK, "2027年8月19日", cross_check={"source": "公司 2026-08-19 上市日期与发行锁定安排", "url": "https://www.sse.com.cn/star/market/stocklist/info/overview/index.shtml?COMPANY_CODE=688836"}, notes="实际解禁数量与日期以公司届时公告为准", estimate="forecast")

registry = {
    "meta": {
        "scope": "688836.SH", "project": "宇树科技投资价值投委会 25 页 IC deck",
        "created": "2026-10-30", "last_validated": RETRIEVED,
        "schema_version": "dr-1.0", "producer": "institutional-slides",
        "staleness_overrides": {}
    },
    "data_points": points,
    "dependency_graph": {},
    "math_checks": []
}
OUT.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {OUT} with {len(points)} data points")
