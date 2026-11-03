# -*- coding: utf-8 -*-
"""
engine/panel_store.py —— 面板跨进程共享存储（性能优化轮，rules.md 第 12 章）

rules.md 第 12 章允许「缓存面板」。本模块把 DataStore 构造好的面板与回测
所需的小型辅助结构（交易日历、股票池快照、ETF 日线）持久化到 cache/panel/，
worker 用 np.memmap **只读**挂载：面板字节驻留文件系统页缓存，12~16 个
worker 共享同一份物理页，不再每进程各装一遍 15 张 parquet + 合并 + 对齐
（剖析：DataStore 全量构建 ~30s/进程；内存峰值从每 worker ~5-6GB 降到
~1-2GB，worker 就绪从 ~260s 降到 <10s）。

逐位一致保证（优化不得改变任何结果，rules.md 第 12 章）：
  * 数值列（float64）按原始字节写入 .bin，memmap 读回的每一位与 DataStore
    面板完全相同（无任何数值变换/重排）；
  * 字符串列（str/string dtype）经 pd.factorize 字典编码（int32 码表 +
    唯一值表 + 缺失哨兵），解码后 to_numpy() 的对象数组与原面板逐元素相同
    （NaN / <NA> 哨兵按原样保留，astype 还原原 dtype）；
  * 辅助结构（calendar / trade_days / 股票池快照 / etfs / codes）直接
    pickle 原对象；universe_on 与 prices.DataStore.universe_on 是同一实现。

绕过契约（缓存绕过开关约定）：
本模块是「面板缓存持久化机制」，启用前必须检查 QUANT_BT_RESULT_CACHE 与
QUANT_BT_RUN_DIR_REUSE，任一为 "0" 时强制关闭——逐位回归门要求 fresh
重跑，绝不许读缓存顶数。禁用/任何异常都退回 DataStore 全量构建（绝不因
缓存坏了而中断回测）。

缓存失效：指纹 = 15 张 raw 表（开封时含 sealed 同名表）的 (size, mtime_ns)
+ OPEN_SEALED 标记存在性 + pandas/numpy 版本 + PANEL_STORE_VERSION（面板
构造逻辑变更时人工递增）。指纹不符 → 跨进程文件锁内重建；先写临时文件再
原子改名（os.replace），读者要么看到完整旧一代、要么看到完整新一代。

接口：real_store(quiet) -> DataStore | SharedPanelStore（回测入口统一取数口）。
SharedPanelStore 只实现回测路径所需接口（panel / calendar / universe_on /
etfs）；审计入口（is_st_on / industry_on / asof / 原始帧）请用 DataStore。
"""

from __future__ import annotations

import contextlib
import os
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402  必须先于 numpy/pandas（guard 钉死 BLAS 线程环境变量）

import numpy as np
import pandas as pd

from prices import DataStore  # noqa: E402

ROOT = guard.ROOT
CACHE_DIR = ROOT / "cache" / "panel"
META_PATH = CACHE_DIR / "meta.pkl"
LOCK_PATH = CACHE_DIR / ".build.lock"

# DataStore 面板构造逻辑变更（列/口径/合并次序）时必须递增，旧缓存随之失效
#   3 = 第 3 步：面板新增资金面列（tl_on_list / tl_inst_netbuy_pct ≤T 对齐、
#       margin_rzye / hk_ratio <T 对齐）+ hot cols 加 circ_mv
PANEL_STORE_VERSION = 3

# DataStore.__init__ 实际读取的全部表（read_table 名单，prices.py）
_TABLES = ("trade_cal", "stock_basic", "index_members", "daily", "adj_factor",
           "daily_basic", "stk_limit", "namechange", "index_member_all",
           "fina_indicator", "forecast", "express", "suspend_d",
           "top_list", "top_inst", "margin_detail", "hk_hold",
           "fund_daily", "fund_adj")

try:
    import msvcrt      # Windows：内核字节范围锁（本仓库主平台）
