# -*- coding: utf-8 -*-
"""
engine/backtest.py —— 单配置回测引擎（rules.md 第 2～4 节，Tushare 版）

撮合：T 日收盘出信号、T+1 开盘价成交；涨跌停价直接用 Tushare stk_limit 的
up_limit / down_limit（不自己推算，rules.md 第 2 节）；停牌 = 当日无行情行
（自然顺延，suspend_d 兜底核对）；ST 以 namechange 历史名称按当日判断；
上市不满 250 个交易日（stock_basic.list_date 起按交易日历）剔除；
股票池 = index_members 按当日快照（沪深300 ∪ 中证500 并集）。
可选行业分散约束 industry_cap：同申万一级行业最多持有 N 只（选股时点 enforce）。
打分型支持周度/月度调仓（rebalance）与两个独立中性化开关（neut_industry 申万
一级行业内截面秩 / neut_size 当日流通市值 5 档内截面秩，rules.md 7.5；生效口径
写入 run 目录 summary.json 的 neutralization 字段）。

成本按第 3 节；仓位按第 4 节。基准：股票池当日可交易、非 ST 成分等权、同样扣成本。

记账模型：
  * 组合净值 = 现金 + Σ 持仓份额 × adj_nav（= close × adj_factor，跨日收益唯一口径）。
  * 买入：成交净值价 = T+1 不复权开盘 × 当日复权因子 × (1+滑点)。
  * 卖出：现金 += 份额×成交净值价×(1-佣金-印花税)。
  * 单票动用资金 = min(组合总值 × 10%, 可用现金)；总值按上一交易日收盘估值。
  * 停牌顺延：买单/卖单挂起顺延；顺延中变 ST 的买单放弃；退市卖单按最后行情日
    收盘净值强制清仓（扣全套成本，保守）。

零件求值：所有零件只回看（全量面板第 T 行值 ≡ as-of-T 切片第 T 行值，selftest
逐零件验证）。回测器把每个 spec（{op,n?,of?}，含嵌套）在全量面板上只算一次，
逐日按行号取值；取值永远只发生在 <= T 的行上。

超额口径（rules.md 第 5.1 节）：日超额 = 策略日收益 − 基准日收益；
ir = mean/std(ddof=1) × √250；超额最大回撤 = cumprod(1+日超额) 的最大回撤。
第 3 层（第 3 版）：ir > 0.4 且超额最大回撤 < 30%（严格不等）。

CLI：python engine/backtest.py <config.yaml> --group A [--start 20140101] [--end 20221231]
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import msvcrt      # Windows：内核字节范围锁（本仓库主平台）
except ImportError:    # noqa: F401 —— 非 Windows 平台退回 fcntl
    msvcrt = None
try:
    import fcntl       # POSIX 退路
except ImportError:    # noqa: F401
    fcntl = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402  必须先于 numpy/pandas：guard 钉死 BLAS 线程环境变量

import numpy as np
import pandas as pd

import ch14                           # rules.md 第 14 章指标（纯函数，无 engine 依赖）
import operators as op
import panel_store
from config import ConfigError, load_config  # noqa: E402
from prices import ETF_BENCHMARK, DataStore  # noqa: E402

ROOT = guard.ROOT
LEDGER_PATH = ROOT / "ledger" / "ledger.csv"
RUNS_DIR = ROOT / "reports" / "runs"

DEFAULT_START = "20140101"       # rules.md 搜索期（YYYYMMDD）
DEFAULT_END = "20221231"

# ---- 成本（rules.md 第 3 节）----
COMMISSION = 0.00025             # 佣金 万2.5，双边
STAMP_TAX_OLD = 0.001            # 印花税，仅卖出；2023-08-28 之前 0.1%
STAMP_TAX_NEW = 0.0005           # 2023-08-28 之后 0.05%（按切换日自动适用，不随切分变）
STAMP_TAX_SWITCH = "20230828"
SLIPPAGE = 0.001                 # 滑点 单边 0.1%

MIN_LISTED_DAYS = 250            # 剔除上市不满 250 个交易日（list_date 起按交易日历）
RULE_MAX_POSITIONS = 10          # 规则型最多同时持有
SCORE_HOLDINGS = 30              # 打分型每周持有
SINGLE_CAP = 0.10                # 单票上限 10%（rules.md 第 4 节）

# 漏斗第 3 层（rules.md 第 3 版）：ir > 0.4 且超额最大回撤 < 30%
L3_IR_MIN = 0.4
L3_EXCESS_DD_MAX = 0.30


# ================================================================ 台账

# 第 14 章评估指标列（rules.md 14.1~14.3，只报告不作门槛）：尾部追加。
# 既有 ledger.csv 由一次性迁移补空列（表头加列、旧行补逗号，旧值逐位不变）。
# 规则型配置前 6 列（ic/分层）留空；13 列只在搜索期回测填写（rules 14.4），
# 验证期/封存期回测留空（验证期同名指标第 6 层后补算，封存期开封后补算）。
LEDGER_COLS = ["ts", "config", "group", "type", "start", "end", "status",
               "n_trades", "ann_ret", "bench_ann_ret", "ann_excess",
               "sharpe", "max_dd", "ir", "excess_max_dd",
               "beat_years", "total_years",
               "funnel_l1", "funnel_l2", "funnel_l3", "funnel_l4", "note"] \
    + list(ch14.CH14_COLS)

# group 合法取值（rules.md 第 6 节）：A、B、monkey_<正整数种子>、example、test
GROUP_RE = re.compile(r"^(A|B|example|test|monkey_[1-9][0-9]*)$")


def check_group(group: str) -> str:
    """校验 group 取值合法；非法抛 ValueError。分组只认台账 group 列。"""
    g = str(group)
    if not GROUP_RE.match(g):
        raise ValueError(
            f"group={group!r} 不合法（rules.md 第 6 节：A / B / monkey_<正整数种子>"
            f" / example / test）")
    return g


# 台账追加锁的字节范围长度（锁文件开头 1 字节即可互斥；空文件也允许锁，
# 见 rules.md 第 12 章并行执行下的实现说明）
LEDGER_LOCK_BYTES = 1


@contextlib.contextmanager
def _ledger_locked(path: Path):
    """台账追加的跨进程互斥锁（rules.md 第 12 章：多进程并行回测落账不丢行）。

    选型：**内核字节范围锁**（Windows 用 msvcrt.locking，POSIX 退回 fcntl.flock），
    而不是 O_EXCL 锁文件或经 Pool initializer 传 mp.Lock。理由：
      * 锁由内核持有、随进程死亡自动释放——没有「进程崩溃留下死锁文件」的
        陈旧锁问题（O_EXCL 锁文件方案需要额外的陈旧锁清理与存活判断）；
      * 作用于文件本身、跨任意独立进程生效——比 mp.Lock 强（mp.Lock 只在
        共享同一锁对象的进程间有效，两个并行的命令行批次互不可见）；
      * 无轮询 sleep（O_EXCL 重试方案需要），持锁窗口只有一行 CSV 追加。
    两者都不可用的平台退化为无锁（当前仓库 win32，msvcrt 恒可用）。
    yield 锁定句柄（O_RDWR|O_CREAT 打开的 fd）：写入必须走**同一句柄**——
    Windows 字节范围锁对同进程的其他句柄同样互斥（空文件首行会写到锁字节
    0），单句柄锁+写才不自我冲突。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_BINARY 必须显式传：Windows 上 CRT 缺省文本模式会把 os.write 字节里的
    # \n 翻译成 \r\n，行尾 \r\n 被写成 \r\r\n（审计返工单第 1 条的根因——
    # 与 StringIO 无关，StringIO 缺省不翻译；此处才是字节污染点）。
    # POSIX 无 O_BINARY（getattr 退 0），两个平台字节行为一致。
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    locked = False
    try:
        if msvcrt is not None:
            # LK_NBLCK 失败立即抛 OSError；小步重试（总上限 ~5s）再抛出
            deadline = time.time() + 5.0
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, LEDGER_LOCK_BYTES)
                    locked = True
                    break
                except OSError:
                    if time.time() >= deadline:
                        raise
                    time.sleep(0.005)
        elif fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
        yield fd
    finally:
        if locked:
            try:
                if msvcrt is not None:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, LEDGER_LOCK_BYTES)
                elif fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def record_ledger(cfg_name: str, typ: str, start: str, end: str, status: str,
                  group: str, metrics: dict | None = None, note: str = "",
                  path: Path | None = None) -> None:
    """统一落账入口。所有回测执行（成功/失败/调试）都必须调用一次，绝不删除行。

    追加在跨进程锁（_ledger_locked，rules.md 第 12 章）内进行：先取锁再判断
    「文件是否为空需写表头」，多 worker 并发落账不丢行、不串行。
    path：台账路径（缺省 = 仓库台账 ledger/ledger.csv）；engine 自测的并发
    竞态用例传临时目录路径，绝不写仓库台账，也不做任何运行时补丁。
    """
    g = check_group(group)
    target = Path(path) if path is not None else LEDGER_PATH
    m = dict(metrics or {})
    f = m.get("funnel") or {}
    for k in ("funnel_l1", "funnel_l2", "funnel_l3", "funnel_l4"):
        if k not in m and k in f:
            m[k] = f[k]
    # 第 14 章指标列：res["ch14"]（回测/复用路径同一挂载点；缺失（非搜索期、
    # 规则型的 ic/分层列）→ 留空
    c14 = m.get("ch14") or {}
    row = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": cfg_name, "group": g, "type": typ, "start": start, "end": end,
        "status": status,
        "n_trades": m.get("n_trades", ""),
        "ann_ret": _fmt(m.get("ann_ret")), "bench_ann_ret": _fmt(m.get("bench_ann_ret")),
        "ann_excess": _fmt(m.get("ann_excess")), "sharpe": _fmt(m.get("sharpe")),
        "max_dd": _fmt(m.get("max_dd")),
        "ir": _fmt(m.get("ir")), "excess_max_dd": _fmt(m.get("excess_max_dd")),
        "beat_years": m.get("beat_years", ""), "total_years": m.get("total_years", ""),
        "funnel_l1": m.get("funnel_l1", ""), "funnel_l2": m.get("funnel_l2", ""),
        "funnel_l3": m.get("funnel_l3", ""), "funnel_l4": m.get("funnel_l4", ""),
        "note": note,
    }
    row.update({c: _fmt(c14.get(c)) for c in ch14.CH14_COLS})
    # newline="" 固定不做行尾翻译：csv.writer 的 \r\n 终止符原样保留，
    # 与既有台账的 CRLF 字节一致（返工单第 1 条；缺省 StringIO 虽在本解释器
    # 不翻译，这里显式钉死，杜绝任何解释器/平台差异）。
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow([row[c] for c in LEDGER_COLS])
    line = buf.getvalue().encode("utf-8")
    with _ledger_locked(target) as fd:
        # 写入走锁定句柄本身（单句柄锁+写，见 _ledger_locked）；表头判定在
        # 持锁后做，多 worker 并发首写也只产生一张表头。
        if os.fstat(fd).st_size == 0:
            head = io.StringIO(newline="")
            csv.writer(head).writerow(LEDGER_COLS)
            os.lseek(fd, 0, os.SEEK_END)
            os.write(fd, head.getvalue().encode("utf-8"))
        os.lseek(fd, 0, os.SEEK_END)
        os.write(fd, line)


