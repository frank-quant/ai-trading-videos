from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent
PAGES = ROOT / "pages"
PAGES.mkdir(exist_ok=True)


def fill(color):
    return {"type": "solid", "color": color}


def text(eid, x, y, w, h, value, style="$body", fontSize=None, color=None,
         bold=None, fontFamily=None, wrap=True, align=None, lineHeight=None, italic=None):
    content = {"text": value, "style": style, "wrap": wrap,
               "align": align or ["left", "top"]}
    if fontSize is not None:
        content["fontSize"] = fontSize
    if color is not None:
        content["color"] = color
    if bold is not None:
        content["bold"] = bold
    if italic is not None:
        content["italic"] = italic
    if fontFamily is not None:
        content["fontFamily"] = fontFamily
    if lineHeight is not None:
        content["lineHeight"] = lineHeight
    return {"elementId": eid, "elementType": "text", "bounds": [x, y, w, h], "content": content}


def rect(eid, x, y, w, h, color="$lt2", border=None):
    out = {"elementId": eid, "elementType": "shape", "bounds": [x, y, w, h],
           "shapeName": "rect", "fill": fill(color)}
    if border:
        out["border"] = border
    return out


def rule(eid, x, y, w, color="$ruleRow", h=0.8):
    return {"elementId": eid, "elementType": "line", "bounds": [x, y, w, h],
            "viewBox": [w, h], "points": f"0,{h/2} {w},{h/2}", "curve": "sharp",
            "border": {"style": "solid", "width": h, "color": color}}


def image(eid, x, y, w, h, src, mode="cover"):
    return {"elementId": eid, "elementType": "image", "bounds": [x, y, w, h],
            "src": src, "fit": {"mode": mode}}


def chart(eid, x, y, w, h, cols, rows, series, xAxis=None, yAxis=None,
          legend=True, barWidth=None):
    out = {"elementId": eid, "elementType": "chart", "bounds": [x, y, w, h],
           "data": {"cols": cols, "rows": rows}, "series": series,
           "legend": {"show": legend, "position": "bottom", "fontSize": 14, "color": "#666666"},
           "fontFamily": "Arial, 楷体"}
    out["xAxis"] = xAxis or {"gridLine": False, "label": {"fontSize": 14, "color": "#333333"},
                             "axisLine": {"color": "#000000", "width": 1}}
    out["yAxis"] = yAxis or {"label": {"fontSize": 14, "color": "#666666"},
                             "axisLine": False, "gridLine": False, "min": 0}
    if barWidth is not None:
        out["barWidth"] = barWidth
    return out


def bar_series(name, x, y, color="$dk2", labels=False, stack=None):
    out = {"type": "bar", "encode": {"x": x, "y": y}, "name": name, "fill": color}
    if labels:
        out["dataLabels"] = {"show": True, "numberFormat": "#,##0.0", "fontSize": 14, "color": "#333333"}
    if stack:
        out["stack"] = stack
    return out


def line_series(name, x, y, color="$accent2", labels=False):
    out = {"type": "line", "encode": {"x": x, "y": y}, "name": name,
           "lineColor": color, "width": 2.5, "marker": {"shape": "circle", "size": 7, "fill": color}}
    if labels:
        out["dataLabels"] = {"show": True, "numberFormat": "0.0", "fontSize": 14, "color": "#333333"}
    return out


def pie_series(x, y, colors):
    return {"type": "pie", "encode": {"category": x, "value": y}, "innerRadius": 0.55,
            "fill": colors, "dataLabels": {"show": True, "content": "percentage", "numberFormat": "0%", "fontSize": 14}}


def native_table(eid, x, y, w, h, rows, widths, font_size=14, aligns=None):
    nrows = len(rows)
    cooked = []
    for ri, row in enumerate(rows):
        crow = []
        for ci, value in enumerate(row):
            align = (aligns[ci] if aligns else ("left" if ci == 0 else "right"))
            cell = {"text": str(value), "fontSize": font_size, "fontFamily": "Arial, 楷体",
                    "align": [align, "middle"], "lineHeight": 1.15,
                    "border": {"style": "solid", "width": 0.5, "color": "$ruleRow"}}
            if ri == 0:
                cell.update({"bold": True, "color": "$dk2", "fill": fill("$lt2")})
            else:
                cell["color"] = "$inkBody"
            crow.append(cell)
        cooked.append(crow)
    return {"elementId": eid, "elementType": "table", "bounds": [x, y, w, h],
            "columnWidths": widths, "rowHeights": [1 / nrows] * nrows, "rows": cooked}


def kpi_cards(prefix, items, x=63, y=150, total_w=1042, h=104, gap=14):
    out = []
    w = (total_w - gap * (len(items) - 1)) / len(items)
    for i, (label, value, note) in enumerate(items):
        xx = x + i * (w + gap)
        out += [rect(f"{prefix}-bg-{i}", xx, y, w, h, "$lt2"),
                text(f"{prefix}-label-{i}", xx + 13, y + 12, w - 26, 16, label, "$kicker", wrap=False),
                text(f"{prefix}-value-{i}", xx + 13, y + 33, w - 26, 31, value, "$statNumeral", wrap=False),
                text(f"{prefix}-note-{i}", xx + 13, y + 72, w - 26, h - 78, note, "$footnote", wrap=True)]
    return out


def bullet_list(prefix, items, x, y, w, row_h=44, style="$body"):
    out = []
    for i, item in enumerate(items):
        yy = y + i * row_h
        out += [rect(f"{prefix}-dot-{i}", x, yy + 5, 5, 5, "$accent2"),
                text(f"{prefix}-txt-{i}", x + 15, yy, w - 15, row_h - 2, item, style, wrap=True)]
    return out


def callout(eid, title, body, x=63, y=641, w=1042, h=70, dark=False):
    bg = "$dk2" if dark else "$lt2"
    title_style = "$darkKicker" if dark else "$tableHeader"
    body_style = "$darkBody" if dark else "$body"
    body_color = "$lt1" if dark else None
    return [rect(f"{eid}-bg", x, y, w, h, bg),
            rect(f"{eid}-edge", x, y, 3, h, "$accent1" if dark else "$dk2"),
            text(f"{eid}-title", x + 16, y + 10, w - 32, 16, title, title_style, wrap=False),
            text(f"{eid}-body", x + 16, y + 32, w - 32, h - 36, body, body_style, color=body_color, wrap=True)]


def insight_panel(items):
    out = [rect("panel-bg", 1125, 145, 252, 570, "$lt2"),
           text("panel-kicker", 1143.5, 158.5, 219, 15, "KEY TAKEAWAYS", "$kicker", wrap=False),
           rule("panel-rule-top", 1141.5, 180, 219, "$dk1")]
    ys = [199, 371, 543]
    for i, ((title, body), yy) in enumerate(zip(items, ys), start=1):
        rich = f'<p><span style="font-size:16px; color:$dk2"><b>{title}</b></span></p><p style="margin-top:8px"><span style="font-size:14px; color:#333333">{body}</span></p>'
        out.append(text(f"panel-item-{i}", 1141.5, yy, 219, 146, rich, "$body", wrap=True))
        if i < 3:
            out.append(rule(f"panel-sep-{i}", 1141.5, yy + 153, 219, "$ruleRow"))
    return out


def chrome(page, section, title, subtitle, footnote, source):
    return [
        text("chrome-breadcrumb", 65, 12.5, 1312, 14.8, section, "$breadcrumb", wrap=False),
        text("chrome-title", 65, 32.8, 1312, 69.5, f"{title}<sup>1</sup>", "$actionTitle", align=["left", "middle"]),
        text("chrome-subtitle", 65, 109.3, 1312, 21.5, subtitle, "$subtitle", wrap=False),
        rule("chrome-rule-top", 63, 137.3, 1314, "$dk1"),
        text("chrome-footnotes", 65, 724.1, 1312, 51.6, footnote, "$footnote", align=["left", "bottom"]),
        rule("chrome-rule-bottom", 63, 780.8, 1314, "$ruleRow"),
        text("chrome-source", 65, 788, 500, 14.8, f"Source: {source}", "$footer", wrap=False),
        text("chrome-brand-center", 820, 788, 400, 14.8, "IC MEMO · 投决会材料", "$footer", color="$accent6", fontFamily="Georgia, 楷体", wrap=False, align=["right", "top"]),
        text("chrome-pageno", 1250, 788, 127, 14.8, f"{page:02d}", "$footer", wrap=False, align=["right", "top"])
    ]


def content_page(page, section, title, subtitle, footnote, source, main, insights):
    elements = chrome(page, section, title, subtitle, footnote, source) + main
    if insights:
        elements += insight_panel(insights)
    write_page(page, elements)