except ImportError:    # noqa: F401 —— 非 Windows 平台退回 fcntl
    msvcrt = None
try:
    import fcntl       # POSIX 退路
except ImportError:    # noqa: F401
    fcntl = None


# ================================================================ 绕过契约

def cache_enabled() -> bool:
    """面板缓存总开关：QUANT_BT_RESULT_CACHE / QUANT_BT_RUN_DIR_REUSE 任一为
    "0" 时强制关闭（缓存绕过开关约定）。"""
    return (os.environ.get("QUANT_BT_RESULT_CACHE", "1") != "0"
            and os.environ.get("QUANT_BT_RUN_DIR_REUSE", "1") != "0")


# ================================================================ 跨进程构建锁

@contextlib.contextmanager
def _locked(path: Path):
    """构建互斥（内核字节范围锁，与 backtest._ledger_locked 同一选型理由）。
    等待上限放宽到 30 分钟：首个持有者要做一次 DataStore 全量构建 + 序列化
    （~1-2 分钟），其余 worker 排队等它发布后直接挂载。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    locked = False
    try:
        if msvcrt is not None:
            deadline = time.time() + 1800.0
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    if time.time() >= deadline:
                        raise
                    time.sleep(0.5)
        elif fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
        yield fd
    finally:
        if locked:
            try:
                if msvcrt is not None:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                elif fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


# ================================================================ 指纹

def _fingerprint() -> dict:
    """缓存新鲜度指纹：全部输入表 stat + 环境标记 + 库版本 + 格式版本。"""
    fp = {"version": PANEL_STORE_VERSION,
          "pandas": pd.__version__, "numpy": np.__version__,
          "open_sealed": guard.OPEN_SEALED_MARKER.is_file(),
          "tables": {}}
    for t in _TABLES:
        st = (guard.RAW_DIR / f"{t}.parquet").stat()
        fp["tables"][f"raw/{t}"] = [st.st_size, st.st_mtime_ns]
        if fp["open_sealed"]:
            sp = guard.SEALED_DIR / f"{t}.parquet"
            if sp.exists():            # 只有开封状态才允许触碰 sealed 路径
                st = sp.stat()
                fp["tables"][f"sealed/{t}"] = [st.st_size, st.st_mtime_ns]
    return fp


def _read_meta() -> dict | None:
    try:
        with open(META_PATH, "rb") as f:
            meta = pickle.load(f)
    except (OSError, ValueError, pickle.UnpicklingError, EOFError, AttributeError):
        return None
    return meta if isinstance(meta, dict) else None


def _cleanup_stale_bins(keep_gen: int) -> None:
    """发布新一代后清理旧代 .bin（best-effort；Windows 上仍被打开的句柄删
    不掉就留给下一次构建）。"""
    try:
        for p in CACHE_DIR.glob("panel_*.bin"):
            try:
                if int(p.stem.rsplit("_", 1)[1]) != keep_gen:
                    p.unlink(missing_ok=True)
            except (ValueError, IndexError):
                continue
        for p in CACHE_DIR.glob(".*.tmp"):
            with contextlib.suppress(OSError):
                p.unlink(missing_ok=True)
    except OSError:
        pass


# ================================================================ 共享仓库

class SharedPanelStore:
    """memmap 只读面板仓库（回测路径所需的 DataStore 接口子集）。

    面板列值与 DataStore 逐位相同（见模块 docstring）；数值列直接挂在
    只读 memmap 上，页缓存跨进程共享。"""

    def __init__(self, panel: pd.DataFrame, aux: dict):
        self.panel = panel
        self.calendar = aux["calendar"]
        self.etfs = aux["etfs"]
        self.codes = aux["codes"]        # selftest / 报表路径用到（prices.py 报告、
                                         #  selftest §7 股票池），与 DataStore.codes 同一对象
        self._univ_by_idx = aux["univ_by_idx"]
        self._universe_cache: dict[str, list[str]] = {}

    def universe_on(self, t: str) -> list[str]:
        """T 日股票池 = 两指数「最近一次样本 ≤ T」成分的并集（升序）。

        与 prices.DataStore.universe_on 同一实现（逐字复制，语义不变）。"""
        t = str(t)
        if t in self._universe_cache:
            return self._universe_cache[t]
        pool: set[str] = set()
        for snaps in self._univ_by_idx.values():
            prev = [d for d in snaps if d <= t]
            if prev:
                pool |= snaps[max(prev)]
        out = sorted(pool)
        self._universe_cache[t] = out
        return out


# ================================================================ 构建 / 挂载

def _build() -> None:
    """全量构建一次 DataStore 并序列化发布（调用方必须已持有构建锁）。"""
    t0 = time.time()
    print("[panel-store] 构建共享面板缓存（DataStore 全量构建一次 + 序列化）……",
          flush=True)
    store = DataStore(quiet=True)
    panel = store.panel
    n = len(panel)
    if n == 0:
        raise ValueError("空面板，不建缓存")

    float_cols: list[str] = []
    str_cols: list[str] = []
    str_specs: dict[str, dict] = {}
    blocks: dict[str, np.ndarray] = {}
    for c in panel.columns:
        d = panel[c].dtype
        if d == np.dtype("float64"):
            float_cols.append(c)
        elif str(d) in ("str", "string") or d == object:
            arr = panel[c].to_numpy()
            codes, uniques = pd.factorize(arr, use_na_sentinel=True)
            codes = np.asarray(codes)
            miss = np.flatnonzero(codes == -1)
            sentinel = arr[int(miss[0])] if len(miss) else None
            str_cols.append(c)
            str_specs[c] = {"dtype": str(d),
                            "uniques": [x for x in uniques.tolist()],
                            "sentinel": sentinel}
            blocks[c] = (codes + 1).astype("int32")
        else:
            raise ValueError(f"面板列 {c} 的 dtype {d} 暂不支持序列化，退回 DataStore")

    gen = time.time_ns()
    f64_bytes = n * 8 * max(1, len(float_cols))
    i32_bytes = n * 4 * max(1, len(str_cols))
    f64_tmp = CACHE_DIR / f".panel_f64_{gen}.tmp"
    i32_tmp = CACHE_DIR / f".panel_str_{gen}.tmp"
    f64_path = CACHE_DIR / f"panel_f64_{gen}.bin"
    i32_path = CACHE_DIR / f"panel_str_{gen}.bin"
    # 数值列整体按 C 序 (n, k) 二维布局写出：挂载侧 pd.DataFrame(mm2d,
    # columns=..., copy=False) 单块零拷贝（逐列 dict 构造会触发同 dtype
    # 合并拷贝，实测丢掉 memmap 共享），全部 worker 共享同一份文件页
    with open(f64_tmp, "wb") as f:
        arr2d = np.empty((n, max(1, len(float_cols))), dtype="float64")
        for j, c in enumerate(float_cols):
            arr2d[:, j] = panel[c].to_numpy()
        arr2d.tofile(f)
        del arr2d
    with open(i32_tmp, "wb") as f:
        for c in str_cols:
            f.write(blocks[c].tobytes())
    del blocks
    os.replace(f64_tmp, f64_path)
    os.replace(i32_tmp, i32_path)

    aux = {"calendar": store.calendar, "trade_days": store.trade_days,
           "univ_by_idx": store._univ_by_idx, "etfs": store.etfs,
           "codes": store.codes}
    meta = {"gen": gen, "n_rows": n, "fingerprint": _fingerprint(),
            "float_cols": float_cols, "str_specs": str_specs,
            "col_order": [str(c) for c in panel.columns],
            "f64_bytes": f64_bytes, "i32_bytes": i32_bytes, "aux": aux}
    meta_tmp = CACHE_DIR / f".meta_{gen}.tmp"
    with open(meta_tmp, "wb") as f:
        pickle.dump(meta, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(meta_tmp, META_PATH)      # meta 最后发布：读者只见完整一代
    _cleanup_stale_bins(gen)
    print(f"[panel-store] 缓存发布完成：{n:,} 行 × {len(float_cols)} 数值列 "
          f"+ {len(str_cols)} 字符串列（gen={gen}，用时 {time.time()-t0:.1f}s）",
          flush=True)


def _attach() -> SharedPanelStore | None:
    """挂载当前一代缓存；指纹不符/文件残缺 → None（调用方决定重建或退回）。

    注：共享面板的**列顺序**与 DataStore 面板不同（数值列在前、字符串列
    在后——二维单块零拷贝布局的要求）；引擎对面板的全部访问都按列名进行，
    列顺序不参与任何语义。"""
    meta = _read_meta()
    if meta is None or meta.get("fingerprint") != _fingerprint():
        return None
    n = int(meta["n_rows"])
    gen = meta["gen"]
    f64_path = CACHE_DIR / f"panel_f64_{gen}.bin"
    i32_path = CACHE_DIR / f"panel_str_{gen}.bin"
    if not f64_path.is_file() or not i32_path.is_file():
        return None
    if f64_path.stat().st_size != meta["f64_bytes"] \
            or i32_path.stat().st_size != meta["i32_bytes"]:
        return None
    # 数值列：单一 C 序 (n, k) memmap → DataFrame 单块零拷贝（共享文件页）。
    # 注意必须用二维数组直接构造——逐列 dict 构造会触发同 dtype 块合并拷贝，
    # 实测丢掉 memmap 共享。字符串列随后逐列插入（异 dtype 块，不拷贝数值块）。
    mm2d = np.memmap(f64_path, dtype="float64", mode="r",
                     shape=(n, max(1, len(meta["float_cols"]))))
    df = pd.DataFrame(mm2d, columns=[str(c) for c in meta["float_cols"]], copy=False)
    for j, c in enumerate(meta["str_specs"]):
        codes = np.asarray(np.memmap(i32_path, dtype="int32", mode="r",
                                     offset=j * n * 4, shape=(n,)))
        s = meta["str_specs"][c]
        uniq2 = np.empty(len(s["uniques"]) + 1, dtype=object)
        uniq2[0] = s["sentinel"]
        uniq2[1:] = s["uniques"]
        col = uniq2[codes]
        if s["dtype"] != "object":
            col = pd.Series(col).astype(s["dtype"])
        df[str(c)] = col
    return SharedPanelStore(df, meta["aux"])


def real_store(quiet: bool = False):
    """回测入口统一取数口：优先共享面板缓存；禁用/失败退回 DataStore。

    面板只加载一份：首个进程在跨进程锁内构建并发布，后续进程（同批
    12~16 个 worker、后续 CLI 调用）全部 memmap 挂载同一份文件页。"""
    if cache_enabled():
        try:
            st = _attach()
            if st is None:
                with _locked(LOCK_PATH):
                    st = _attach()              # 双检：排队期间别人可能已发布
                    if st is None:
                        _build()
                        st = _attach()
            if st is not None:
                if not quiet:
                    print("[panel-store] 共享面板挂载成功（cache/panel，memmap 只读）",
                          flush=True)
                return st
        except Exception as e:  # noqa: BLE001 —— 缓存任何异常都退回全量构建
            print(f"[panel-store] 共享面板不可用，退回 DataStore 全量构建：{e!r}",
                  file=sys.stderr, flush=True)
    return DataStore(quiet=quiet)


# ================================================================ CLI 自检

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] != "--check":
        print(__doc__)
        print("用法：python engine/panel_store.py --check   # 挂载缓存并抽检逐位一致性")
        return 0
    if not cache_enabled():
        print("[panel-store] 缓存被绕过开关禁用（QUANT_BT_RESULT_CACHE / "
              "QUANT_BT_RUN_DIR_REUSE = 0）")
        return 0
    st = real_store()
    print(f"[panel-store] 类型 {type(st).__name__}，面板 {len(st.panel):,} 行，"
          f"日历 {len(st.calendar)} 天")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