def _fmt(x):
    if x is None or x == "":
        return ""
    try:
        return f"{float(x):.6f}"
    except (TypeError, ValueError):
        return str(x)


def information_ratio(daily_excess: list[float]) -> float:
    """信息比率（rules.md 第 5.1 节）：日超额均值 ÷ 日超额标准差(ddof=1) × √250。"""
    a = np.asarray(daily_excess, dtype="float64")
    if len(a) < 2:
        return 0.0
    sd = float(np.std(a, ddof=1))
    if sd == 0:
        return 0.0
    return float(np.mean(a) / sd * np.sqrt(250.0))


def funnel_flags(metrics: dict) -> dict:
    """漏斗第 1～4 层判定（rules.md 第 5.2 节，3.4 修订版口径，搜索期）。

    L1 交易 ≥ 100 笔（买入、卖出各算一笔）；打分型按调仓频率分档：
       周度 ≥ 300 期、月度 ≥ 80 期（rebalance 缺省按周度 300，兼容旧台账行）。
    L2 扣成本年化超额 > 0。
    L3 信息比率 ir > 0.4，且超额最大回撤 abs(excess_max_dd) < 0.30（严格不等）。
    L4 9 个完整年份里至少 6 年年度超额 > 0（beat_years ≥ 6）。
    缺指标（报错行/旧数据）按不通过处理（ir 缺省 0、超额回撤缺省 1）。
    策略自身的 sharpe / max_dd 只记台账作参考，不参与任何层判定。
    """
    typ = metrics.get("type", "")
    if typ == "score":
        thresh = 80 if str(metrics.get("rebalance", "")) == "monthly_first_trade_day" else 300
        l1 = int(int(metrics.get("n_rebalances", 0) or 0) >= thresh)
    else:
        l1 = int(int(metrics.get("n_trades", 0) or 0) >= 100)
    l2 = int(float(metrics.get("ann_excess", -1.0)) > 0)
    l3 = int(float(metrics.get("ir", 0.0)) > L3_IR_MIN
             and abs(float(metrics.get("excess_max_dd", 1.0))) < L3_EXCESS_DD_MAX)
    l4 = int(int(metrics.get("beat_years", 0) or 0) >= 6)
    return {"funnel_l1": l1, "funnel_l2": l2, "funnel_l3": l3, "funnel_l4": l4}


# ================================================================ 进程级共享上下文
#
# 同一 DataStore 面板在一次批量里跑几十上百个配置单（L5 邻域/猴子农场），
# 日期分组索引、逐码行映射、热路径列视图与零件全量值都与配置无关——按面板
# id 缓存共享。面板随 DataStore 存活整个进程；缓存的是派生数组，不改变任何
# 数值语义。
#
# _ctx 用「先查后建」（get → miss 才构造）。旧写法
# _CTX.setdefault(id(panel), _StoreCtx(panel)) 的默认参数**每次调用都先完整
# 构造再丢弃**：剖析（tools/perf_profile.py）显示一次单配置回测里 _StoreCtx
# 被建了 2 次（Backtester.__init__ 223s + run_benchmark 230s，仅首次必要），
# 批量模式下每个配置再各浪费 ~450s。命中时同时校验面板对象同一性，杜绝
# id 地址复用误命中（旧 setdefault 同样存在该理论隐患，这里一并封死）。

_CTX: dict[int, "_StoreCtx"] = {}

# 截面/回测热路径直接消费的面板列（只读 numpy 视图，跨配置共享；
# circ_mv 供打分型市值分档中性化与规模零件截面取值）
_PANEL_HOT_COLS = ("code", "date", "is_st", "adj_nav",
                   "open", "high", "low", "close", "pre_close", "pct_chg",
                   "vol", "turnover_rate", "af", "up_limit", "down_limit",
                   "l1_code", "n_listed", "circ_mv")


class _StoreCtx:
    def __init__(self, panel: pd.DataFrame):
        self.panel = panel                    # 仅作 _ctx 同一性校验，不参与计算
        self.rows_by_date, self.cols, self.date_ids = _build_date_rows(panel)
        dates = self.cols["date"]
        codes = self.cols["code"]
        self.spec_cache: dict[str, np.ndarray] = {}
        self.ret = _panel_ret(panel)
        self.idx_by_code: dict[str, np.ndarray] = {}
        self.dates_by_code: dict[str, np.ndarray] = {}
        self.codes_all: np.ndarray = np.array([], dtype=object)
        self.code_ids: np.ndarray = np.array([], dtype="int64")
        self._build_code_maps(codes, dates)

    def _build_code_maps(self, codes: np.ndarray, dates: np.ndarray) -> None:
        """逐码行映射（idx_by_code / dates_by_code / codes_all / code_ids）。

        与旧实现「np.unique 后逐码 flatnonzero(codes == code)」**逐位同值**：
        面板按 (code, date) 稳定排序（DataStore 构造保证）时每码行是连续块，
        一次边界切分 O(N) 即得全部映射；dates 同码非降序由 date_ids 整数比较
        一并校验，row_of/_last_row_before 的二分查找因此合法。面板不满足
        排序前提时退回逐码扫描（语义一致，仅慢，供异常输入兜底）。
        """
        n = len(codes)
        if n == 0:
            return
        same = codes[1:] == codes[:-1]                 # 一次 7.8M 元素比较，两处复用
        starts = np.flatnonzero(np.r_[True, ~same])
        bounds = np.r_[starts, n]
        heads = codes[starts]
        heads_l = [str(h) for h in heads]
        ascending = all(a < b for a, b in zip(heads_l, heads_l[1:]))
        dates_ok = (self.date_ids is not None
                    and not bool(np.any(same & (self.date_ids[1:] < self.date_ids[:-1]))))
        if ascending and dates_ok:
            self.codes_all = heads
            self.code_ids = np.repeat(np.arange(len(heads)), np.diff(bounds))
            for i, b0, b1 in zip(range(len(heads)), bounds[:-1], bounds[1:]):
                c = heads_l[i]
                self.idx_by_code[c] = np.arange(b0, b1, dtype="int64")
                self.dates_by_code[c] = dates[b0:b1]
        else:
            self.codes_all = np.unique(codes)
            self.code_ids = np.searchsorted(self.codes_all, codes)
            for c in self.codes_all:
                ix = np.flatnonzero(codes == c)
                # 按日期稳定排序：row_of/_last_row_before 的二分查找要求同码
                # 日期非降序；稳定排序下重复 (code, date) 行保持面板原序，
                # searchsorted('right')−1 取到最后一条 == 旧 pos_by_code
                # 字典「后写覆盖」语义（对已有序输入为恒等变换）。
                om = np.argsort(dates[ix], kind="stable")
                ix = ix[om]
                cc = str(c)
                self.idx_by_code[cc] = ix
                self.dates_by_code[cc] = dates[ix]


def _ctx(panel: pd.DataFrame) -> _StoreCtx:
    cx = _CTX.get(id(panel))
    if cx is None or cx.panel is not panel:
        cx = _StoreCtx(panel)
        _CTX[id(panel)] = cx
    return cx


# ================================================================ 基准

_BENCH_CACHE: dict[tuple, list[float]] = {}


def _date_ids(dates: np.ndarray) -> np.ndarray | None:
    """dates(object, YYYYMMDD) → 按日期字符串升序的 int64 下标。

    pd.factorize（杂凑 O(N)）+ 一次性小排序 + 重映射，避免对 7.8M 个
    字符串做 np.unique 整体排序；YYYYMMDD 定宽数字串的字典序 == 整数序。
    """
    if len(dates) == 0:
        return np.array([], dtype="int64")
    codes, uniques = pd.factorize(dates, use_na_sentinel=False)
    u = np.asarray(uniques)
    order = np.argsort(u, kind="stable")
    remap = np.empty(len(u), dtype="int64")
    remap[order] = np.arange(len(u), dtype="int64")
    return remap[np.asarray(codes)]


def _build_date_rows(panel: pd.DataFrame) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], np.ndarray | None]:
    """按日期预分组的行索引（组内代码升序，np.int64 数组）+ 热路径列视图
    + 每行日期下标（快路径时非 None）。

    Backtester 与基准共用（热路径：逐日截面扫描）。面板按 (code, date)
    稳定排序时（DataStore 构造保证），一次 date_id 的稳定 argsort 与旧
    np.lexsort((codes, dates))（对象字符串排序，O(N log N) Python 比较）
    产生**完全相同的排列**：主键 date 的字符串序 == 整数下标序；同日内
    行按代码升序来自面板原始顺序，稳定排序保持；全并列（重复 (code,date)
    行）同样稳定保序。不满足前提时退回 lexsort 慢路径（语义一致）。
    """
    dates = panel["date"].to_numpy()
    codes = panel["code"].to_numpy()
    date_ids = _date_ids(dates)
    heads_sorted = False
    if date_ids is not None and len(codes) > 1:
        same_code = codes[1:] == codes[:-1]
        starts = np.flatnonzero(np.r_[True, ~same_code])
        hl = [str(h) for h in codes[starts]]
        heads_sorted = all(a < b for a, b in zip(hl, hl[1:]))
        if heads_sorted:
            # 同码相邻行日期还须非降序：否则面板并非 (code, date) 有序，
            # 同日内的面板原始顺序不再保证代码升序，必须退回 lexsort
            heads_sorted = not bool(np.any(
                same_code & (date_ids[1:] < date_ids[:-1])))
    elif len(codes) <= 1:
        heads_sorted = True
    if heads_sorted:
        order = np.argsort(date_ids, kind="stable")
    else:
        order = np.lexsort((codes.astype(str), dates.astype(str)))
        date_ids = None
    ds = dates[order]
    bounds = np.flatnonzero(np.r_[True, ds[1:] != ds[:-1]])
    bounds = np.r_[bounds, len(ds)]
    rows_by_date: dict[str, np.ndarray] = {
        str(ds[b0]): order[b0:b1] for b0, b1 in zip(bounds[:-1], bounds[1:])
    }
    cols = {c: panel[c].to_numpy() for c in _PANEL_HOT_COLS}
    return rows_by_date, cols, date_ids