def write_page(page, elements, page_type="content", background="$lt1"):
    data = {"pageType": page_type, "background": fill(background), "elements": elements}
    path = PAGES / f"page-{page:02d}.page"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1200), encoding="utf-8")


def divider(page, part, title, summary, cards):
    elements = [rect("div-spine", 0, 0, 39, 810, "$dk2"),
                text("div-part-label", 104, 168.6, 1273, 20, part, "$partLabel", wrap=False),
                text("div-title", 104, 204.6, 1273, 82, title, "$dividerH", wrap=True),
                rect("div-accent-rule", 102, 296, 135, 3, "$accent1"),
                text("div-summary", 104, 320, 900, 74, summary, "$subtitle", lineHeight=1.12)]
    for i, (pages, label, desc) in enumerate(cards):
        x = 102 + i * 242
        elements += [rule(f"idx-rule-{i}", x, 435, 210, "$dk2", 1.5),
                     text(f"idx-range-{i}", x + 2, 449, 205, 18, pages, "$unitLabel", wrap=False),
                     text(f"idx-title-{i}", x + 2, 474, 205, 42, label, "$chartLabel"),
                     text(f"idx-desc-{i}", x + 2, 522, 205, 70, desc, "$bodyTight", color="$accent5")]
    write_page(page, elements)


# 01 封面
cover = [image("cover-photo", 0, 0, 1440, 810, "media/cover-photo.jpg", "fill"),
         {"elementId": "cover-dimmer", "elementType": "shape", "bounds": [0, 0, 1440, 810], "shapeName": "rect",
          "fill": {"type": "gradient", "gradientType": "linear", "angle": 0,
                   "stops": [{"position": 0, "color": "#0000009E"}, {"position": 0.46, "color": "#00000057"}, {"position": 0.78, "color": "#00000000"}]}},
         rect("cover-panel", 66, 154.5, 942, 616.5, "$coverPanel"),
         rule("cover-panel-hairline", 66, 154.5, 942, "$coverHairline"),
         text("cover-brand", 113, 196.3, 873.6, 65, "IC MEMO · 投决会材料", "$coverH1", fontSize=30, fontFamily="Georgia, 楷体"),
         text("cover-h1", 113, 306, 933.2, 74, "宇树科技", "$coverH1", fontSize=62, fontFamily="Georgia, 楷体"),
         text("cover-subtitle", 113, 390, 933.2, 48, "投资价值与估值安全边际", "$coverH1", fontSize=38, italic=True, fontFamily="Georgia, 楷体")]
stat_items = [("RECOMMENDATION", "不建仓"), ("PRICE", "¥667.10"), ("TTM PE", "482x"), ("TICKER", "688836.SH")]
for i, (label, value) in enumerate(stat_items):
    x = 111 + i * 215.6
    cover += [rect(f"stat{i}-bg", x, 464.2, 205.1, 80.6, "$coverStatBg"),
              text(f"stat{i}-label", x + 17, 478.2, 188.6, 15.1, label, "$darkLabel", fontSize=14),
              text(f"stat{i}-value", x + 17, 498.8, 188.6, 33.5, value, "$coverH1", fontSize=30, color="#00A9F4" if i == 0 else "$lt1", fontFamily="Georgia, 楷体")]
cover += [text("cover-date", 113, 572.3, 933.2, 21.5, "2026 年 10 月 30 日 · 盘中行情快照", "$darkLabel", fontSize=20, color="#00A9F4"),
          text("cover-sector-1", 113, 606.8, 430, 17.8, "高性能通用机器人 · 人形与四足", "$darkValue", fontSize=16),
          text("cover-sector-2", 600, 606.8, 360, 17.8, "内部投委会讨论稿", "$darkLabel", fontSize=16),
          text("cover-disclaimer", 113, 701.8, 873.6, 44.7, "本材料基于公开披露与机构研究，含内部情景假设；不构成任何证券买卖要约或个性化投资建议。", "$darkBody", fontSize=12, color="$lt1", align=["justify", "top"])]
write_page(1, cover, "cover", "$dk1")

# 02 投决摘要（L02 结构页）
main = []
main += kpi_cards("call", [("ACTION", "不建仓", "列入高优先观察池"),
                            ("PRICE / TTM PE", "667.10 / 482x", "2026-10-30 盘中"),
                            ("FY2026 CONSENSUS PE", "397x", "6 家 EPS 共识"),
                            ("REVIEW", "季度复议", "经营证据与价格并重")], x=63, y=150, total_w=1314, h=108)
main += [text("call-long-title", 65, 284, 630, 22, "支持投资价值的 3 项事实", "$exhibitTitle", wrap=False),
         text("call-risk-title", 730, 284, 647, 22, "限制当前配置的 3 项约束", "$exhibitTitle", wrap=False)]
main += bullet_list("call-long", ["2025 年人形出货 5511 台，全球出货领先已具备规模证据", "人形与四足合计贡献 93.4% 主营收入，硬件毛利率已获验证", "行业仍处放量初期，模型、产能与生态提供长期可选性"], 65, 320, 625, 55)
main += bullet_list("call-risk", ["2026 年前三季度扣非净利润下降 18.8%，利润方向与收入背离", "人形科研教育收入占 73.6%，工业重复订单仍需持续验证", "反向估值要求 2028 年净利约 34—56 亿元，超过主流预测"], 730, 320, 647, 55)
main += callout("call-condition", "复议条件", "同时看到行业应用占比与重复订单改善、扣非利润和经营现金流企稳，以及估值回到可讨论的风险收益区间。", x=63, y=530, w=1314, h=82, dark=True)
main += [text("call-method", 65, 636, 1312, 54, "阅读顺序：先检验商业与市场证据，再评估护城河与模型投入，随后核对财务质量，最后以反向估值和风险登记册形成投决。", "$body", wrap=True)]
content_page(2, "Front Matter › Recommendation & Terms", "667 元股价对应约 482x TTM PE，现阶段建议不建仓并等待商业验证", "好公司与好价格分开表决，先验证重复订单、扣非利润和现金流，再讨论平台溢价", "1. 行情为 2026-10-30 盘中快照；建议仅用于内部投委会讨论，不构成个性化投资建议。", "公司三季报；Wind；团队分析", main, None)

# 03 估值与投决条款
main = kpi_cards("market", [("盘中股价", "¥667.10", "2026-10-30"),
                             ("盘中总市值", "¥2,698 亿", "按最新总股本"),
                             ("TTM PE", "482x", "Wind 快照"),
                             ("自由流通比例", "7.4%", "约 3009 万股")])
main += [text("market-chart-title", 65, 282, 630, 22, "当前价格隐含的估值层级", "$exhibitTitle", wrap=False),
         chart("market-pe", 63, 314, 640, 245, ["口径", "PE"], [["TTM", 482.188], ["FY2026 共识", 397.083], ["FY2028 东吴最新", 178.847]], [bar_series("PE（x）", "口径", "PE", "$dk2", True)], legend=False, barWidth=0.48),
         text("market-terms-title", 730, 282, 375, 22, "三项复议条件", "$exhibitTitle", wrap=False)]
main += bullet_list("market-terms", ["商业：人形行业应用与重复采购形成连续披露", "财务：扣非利润、经营现金流和存货周转共同企稳", "估值：远期利润假设与退出倍数提供足够安全边际"], 730, 320, 375, 66)
main += callout("market-note", "价格与稀缺性同时放大波动", "约 7.4% 的自由流通比例有助于稀缺性溢价形成，但不能替代盈利锚；流通盘变化会放大估值重定价。", x=63, y=585, w=1042, h=92)
content_page(3, "Front Matter › Market Snapshot & Terms", "2,698 亿元市值已计入强光平台预期，三项条件决定可否重估", "当前估值同时要求业绩高速增长、远期高倍数延续和稀缺性溢价不被稀释", "1. FY2026 PE=盘中价/同花顺 6 家共识 EPS；FY2028 PE=盘中价/东吴最新 EPS。2. 自由流通比例按约数估算。", "Wind；同花顺共识；公司三季报；东吴证券", main, [("估值已很充分", "TTM PE 482x、FY2026 共识 PE 约 397x，业绩容错空间有限。"), ("流通盘强化稀缺叙事", "自由流通比例约 7.4%，但不能作为长期估值底。"), ("复议需三项共振", "商业订单、财务质量与估值安全边际缺一不可。")])

