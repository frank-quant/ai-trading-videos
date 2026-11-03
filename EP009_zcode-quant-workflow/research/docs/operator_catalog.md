# 零件目录（parts catalog）

> 第 4 步搜索 Agent 的唯一零件参考。每个零件 = `engine/operators.py` 注册表里的
> 一个键，可在策略 YAML 的 `buy` / `sell` / `rank` / `factors` 里按 spec 引用：
> `{op: 名字, n: 窗口?, of?: 嵌套spec?}`。窗口 n 只能取 3/5/10/20/60/120/250，
> 阈值只能取 rules.md 第 7 节档位（由 `engine/config.py` 强校验，越档即拒）。
>
> **对齐口径总原则**（rules.md 7.5，point-in-time）：T 日收盘出信号，零件的
> 「T 日值」只依赖 ≤ T 的信息。财务/预告/快报按公告日 `ann_date` 对齐；
> 龙虎榜（top_list/top_inst）T 日盘后披露 → T 日收盘信号**可用当日（≤T）记录**；
> 两融（margin_detail）与北向（hk_hold）当前按 **trade_date < T**
> 对齐；实际可用时点仍须按历史披露制度审核，尤其不能把北向统一滞后一天视为已完成全时期审核。行业按申万 in_date ≤ T < out_date；估值/规模
> （daily_basic）T 日盘后可得 → 用 T 日值。
>
> **缺失语义总原则**：任何零件的数据缺失一律输出 NaN，绝不用 0 填充。NaN 作
> 条件（buy/sell）恒为 False；作打分因子时经截面排名映射为中性 0.5；作 rank
> 排序键时排在并列末尾。窗口零件前 n−1 行（窗口不完整）为 NaN。

## 1. 量价零件

| yaml 键 | 语义 | 参数 | 可作条件 | 阈值量纲 |
|---|---|---|---|---|
| `ret_n` | N 日涨跌幅 %（复权净值口径 adj_nav[T]/adj_nav[T−n]−1；停牌夹在中间为含停牌区间收益） | n | ✓ | pct（±1/2/3/5/8/10/15） |
| `ma_n` | N 日均线（复权净值口径；numpy 滑动窗口，确定性） | n | ✓ | pct |
| `close_over_ma_n` | 收盘 / N 日均线（无量纲倍数） | n | ✓ | mult（0.5~2.0） |
| `dist_high_n` | 收盘距 N 日最高的幅度 %（≤0，复权口径） | n | ✓ | pct |
| `dist_low_n` | 收盘距 N 日最低的幅度 %（≥0） | n | ✓ | pct |
| `close_pos_range` | 收盘在当日振幅中的位置（0~1；一字板按涨跌向 0/1） | — | ✓ | mult |
| `vol_ratio_n` | 量比 = 当日量 / 前 N 日均量（不含当日） | n | ✓ | mult |
| `turn` | 当日换手率 %（daily_basic.turnover_rate 原值） | — | ✓ | pct |
| `turn_ma_n` | N 日平均换手率 % | n | ✓ | pct |
| `vol_n` | N 日收益波动率 %（pct_chg 样本标准差 ddof=1） | n | ✓ | pct |
| `atr_close_n` | N 日 ATR / 当日收盘 %（不复权口径） | n | ✓ | pct |
| `streak_up` | 连续上涨天数（pct_chg>0 累积，无上界窗口） | — | ✓ | streak（3/5/10/20/60/120/250） |
| `streak_down` | 连续下跌天数 | — | ✓ | streak |
| `break_high_n` | 是否突破 N 日最高（1/0；前 N 根不含当日，不足 N 根 → NaN） | n | ✓ | mult |
| `etf_above_ma_n` | **沪深300 ETF** 复权收盘是否在 N 日均线上方（1/0；市场级，ETF 日线上求值，与个股行无关） | n | ✓ | mult |

## 2. 规模 / 估值 / 财务 / 预告快报零件（rules.md 7.5）

全部 `threshold_kind=none`：**只能作打分因子 / rank / 嵌套基值，不能作 buy/sell 条件**。
财务与预告/快报列已在 `engine/prices.py` 严格按 `ann_date` 对齐（T 日只见 ann_date ≤ T
的最新一期；同公告日取 end_date 更晚者）。