def _panel_ret(panel: pd.DataFrame) -> np.ndarray:
    """面板逐行日收益 = adj_nav / 上一行 adj_nav − 1（按 code 分组）。"""
    nav = panel["adj_nav"].to_numpy(dtype="float64")
    codes = panel["code"].to_numpy()
    prev = np.full(len(nav), np.nan)
    mask = codes[1:] == codes[:-1]
    prev[1:][mask] = nav[:-1][mask]
    with np.errstate(divide="ignore", invalid="ignore"):
        return nav / prev - 1.0


def _uni_mask(store, cx: "_StoreCtx", today: str) -> np.ndarray:
    """当日股票池在唯一码空间（cx.codes_all）上的布尔掩码，缓存于 store 对象。

    与「set(store.universe_on(today)) 逐行 in」逐位同值（精确成员判定，
    searchsorted 命中后再回比唯一码，杜绝越界/错位）。截面（_cross_arrays）
    与基准（run_benchmark）共用；同一 (store, today) 跨配置只算一次。
    """
    cache = getattr(store, "_uni_mask_cache", None)
    if cache is None:
        cache = {}
        try:
            store._uni_mask_cache = cache       # 纯派生缓存，不改任何数值语义
        except (AttributeError, TypeError):     # 只读 store 替身：退化为不缓存
            cache = None
    if cache is not None:
        m = cache.get(today)
        if m is not None:
            return m
    m = np.zeros(len(cx.codes_all), dtype=bool)
    if len(cx.codes_all):
        uni = store.universe_on(today)
        if uni:
            u = np.asarray(list(uni), dtype=object)
            pos = np.searchsorted(cx.codes_all, u)
            pos = np.clip(pos, 0, len(cx.codes_all) - 1)
            m[pos[cx.codes_all[pos] == u]] = True
    if cache is not None:
        cache[today] = m
    return m


def run_benchmark(store: DataStore, cal: list[str]) -> list[float]:
    """基准：股票池当日可交易、非 ST 成分等权，同样扣成本（rules.md 5.1）。

    逐日收益 = 当日股票池（快照 as-of 当日）中有行情行、非 ST 成分的
    adj_nav 日收益等权平均（复牌日带跨停牌区间的补涨收益，与策略持仓
    语义一致）。成本：成分月度调整的换手成本摊到每日 0.0035%（保守向上
    取整，沿用第 2 版口径）。结果按 (id(store), 起止日) 缓存。
    """
    key = (id(store), cal[0], cal[-1])
    if key in _BENCH_CACHE:
        return _BENCH_CACHE[key]
    cx = _ctx(store.panel)
    ret = cx.ret
    cost_per_day = 0.000035
    st_col = cx.cols["is_st"]
    rets = []
    for d in cal:
        rows = cx.rows_by_date.get(d)
        if rows is None or len(rows) == 0:
            rets.append(-cost_per_day)
            continue
        rows = rows[_uni_mask(store, cx, d)[cx.code_ids[rows]]]
        if not len(rows):
            rets.append(-cost_per_day)
            continue
        ok = (st_col[rows] == 0.0) & np.isfinite(ret[rows])
        v = ret[rows][ok]
        r = float(v.mean()) if len(v) else 0.0
        rets.append(r - cost_per_day)
    _BENCH_CACHE[key] = rets
    return rets


# ================================================================ 指标

def annualized_return(daily: list[float]) -> float:
    nav = 1.0
    for r in daily:
        nav *= 1.0 + r
    n = len(daily)
    if nav <= 0 or n == 0:
        return -1.0
    return nav ** (250.0 / n) - 1.0


def sharpe_ratio(daily: list[float]) -> float:
    a = np.asarray(daily, dtype="float64")
    if len(a) < 2:
        return 0.0
    sd = float(np.std(a, ddof=1))
    if sd == 0:
        return 0.0
    return float(np.mean(a) / sd * np.sqrt(250.0))


def max_drawdown(daily: list[float]) -> float:
    nav = np.cumprod(1.0 + np.asarray(daily, dtype="float64"))
    peak = np.maximum.accumulate(nav)
    return float((nav / peak - 1.0).min())


# ================================================================ 打分辅助

def _winsorize_mad(arr: np.ndarray, k: float = 5.0) -> np.ndarray:
    """去极值（MAD 法）：以中位数为中心 clip 到 ±k×1.4826×MAD。NaN 保留。"""
    a = np.asarray(arr, dtype="float64").copy()
    with np.errstate(all="ignore"):
        med = np.nanmedian(a)
        if not np.isfinite(med):
            return a
        mad = np.nanmedian(np.abs(a - med))
    if not np.isfinite(mad) or mad <= 0:
        return a
    lo, hi = med - k * 1.4826 * mad, med + k * 1.4826 * mad
    return np.clip(a, lo, hi)


def _avg_ranks_1d(v: np.ndarray) -> np.ndarray:
    """一维数组升序平均名次（0-based，并列取平均）——向量化实现。

    与 `pd.Series(v).rank(method="average").to_numpy() - 1.0` 逐位同值：
    稳定排序把相等值排成连续段（浮点 == 判并列，-0.0==0.0 与 pandas 一致），
    段内位置取平均；平均名次只依赖段的首位置与长度，与段内次序无关。
    （性能优化轮：剖析显示 _cross_rank/_group_rank_pct 的逐截面 pandas
    rank 链为撮合循环最大热点——pandas rank 61,624 次调用 ~3.0s tottime、
    Series 构造链 cumtime 2.70s；本实现零 pandas 调用。）
    """
    n = len(v)
    if n == 0:
        return np.empty(0, dtype="float64")
    order = np.argsort(v, kind="mergesort")       # 稳定：相等值连续
    vs = v[order]
    brk = np.r_[True, vs[1:] != vs[:-1]]
    seg = np.cumsum(brk) - 1
    starts = np.flatnonzero(brk)                  # 每段首位置（0-based）
    counts = np.diff(np.r_[starts, n])            # 每段长度
    avg0_sorted = starts[seg] + (counts[seg] - 1) / 2.0
    out = np.empty(n, dtype="float64")
    out[order] = avg0_sorted
    return out


def _cross_rank(arr: np.ndarray) -> np.ndarray:
    """截面升序百分位排名（0~1），并列取平均名次；NaN → 0.5（中性）。

    向量化（rules.md 第 12 章）：与旧 `pd.Series(...).rank()` 实现逐位同值
    （见 _avg_ranks_1d）；n_valid < 2 时保持全 0.5。
    """
    a = np.asarray(arr, dtype="float64")
    out = np.full(len(a), 0.5)
    m = np.isfinite(a)
    n = int(m.sum())
    if n >= 2:
        out[m] = _avg_ranks_1d(a[m]) / (n - 1.0)
    return out


def _group_rank_pct(keys: np.ndarray, vals: np.ndarray) -> np.ndarray:
    """组内升序百分位排名（0~1）：中性化用（rules.md 7.5）。

    keys：分组键（行业代码 / 市值档），NaN 键自成一组；单元素组 → 0.5；
    组内 NaN 值 → 0.5（与 _cross_rank 的中性语义一致）；并列取平均名次。

    向量化（rules.md 第 12 章）：旧实现逐组 Python 循环 + 每组一次
    `pd.Series.rank`（剖析：1848 次调用 cumtime 5.32s = 撮合循环 73%）。
    新实现 lexsort((值, 组)) 一次排全截面，段（同组同值）边界切分后取
    平均名次，按组内有限值计数归一——与旧实现逐位同值：
      * 组定义沿用 pd.factorize(use_na_sentinel=True)（NaN 键 → -1），
        -1 统一映射到 n_uniq 与唯一组同路径（组间排序顺序不影响组内名次）；
      * n_g >= 2：pct = avg0/(n_g-1)（= pandas 1-based rank 减 1 后同式）；
        n_g < 2（单元素组/组内全 NaN）→ 0.5；
      * 并列 = 浮点相等段（-0.0==0.0 与 pandas 一致）。
    """
    keys = np.asarray(keys, dtype=object)
    vals = np.asarray(vals, dtype="float64")
    out = np.full(len(vals), 0.5)
    codes, uniques = pd.factorize(keys, use_na_sentinel=True)
    m = np.isfinite(vals)
    if not m.any():
        return out
    # NaN 键（codes<0）映射到 len(uniques)：与唯一组同一条 bincount/lexsort 路径
    c = np.where(codes < 0, len(uniques), codes)[m]
    v = vals[m]
    gcount = np.bincount(c)                       # 每组**有限值**个数（n_g）
    order = np.lexsort((v, c))                    # 主键组、次键值
    cs, vs = c[order], v[order]
    n = len(order)
    brk = np.r_[True, (cs[1:] != cs[:-1]) | (vs[1:] != vs[:-1])]
    seg = np.cumsum(brk) - 1
    starts = np.flatnonzero(brk)
    counts = np.diff(np.r_[starts, n])
    avg0_abs = starts[seg] + (counts[seg] - 1) / 2.0   # 段平均**绝对**位置
    # 绝对位置 → 组内名次：减去每组首元素在排序数组中的位置
    #（组在 lexsort 下连续，组 g 的全部元素从 gstart[g] 起）。
    grp_brk = np.r_[True, cs[1:] != cs[:-1]]
    gstart = np.zeros(len(gcount), dtype="float64")
    gstart[cs[grp_brk]] = np.flatnonzero(grp_brk)
    avg0_group = avg0_abs - gstart[cs]
    gn = gcount[cs]                               # 每行的组内有限值计数
    pct_sorted = np.where(gn >= 2,
                          avg0_group / np.maximum(gn - 1.0, 1.0), 0.5)
    res = np.empty(n, dtype="float64")
    res[order] = pct_sorted
    out[m] = res
    return out


def _size_buckets(vals: np.ndarray, n_buckets: int = 5) -> np.ndarray:
    """市值分档（rules.md 第 7 节：按当日流通市值分位 5 档）。

    当日截面按流通市值排名均分 n_buckets 档（档 ≈ 各 1/n_buckets，并列按
    平均名次，确定性）；NaN → -1（自成「无市值」档）。返回档号（int 语义的
    float，供 _group_rank_pct 作分组键）。
    """
    vals = np.asarray(vals, dtype="float64")
    out = np.full(len(vals), -1.0)
    m = np.isfinite(vals)
    if int(m.sum()) >= 2:
        r = pd.Series(vals[m]).rank(method="average").to_numpy()
        out[m] = np.clip(np.floor((r - 1.0) / (float(m.sum()) - 1.0) * n_buckets),
                         0, n_buckets - 1)
    return out


def _cmp(v, spec: dict) -> bool:
    """条件比较：above = 值 > 阈值；below = 值 < 阈值。NaN/None → False。"""
    if v is None or not np.isfinite(v):
        return False
    t = spec["threshold"]
    return bool(v > t) if spec["dir"] == "above" else bool(v < t)


# ================================================================ 回测器