# 04 分歧对照
main = [text("variant-title", 65, 153, 1040, 22, "共识、内部判断与裁决指标", "$exhibitTitle", wrap=False),
        native_table("variant-table", 63, 184, 1042, 360, [["市场共识", "我们的判断", "用什么裁决"], ["量产领先=长期商业壁垒", "承认先发，但客户结构决定收入质量", "行业应用占比、重复采购"], ["物理 AI 大会=S 曲线前移", "技术可选性上升，订单证据尚未同步", "现场任务成功率、人工接管率"], ["归母 +270%=盈利跃升", "低基数影响大，扣非与现金流更关键", "扣非净利率、经营现金流"], ["稀缺上市地位=估值底", "稀缺溢价可存在，但不能消除回撤", "远期 PE、流通盘与解禁"]], [0.34, 0.42, 0.24], 14),
        text("variant-series-title", 65, 568, 1040, 22, "六个季度化裁决序列", "$exhibitTitle", wrap=False)]
series = ["行业应用收入占比", "重复采购与复购", "模型现场可靠性", "扣非净利率", "存货与现金转化", "估值与流通盘"]
for i, label in enumerate(series):
    x = 63 + (i % 3) * 350
    y = 604 + (i // 3) * 46
    main += [rect(f"variant-chip-{i}", x, y, 330, 34, "$lt2"), text(f"variant-chip-txt-{i}", x + 12, y + 8, 306, 18, f"{i+1}. {label}", "$chartLabel", wrap=False)]
main += [text("variant-bottom-line", 65, 694, 1040, 20, "裁决原则：先验证经营序列，再调整估值假设；不以单次出货、单次模型演示或单日价格作为投决依据。", "$body", wrap=False)]
content_page(4, "Front Matter › Variant Perception", "市场把 4 项先发优势外推为平台溢价，我们用 6 个序列检验兑现", "不否认量产和运控领先，争议在于这些优势能否转成可持续企业订单与现金回报", "1. 内部判断不代表公司指引；裁决序列按季度复核。", "公司披露；4 家机构研报；团队分析", main, [("先承认事实优势", "量产、运控、成本与生态均是真实基础，不做反向叙事。"), ("核心在订单质量", "科研采购向企业重复订单迁移，是平台价值的关键证据。"), ("估值不能脱离现金流", "稀缺性和大会催化必须接受利润与现金流检验。")])

# 05 商业与市场隔页
divider(5, "PART ONE · 商业与市场", "2025 年人形收入占 51.8%，第二增长曲线已经切换", "从产品矩阵、行业空间和客户结构判断：宇树的硬件领先有多大事实基础，人形商业化又处在哪个阶段。", [("06—07", "产品与路径", "人形、四足、组件与十年工程复用"), ("08—09", "行业与竞争", "出货空间、份额与统计口径"), ("10", "应用结构", "科研教育与工业验证的距离")])

# 06 产品矩阵与收入
main = [image("product-g1", 63, 150, 505, 225, "media/g1-detail.jpg"),
        image("product-b2", 584, 150, 521, 225, "media/b2.jpg"),
        text("product-g1-cap", 65, 382, 500, 36, "人形：2025 收入 8.68 亿元 / 毛利率 63.18%", "$chartLabel"),
        text("product-b2-cap", 586, 382, 519, 36, "四足：2025 收入 6.98 亿元 / 毛利率 56.72%", "$chartLabel"),
        text("product-table-title", 65, 438, 1040, 22, "2025 主营业务构成", "$exhibitTitle", wrap=False),
        native_table("product-table", 63, 468, 1042, 184, [["业务", "收入（亿元）", "主营占比", "毛利率"], ["人形机器人", "8.68", "51.78%", "63.18%"], ["四足机器人", "6.98", "41.62%", "56.72%"], ["机器人组件", "1.04", "6.19%", "59.36%"]], [0.34, 0.22, 0.22, 0.22], 14)]
main += callout("product-note", "价值仍主要通过整机实现", "人形与四足合计占主营收入 93.4%；组件和模型尚未形成独立收入支柱。", x=63, y=660, w=1042, h=50)
content_page(6, "Part One › Business & Market › Product Matrix", "人形与四足贡献 93.4% 主营收入，硬件整机决定当前价值", "人形完成收入主引擎切换，四足提供规模基础，组件与模型尚未形成独立收入支柱", "1. 分产品占比为主营业务口径，与营业总收入口径略有差异。图片：宇树科技官网。", "招股说明书上会稿；宇树科技官网", main, [("人形成为主引擎", "2025 年人形收入占主营 51.78%，首次超过四足。"), ("硬件盈利已验证", "人形与四足毛利率分别为 63.18% 和 56.72%。"), ("平台收入尚待形成", "组件仅占 6.19%，模型与生态仍主要依附整机。")])

# 07 发展路径
main = [text("timeline-title", 65, 153, 1040, 22, "四足验证先行，人形放量随后，模型投入当前加速", "$exhibitTitle", wrap=False)]
milestones = [("2016", "公司成立", "电驱与运控起点"), ("2017", "Laikago", "商用四足交付"), ("2023", "H1", "进入全尺寸人形"), ("2024", "G1", "十万元以内放量"), ("2025", "R1 / H2", "全价格带扩展"), ("2026", "模型与算力", "物理 AI 投入加速")]
for i, (year, name, desc) in enumerate(milestones):
    x = 63 + i * 174
    main += [rect(f"tl-dot-{i}", x + 8, 224, 16, 16, "$accent1" if i >= 4 else "$dk2"),
             rule(f"tl-line-{i}", x + 24, 231, 158, "$accent3", 2),
             text(f"tl-year-{i}", x, 190, 158, 26, year, "$statNumeral", wrap=False),
             text(f"tl-name-{i}", x, 256, 158, 24, name, "$chartLabel"),
             text(f"tl-desc-{i}", x, 286, 158, 58, desc, "$footnote")]
main += [text("reuse-title", 65, 380, 1040, 22, "可复用的工程资产", "$exhibitTitle", wrap=False)]
reuse = [("关节与电驱", "电机、减速器、驱动器和模组规格复用"), ("运动控制", "强化学习、仿真训练与全身控制迁移"), ("供应链与制造", "采购议价、装配测试与质量经验复用"), ("开发者生态", "科研客户、论文、工具链与二次开发")]
for i, (t, b) in enumerate(reuse):
    x = 63 + (i % 2) * 526
    y = 420 + (i // 2) * 90
    main += [rect(f"reuse-bg-{i}", x, y, 510, 74, "$lt2"), text(f"reuse-t-{i}", x + 14, y + 10, 482, 20, t, "$panelItemTitle"), text(f"reuse-b-{i}", x + 14, y + 36, 482, 30, b, "$footnote")]
main += callout("timeline-note", "路径依赖带来的效率", "四足先完成硬件、运控和量产验证，使人形在约 3 年内完成从发布到规模出货；当前投入重点转向模型。", x=63, y=620, w=1042, h=70)
content_page(7, "Part One › Business & Market › Development Path", "10 年运控积累压缩至 3 年人形放量，工程复用是核心路径", "关节、电驱、控制算法与供应链在四足和人形之间复用，缩短产品验证与降本周期", "1. 10 年为公司成立至 2026 年的近似时间跨度；3 年指 2023 年 H1 至 2026 年。", "招股说明书；东吴证券；太平洋证券", main, [("先四足后人形", "四足先完成工程与商业验证，降低人形探索成本。"), ("复用形成速度", "硬件、算法、供应链和开发生态共同缩短迭代周期。"), ("竞争焦点已变化", "2024 年后模型与算力成为新的投入重点。")])

# 08 行业空间
main = [text("industry-chart-title", 65, 153, 650, 22, "全球人形机器人出货量（万台）", "$exhibitTitle", wrap=False),
        chart("industry-shipments", 63, 184, 650, 330, ["年份", "实际", "预测"], [["2024", 0.26, None], ["2025", 1.66, None], ["2026E", None, 8.17]], [bar_series("实际", "年份", "实际", "$dk2", True), bar_series("预测", "年份", "预测", "$accent1", False)], barWidth=0.5),
        text("industry-2030-title", 740, 153, 365, 22, "2030E 第三方空间", "$exhibitTitle", wrap=False)]
main += kpi_cards("industry-2030", [("销量", "60.57 万台", "GGII 预测"), ("市场规模", "¥1,022 亿", "GGII 预测")], x=740, y=184, total_w=365, h=116, gap=12)
main += [text("industry-caveat-title", 740, 330, 365, 22, "口径必须先统一", "$exhibitTitle", wrap=False)]
main += bullet_list("industry-caveat", ["出货不是确认收入，产能也不是销量", "人形与双臂轮式统计范围不同", "远期空间依赖价格、场景和模型假设"], 740, 368, 365, 54)
main += callout("industry-note", "高增长仍处低基数阶段", "2026E 出货 8.17 万台是第三方预测；公司投资价值应以份额、单价和真实场景交付验证，而非直接套用行业增速。", x=63, y=548, w=1042, h=100)
main += [text("industry-bottom-line", 65, 662, 1040, 30, "行业空间提供需求上限，公司的份额、单价和重复交付才决定可实现的收入下限。", "$body", wrap=False)]
content_page(8, "Part One › Business & Market › Industry Growth", "2026E 全球人形出货或达 8.17 万台，高增长仍依赖低基数", "行业处于样机向批量交付过渡期，出货基数、产品定义和预测机构差异会显著放大远期空间", "1. 2026E 与 2030E 均为第三方预测；Yano Research 与 GGII 统计口径不同，不与公司订单或确认收入混用。", "东吴证券；华金证券；Yano Research；GGII", main, [("行业进入放量期", "2024—2026E 出货快速上升，但基数仍低。"), ("远期空间可观", "GGII 预计 2030 年市场约 1022 亿元。"), ("预测不可混用", "统计范围与出货定义差异，要求逐年复核。")])

# 09 竞争格局
main = [text("share-chart-title", 65, 153, 650, 22, "2025 全球人形出货份额（Omdia）", "$exhibitTitle", wrap=False),
        chart("share-bar", 63, 184, 650, 340, ["厂商", "份额"], [["宇树", 37.54], ["智元", 35.21], ["优必选", 6.81], ["乐聚", 3.41], ["众擎", 2.72], ["其他", 14.31]], [bar_series("份额（%）", "份额", "厂商", "$dk2", True)], xAxis={"type": "value", "min": 0, "max": 45, "label": {"fontSize": 14, "color": "#666666"}, "gridLine": False}, yAxis={"type": "category", "label": {"fontSize": 14, "color": "#333333"}, "axisLine": {"color": "#000000"}, "gridLine": False}, legend=False, barWidth=0.55),
        text("share-table-title", 740, 153, 365, 22, "竞争判断与跟踪", "$exhibitTitle", wrap=False)]
main += bullet_list("share-points", ["宇树与智元差距仅 2.33pct", "前两名合计份额 72.75%", "工业订单可改变后续排名", "海外厂商出货仍处小规模"], 740, 194, 365, 58)
main += callout("share-note", "领先并非稳定垄断", "份额优势支持规模与数据期权，但第一名与第二名差距很小；需持续跟踪重复订单、价格带与真实交付。", x=63, y=552, w=1042, h=98)
content_page(9, "Part One › Business & Market › Competitive Landscape", "2025 年宇树以 37.5% 份额居首，但前两名合计已达 72.8%", "宇树与智元形成第一梯队，后续排名取决于工业订单、价格带与真实交付而非单次出货", "1. 出货份额为 Omdia 与招股问询采用口径，可能包含部分双臂轮式产品；其他机构排名可能不同。", "太平洋证券；招股问询回复；Omdia", main, [("宇树出货居首", "2025 年出货 5511 台，份额 37.54%。"), ["头部差距有限", "智元份额 35.21%，两者仅差 2.33pct。"], ["格局仍会变化", "工业场景、模型与价格竞争可能重排份额。"]])

# 10 应用结构
main = [text("app-human-title", 65, 153, 500, 22, "人形收入应用结构", "$exhibitTitle", wrap=False),
        chart("app-human-pie", 63, 184, 500, 320, ["应用", "占比"], [["科研教育", 73.60], ["商业消费", 17.39], ["行业应用", 9.01]], [pie_series("应用", "占比", ["#051C2C", "#00A9F4", "#B8C4CC"])], legend=True),
        text("app-quad-title", 605, 153, 500, 22, "四足收入应用结构", "$exhibitTitle", wrap=False),
        chart("app-quad-pie", 603, 184, 500, 320, ["应用", "占比"], [["科研教育", 31.58], ["商业消费", 42.30], ["行业应用", 26.11]], [pie_series("应用", "占比", ["#051C2C", "#00A9F4", "#B8C4CC"])], legend=True),
        text("app-center-human", 183, 316, 260, 38, "73.6%", "$heroNumeral", fontSize=28, align=["center", "middle"], wrap=False),
        text("app-center-quad", 723, 316, 260, 38, "26.1%", "$heroNumeral", fontSize=28, align=["center", "middle"], wrap=False)]
main += callout("app-note", "真正的工业收入仍很薄", "人形行业应用仅占 9.01%，其中企业导览占比较高；智能制造、巡检、物流合计约 2.64%，重复工业订单仍需验证。", x=63, y=532, w=1042, h=94)
main += [text("app-path", 65, 648, 1040, 42, "投决跟踪顺序：科研平台采购 → 商业展示与服务 → 企业导览 → 制造/巡检/物流 → 可复制的重复生产订单。", "$body", wrap=True)]
content_page(10, "Part One › Business & Market › Customer Mix", "人形科研教育收入占 73.6%，工业场景尚处 9.0% 验证期", "科研采购提供品牌和开发生态，重复工业订单才决定人形业务的长期收入质量", "1. 应用结构为 2025 年 1—9 月收入口径，三季报未更新。2. 2.64% 为媒体依据第二轮问询明细计算，行业应用中企业导览约占 50%—70%。", "首轮问询函回复；第二轮问询回复；36氪；虎嗅", main, [("科研仍占主导", "人形科研教育收入占 73.6%，工业转化尚未完成。"), ["四足提供迁移经验", "四足行业应用已达 26.1%，具备场景拓展基础。"], ["跟踪重复生产订单", "真正制造、巡检与物流占比约 2.64%，需优先验证。"]])

# 11 护城河与商业化隔页
divider(11, "PART TWO · 护城河与商业化", "核心部件自研与量产构成护城河，模型能力决定估值上限", "本部分分别检验成本优势、运控与模型差距，以及募投、产能和算力扩张带来的回报要求。", [("12", "成本优势", "降价、销量与毛利率的联合证据"), ("13", "模型能力", "运控长板与大脑短板"), ("14", "资本投入", "募投、产能与物理 AI 新方向")])

# 12 成本优势
main = [text("cost-asp-title", 65, 153, 500, 22, "人形平均售价（万元/台）", "$exhibitTitle", wrap=False),
        chart("cost-asp", 63, 184, 500, 275, ["年份", "均价"], [["2023", 59.34], ["2024", 26.04], ["2025", 16.64]], [bar_series("均价", "年份", "均价", "$dk2", True)], legend=False, barWidth=0.46),
        text("cost-margin-title", 605, 153, 500, 22, "分产品毛利率（%）", "$exhibitTitle", wrap=False),
        chart("cost-margin", 603, 184, 500, 275, ["业务", "毛利率"], [["人形", 63.18], ["四足", 56.72], ["组件", 59.36]], [bar_series("毛利率", "业务", "毛利率", "$dk2", True)], legend=False, barWidth=0.46)]
main += kpi_cards("cost-kpi", [("均价降幅", "−72.0%", "2023—2025"), ("人形销量", "5,215 台", "2025"), ("人形收入", "¥8.68 亿", "2025"), ["人形毛利率", "63.18%", "2025"]], x=63, y=485, total_w=1042, h=100)
main += callout("cost-note", "降价与结构下移并未破坏盈利", "均价下降包含 H1 向 G1 的产品结构变化；工艺、采购和规模降本推动销量放大，使人形仍维持 63.18% 毛利率。", x=63, y=610, w=1042, h=82)
content_page(12, "Part Two › Moat & Commercialization › Unit Economics", "人形均价两年降 72.0% 而毛利率守住 63.2%，成本优势已被验证", "产品结构下移与工艺、采购降本同时发生，销量放大吸收价格下降并保持高毛利", "1. 均价下降包含产品结构变化，不能全部解释为同型号降价。2. 2023 年初代 H1 仅 5 台，与后续年度可比性有限。", "招股说明书上会稿", main, [("价格带显著下探", "人形均价由 59.34 万元降至 16.64 万元。"), ["销量放大对冲降价", "2025 年销量 5215 台、收入 8.68 亿元。"], ["成本优势有报表证据", "人形毛利率仍为 63.18%，而非仅靠叙事支撑。"]])

# 13 运控与模型
main = [text("brain-title", 65, 153, 1040, 22, "大脑、小脑与本体的能力成熟度并不一致", "$exhibitTitle", wrap=False)]
columns = [("本体", "已规模交付", "关节、电驱、结构与热管理", "量产与可靠性"), ("小脑", "运控长板", "强化学习、仿真与高动态控制", "响应与抗冲击"), ("大脑", "仍在追赶", "WMA / VLA / WVLA 与真实数据", "泛化与自主任务")]
for i, (name, status, evidence, metric) in enumerate(columns):
    x = 63 + i * 350
    main += [rect(f"brain-bg-{i}", x, 190, 330, 190, "$lt2" if i < 2 else "$accent4"),
             text(f"brain-name-{i}", x + 16, 205, 298, 26, name, "$sectionHeader"),
             text(f"brain-status-{i}", x + 16, 239, 298, 26, status, "$statNumeral", color="$accent2" if i == 2 else "$dk2"),
             text(f"brain-evidence-{i}", x + 16, 280, 298, 42, evidence, "$body"),
             text(f"brain-metric-{i}", x + 16, 334, 298, 22, f"指标：{metric}", "$footnote")]
main += [text("model-timeline-title", 65, 410, 1040, 22, "模型投入与验证里程碑", "$exhibitTitle", wrap=False)]
models = [("2024", "加强具身大模型研发"), ("2025", "WMA / VLA 开源"), ("2026.05", "WVLA 2.0 长程整理演示"), ("2026.10", "自进化 V1.0 预研")]
for i, (date, event) in enumerate(models):
    x = 63 + i * 260
    main += [text(f"model-date-{i}", x, 450, 240, 25, date, "$statNumeral", wrap=False),
             rule(f"model-rule-{i}", x, 484, 240, "$accent1" if i >= 2 else "$dk2", 2),
             text(f"model-event-{i}", x, 498, 240, 56, event, "$body")]
main += callout("model-note", "演示结果需要转成客户现场指标", "后续应跟踪任务成功率、人工接管率、连续工作时间、安全表现与重复部署成本，而非模型发布次数。", x=63, y=590, w=1042, h=88)
content_page(13, "Part Two › Moat & Commercialization › Brain vs Motion Control", "运控积累超过 10 年、模型投入仅约 2 年，大脑仍是关键短板", "高动态运控已产品化，通用任务模型仍需用真实场景的泛化、可靠性和安全指标验证", "1. 模型投入约 2 年按 2024 年至 2026 年近似计算；演示结果不等于客户现场稳定性。", "招股说明书；东吴证券；华金证券；中国证券报", main, [("运控已形成产品壁垒", "本体与小脑积累超过 10 年并已产品化。"), ["模型仍处验证阶段", "2024 年后才加强大模型投入，通用能力仍需现场检验。"], ["建立可观测指标", "用成功率、接管率与连续运行衡量模型价值。"]])

# 14 募投与产能
main = [text("fund-title", 65, 153, 500, 22, "IPO 募投结构（%）", "$exhibitTitle", wrap=False),
        chart("fund-pie", 63, 184, 500, 315, ["项目", "占比"], [["模型研发", 48.13], ["本体研发", 26.41], ["新产品", 10.60], ["制造基地", 14.85]], [pie_series("项目", "占比", ["#00A9F4", "#051C2C", "#006BA6", "#B8C4CC"])], legend=True),
        text("capacity-title", 605, 153, 500, 22, "制造与模型投入方向", "$exhibitTitle", wrap=False)]
main += kpi_cards("capacity", [("模型研发", "¥20.22 亿", "募投 48.13%"), ["人形设计产能", "7.5 万台", "年产规划"], ["四足设计产能", "11.5 万台", "年产规划"]], x=605, y=184, total_w=500, h=116, gap=10)
main += bullet_list("capacity-points", ["自进化 V1.0：仿真、真机、评估与反馈迭代", "超大算力集群：支撑模型训练与数据处理", "硬件量产：面向更大规模的制造与交付"], 605, 330, 500, 55)
main += callout("fund-note", "投入扩张同时抬高回报门槛", "模型、产能和算力可打开平台空间，也会增加研发费用、折旧与产能消化压力；规划产能不能当作当前订单。", x=63, y=532, w=1042, h=94)
main += [text("fund-monitoring", 65, 648, 1040, 42, "跟踪：募投投入节奏、真实产能爬坡、单位研发产出、工业订单对新增产能的覆盖程度。", "$body", wrap=True)]
content_page(14, "Part Two › Moat & Commercialization › Capex & Capacity", "48.1% 募投投向模型研发，扩产与算力将同时抬高兑现门槛", "模型、产能与算力同步投入可打开平台空间，也会增加费用、折旧和商业回报压力", "1. 产能为募投规划而非当前有效产能。2. 自进化模型与超大算力为公司 2026-10-22 公开演讲口径。", "招股说明书；第二轮问询回复；东吴证券；中国证券报", main, [("模型是最大募投方向", "20.22 亿元、占 48.13%，战略重心明确。"), ["产能需要订单消化", "人形 7.5 万台、四足 11.5 万台均为规划产能。"], ["投入回报必须复核", "算力、研发与折旧会增加业绩兑现要求。"]])

# 15 财务与预测隔页
divider(15, "PART THREE · 财务与预测", "2026 年前三季度收入增 55.7%，利润与现金流开始承压", "先拆解历史增长和盈利质量，再检验最新季度的研发、毛利率、存货与现金流，最后比较卖方远期预测。", [("16—17", "历史增长", "收入结构与 2025 盈利质量"), ("18—19", "最新季度", "研发、毛利率、存货与现金流"), ("20", "预测分歧", "四份卖方模型与修订方向")])

# 16 历史营收
main = [text("rev-chart-title", 65, 153, 620, 22, "营业收入（亿元）", "$exhibitTitle", wrap=False),
        chart("rev-history", 63, 184, 620, 315, ["年份", "收入"], [["2022", 1.23], ["2023", 1.59], ["2024", 3.93], ["2025", 16.99]], [bar_series("营业收入", "年份", "收入", "$dk2", True)], legend=False, barWidth=0.5),
        text("rev-profit-title", 715, 153, 390, 22, "2025 利润与结构", "$exhibitTitle", wrap=False)]
main += kpi_cards("rev-profit", [("归母净利润", "¥2.78 亿", "2025"), ("扣非净利润", "¥5.91 亿", "2025"), ("人形收入占比", "51.78%", "主营业务")], x=715, y=184, total_w=390, h=116, gap=10)
main += [text("rev-mix-title", 715, 330, 390, 22, "增长驱动", "$exhibitTitle", wrap=False)]
main += bullet_list("rev-drivers", ["四足建立规模与现金流基础", "人形成为第一大收入来源", "2022—2025 营收 CAGR 约 140%"], 715, 370, 390, 55)
main += callout("rev-note", "历史拐点已经实现，但不能线性外推", "2025 年收入与扣非利润同步跃升；后续需要判断高增速能否穿越价格下降、竞争和研发投入周期。", x=63, y=532, w=1042, h=94)
main += [text("rev-mix-note", 65, 648, 1040, 42, "2025 主营收入结构：人形 51.78% / 四足 41.62% / 组件 6.19% / 其他 0.41%。", "$body", wrap=True)]
content_page(16, "Part Three › Financials › Revenue History", "营收三年由 1.23 亿升至 16.99 亿，人形成为 51.8% 收入主引擎", "四足建立规模基础后人形快速放量，2025 年收入与扣非利润同步跃升", "1. CAGR 由 2022—2025 年营收计算；2022 年数据来自招股书及券商整理。", "招股说明书；东吴证券；华金证券", main, [("三年高速放量", "营收由 1.23 亿元升至 16.99 亿元，CAGR 约 140%。"), ["人形接替增长", "2025 年人形收入 8.68 亿元，占主营 51.78%。"], ["盈利拐点已现", "2025 年扣非净利润 5.91 亿元，主业已盈利。"]])

# 17 盈利质量
main = [text("quality-margin-title", 65, 153, 500, 22, "2025 毛利率对比（%）", "$exhibitTitle", wrap=False),
        chart("quality-margin", 63, 184, 500, 280, ["公司", "毛利率"], [["宇树", 60.44], ["可比均值", 44.44]], [bar_series("毛利率", "公司", "毛利率", "$dk2", False)], legend=False, barWidth=0.42),
        text("quality-profit-title", 605, 153, 500, 22, "归母与扣非净利润（亿元）", "$exhibitTitle", wrap=False),
        chart("quality-profit", 603, 184, 500, 280, ["口径", "净利润"], [["归母", 2.7821], ["扣非", 5.9075]], [bar_series("净利润", "口径", "净利润", "$dk2", False)], legend=False, barWidth=0.42)]
main += kpi_cards("quality-kpi", [("扣非净利率", "34.8%", "2025"), ("利润差额", "¥3.13 亿", "扣非−归母"), ("股份支付", "¥3.49 亿", "非现金费用")], x=63, y=490, total_w=1042, h=100)
main += callout("quality-note", "会计扰动与经营趋势分开", "股份支付压低归母净利润但不涉及现金流出；判断经营趋势应同时看扣非利润与现金流，而非只看归母增速。", x=63, y=615, w=1042, h=78)
content_page(17, "Part Three › Financials › Earnings Quality", "2025 年扣非净利率达 34.8%，股份支付使归母与扣非相差 3.13 亿", "一次性股份支付压低归母净利润但不涉及现金流出，判断经营趋势应同时看扣非与现金流", "1. 扣非净利率按扣非净利润/营业收入计算；可比均值来自招股说明书。2. 股份支付为 2025 年一次性非现金费用。", "招股说明书上会稿；东吴证券", main, [("毛利率领先同业", "2025 综合毛利率 60.44%，可比均值 44.44%。"), ["扣非更能反映主业", "归母 2.78 亿元、扣非 5.91 亿元，差额 3.13 亿元。"], ["避免误读会计费用", "3.49 亿元股份支付不涉及现金流出。"]])

# 18 最新季度
main = kpi_cards("q3", [("单 Q3 收入", "+69.9%", "6.65 亿元"), ("单 Q3 扣非", "−17.4%", "1.05 亿元"), ("单 Q3 研发", "+249.6%", "1.27 亿元"), ["前三季度毛利率", "54.02%", "同比 −5.73pct"]])
main += [text("q3-yoy-title", 65, 282, 630, 22, "单 Q3 同比增速（%）", "$exhibitTitle", wrap=False),
         chart("q3-yoy", 63, 314, 630, 260, ["指标", "同比"], [["营业收入", 69.93], ["归母净利", -17.37], ["扣非净利", -17.42]], [bar_series("同比增速", "指标", "同比", "$dk2", True)], yAxis={"label": {"fontSize": 14, "color": "#666666"}, "axisLine": False, "gridLine": False, "min": -30, "max": 80}, legend=False, barWidth=0.45),
         text("q3-rd-title", 730, 282, 375, 22, "利润约束来自哪里", "$exhibitTitle", wrap=False)]
main += bullet_list("q3-drivers", ["研发费用率升至 19.10%", "销售与研发团队同步扩张", "毛利率回落至 50.58%（单 Q3）", "成本增速高于收入增速"], 730, 322, 375, 56)
main += callout("q3-note", "三季报尚不能解释全部毛利下滑", "三季报未披露分产品收入与毛利率，暂不能区分价格、产品结构和制造成本影响；需在后续披露中核验。", x=63, y=598, w=1042, h=84)
content_page(18, "Part Three › Financials › Latest Quarter", "Q3 收入增 69.9% 而扣非降 17.4%，研发增量是主要利润约束", "三季度收入加速，但毛利率回落与研发、销售投入增加共同压缩当期利润", "1. 三季报未经审计；前三季度毛利率按收入与成本计算。2. 三季报未披露分产品毛利率，暂不作进一步归因。", "公司 2026 年三季报；东吴证券三季报点评", main, [("收入仍在加速", "单 Q3 收入 6.65 亿元、同比增 69.93%。"), ["利润开始承压", "单 Q3 扣非净利润 1.05 亿元、同比降 17.42%。"], ["研发投入是主变量", "单 Q3 研发 1.27 亿元、费用率 19.10%。"]])

# 19 营运资金
main = kpi_cards("wc", [("存货", "+177.1%", "期末 10.19 亿元"), ("应收账款", "+143.5%", "期末 1.43 亿元"), ("合同负债", "+70.2%", "期末 2.33 亿元"), ["经营现金流", "−54.7%", "前三季度 1.94 亿元"]])
main += [text("wc-balance-title", 65, 282, 630, 22, "2025 年末 → 2026Q3 末（亿元）", "$exhibitTitle", wrap=False),
         chart("wc-balance", 63, 314, 630, 265, ["科目", "年初", "期末"], [["存货", 3.68, 10.19], ["应收账款", 0.59, 1.43], ["合同负债", 1.37, 2.33]], [bar_series("2025 年末", "科目", "年初", "$accent3", True), bar_series("2026Q3 末", "科目", "期末", "$accent1", False)], barWidth=0.55),
         text("wc-cash-title", 730, 282, 375, 22, "现金缓冲与使用", "$exhibitTitle", wrap=False)]
main += kpi_cards("wc-cash", [("货币资金", "¥73.54 亿", "IPO 募资到账"), ("经营现金流", "¥1.94 亿", "同比 −54.69%")], x=730, y=314, total_w=375, h=116, gap=10)
main += bullet_list("wc-points", ["备货与预收支持后续交付", "采购、人工与研发支出占用现金", "需核验存货周转和订单转化"], 730, 458, 375, 50)
main += callout("wc-note", "现金储备不等于经营现金流改善", "货币资金增加主要来自 IPO 募资；经营现金流下降才是当期营运质量信号，需与存货和应收共同解读。", x=63, y=606, w=1042, h=78)
content_page(19, "Part Three › Financials › Working Capital", "存货较年初增 177%、经营现金流降 54.7%，备货转化需重点核验", "备货与预收同步增加支持后续交付，但采购、人工和费用支出已显著压缩现金净流入", "1. 货币资金增加主要来自 IPO 募资，不应理解为经营现金流改善。2. 存货、应收与合同负债均为期末资产负债表口径。", "公司 2026 年三季报", main, [("备货显著上升", "存货 10.19 亿元、较年初增约 177%。"), ["订单信号与现金压力并存", "合同负债增加，但经营现金流下降 54.69%。"], ["资金缓冲充足", "货币资金 73.54 亿元，可支撑投入但需看转化。"]])

# 20 卖方预测
main = [text("forecast-table-title", 65, 153, 1040, 22, "四份卖方模型预测对照（亿元）", "$exhibitTitle", wrap=False),
        native_table("forecast-table", 63, 184, 1042, 276, [["报告", "2026 收入", "2027 收入", "2028 收入", "2028 归母"], ["东吴 2026-08-09", "30.97", "49.60", "76.83", "22.37"], ["华鑫 2026-09-19", "27.56", "45.43", "68.74", "12.68"], ["太平洋 2026-10-19", "27.91", "43.13", "64.82", "15.10"], ["东吴 2026-10-29", "26.27", "43.13", "59.53", "15.08"]], [0.32, 0.17, 0.17, 0.17, 0.17], 14),
        text("forecast-chart-title", 65, 486, 650, 22, "2028 归母净利润预测（亿元）", "$exhibitTitle", wrap=False),
        chart("forecast-chart", 63, 516, 650, 120, ["机构", "净利润"], [["东吴 8 月", 22.37], ["华鑫", 12.68], ["太平洋", 15.10], ["东吴 10 月", 15.08]], [bar_series("2028E 归母", "机构", "净利润", "$accent1", True)], legend=False, barWidth=0.48),
        text("forecast-revision-title", 740, 486, 365, 22, "东吴两版修订", "$exhibitTitle", wrap=False)]
main += kpi_cards("forecast-revision", [("2028 收入", "−22.5%", "76.83 → 59.53"), ("2028 归母", "−32.6%", "22.37 → 15.08")], x=740, y=516, total_w=365, h=108, gap=10)
main += callout("forecast-note", "远期假设比近期收入更分歧", "2028 年预测高低差约 1.76x；东吴最新模型因加码研发与算力显著下修，估值必须同时呈现利润与倍数敏感性。", x=63, y=648, w=1042, h=52)
content_page(20, "Part Three › Forecasts › Seller Comparison", "4 份卖方模型 2028 年净利相差 1.8x，远期假设比近期收入更分歧", "各机构对 2026 年收入预测相对集中，对 2028 年业务增速、净利率与研发费用假设差异扩大", "1. 预测分别来自东吴 2026-08-09、华鑫 2026-09-19、太平洋 2026-10-19、东吴 2026-10-29；均为券商预测（估计值，estimate）而非公司指引。", "4 份机构完整研报；团队计算", main, [("远期离散度更高", "2028 归母预测从 12.68 到 22.37 亿元。"), ["最新预测已下修", "东吴 10 月版显著下调收入与利润。"], ["不能单点估值", "预测与退出倍数必须联合敏感性分析。"]])

# 21 估值与投决隔页
divider(21, "PART FOUR · 估值与投决", "约 2,698 亿元市值要求超额兑现，估值是投决的第一约束", "用反向估值、情景折现和风险登记册回答：当前价格需要多少利润、多少倍数和多少商业验证才能成立。", [("22", "反向估值", "现价隐含的 2028 利润要求"), ("23", "情景价值", "下行、基准与乐观三档"), ("24", "风险与执行", "催化剂、监测指标与复议安排")])

# 22 反向估值
main = [rect("reverse-formula-bg", 63, 150, 1042, 88, "$dk2"),
        text("reverse-formula-kicker", 80, 163, 1000, 18, "REVERSE VALUATION", "$darkKicker", wrap=False),
        text("reverse-formula", 80, 190, 1000, 30, "所需 2028 净利 = 当前市值 × 1.12² ÷ 退出 PE", "$darkValue", fontSize=22, fontFamily="Georgia, 楷体", wrap=False)]
main += kpi_cards("reverse-kpi", [("当前市值", "¥2,698 亿", "2026-10-30 盘中"), ("两年后预期市值", "¥3,384 亿", "12% 要求回报"), ["100x 所需净利", "¥33.85 亿", "2028"], ["60x 所需净利", "¥56.41 亿", "2028"]], x=63, y=262, total_w=1042, h=108)
main += [text("reverse-chart-title", 65, 400, 630, 22, "所需净利与卖方最高预测（亿元）", "$exhibitTitle", wrap=False),
         chart("reverse-chart", 63, 432, 630, 235, ["口径", "净利润"], [["卖方最高预测", 22.37], ["100x 要求", 33.85], ["60x 要求", 56.41]], [bar_series("2028 净利", "口径", "净利润", "$accent1", False)], legend=False, barWidth=0.45),
         text("reverse-sens-title", 730, 400, 375, 22, "预期差", "$exhibitTitle", wrap=False)]
main += kpi_cards("reverse-gap", [("相对最高预测", "+51.3%", "100x 要求 vs 22.37"), ("相对最低预测", "+344.9%", "60x 要求 vs 12.68")], x=730, y=432, total_w=375, h=116, gap=10)
main += callout("reverse-note", "现价需要“利润上修 + 高倍数延续”", "即使按 100x 退出 PE，所需利润仍高于四份卖方最高预测；若倍数回落到 60x，业绩要求进一步上升。", x=63, y=664, w=1042, h=50)
content_page(22, "Part Four › Valuation › Reverse Expectations", "现价需 2028 年净利约 34—56 亿元，较主流预测高 51%—345%", "以 12% 要求回报折现两年，只有维持 100x—60x 退出 PE 并显著超越卖方预测才能支撑市值", "1. 反向估值为内部假设，不是目标价；未考虑分红与净现金调整。2. 四份卖方 2028 净利预测范围为 12.68—22.37 亿元。", "Wind；4 份机构研报；团队测算", main, [("现价隐含超额增长", "100x 退出也需净利约 33.85 亿元。"), ["倍数回落提高门槛", "60x 退出所需净利约 56.41 亿元。"], ["预期差是核心风险", "所需利润高于主流预测 51%—345%。"]])

# 23 情景估值
main = []
scenarios = [("下行 · 30%", "¥112", "12.68 亿净利 / 45x", "−83.1%", "$lt2"), ("基准 · 50%", "¥265", "22.37 亿净利 / 60x", "−60.3%", "$accent4"), ("乐观 · 20%", "¥631", "32.02 亿净利 / 100x", "−5.4%", "$lt2")]
for i, (name, value, assumption, ret, bg) in enumerate(scenarios):
    x = 63 + i * 350
    main += [rect(f"sc-bg-{i}", x, 150, 330, 245, bg),
             rect(f"sc-band-{i}", x, 150, 330, 4, "$accent1" if i == 2 else "$dk2"),
             text(f"sc-name-{i}", x + 16, 169, 298, 20, name, "$panelItemTitle"),
             text(f"sc-value-{i}", x + 16, 202, 298, 42, value, "$heroNumeral", color="$accent2" if i == 2 else "$dk2"),
             text(f"sc-assumption-{i}", x + 16, 256, 298, 40, assumption, "$body"),
             text(f"sc-return-{i}", x + 16, 312, 298, 26, f"对现价 {ret}", "$statNumeral", color="$accent5"),
             text(f"sc-note-{i}", x + 16, 350, 298, 26, "2028 → 当前折现价值", "$footnote")]
main += kpi_cards("sc-weighted", [("概率加权价值", "¥292 / 股", "30% / 50% / 20%"), ("当前股价", "¥667.10 / 股", "2026-10-30 盘中"), ["乐观情景差距", "−5.4%", "仍未覆盖要求回报"]], x=63, y=425, total_w=1042, h=108)
main += [text("sc-sens-title", 65, 560, 1040, 22, "估值使用的关键假设", "$exhibitTitle", wrap=False),
         native_table("sc-sens", 63, 590, 1042, 100, [["折现率", "折现期", "退出 PE", "利润口径"], ["12%", "2 年", "45x / 60x / 100x", "2028 归母净利润"]], [0.18, 0.18, 0.34, 0.30], 14)]
content_page(23, "Part Four › Valuation › Scenario Analysis", "三情景折现价值均低于现价，乐观情景也仅接近 631 元", "即使采用 2028 年 32.02 亿元净利与 100x 退出 PE，折现后仍略低于当前股价", "1. 情景概率、退出 PE 与折现率为内部讨论假设；不是盈利预测或目标价。2. 乐观利润采用媒体转述的摩根大通预测；未考虑分红与净现金。", "4 份机构研报；财新；腾讯新闻；团队测算", main, [("乐观也缺乏安全边际", "32.02 亿净利与 100x 仍仅对应约 631 元。"), ["基准价值显著更低", "22.37 亿净利与 60x 对应约 265 元。"], ["概率加权仅作比较", "约 292 元用于风险收益讨论，不是目标价。"]])

# 24 风险与催化剂
main = [text("risk-title", 65, 153, 650, 22, "六项风险与监控口径", "$exhibitTitle", wrap=False),
        native_table("risk-table", 63, 184, 650, 412, [["风险", "季度监控"], ["商业订单不及预期", "行业应用占比、重复采购"], ["模型研发回报不足", "成功率、接管率、连续运行"], ["毛利率与价格竞争", "分产品均价与毛利率"], ["费用与算力投入超支", "研发费率、算力投入"], ["存货与现金流", "周转、合同负债、OCF"], ["估值与解禁", "远期 PE、2027-08 解禁"]], [0.44, 0.56], 13),
        text("catalyst-title", 740, 153, 365, 22, "五个复核与催化节点", "$exhibitTitle", wrap=False)]
catalysts = [("2026Q4", "年报与分产品毛利"), ("2027H1", "制造基地与产能爬坡"), ("2027 年内", "模型现场指标与订单"), ("2027-08", "首轮限售股解禁"), ("持续", "行业政策与商业部署")]
for i, (date, event) in enumerate(catalysts):
    y = 192 + i * 78
    main += [text(f"cat-date-{i}", 740, y, 110, 20, date, "$chartLabel", wrap=False),
             rule(f"cat-rule-{i}", 740, y + 27, 365, "$accent1" if i == 3 else "$ruleRow", 1.5),
             text(f"cat-event-{i}", 740, y + 36, 365, 34, event, "$body")]
main += callout("risk-action", "复议规则", "经营证据和估值安全边际需同时改善；大会、模型发布或单日股价上涨本身不足以改变“不建仓”建议。", x=63, y=624, w=1042, h=72)
content_page(24, "Part Four › Risks & Execution › Monitoring Plan", "6 项风险与 5 个催化剂同向跟踪，2027 年解禁前需看到订单质量", "把估值风险转成季度可观测指标，避免仅按大会、模型发布或单日股价调整判断", "1. 解禁时间来自公开报道与发行锁定安排，实际数量与日期以公司公告为准。2. 复核频率为季度及重大披露后。", "公司公告；财新；团队分析", main, [("风险必须可观测", "订单、模型、毛利、费用、现金与估值均绑定序列。"), ["解禁是额外窗口", "2027 年 8 月前需要看到商业质量提升。"], ["复议不追单点催化", "经营证据与估值条件需同时满足。"]])

# 25 附录与方法论
appendix = [text("chrome-breadcrumb", 65, 12.5, 1312, 14.8, "Appendix › Methodology, Sources & Disclaimer", "$breadcrumb", wrap=False),
            text("chrome-title", 65, 34.3, 1312, 48, "研究方法覆盖 4 家机构 5 份研报，预测与估计分口径标注", "$actionTitle", fontSize=32, wrap=False, align=["left", "middle"]),
            text("chrome-subtitle", 65, 88, 1312, 21.5, "原始披露优先，机构预测并列，内部情景单独标识；所有关键数字均可回溯至数据台账", "$subtitle", wrap=False),
            rule("chrome-rule-top", 63, 117, 1314, "$dk1"),
            text("method-title", 65, 137, 630, 24, "I. 研究方法", "$sectionHeader"),
            text("source-title", 740, 137, 637, 24, "II. 完整研报与原始资料", "$sectionHeader")]
methods = [("实际值", "公司招股书、问询回复与 2026 年三季报；以期末报告口径为准。"), ("行业与竞争", "Yano Research、GGII、Omdia 等第三方口径并列，不强行消除统计差异。"), ("卖方预测", "东吴两版、华鑫、太平洋完整报告；单家预测不作为公司指引。"), ("内部估值", "12% 要求回报、2 年折现、45x/60x/100x 退出 PE 与主观情景概率。"), ("数据治理", "71 个数据点登记来源、时间、口径、原文坐标与使用页码，并复算派生值。")]
for i, (t, b) in enumerate(methods):
    y = 180 + i * 92
    appendix += [text(f"method-t-{i}", 65, y, 150, 22, t, "$panelItemTitle"), text(f"method-b-{i}", 220, y, 480, 68, b, "$body"), rule(f"method-rule-{i}", 63, y + 72, 636, "$ruleRow")]
source_files = ["东吴证券｜人形机器人产业化奇点已至（2026-08-09，32 页）", "华金证券｜新股覆盖研究（2026-08-12，12 页）", "华鑫证券｜茁壮成长的中国树（2026-09-19，8 页）", "太平洋证券｜宇树科技深度报告（2026-10-19，32 页）", "东吴证券｜2026 年三季报点评（2026-10-29，3 页）", "公司资料｜招股说明书、两轮问询回复、2026 年三季报", "补充资料｜Wind、同花顺共识、财新、中国证券报等公开信息"]
for i, item in enumerate(source_files):
    y = 180 + i * 55
    appendix += [rect(f"source-dot-{i}", 740, y + 6, 5, 5, "$accent2"), text(f"source-item-{i}", 755, y, 622, 46, item, "$body"), rule(f"source-rule-{i}", 740, y + 43, 637, "$ruleRow")]
appendix += [rect("disclaimer-bg", 740, 582, 637, 120, "$lt2"),
             text("disclaimer-title", 756, 595, 600, 20, "III. 使用限制", "$panelItemTitle"),
             text("disclaimer-body", 756, 623, 600, 66, "本材料用于内部投委会讨论，含第三方预测和内部情景假设，不构成证券买卖要约、收益承诺或个性化投资建议。行情与预测均可能变化，使用时应更新。", "$footnote"),
             text("chrome-footnotes", 65, 724.1, 1312, 51.6, "完整研报与原始披露存放于 output/research；关键数字登记与复算见 output/deck/data-registry.json。", "$footnote", align=["left", "bottom"]),
             rule("chrome-rule-bottom", 63, 780.8, 1314, "$ruleRow"),
             text("chrome-source", 65, 788, 500, 14.8, "Source: 本页所列完整资料与数据台账", "$footer", wrap=False),
             text("chrome-brand-center", 820, 788, 400, 14.8, "IC MEMO · 投决会材料", "$footer", color="$accent6", fontFamily="Georgia, 楷体", wrap=False, align=["right", "top"]),
             text("chrome-pageno", 1250, 788, 127, 14.8, "25", "$footer", wrap=False, align=["right", "top"])]
write_page(25, appendix)

# 主入口
presentation = {
    "version": "v2",
    "title": "宇树科技投资价值投委会",
    "size": [1440, 810],
    "theme": {
        "colors": {
            "dk1": "#000000", "lt1": "#FFFFFF", "dk2": "#051C2C", "lt2": "#F2F2F2",
            "accent1": "#00A9F4", "accent2": "#006BA6", "accent3": "#B8C4CC", "accent4": "#E3F2FD",
            "accent5": "#666666", "accent6": "#999999", "hlink": "#006BA6", "folHlink": "#954F72",
            "inkBody": "#333333", "ruleRow": "#CCCCCC", "onDarkBody": "#D9E4EA", "onDarkSecondary": "#BFD3DE",
            "onDarkLabel": "#8FA3B0", "onDarkRule": "#24435A", "darkAlt": "#0A2637", "panelSubtle": "#F8F8F8",
            "coverPanel": "#061422E6", "coverHairline": "#FFFFFF29", "coverStatBg": "#FFFFFF1C", "onDarkStatLabel": "#C9DCE8"
        },
        "textStyles": {
            "breadcrumb": {"color": "$accent5", "fontSize": 14, "fontFamily": "Arial, 楷体"},
            "actionTitle": {"color": "$dk1", "fontSize": 28, "fontFamily": "Georgia, 楷体", "bold": True, "lineHeight": 0.98},
            "subtitle": {"color": "$inkBody", "fontSize": 18, "fontFamily": "Arial, 楷体", "lineHeight": 1.03},
            "footnote": {"color": "$accent5", "fontSize": 12, "fontFamily": "Arial, 楷体", "lineHeight": 1.0},
            "footer": {"color": "$accent5", "fontSize": 12, "fontFamily": "Arial, 楷体", "lineHeight": 1.0},
            "unitLabel": {"color": "$accent5", "fontSize": 14, "fontFamily": "Arial, 楷体"},
            "exhibitTitle": {"color": "$dk2", "fontSize": 18, "fontFamily": "Arial, 楷体", "bold": True},
            "sectionHeader": {"color": "$dk2", "fontSize": 18, "fontFamily": "Arial, 楷体", "bold": True},
            "body": {"color": "$inkBody", "fontSize": 16, "fontFamily": "Arial, 楷体", "lineHeight": 1.25},
            "bodyTight": {"color": "$inkBody", "fontSize": 16, "fontFamily": "Arial, 楷体", "lineHeight": 1.25},
            "panelItemTitle": {"color": "$dk2", "fontSize": 16, "fontFamily": "Arial, 楷体", "bold": True},
            "panelBody": {"color": "$inkBody", "fontSize": 16, "fontFamily": "Arial, 楷体", "lineHeight": 1.25},
            "kicker": {"color": "$accent5", "fontSize": 14, "fontFamily": "Arial, 楷体"},
            "microLabel": {"color": "$accent6", "fontSize": 14, "fontFamily": "Arial, 楷体"},
            "tableHeader": {"color": "$accent5", "fontSize": 14, "fontFamily": "Arial, 楷体", "bold": True},
            "tableBody": {"color": "$inkBody", "fontSize": 16, "fontFamily": "Arial, 楷体"},
            "tableBodyBold": {"color": "$dk2", "fontSize": 16, "fontFamily": "Arial, 楷体", "bold": True},
            "heroNumeral": {"color": "$dk2", "fontSize": 36, "fontFamily": "Georgia, 楷体", "bold": True, "lineHeight": 1},
            "statNumeral": {"color": "$dk2", "fontSize": 24, "fontFamily": "Georgia, 楷体", "bold": True, "lineHeight": 1},
            "chartLabel": {"color": "$dk2", "fontSize": 14, "fontFamily": "Arial, 楷体", "bold": True},
            "accentText": {"color": "$accent2", "fontSize": 14, "fontFamily": "Arial, 楷体", "bold": True},
            "accentTextLarge": {"color": "$accent2", "fontSize": 18, "fontFamily": "Arial, 楷体", "bold": True},
            "darkKicker": {"color": "$onDarkLabel", "fontSize": 14, "fontFamily": "Arial, 楷体"},
            "darkBody": {"color": "$onDarkBody", "fontSize": 14, "fontFamily": "Arial, 楷体", "lineHeight": 1.25},
            "darkLabel": {"color": "$onDarkLabel", "fontSize": 14, "fontFamily": "Arial, 楷体"},
            "darkValue": {"color": "$lt1", "fontSize": 14, "fontFamily": "Arial, 楷体", "bold": True},
            "coverH1": {"color": "$lt1", "fontSize": 66, "fontFamily": "Georgia, 楷体", "bold": True, "lineHeight": 0.92},
            "dividerH": {"color": "$dk1", "fontSize": 50, "fontFamily": "Georgia, 楷体", "bold": True, "lineHeight": 0.95},
            "partLabel": {"color": "$accent5", "fontSize": 18, "fontFamily": "Georgia, 楷体", "letterSpacing": 4.5}
        }
    },
    "pages": [f"pages/page-{i:02d}.page" for i in range(1, 26)]
}
(ROOT / "presentation.pptd").write_text(yaml.safe_dump(presentation, allow_unicode=True, sort_keys=False, width=1200), encoding="utf-8")
print(f"Generated {len(presentation['pages'])} pages in {ROOT}")