| yaml 键 | 语义 | 缺失语义 |
|---|---|---|
| `size_ln` | 流通市值自然对数（daily_basic.circ_mv，**单位万元**） | circ_mv 缺 → NaN |
| `pe_ttm` | 市盈率 TTM（daily_basic 原值；亏损为负） | NaN |
| `pb` | 市净率（原值） | NaN |
| `ps_ttm` | 市销率 TTM（原值） | NaN |
| `roe` | 最新一期 ROE（fina_indicator，ann_date 对齐） | 无可见财报 → NaN |
| `or_yoy` | 营业收入同比 %（ann_date 对齐） | NaN |
| `netprofit_yoy` | 归母净利润同比 %（ann_date 对齐） | NaN |
| `fc_type_code` | 最近一次业绩预告类型编码：预增 2 / 扭亏 1.5 / 略增 1 / 续盈 0.5 / 不确定 0 / 续亏 −0.5 / 首亏 −1.5 / 略减 −1 / 预减 −2 | 无预告 → NaN |
| `fc_chg_mid` | 最近一次预告变动幅度 %（(p_change_min+p_change_max)/2，单边取单边） | 无预告 → NaN |
| `fc_days` | 距最近一次预告公告日的自然日数（T − ann_date） | 无预告 → NaN |
| `ex_yoy` | 最近一次快报净利同比 %（express.yoy_net_profit，ann_date 对齐） | 无快报 → NaN |
| `ex_days` | 距最近一次快报公告日的自然日数 | 无快报 → NaN |

## 3. 通用嵌套零件（rules.md 7.5「任意零件的时序/截面分位」）

spec 形态 `{op, n?, of: 基spec}`，嵌套一层（可复合，如 ts_pct of xsec_pct of pb）。

| yaml 键 | 语义 | 缺失语义 |
|---|---|---|
| `ts_pct` | 基零件值在过去 n 根K线的时序分位（0~1，含当日；窗口内任何 NaN → NaN） | 窗口不完整 → NaN |
| `xsec_pct` | 基零件值当日截面分位（0~1，并列平均名次；整日全组参与） | 组内全 NaN → NaN |
| `ind_rank` | 基零件值当日**申万一级行业内**分位（0~1） | 无行业归属 → NaN |

## 4. 资金面零件（rules.md 7.5）

实现中的字段与对齐约定：
- `top_list` / `top_inst` 无 ann_date，T 日盘后披露 → **T 日收盘信号可用
  trade_date ≤ T 记录**（当日上榜当日可用）。
- `margin_detail`与`hk_hold`在当前实现中按`trade_date < T`对齐。实际公布时间须另行核验，缺失或制度变更后的未知可用时点不得当作已知。
- `hk_hold` 只用 exchange=SH/SZ（北向持股 A 股部分；HK 记录是南向，剔除）。
  北向明细与整体资金流的覆盖范围不同，按各自源表核验；无明细记录的日期保留NaN。
- **单位换算**：`margin_detail.rzye`（融资余额）单位**元**；`daily_basic.circ_mv`
  单位**万元**（×1e4 → 元）；`top_list.l_amount` 与 `top_inst.net_buy` 单位**元**；
  `hk_hold.ratio` = 北向持股/流通股本×100（%，vol 单位为股）。
- `top_inst` 列语义：`net_buy`
  列 = 机构/营业部席位净成交额（买入−卖出，元），**可直接求和**；「机构席位」=
  `exalter == "机构专用"`。