class Backtester:
    """单配置回测器。构造时共享 DataStore（批量时一次加载）。"""

    def __init__(self, store: DataStore, cfg: dict, start: str, end: str):
        self.store = store
        self.cfg = cfg
        self.start, self.end = start, end
        guard.check_date_range(start, end)      # 任何区间请求必经守卫

        self.panel = store.panel
        cx = _ctx(self.panel)
        self._cx = cx
        self._idx_by_code = cx.idx_by_code
        self._dates_by_code = cx.dates_by_code
        # 按日期预分组的行（组内按代码升序）——逐日截面扫描的热路径
        self._rows_by_date = cx.rows_by_date
        # 热路径列视图（全部面板派生，跨配置共享；只读）
        self._cols = cx.cols

        # 零件全量面板结果缓存：canon(spec) -> 值数组（进程内跨配置共享；
        # 旧代码此处随后被空字典覆盖，跨配置共享实际未生效，已修复）
        self._op_full = cx.spec_cache
        # id(spec) -> (spec, 值数组)：热路径直取数组，免去每次 _val 都做
        # canon_spec 的 json.dumps（剖析：3.59M 次 ~11.5s）。spec 字典由
        # cfg 持有、缓存同时持 spec 强引用，id 不会被复用。
        self._spec_arr: dict[int, tuple[dict, np.ndarray]] = {}
        # ETF 零件全量结果：n -> (dates 数组, 值数组)
        self._op_etf: dict[int, tuple] = {}

        self.cal = [str(d) for d in store.calendar if start <= str(d) <= end]
        if not self.cal:
            raise ValueError(f"区间 [{start},{end}] 内没有交易日")
        self._cal_index = {d: i for i, d in enumerate(store.calendar)}

    # ------------------------------------------------------------ 数据访问

    def row_of(self, code: str, date: str) -> int | None:
        """该股当日的面板行号；无行 → None。

        与旧「预构建 {code: {date: row}} 大字典」**逐位同值**：重复 (code,date)
        行时都取最后一行（字典后写覆盖 == searchsorted('right')−1）。二分
        查找 O(log n)，免去每进程数百万条目字典的构建时间与 ~1.5GB 内存
        （dates_by_code 同码非降序已在 _StoreCtx 构建时校验）。
        """
        ds = self._dates_by_code.get(code)
        if ds is None or len(ds) == 0:
            return None
        i = int(np.searchsorted(ds, date, side="right")) - 1
        if i < 0 or ds[i] != date:
            return None
        return int(self._idx_by_code[code][i])

    def _last_row_before(self, code: str, date: str, include_date: bool = True) -> int | None:
        """该股 <= date（或 < date）的最后一行行号。

        include_date=False 用于开盘时点的估值：开盘时当日收盘未知，
        只能用严格早于当日的最后收盘。
        """
        ds = self._dates_by_code.get(code)
        if ds is None or len(ds) == 0:
            return None
        i = int(np.searchsorted(ds, date, side="right" if include_date else "left")) - 1
        return int(self._idx_by_code[code][i]) if i >= 0 else None

    def _op_values(self, spec: dict) -> np.ndarray:
        """零件 spec 在全量面板上的值（只回看，第 T 行只依赖 <= T 的行）。

        etf_above_ma_n 不允许走本入口（其输入必须是 ETF 日线而非股票面板）。
        id(spec) 备忘直取数组（热路径，免去逐次 canon_spec 的 json.dumps）；
        值数组本体按 canon(spec) 进 cx.spec_cache，进程内跨配置共享。
        """
        if spec["op"] == "etf_above_ma_n":
            raise ValueError(
                "etf_above_ma_n 必须走 _etf_value_on（在 ETF 日线上求值），"
                "不能在股票面板上求值")
        hit = self._spec_arr.get(id(spec))
        if hit is not None:
            return hit[1]
        key = op.canon_spec(spec)
        if key not in self._op_full:
            self._op_full[key] = op.eval_spec(self.panel, spec)["value"].to_numpy()
        arr = self._op_full[key]
        self._spec_arr[id(spec)] = (spec, arr)    # 持 spec 强引用，防 id 复用
        return arr

    def _etf_values(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        """ETF 零件在全量 ETF 日线上的值（同样只回看）。"""
        if n not in self._op_etf:
            etf = self.store.etfs[ETF_BENCHMARK]
            res = op.etf_above_ma_n(etf, n)
            self._op_etf[n] = (etf["date"].to_numpy(), res["value"].to_numpy())
        return self._op_etf[n]

    def _etf_value_on(self, n: int, date: str) -> float | None:
        ds, vals = self._etf_values(n)
        i = int(np.searchsorted(ds, date, side="right")) - 1
        if i < 0:
            return None
        v = float(vals[i])
        return v if np.isfinite(v) else None

    def _val(self, spec: dict, row: int) -> float:
        """零件 spec 在指定行的值。etf_above_ma_n 走 ETF 日线（市场级，与行无关）。"""
        if spec["op"] == "etf_above_ma_n":
            v = self._etf_value_on(int(spec["n"]), str(self._cols["date"][row]))
            return np.nan if v is None else v
        return float(self._op_values(spec)[row])

    def _spec_values_on(self, spec: dict, rows: np.ndarray, today: str) -> np.ndarray:
        """零件 spec 在截面行上的值数组（ETF 零件为市场级同值）。"""
        if spec["op"] == "etf_above_ma_n":
            v = self._etf_value_on(int(spec["n"]), today)
            return np.full(len(rows), np.nan if v is None else v)
        return self._op_values(spec)[rows]

    # ------------------------------------------------------------ 截面

    _EMPTY_CROSS_CODES = np.array([], dtype=object)
    _EMPTY_CROSS_ROWS = np.array([], dtype="int64")

    def _cross_arrays(self, today: str) -> tuple[np.ndarray, np.ndarray]:
        """当日截面 (codes, rows) 数组，按代码升序。与 _cross_rows 逐位同值。

        可交易 = 当日有行情行（Tushare daily 无停牌行；无行即停牌/未上市/退市）
        且开盘价有效；另剔 ST 与上市不满 250 个交易日。向量化布尔掩码替代
        逐行 Python 循环（剖析：_cross_rows 2,191 日累计 ~6.6s）：
          * 股票池成员 = _uni_mask 在唯一码空间上的精确判定；
          * is_st[r] == 1.0 剔除（NaN 视为非 ST，与旧逐行判断一致）；
          * n_listed 缺失/不足 250 剔除；open 非有限剔除。
        顺序保持 rows_by_date 的代码升序。
        """
        rows = self._rows_by_date.get(today)
        if rows is None or len(rows) == 0:
            return self._EMPTY_CROSS_CODES, self._EMPTY_CROSS_ROWS
        keep = _uni_mask(self.store, self._cx, today)[self._cx.code_ids[rows]]
        rows = rows[keep]
        if len(rows) == 0:
            return self._EMPTY_CROSS_CODES, self._EMPTY_CROSS_ROWS
        c = self._cols
        nl = c["n_listed"][rows]
        with np.errstate(invalid="ignore"):
            ok = (c["is_st"][rows] != 1.0) & np.isfinite(nl) \
                & (nl >= MIN_LISTED_DAYS) & np.isfinite(c["open"][rows])
        rows = rows[ok]
        return self._cx.codes_all[self._cx.code_ids[rows]], rows

    def _cross_rows(self, today: str) -> list[tuple[str, int]]:
        """当日股票池内可交易、非 ST、上市满 250 个交易日的 (code, 行号)，按代码排序。

        （兼容接口：列表形态；热路径请用 _cross_arrays。）
        """
        codes, rows = self._cross_arrays(today)
        return list(zip(codes.tolist(), rows.tolist()))

    def _industry_of_row(self, r: int) -> str:
        """截面行的申万一级行业代码（无归属记「未知」桶，同样受约束）。"""
        v = self._cols["l1_code"][r]
        return str(v) if v is not None else "未知"

    def _industry_of_code(self, code: str, today: str) -> str | None:
        """任意代码在 today 的行业（用于持仓/挂单计数；无行/无归属 → None）。"""
        r = self.row_of(code, today)
        if r is None:
            r = self._last_row_before(code, today)
        if r is None:
            return None
        return self._industry_of_row(r)

    # ------------------------------------------------------------ 组合估值

    def _nav_est(self, cash: float, positions: dict, ref_date: str) -> float:
        """组合总值估计：现金 + 持仓按**严格早于 ref_date** 的最后收盘净值估值。"""
        total = cash
        for code, pos in positions.items():
            r = self._last_row_before(code, ref_date, include_date=False)
            navv = float(self._cols["adj_nav"][r]) if r is not None else pos["cost_nav"]
            total += pos["shares"] * navv
        return total

    def _mark_nav(self, cash: float, positions: dict, today: str) -> float:
        """收盘盯市总值：持仓按当日收盘净值（当日无行用最后已知行）。"""
        total = cash
        for code, pos in positions.items():
            r = self.row_of(code, today)
            if r is None:
                r = self._last_row_before(code, today)
            navv = float(self._cols["adj_nav"][r]) if r is not None else pos["cost_nav"]
            total += pos["shares"] * navv
        return total

    # ------------------------------------------------------------ 撮合执行

    def _try_sell(self, trades: list, positions: dict, cash: float,
                  code: str, today: str, sig: str, why: str):
        """在 today 开盘卖出。返回 (ok, cash)。停牌/跌停 → ok=False（顺延）。

        跌停判定直接用 stk_limit 的 down_limit（当日无记录 → 无跌停约束）。
        """
        r = self.row_of(code, today)
        cols = self._cols
        if r is None:
            return False, cash
        pos = positions.get(code)
        if pos is None:
            return True, cash          # 已不在持仓（视为完成）
        px_raw = float(cols["open"][r])
        dnv = float(cols["down_limit"][r])
        if np.isfinite(dnv) and px_raw <= dnv:
            return False, cash         # 跌停卖不出
        factor_today = float(cols["af"][r])
        exec_nav = px_raw * factor_today * (1.0 - SLIPPAGE)
        gross = pos["shares"] * exec_nav
        stamp = STAMP_TAX_NEW if today >= STAMP_TAX_SWITCH else STAMP_TAX_OLD
        fee = gross * (COMMISSION + stamp)
        cash = cash + gross - fee
        del positions[code]
        trades.append({
            "code": code, "side": "sell", "signal_date": sig, "exec_date": today,
            "exec_price": px_raw, "exec_nav": exec_nav, "shares": pos["shares"],
            "gross": gross, "fee": fee, "reason": why,
            "pnl_pct": exec_nav / pos["cost_nav"] - 1.0,
        })
        return True, cash

    def _try_buy(self, trades: list, positions: dict, cash: float,
                 code: str, today: str, sig: str, budget: float, reason: str):
        """在 today 开盘买入 budget 金额。返回 (ok, cash)。停牌/涨停 → ok=False。

        涨停判定直接用 stk_limit 的 up_limit；开盘价 >= 涨停价买不进。
        """
        r = self.row_of(code, today)
        cols = self._cols
        if r is None:
            return False, cash
        if float(cols["is_st"][r]) == 1.0:
            return None, cash          # 变 ST：放弃（不再顺延）
        px_raw = float(cols["open"][r])
        upv = float(cols["up_limit"][r])
        if np.isfinite(upv) and px_raw >= upv:
            return False, cash         # 涨停买不进
        use = min(budget, cash)
        if use <= 0:
            return False, cash
        factor_today = float(cols["af"][r])
        exec_nav = px_raw * factor_today * (1.0 + SLIPPAGE)
        shares = use * (1.0 - COMMISSION) / exec_nav
        fee = use * COMMISSION
        cash = cash - use
        positions[code] = {"shares": shares, "cost_nav": exec_nav,
                           "entry_date": today, "signal_date": sig}
        trades.append({
            "code": code, "side": "buy", "signal_date": sig, "exec_date": today,
            "exec_price": px_raw, "exec_nav": exec_nav, "shares": shares,
            "gross": use - fee, "fee": fee, "reason": reason, "pnl_pct": 0.0,
        })
        return True, cash

    def _force_liquidate(self, trades: list, positions: dict, code: str,
                         last_date: str, why: str, sig: str) -> None:
        """退市清仓：以最后行情日收盘净值成交，扣全套成本（保守）。"""
        pos = positions.get(code)
        if pos is None:
            return
        r = self.row_of(code, last_date)
        if r is None:
            return
        cols = self._cols
        exec_nav = float(cols["adj_nav"][r]) * (1.0 - SLIPPAGE)
        gross = pos["shares"] * exec_nav
        stamp = STAMP_TAX_NEW if last_date >= STAMP_TAX_SWITCH else STAMP_TAX_OLD
        fee = gross * (COMMISSION + stamp)
        del positions[code]
        trades.append({
            "code": code, "side": "sell", "signal_date": sig, "exec_date": last_date,
            "exec_price": float(cols["close"][r]), "exec_nav": exec_nav,
            "shares": pos["shares"], "gross": gross, "fee": fee,
            "reason": f"{why}|delist", "pnl_pct": exec_nav / pos["cost_nav"] - 1.0,
        })

    def _is_delisted_before(self, code: str, date: str) -> bool:
        """股票在 date 之前已无任何后续行情（面板内最后日期 < date）。"""
        ds = self._dates_by_code.get(code)
        return ds is not None and len(ds) and str(ds[-1]) < date

    # ------------------------------------------------------------ 主循环（规则型）

    def _run_rule(self) -> dict:
        cfg = self.cfg
        cal = self.cal
        cols = self._cols

        cash = 1.0
        positions: dict[str, dict] = {}
        pending_buys: list[tuple[str, str]] = []        # (code, 信号日) FIFO
        pending_sells: list[tuple[str, str, str]] = []  # (code, 信号日, 原因)
        trades: list[dict] = []
        daily_ret: list[float] = []
        dates_out: list[str] = []
        nav_prev = 1.0

        buy_specs = cfg["buy"]
        sell_specs = cfg["sell"]
        rank = cfg["rank"]
        max_hold = cfg["max_hold_days"]
        stop_loss = cfg["stop_loss"]
        max_pos = cfg["max_positions"]
        ind_cap = int(cfg.get("industry_cap") or 0)

        for di, today in enumerate(cal):
            tomorrow = cal[di + 1] if di + 1 < len(cal) else None

            # ============ 1) 开盘：先卖后买 ============
            still: list[tuple[str, str, str]] = []
            for code, sig, why in pending_sells:
                if code not in positions:
                    continue
                if self.row_of(code, today) is None:
                    if self._is_delisted_before(code, today):
                        self._force_liquidate(trades, positions, code,
                                              str(self._dates_by_code[code][-1]), why, sig)
                        continue
                    still.append((code, sig, why))       # 无行情（未退市）：顺延
                    continue
                ok, cash = self._try_sell(trades, positions, cash, code, today, sig, why)
                if not ok:
                    still.append((code, sig, why))       # 停牌/跌停：顺延
            pending_sells = still

            # 买入预算：单票 ≤ 组合总值(昨收估值)×10%，且 ≤ 现金
            nav_est = self._nav_est(cash, positions, today)
            budget = min(SINGLE_CAP * nav_est, max(cash, 0.0))

            still_b: list[tuple[str, str]] = []
            for code, sig in pending_buys:
                if len(positions) >= max_pos:
                    still_b.append((code, sig))
                    continue
                if code in positions:
                    continue
                if self.row_of(code, today) is None:
                    if self._is_delisted_before(code, today):
                        continue                          # 已退市：放弃买单
                    still_b.append((code, sig))
                    continue
                ok, cash = self._try_buy(trades, positions, cash, code, today, sig,
                                         budget, "buy")
                if ok is None:
                    continue                              # 变 ST：放弃
                if not ok:
                    still_b.append((code, sig))           # 停牌/涨停/资金不足：顺延
            pending_buys = still_b

            # ============ 2) 收盘盯市 ============
            nav_total = self._mark_nav(cash, positions, today)
            daily_ret.append(nav_total / nav_prev - 1.0)
            nav_prev = nav_total
            dates_out.append(today)

            # ============ 3) 信号（T 收盘 → T+1 开盘执行） ============
            if tomorrow is None:
                break

            # 3a. 持仓卖出信号
            cross_codes, cross_rows = self._cross_arrays(today)
            cross_map = dict(zip(cross_codes.tolist(), cross_rows.tolist()))
            for code in sorted(positions.keys()):
                pos = positions[code]
                if any(c == code for c, _, _ in pending_sells):
                    continue
                # 持有天数上限（信号日起的交易日数，停牌日照计）
                n_days = self._cal_index.get(today, 0) - self._cal_index.get(pos["entry_date"], 0)
                if n_days >= max_hold:
                    pending_sells.append((code, today, "max_hold"))
                    continue
                # 卖出条件（任一满足；当日停牌/ST 的持仓不在截面里，条件不触发）
                r = cross_map.get(code)
                if r is not None and sell_specs:
                    if any(_cmp(self._val(s, r), s) for s in sell_specs):
                        pending_sells.append((code, today, "sell_cond"))
                        continue
                # 止损（今日收盘净值相对成本）
                if stop_loss is not None:
                    pnl = float(cols["adj_nav"][r]) / pos["cost_nav"] - 1.0 if r is not None else 0.0
                    if pnl <= -stop_loss / 100.0:
                        pending_sells.append((code, today, "stop_loss"))

            # 3b. 买入候选（全部条件满足；rank 排序；并列按代码；行业约束）
            free_slots = max_pos - len(positions) - len({c for c, _ in pending_buys})
            if free_slots > 0 and len(cross_rows):
                # 条件过滤向量化：每 spec 一次截面取值 + 布尔掩码 AND，
                # 与逐行 all(_cmp(...)) 逐位同值（NaN → False；> / < 严格不等）
                mask = np.ones(len(cross_rows), dtype=bool)
                for s in buy_specs:
                    v = self._spec_values_on(s, cross_rows, today)
                    t = s["threshold"]
                    with np.errstate(invalid="ignore"):
                        mask &= np.isfinite(v) & (
                            (v > t) if s["dir"] == "above" else (v < t))
                held_or_pending = set(positions) | {c for c, _ in pending_buys}
                cands: list[tuple[str, int]] = [
                    (c, r) for c, r in zip(cross_codes[mask].tolist(),
                                           cross_rows[mask].tolist())
                    if c not in held_or_pending]
                if rank is not None and cands:
                    if rank["op"] == "etf_above_ma_n":
                        cands.sort(key=lambda cr: cr[0])
                    elif rank.get("order", "desc") == "desc":
                        cands.sort(key=lambda cr: (-self._val(rank, cr[1]), cr[0]))
                    else:
                        cands.sort(key=lambda cr: (self._val(rank, cr[1]), cr[0]))
                else:
                    cands.sort(key=lambda cr: cr[0])
                # 行业分散约束：持仓 + 挂起买单 + 新选入，同行业 ≤ industry_cap
                ind_cnt: dict[str, int] = {}
                if ind_cap:
                    row_map = cross_map
                    for code in list(positions) + [c for c, _ in pending_buys]:
                        r0 = row_map.get(code) or self.row_of(code, today)
                        if r0 is None:
                            r0 = self._last_row_before(code, today)
                        if r0 is not None:
                            k = self._industry_of_row(r0)
                            ind_cnt[k] = ind_cnt.get(k, 0) + 1
                picked = 0
                for code, r in cands:
                    if picked >= free_slots:
                        break
                    if ind_cap:
                        k = self._industry_of_row(r)
                        if ind_cnt.get(k, 0) >= ind_cap:
                            continue
                        ind_cnt[k] = ind_cnt.get(k, 0) + 1
                    pending_buys.append((code, today))
                    picked += 1

        return self._finish(trades, daily_ret, dates_out, positions, n_rebalances=None)

    # ------------------------------------------------------------ 主循环（打分型）

    def _run_score(self) -> dict:
        cfg = self.cfg
        cal = self.cal
        holdings_n = cfg["holdings"]
        ind_cap = int(cfg.get("industry_cap") or 0)
        # 中性化两开关（rules.md 7.5）：行业内截面秩 / 市值分档内截面秩，
        # 独立开关、可同时启用（先行业内秩、再市值档内秩，逐级复合）。
        neut_ind = bool(cfg.get("neut_industry", False))
        neut_size = bool(cfg.get("neut_size", False))

        cash = 1.0
        positions: dict[str, dict] = {}
        pending_sells: list[tuple[str, str, str]] = []
        pending_buys: list[tuple[str, str]] = []
        trades: list[dict] = []
        daily_ret: list[float] = []
        dates_out: list[str] = []
        nav_prev = 1.0
        n_rebalances = 0
        # 第 14 章指标输入（rules 14.1）：逐调仓日的打分截面快照
        # （当日 = 调仓信号日；codes = 打分截面全体，scores = 中性化后的复合分数，
        #  与选股同一口径）。只记录，不影响任何交易与指标。
        score_snaps: list[dict] = []

        # 调仓日：周度 = 每周第一个交易日；月度 = 每月第一个交易日
        # （rules.md 第 7 节调仓频率档位：周度、月度）
        reb = str(cfg.get("rebalance", "weekly_first_trade_day"))
        period_days: dict = {}
        for d in cal:
            k = d[:6] if reb == "monthly_first_trade_day" \
                else datetime.strptime(d, "%Y%m%d").isocalendar()[:2]
            period_days.setdefault(k, []).append(d)
        rebalance_days = set(ds[0] for ds in period_days.values())

        for di, today in enumerate(cal):
            tomorrow = cal[di + 1] if di + 1 < len(cal) else None

            # ---- 开盘：先卖后买 ----
            still: list[tuple[str, str, str]] = []
            for code, sig, why in pending_sells:
                if code not in positions:
                    continue
                if self.row_of(code, today) is None:
                    if self._is_delisted_before(code, today):
                        self._force_liquidate(trades, positions, code,
                                              str(self._dates_by_code[code][-1]), why, sig)
                        continue
                    still.append((code, sig, why))
                    continue
                ok, cash = self._try_sell(trades, positions, cash, code, today, sig, why)
                if not ok:
                    still.append((code, sig, why))
            pending_sells = still

            nav_est = self._nav_est(cash, positions, today)
            budget = min(nav_est / holdings_n, SINGLE_CAP * nav_est, max(cash, 0.0))

            still_b: list[tuple[str, str]] = []
            for code, sig in pending_buys:
                if len(positions) >= holdings_n:
                    still_b.append((code, sig))
                    continue
                if code in positions:
                    continue
                if self.row_of(code, today) is None:
                    if self._is_delisted_before(code, today):
                        continue
                    still_b.append((code, sig))
                    continue
                ok, cash = self._try_buy(trades, positions, cash, code, today, sig,
                                         budget, "rebalance_buy")
                if ok is None:
                    continue
                if not ok:
                    still_b.append((code, sig))
            pending_buys = still_b

            # ---- 收盘盯市 ----
            nav_total = self._mark_nav(cash, positions, today)
            daily_ret.append(nav_total / nav_prev - 1.0)
            nav_prev = nav_total
            dates_out.append(today)

            # ---- 调仓信号（T 收盘打分 → T+1 开盘执行） ----
            if tomorrow is not None and today in rebalance_days:
                n_rebalances += 1
                codes_cs, rows_cs = self._cross_arrays(today)
                codes_list = codes_cs.tolist()
                # 中性化分组键（rules.md 7.5）：行业内 = 当日申万一级行业
                # （无行业 NaN 自成一组）；市值档 = 当日流通市值截面 5 档
                # （NaN 自成一组）。两开关全关时不取键（保持原截面排名路径）。
                l1_cs = self._cols["l1_code"][rows_cs] if neut_ind else None
                sz_cs = _size_buckets(self._cols["circ_mv"][rows_cs]) if neut_size else None
                total = np.zeros(len(codes_list))
                for f in cfg["factors"]:
                    arr = self._spec_values_on(f, rows_cs, today)
                    r = _cross_rank(_winsorize_mad(arr))
                    if neut_ind:
                        r = _group_rank_pct(l1_cs, r)
                    if neut_size:
                        r = _group_rank_pct(sz_cs, r)
                    total += f["weight"] * r
                score_snaps.append({"date": today, "codes": list(codes_list),
                                    "scores": total.tolist()})
                order = sorted(range(len(codes_list)),
                               key=lambda i: (-total[i], codes_list[i]))
                # 行业分散约束：分数降序贪心选入，同行业超过 industry_cap 跳过
                # （已持仓计入行业配额——当日卖出可能失败，保守）
                target: list[str] = []
                ind_cnt: dict[str, int] = {}
                if ind_cap:
                    row_map = dict(zip(codes_list, rows_cs.tolist()))
                    for code in positions:
                        r0 = row_map.get(code) or self.row_of(code, today)
                        if r0 is None:
                            r0 = self._last_row_before(code, today)
                        if r0 is not None:
                            k = self._industry_of_row(r0)
                            ind_cnt[k] = ind_cnt.get(k, 0) + 1
                for i in order:
                    if len(target) >= holdings_n:
                        break
                    code = codes_cs[i]
                    k = self._industry_of_row(int(rows_cs[i])) if ind_cap else None
                    if ind_cap and ind_cnt.get(k, 0) >= ind_cap:
                        continue
                    target.append(code)
                    if ind_cap:
                        ind_cnt[k] = ind_cnt.get(k, 0) + 1
                # 卖：不在目标中
                for code in sorted(positions.keys()):
                    if code in target:
                        continue
                    if not any(c == code for c, _, _ in pending_sells):
                        pending_sells.append((code, today, "rebalance_out"))
                # 买：目标中未持有（分数降序）；清掉不在新目标里的挂起买单
                pending_buys = [(c, s) for (c, s) in pending_buys if c in target]
                for code in target:
                    if code in positions:
                        continue
                    if any(c == code for c, _ in pending_buys):
                        continue
                    pending_buys.append((code, today))

        res = self._finish(trades, daily_ret, dates_out, positions,
                           n_rebalances=n_rebalances)
        res["score_snapshots"] = score_snaps   # rules 14.1 IC/分层输入（仅打分型）
        return res

    # ------------------------------------------------------------ 收尾

    def run(self) -> dict:
        if self.cfg["type"] == "rule":
            return self._run_rule()
        return self._run_score()

    def _finish(self, trades, daily_ret, dates_out, positions, n_rebalances) -> dict:
        return {
            "trades": trades, "daily_ret": daily_ret, "dates": dates_out,
            "open_positions": len(positions),
            "n_rebalances": n_rebalances,
        }


# ================================================================ 第 14 章指标挂载
#
# rules.md 第 14 章（只报告、不作门槛；14.4 只在搜索期算）：数据准备在这里
# （面板/成交/分数快照 → 数组），全部数值口径在 engine/ch14.py 的纯函数里，
# 回测管线与审计探针（直接 import ch14 喂合成数据）调用同一实现。

def _ch14_row_on(cx: "_StoreCtx", code: str, date: str) -> int | None:
    """code 当日的面板行号（无行 → None）。"""
    ds = cx.dates_by_code.get(code)
    if ds is None or len(ds) == 0:
        return None
    i = int(np.searchsorted(ds, date, side="right")) - 1
    if i < 0 or ds[i] != date:
        return None
    return int(cx.idx_by_code[code][i])


def _ch14_nav_at(cx: "_StoreCtx", code: str, date: str, cache: dict) -> float:
    """code 在 <= date 的最后已知 adj_nav（停牌沿用最后已知，与 _mark_nav 同
    语义；无任何 <= date 的行 → NaN）。"""
    key = (code, date)
    if key in cache:
        return cache[key]
    ds = cx.dates_by_code.get(code)
    v = float("nan")
    if ds is not None and len(ds):
        i = int(np.searchsorted(ds, date, side="right")) - 1
        if i >= 0:
            v = float(cx.cols["adj_nav"][int(cx.idx_by_code[code][i])])
    cache[key] = v
    return v


def _ch14_compute(store: DataStore, res: dict, cfg: dict) -> dict:
    """第 14 章三组指标（rules 14.1/14.2/14.3）。调用点已由 _attach_ch14 保证
    回测区间 ⊆ 搜索期；全部前瞻窗口都以 res["dates"]（回测自身日历）为界，
    绝不读取回测 end 之后的面板数据（rules 14.4）。

    输入口径（详见 engine/ch14.py 模块 docstring）：
      IC/分层   打分截面 = _run_score 逐调仓日快照（中性化后复合分数，与选股
                同一口径）；下一期收益 = 下一调仓日 adj_nav ÷ 当日 adj_nav − 1；
      换手率    逐年买入金额(gross+fee) ÷ 逐日重建的收盘持仓市值均值；
      容量      每笔买入 1%×当日成交额÷gross 的日 min（成交额单位元 =
                Tushare amount 千元 × 1000，已对全量数据核验）；
      衰减      打分型 = 每调仓日分数 top-holdings、规则型 = 每笔买入
                (code, signal_date) 的信号事件，持有 h∈{1,5,20,60} 交易日的
                年化超额（对基准同窗口）。
    返回 {"metrics": 13 个台账列值, "detail": 报告/审计明细}。"""
    cx = _ctx(store.panel)
    dates = [str(d) for d in res["dates"]]
    cal_index = {d: i for i, d in enumerate(dates)}
    n_days = len(dates)
    bench = np.asarray(res["bench_daily"], dtype="float64")
    trades = pd.DataFrame(res["trades"]) if res.get("trades") else pd.DataFrame(
        columns=["code", "side", "exec_date", "signal_date", "shares", "gross", "fee"])
    out: dict = {}
    detail: dict = {}
    nav_cache: dict = {}

    # ---- 14.2 年化换手率（全部类型）----
    if len(trades):
        intervals = ch14.position_intervals(trades, dates)
        hold_value = ch14.hold_value_from_intervals(
            intervals, lambda c, i: _ch14_nav_at(cx, c, dates[i], nav_cache), n_days)
        trep = ch14.turnover_report(trades, dates, hold_value)
        out["turnover_ann"] = trep["turnover_ann"]
        detail["turnover_yearly"] = trep["yearly"]
    else:
        out["turnover_ann"] = float("nan")

    # ---- 14.2 容量粗估（全部类型；不含冲击成本，仅作参考，rules 14.2）----
    buys = trades[trades["side"].astype(str) == "buy"] if len(trades) else trades
    if len(buys):
        amount_col = store.panel["amount"].to_numpy(dtype="float64")
        dates_b = buys["exec_date"].astype(str).tolist()
        amt = np.full(len(buys), np.nan)
        for k, c in enumerate(buys["code"].astype(str).tolist()):
            r = _ch14_row_on(cx, c, dates_b[k])
            if r is not None:
                amt[k] = amount_col[r] * 1000.0          # 千元 → 元（已核验）
        cap = ch14.capacity_report(dates_b,
                                   buys["gross"].astype("float64").to_numpy(), amt)
        out["cap_median"] = cap["cap_median"]
        out["cap_p5"] = cap["cap_p5"]
        detail["capacity_days"] = cap["n_cap_days"]
        detail["capacity_note"] = "单日买入≤该股当日成交额1%的粗估；不含冲击成本，仅作参考"
    else:
        out["cap_median"] = float("nan")
        out["cap_p5"] = float("nan")

    # ---- 14.3 信号衰减（全部类型）----
    # 信号事件口径：打分型 = 每个调仓日分数最高的 holdings 只（与选股同序：
    # 分数降序、并列按代码；不含行业分散约束——那是组合构建约束而非信号本身）；
    # 规则型 = 成交明细里每笔买入的 (code, signal_date)（引擎实际执行的买入信号）。
    ev_pairs: list[tuple[str, str]] = []
    snaps_d = res.get("score_snapshots") or []
    if cfg["type"] == "score" and snaps_d:
        hold_n = int(cfg.get("holdings") or SCORE_HOLDINGS)
        for s in snaps_d:
            order = sorted(range(len(s["codes"])),
                           key=lambda i: (-s["scores"][i], s["codes"][i]))
            ev_pairs += [(s["codes"][i], s["date"]) for i in order[:hold_n]]
    elif len(trades):
        ev = trades[trades["side"].astype(str) == "buy"].drop_duplicates(
            ["code", "signal_date"])
        ev_pairs = list(zip(ev["code"].astype(str).tolist(),
                            ev["signal_date"].astype(str).tolist()))
    if ev_pairs:
        cb = np.cumprod(1.0 + bench)
        rets_by_h: dict[int, tuple] = {}
        n_events: dict[int, int] = {}
        for h in ch14.DECAY_HORIZONS:
            s_list: list[float] = []
            b_list: list[float] = []
            for c, d0 in ev_pairs:
                i0 = cal_index.get(d0)
                if i0 is None or i0 + h >= n_days:
                    continue          # 窗口超出回测末日：剔除，绝不读 end 之后
                nav0 = _ch14_nav_at(cx, c, d0, nav_cache)
                nav1 = _ch14_nav_at(cx, c, dates[i0 + h], nav_cache)
                if not (np.isfinite(nav0) and np.isfinite(nav1)) or nav0 <= 0:
                    continue
                s_list.append(nav1 / nav0 - 1.0)
                b_list.append(cb[i0 + h] / cb[i0] - 1.0)
            rets_by_h[h] = (np.asarray(s_list), np.asarray(b_list))
            n_events[h] = len(s_list)
        out.update(ch14.decay_report(rets_by_h))
        detail["decay_events"] = n_events
        detail["decay_n_signals"] = len(ev_pairs)
    else:
        for h in ch14.DECAY_HORIZONS:
            out[f"decay_{h}d"] = float("nan")

    # ---- 14.1 IC / ICIR / 10 层分层（仅打分型；规则型这些列留空）----
    snaps = res.get("score_snapshots") or []
    if cfg["type"] == "score" and len(snaps) >= 2:
        snap_dates = [s["date"] for s in snaps]
        codes_union = sorted({c for s in snaps for c in s["codes"]})
        col_of = {c: k for k, c in enumerate(codes_union)}
        snap_arr = np.array(snap_dates, dtype=object)
        # 逐码一次 searchsorted 取全部调仓日净值（<= 各调仓日的最后已知 adj_nav）
        nav_mat = np.full((len(codes_union), len(snap_dates)), np.nan)
        for k, c in enumerate(codes_union):
            ds = cx.dates_by_code.get(c)
            if ds is None or len(ds) == 0:
                continue
            p = np.searchsorted(ds, snap_arr, side="right") - 1
            ok = p >= 0
            nav_mat[k, ok] = cx.cols["adj_nav"][cx.idx_by_code[c][p[ok]]]
        smat = np.full((len(snaps), len(codes_union)), np.nan)
        for j, s in enumerate(snaps):
            ks = np.fromiter((col_of[c] for c in s["codes"]), dtype="int64",
                             count=len(s["codes"]))
            smat[j, ks] = np.asarray(s["scores"], dtype="float64")
        # 最后一期无完整前瞻周期 → 剔除（分数/收益面板同步去掉末行）
        with np.errstate(divide="ignore", invalid="ignore"):
            fwd = nav_mat[:, 1:] / nav_mat[:, :-1] - 1.0
        score_panel = pd.DataFrame(smat[:-1], index=snap_dates[:-1], columns=codes_union)
        fwd_panel = pd.DataFrame(fwd.T, index=snap_dates[:-1], columns=codes_union)
        period_days = np.array([cal_index[snap_dates[j + 1]] - cal_index[snap_dates[j]]
                                for j in range(len(snaps) - 1)], dtype="float64")
        ppy = ch14.periods_per_year(len(snaps) - 1, float(period_days.sum()))
        ics = ch14.ic_series(score_panel, fwd_panel)
        irep = ch14.ic_report(ics.to_numpy(), ppy)
        out["ic_mean"], out["ic_std"] = irep["ic_mean"], irep["ic_std"]
        out["icir"], out["ic_pos_ratio"] = irep["icir"], irep["ic_pos_ratio"]
        lrep = ch14.layer_report(ch14.decile_layer_returns(score_panel, fwd_panel),
                                 period_days)
        out["decile_ls_ann"] = lrep["decile_ls_ann"]
        out["decile_monotonicity"] = lrep["decile_monotonicity"]
        detail.update({"ic_periods": irep["n_ic_periods"], "periods_per_year": ppy,
                       "layer_ann": lrep["layer_ann"], "n_rebalance_snaps": len(snaps)})
    return {"metrics": out, "detail": detail}


def _attach_ch14(store: DataStore, res: dict, cfg: dict,
                 start: str, end: str) -> None:
    """第 14 章指标挂载入口（run_backtest 复用两条路径共用的唯一闸门）。

    区间闸门（rules 14.4）：回测区间 ⊆ 搜索期（20140101~20221231）才计算；
    验证期/封存期/其他区间的回测 13 列全部留空（验证期同名指标在第 6 层跑完
    后补算，封存期开封后补算）。"""
    res["ch14"] = {}
    res["ch14_detail"] = {}
    if not (str(start) >= ch14.SEARCH_START and str(end) <= ch14.SEARCH_END):
        return
    comp = _ch14_compute(store, res, cfg)
    res["ch14"] = comp["metrics"]
    res["ch14_detail"] = comp["detail"]


def _ch14_sanitize(v):
    """ch14 明细落 JSON 前把非有限浮点换成 None（严格 JSON，不写 NaN 字面量）。"""
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: _ch14_sanitize(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_ch14_sanitize(x) for x in v]
    return v


# ================================================================ 入口

def _cfg_sha256(cfg: dict) -> str:
    """配置单内容的规范化指纹（键排序 JSON 的 sha256）。

    结果复用防串味的第二道闸：配置名相同但内容改过（同路径重写 YAML）时
    指纹不同，复用立即失效、照常重跑。只在本文件内自洽（写入 summary.json
    与复用时比对），不要求与 funnel.canonical_config 逐字相同。

    指纹还掺入 _ENGINE_REV（引擎语义修订号）：xsec_pct 语义修复等改变回测
    结果的引擎变更必须递增它——配置内容没变但旧结果已不代表当前引擎，
    旧 summary 的指纹随之全部失配，结果复用自动失效、照常重跑。
    """
    import hashlib
    blob = json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{_ENGINE_REV}|".encode("utf-8")
                          + blob.encode("utf-8")).hexdigest()


# 引擎语义修订号（改回测结果的引擎变更时递增；性能优化不递增）：
#   2 = xsec_pct 语义修复：按「日期值」分组计算当日全截面分位（此前按相邻
#       同日期行块分组，(code,date) 排序面板上恒为 0.5/NaN、代码块边界偶发
#       0.0/1.0，as-of 切片不一致）。
#   3 = 第 3 步扩展（rules.md 3.4/3.5）：① 面板新增资金面列（龙虎榜 ≤T、
#       两融/北向 <T 对齐）——旧配置不取这些列，回测数值不变；② L4 门槛
#       5→6 年、L1 按调仓频率分档（月度 ≥80），funnel 标记随之变化；
#       ③ 打分型新增中性化两开关与月度调仓（默认关闭/周度，旧配置不变）。
#       旧 run 目录 summary 的指纹随之全部失配 → 结果复用自动失效、照常重跑
#       （funnel 标记与 summary 新字段必须与当前引擎一致，不许拿旧产物顶数）。
_ENGINE_REV = "3"


def _reuse_enabled() -> bool:
    """结果复用总开关（绕过契约，缓存绕过开关约定）：
    QUANT_BT_RESULT_CACHE / QUANT_BT_RUN_DIR_REUSE 任一为 "0" 时强制关闭——
    逐位回归门（--dump/--compare）必须 fresh 重跑，绝不许读旧结果顶数。"""
    return (os.environ.get("QUANT_BT_RESULT_CACHE", "1") != "0"
            and os.environ.get("QUANT_BT_RUN_DIR_REUSE", "1") != "0")