| yaml 键 | 语义（T 日值） | 对齐口径 | 缺失语义 | 参数/量纲 |
|---|---|---|---|---|
| `top_list_n` | 近 N 日是否上过龙虎榜（1/0；窗口=该股最近 n 行K线**含当日**，当日上榜也算） | 龙虎榜 ≤T（当日盘后披露、当日收盘信号可用） | 窗口不完整（前 n−1 行）→ NaN；从不上榜 = 0 | n；mult（阈值 0.5 = 「上过」） |
| `inst_netbuy` | 最近一次上榜事件的**机构席位净买入占比 %** = Σ(该次上榜机构专用席位 net_buy，元) / 该次上榜全部理由行 l_amount 最大值（元）× 100 | ≤T 的最新一次上榜事件（当日上榜当日即有值，之后保持到下一次上榜） | 从未上榜 → NaN；该次上榜无机构席位 = 0（真实零，非填充）；l_amount≤0 → NaN | —；pct |
| `margin_ratio` | 融资余额占流通市值比 % = rzye(T−1 披露，元) / (circ_mv(T 日，万元)×1e4) × 100 | 两融 <T（≤T−1）；市值 T 日 | 两融或市值任一缺失 → NaN（2014 年初仅约 700 只标的两融，未覆盖即 NaN） | —；pct |
| `margin_chg_n` | 融资余额近 N 日变化率 % = 对齐 rzye[T] / rzye[T−n] − 1（T−n 行即 ≤T−n−1 口径） | 两融 <T | 窗口不完整 / 前值 0 或缺失 → NaN | n；pct（可负） |
| `hk_ratio` | 北向持股占流通股本 %（hk_hold.ratio 原值，SH/SZ） | 北向 <T（≤T−1） | 无记录或覆盖开始之前 → NaN | —；pct |
| `hk_chg_n` | 北向持股占比近 N 日变化（**百分点**）= 占比[T] − 占比[T−n] | 北向 <T | 窗口不完整 / 任一缺失 → NaN | n；pct（可负） |

## 5. 打分型专用 yaml 键（规则型不可用）

| yaml 键 | 语义 | 缺省 |
|---|---|---|
| `rebalance` | 调仓频率：`weekly_first_trade_day`（每周第一个交易日）或 `monthly_first_trade_day`（每月第一个交易日）。L1 按频率分档：周度 ≥300 期、月度 ≥80 期 | 周度 |
| `neut_industry` | **行业内排名中性化**（独立开关）：每个因子先去极值 + 全截面排名，再在当日**申万一级行业**内重排名（无行业股票自成一组，组内并列平均名次；组内 NaN 值 → 中性 0.5；单元素组 → 0.5）。分数只表达行业内相对强弱 | false |
| `neut_size` | **市值分档内排名中性化**（独立开关）：当日截面按**流通市值**排名均分 **5 档**（每档约 1/5，并列按平均名次，确定性），在档内重排名；流通市值缺失自成一组 | false |
| `holdings` | 打分型持仓数，固定 30（rules.md 第 4 节，不可改） | 30 |

两开关可各自独立启用；同时启用时**先行业内秩、再市值档内秩**逐级复合（单调变换
可复合）。生效口径（industry_rank / size_bucket_rank 两布尔）随每次回测写入
run 目录 `summary.json` 的 `neutralization` 字段与 `rebalance` 字段（rules.md
7.5「报告里注明用了哪种」的机器可读载体）。

规则型 `max_hold_days` 档位：**3/5/10/20/40/60**（rules.md 第7节）。

## 6. 引用样例

以下为字段片段，不是完整配置文件。完整YAML见`strategies/examples/`和`tests/fixtures/`。

```yaml
# 规则型：近 20 日上过龙虎榜且最近一次上榜机构净买 > 5%，持有 60 日
buy:
  - {op: top_list_n, n: 20, dir: above, threshold: 0.5}
  - {op: inst_netbuy, dir: above, threshold: 5}
rank: {op: inst_netbuy, order: desc}
max_hold_days: 60
stop_loss: 10

# 打分型：北向占比 + 动量 + 低波，月度调仓，行业内中性化
factors:
  - {op: hk_ratio, weight: 0.4}
  - {op: ret_n, n: 60, weight: 0.3}
  - {op: vol_n, n: 20, weight: -0.3}
holdings: 30
rebalance: monthly_first_trade_day
neut_industry: true
neut_size: false
```

完整样例见`strategies/examples/`和`tests/fixtures/`。未来数据截断与资金面对齐检查见`tests/newspaper_test.py`；零件手算与L1/L4判据见`engine/selftest.py`。扩展零件需另做语义、缺失值、时点和独立数值审核。

## 7. 扩展零件

实现位于`parts/b_ops.py`，通过`engine/operator_registry.json`登记。导入时并入零件注册表，配置校验与随机生成器使用相同的注册定义。新增或修改零件须独立审核后再用于正式搜索。