def _reuse_result(cfg: dict, start: str, end: str) -> dict | None:
    """已落账且 run 目录完整、配置同构的历史结果直接复用（rules.md 第 12 章
    「复用已算结果」）。

    复用条件（缺一不可）：
      * 绕过开关放行（见 _reuse_enabled）；
      * 台账里该 (config, start, end) 有 ok 行且 note 指向存在的 run 目录
        （trades.parquet / daily_returns.csv / summary.json 三件齐全）；
      * summary.json 里的 config_sha256 与当前配置内容一致（防同名改配置）。
    复用同样照常追加一条台账行（note 标 reuse=<dir>，台账只增不删）；
    指标全部从日收益/成交明细**重算**（与真实回测同一代码路径），不依赖
    summary.json 的浮点序列化。
    """
    if not _reuse_enabled():
        return None
    try:
        led = pd.read_csv(LEDGER_PATH, dtype=str, keep_default_na=False)
    except (OSError, ValueError):
        return None
    if "config" not in led.columns or "note" not in led.columns:
        return None
    sub = led[(led["config"] == cfg["name"]) & (led["start"] == start)
              & (led["end"] == end) & (led["status"] == "ok")
              & (led["note"].str.startswith("out="))]
    if not len(sub):
        return None
    row = sub.sort_values("ts", kind="stable").iloc[-1]
    out_dir = RUNS_DIR / str(row["note"])[4:]
    if not all((out_dir / f).is_file()
               for f in ("trades.parquet", "daily_returns.csv", "summary.json")):
        return None
    try:
        summ = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        tr = pd.read_parquet(out_dir / "trades.parquet")
        # float_precision='round_trip'：逐位还原落盘浮点（缺省解析器有 ULP 级
        # 误差，复用指标会差末位——实测 ir 差 ~1e-14，必须钉死精确解析）
        dd = pd.read_csv(out_dir / "daily_returns.csv", dtype={"date": str},
                         float_precision="round_trip")
    except Exception:  # noqa: BLE001 —— 工件残缺即不复用，退回真跑
        return None
    if summ.get("config_sha256") != _cfg_sha256(cfg):
        return None
    # 第 14 章指标（rules 14.4 只在搜索期算）：搜索期复用必须带 ch14_metrics.json
    # ——旧 run 目录（无此工件）不能顶数，退回真跑；非搜索期（验证期）复用
    # 不需要（这些列本就留空）。指标值直接取落盘 JSON（repr 精确、与首跑一致；
    # 重算需要打分截面快照，快照不进工件）。
    in_search = (start >= ch14.SEARCH_START and end <= ch14.SEARCH_END)
    ch14_path = out_dir / "ch14_metrics.json"
    ch14_metrics: dict = {}
    if ch14_path.is_file():
        try:
            ch14_metrics = json.loads(
                ch14_path.read_text(encoding="utf-8")).get("metrics") or {}
        except (OSError, ValueError):
            ch14_metrics = {}
    if in_search and not ch14_metrics:
        return None
    res = {
        "trades": tr.to_dict("records"),
        "daily_ret": [float(x) for x in dd["strategy_ret"].tolist()],
        "dates": [str(x) for x in dd["date"].tolist()],
        "open_positions": summ.get("open_positions"),
        "n_rebalances": summ.get("n_rebalances"),
        "ch14": ch14_metrics,
    }
    bench_rets = [float(x) for x in dd["benchmark_ret"].tolist()]
    res["bench_daily"] = bench_rets
    return _attach_metrics(res, bench_rets, cfg, reused_dir=out_dir)


def _attach_metrics(res: dict, bench_rets: list[float], cfg: dict,
                    reused_dir: Path | None = None) -> dict:
    """基准/年化/夏普/回撤/超额/逐年/漏斗判定（真实回测与结果复用共用同一
    代码路径——复用时指标从日收益序列重算，与首跑逐位一致）。"""
    # n_trades 语义（rules.md 第 5.2 节 L1）：买卖合计，买入和卖出各算一笔
    res["n_trades"] = len(res["trades"])
    res["ann_ret"] = annualized_return(res["daily_ret"])
    res["bench_ann_ret"] = annualized_return(bench_rets)
    res["ann_excess"] = res["ann_ret"] - res["bench_ann_ret"]
    res["sharpe"] = sharpe_ratio(res["daily_ret"])
    res["max_dd"] = max_drawdown(res["daily_ret"])

    # ---- 超额口径（rules.md 第 5.1 节）----
    res["excess_daily"] = [s - b for s, b in zip(res["daily_ret"], bench_rets)]
    res["ir"] = information_ratio(res["excess_daily"])
    res["excess_max_dd"] = max_drawdown(res["excess_daily"])

    # 逐年对比（策略 vs 基准；年度收益 = 该年日收益累乘）
    dfy = pd.DataFrame({"date": res["dates"], "ret": res["daily_ret"]})
    dfy["year"] = dfy["date"].str[:4]
    by = dfy.groupby("year")["ret"].apply(lambda s: float(np.prod(1 + s) - 1))
    dfb = pd.DataFrame({"date": res["dates"], "ret": bench_rets})
    dfb["year"] = dfb["date"].str[:4]
    bb = dfb.groupby("year")["ret"].apply(lambda s: float(np.prod(1 + s) - 1))
    res["yearly"] = {y: (float(by[y]), float(bb[y])) for y in by.index}
    res["yearly_excess"] = {y: float(by[y]) - float(bb[y]) for y in by.index}
    res["beat_years"] = int(sum(1 for y in by.index if res["yearly_excess"][y] > 0))
    res["total_years"] = len(by.index)
    res["type"] = cfg["type"]
    res["config_name"] = cfg["name"]
    # 调仓频率（L1 分档依据）与中性化口径（rules.md 7.5：报告须注明用了哪种）
    if cfg["type"] == "score":
        res["rebalance"] = str(cfg.get("rebalance", "weekly_first_trade_day"))
        res["neut_industry"] = bool(cfg.get("neut_industry", False))
        res["neut_size"] = bool(cfg.get("neut_size", False))
    res["funnel"] = funnel_flags(res)
    if reused_dir is not None:
        res["out_dir"] = str(reused_dir)
    return res