| yaml 键 | 语义 | 对齐口径 | 缺失语义 | 参数/量纲 |
|---|---|---|---|---|
| `ind_median_pb` | 当日（date）申万一级行业（l1_code）内 **pb 的截面中位数**（行业估值锚）。组内只取有限值（忽略 NaN）；无行业股票自成一组；输出是行业级特征——**该行自身 pb 缺失也照给行业锚** | 纯当日截面，无回看窗口；pb 为 daily_basic T 日盘后值（T 日收盘信号可用，与 `pb` 零件同源同口径）；只依赖 ≤T 的行 | 组内全 NaN → NaN（绝不 0 填充） | 无参数；threshold none（只能作打分因子 / rank，不能作条件） |
| `ind_median_ps` | 当日申万一级行业内 **ps_ttm 的截面中位数**（行业估值锚，市销率口径）。组内语义同 `ind_median_pb`（忽略 NaN、无行业自组、行业锚与自身基值缺失无关） | 纯当日截面，无回看窗口；ps_ttm 为 daily_basic T 日盘后值（与 `ps_ttm` 零件同源同口径）；只依赖 ≤T 的行 | 组内全 NaN → NaN（绝不 0 填充） | 无参数；threshold none |
| `ind_median_fc_chg_mid` | 当日申万一级行业内 **fc_chg_mid 的截面中位数**（行业预告动量锚）。组内语义同 `ind_median_pb`。**注意：原样取 ann_date 对齐列，无「距公告 ≤60 日」新鲜度过滤**——陈旧预告也参与锚值（与 `fc_demean_ind` 的 60 日窗口语义不同，按需选用） | 纯当日截面，无回看窗口；fc_chg_mid 列已按公告日 ann_date ≤T point-in-time 对齐（T 日只见已公告的最近一次预告，持有到下一次预告）；只依赖 ≤T 的行 | 组内全 NaN（该行业当日无任何已公告预告）→ NaN（绝不 0 填充） | 无参数；threshold none |
| `fc_demean_ind` | **预告意外度的行业调整** = 该行 fc_chg_mid − 当日同申万一级行业内「距公告 ≤60 自然日」预告（**含自身**，60 含当日 / 61 剔除）的 fc_chg_mid 中位数（pct 量纲）。无行业股票自成一组。边界：自身陈旧预告（fc_days > 60）不参与中位数，但输出仍 = fc_chg_mid − med | 纯当日截面，无回看窗口；fc_chg_mid / fc_days 列均已按公告日 ann_date ≤T point-in-time 对齐；只依赖 ≤T 的行 | 自身无预告（fc_chg_mid 缺失）→ NaN；组内无任何合格预告 → NaN（绝不 0 填充） | 无参数；**threshold pct（可作 buy/sell 条件与 rank/因子）** |
| `ulcer_n` | **溃疡指数**（防御因子，值小 = 离新高近 / 回撤浅，建议负权）：最近 n 行K线（含当日）窗口内 dd_j = adj_nav_j / cummax(窗口起点..j) − 1，输出 = sqrt(mean(dd²)) × 100（%，≥0）。**日历跨度边界（本零件特有）**：窗口首末行的交易日历位置差 > 254（长停牌股的行窗横跨超一年）→ NaN——陈旧价格路径与正常股票不可比 | 每码行窗（与其他窗口零件同口径）；adj_nav 复权净值口径；只依赖该股自身 ≤T 的行（无横截面依赖） | 前 n−1 行（窗口不完整）→ NaN；跨度 > 254 → NaN；adj_nav存在NaN时，当前实现使用nanmean跳过缺失项；使用前须按实际数据核验此语义 | n ∈ 3/5/10/20/60/120/250；**threshold pct（可作条件）** |

引用样例（打分因子 / rank 两种形态；与 `xsec_pct of pb` 的区别：给的是
**行业锚的绝对水平**而非个股在全截面的分位，方向与权重由策略自定）：

```yaml
# 打分型：作行业估值锚因子（方向/权重由策略假设决定）
factors:
  - {op: pb, weight: -0.4}
  - {op: roe, weight: 0.3}
  - {op: ind_median_pb, weight: 0.2}
holdings: 30
rebalance: monthly_first_trade_day

# 或规则型排序键：rank: {op: ind_median_pb, order: desc}
```