def run_backtest(store: DataStore, cfg_path: str | Path,
                 start: str = DEFAULT_START, end: str = DEFAULT_END, *,
                 group: str, record: bool = True, quiet: bool = False) -> dict:
    """执行一次回测（读配置 → [复用判定] → 回测 → 基准 → 指标 → 落盘 → 落账）。

    group 必填关键字参数：本次执行的归属组（rules.md 第 6 节）。分组只认
    台账 group 列；配置单命名前缀（a_/b_/m<种子>_）仅是命名约定，不参与分组。
    复用只对落账执行开启（record=True）；record=False 是自测注入通道，
    永远真跑（rules.md 第 12 章「并行与串行逐位一致」用例依赖真实回测）。
    """
    g = check_group(group)
    cfg_path = Path(cfg_path)
    cfg: dict = {}
    try:
        cfg = load_config(cfg_path)
        if record:
            reused = _reuse_result(cfg, start, end)
            if reused is not None:
                if record:
                    record_ledger(cfg["name"], cfg["type"], start, end, "ok", g,
                                  reused, note=f"reuse={Path(reused['out_dir']).name}")
                if not quiet:
                    print(f"[backtest] {cfg['name']}: 复用既有结果 "
                          f"{reused['out_dir']}（绕过开关见函数注释）")
                    _print_summary(reused)
                return reused
        bt = Backtester(store, cfg, start, end)
        res = bt.run()
        bench_rets = run_benchmark(store, bt.cal)
        res["bench_daily"] = bench_rets
        _attach_metrics(res, bench_rets, cfg)
        _attach_ch14(store, res, cfg, start, end)   # rules 第 14 章（只报告）

        out_dir = _dump_artifacts(cfg, res, start, end)
        res["out_dir"] = str(out_dir)

        if record:
            record_ledger(cfg["name"], cfg["type"], start, end, "ok", g, res,
                          note=f"out={out_dir.name}")
        if not quiet:
            _print_summary(res)
        return res
    except Exception as e:  # noqa: BLE001 —— 任何执行失败也必须落账
        if record:
            record_ledger(cfg.get("name", cfg_path.stem), cfg.get("type", "?"),
                          start, end, "error_runtime", g, note=repr(e)[:300])
        raise


def _dump_artifacts(cfg: dict, res: dict, start: str, end: str) -> Path:
    out_dir = RUNS_DIR / f"{cfg['name']}__{start}_{end}"
    out_dir.mkdir(parents=True, exist_ok=True)
    tr = pd.DataFrame(res["trades"])
    tr.to_parquet(out_dir / "trades.parquet", index=False)
    dd = pd.DataFrame({
        "date": res["dates"],
        "strategy_ret": res["daily_ret"],
        "benchmark_ret": res["bench_daily"],
        "excess": res["excess_daily"],       # 日超额 = 策略日收益 − 基准日收益
    })
    dd["strategy_nav"] = np.cumprod(1 + dd["strategy_ret"])
    dd["benchmark_nav"] = np.cumprod(1 + dd["benchmark_ret"])
    dd.to_csv(out_dir / "daily_returns.csv", index=False, encoding="utf-8")
    # 第 14 章指标工件（metrics = 台账 13 列的落盘真值，供结果复用取数；
    # detail = 分层年化/逐年换手/容量天数等报告明细）
    (out_dir / "ch14_metrics.json").write_text(
        json.dumps(_ch14_sanitize({"metrics": res.get("ch14") or {},
                                   "detail": res.get("ch14_detail") or {}}),
                   ensure_ascii=False, indent=1), encoding="utf-8")
    summ = {"config_name": cfg["name"], "type": cfg["type"], "start": start, "end": end,
            "config_sha256": _cfg_sha256(cfg),   # 结果复用的配置同构指纹
            # rules.md 7.5：报告须注明用了哪种中性化口径——生效口径随结果落盘。
            "neutralization": ({"industry_rank": res.get("neut_industry", False),
                                "size_bucket_rank": res.get("neut_size", False)}
                               if cfg["type"] == "score" else None),
            "rebalance": res.get("rebalance"),
            "n_trades": res["n_trades"], "n_rebalances": res.get("n_rebalances"),
            "open_positions": res.get("open_positions"),
            "ann_ret": res["ann_ret"], "bench_ann_ret": res["bench_ann_ret"],
            "ann_excess": res["ann_excess"], "sharpe": res["sharpe"],
            "max_dd": res["max_dd"],
            "ir": res["ir"], "excess_max_dd": res["excess_max_dd"],
            "beat_years": res["beat_years"],
            "total_years": res["total_years"], "funnel": res["funnel"],
            "yearly": {y: list(v) for y, v in res["yearly"].items()},
            "yearly_excess": res["yearly_excess"]}
    (out_dir / "summary.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir


def _print_summary(res: dict):
    print(f"  交易笔数(买卖合计): {res['n_trades']}"
          + (f"   调仓期数: {res.get('n_rebalances')}"
             if res.get("n_rebalances") is not None else ""))
    if res.get("rebalance") is not None:
        neut = ("行业内秩" if res.get("neut_industry") else "") \
            + ("市值档内秩" if res.get("neut_size") else "")
        neut = neut or "无"
        print(f"  调仓频率       : {res['rebalance']}   中性化口径: {neut}"
              f"（rules.md 7.5，已写入 summary.json）")
    print(f"  扣成本年化     : {res['ann_ret']*100:.2f}%   基准: {res['bench_ann_ret']*100:.2f}%"
          f"   超额: {res['ann_excess']*100:+.2f}%")
    print(f"  信息比率       : {res['ir']:.2f}   超额最大回撤: {res['excess_max_dd']*100:.2f}%")
    print(f"  夏普(参考)     : {res['sharpe']:.2f}   绝对最大回撤(参考): {res['max_dd']*100:.2f}%")
    print(f"  年度超额>0     : {res['beat_years']}/{res['total_years']} 年")
    f = res["funnel"]
    print(f"  漏斗1-4层      : L1={f['funnel_l1']} L2={f['funnel_l2']} L3={f['funnel_l3']} L4={f['funnel_l4']}")
    c14 = res.get("ch14") or {}

    def _c(k: str):
        v = c14.get(k)
        return v if isinstance(v, (int, float)) and np.isfinite(v) else None

    seg = []
    if _c("ic_mean") is not None:
        icir = _c("icir")
        seg.append(f"IC={_c('ic_mean'):+.3f}"
                   + (f" ICIR={icir:+.2f}" if icir is not None else " ICIR=nan")
                   + f" 单调性={_c('decile_monotonicity'):+.2f}")
    if _c("turnover_ann") is not None:
        seg.append(f"年换手={_c('turnover_ann'):.2f}x")
    if _c("cap_median") is not None:
        seg.append(f"容量中位/5%位={_c('cap_median') / 1e8:.2f}亿"
                   f"/{_c('cap_p5') / 1e8:.2f}亿(不含冲击成本)")
    dd_ = [_c(f"decay_{h}d") for h in (1, 5, 20, 60)]
    if all(x is not None for x in dd_):
        seg.append("衰减年化超额(1/5/20/60日)="
                   + "/".join(f"{x:+.1%}" for x in dd_))
    if seg:
        print("  第14章指标     : " + "  ".join(seg) + "  (只报告，不作门槛)")
    print(f"  明细目录       : {res['out_dir']}")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    ap = argparse.ArgumentParser(description="单配置回测")
    ap.add_argument("config", help="策略 YAML 路径")
    ap.add_argument("--group", required=True, type=check_group,
                    help="本次执行的归属组：A / B / monkey_<正整数种子> / example / test")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    a = ap.parse_args(argv)
    guard.check_date_range(a.start, a.end)
    print(f"[backtest] {a.config}  区间 {a.start} ~ {a.end}  group={a.group}")
    t0 = time.time()
    store = panel_store.real_store()      # 优先共享面板缓存，禁用/失败退回全量构建
    res = run_backtest(store, a.config, a.start, a.end, group=a.group)
    print(f"[backtest] 完成，用时 {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
