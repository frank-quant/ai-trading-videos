# -*- coding: utf-8 -*-
"""
engine/guard.py —— 封存守卫（rules.md 第 1 节）

封存期 2025-01-01 起的数据放在 data/sealed/，锁死。本模块是全引擎唯一的数据读取入口：
任何涉及 >= 2025-01-01 的日期区间请求、或 data/sealed/ 路径的读取，在项目根目录
不存在 OPEN_SEALED 文件时直接抛 SealedDataError（异常信息注明封存期未开封）。

用法：所有 parquet 读取一律通过 guard.read_parquet(rel_or_path, ...)；
日期区间一律通过 guard.check_date_range(start, end)。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---- BLAS/OpenMP 线程钉死为 1（性能优化轮，rules.md 第 12 章）----
# 多进程批量回测（12~16 worker）下，BLAS 内部再开多线程只会造成超订与缓存
# 争用；本仓库全部数值路径（numpy 逐元素 / pandas 分组排名）不经 BLAS 归约，
# 设 1 不改变任何回测结果，还消掉一类跨线程归约顺序的潜在抖动。setdefault
# 尊重外部显式设置。guard 是全部引擎模块的第一个 import（本文件不依赖
# numpy），因此在 numpy/OpenBLAS 装载之前生效；engine 各入口脚本均已把
# `import guard` 排在 numpy/pandas 之前。
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")
del _var

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent          # 研究工程根目录
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SEALED_DIR = DATA_DIR / "sealed"
OPEN_SEALED_MARKER = ROOT / "OPEN_SEALED"

# 引擎内部日期一律用 Tushare 口径 YYYYMMDD 字符串（字典序即时间序）
SEALED_START = "20250101"          # rules.md：封存期 2025-01-01 ~ 至今
RAW_END = "20241231"               # data/raw/ 数据上界（tools/fetch_tushare.py 的切分日）


class SealedDataError(RuntimeError):
    """试图读取封存期数据而项目根目录没有 OPEN_SEALED 开封标记。"""


def _marker_exists() -> bool:
    return OPEN_SEALED_MARKER.is_file()


def _fail_date(start: str | None, end: str | None) -> "SealedDataError":
    return SealedDataError(
        f"封存期未开封：请求的日期区间 [{start} ~ {end}] 触及 {SEALED_START} 及以后的数据；"
        f"封存期数据锁死（rules.md 第 1 节），只有项目根目录存在 OPEN_SEALED 文件时才允许读取。"
    )


def _fail_path(path: Path) -> "SealedDataError":
    return SealedDataError(
        f"封存期未开封：拒绝读取封存路径 {path}（rules.md 第 1 节：data/sealed/ 锁死，"
        f"只有项目根目录存在 OPEN_SEALED 文件时才允许读取）。"
    )


def is_sealed_date(d: str | None) -> bool:
    """d 是否落在封存期（含当日）。None/空视为未触及。

    兼容 YYYYMMDD 与 YYYY-MM-DD 两种写法（内部统一按 YYYYMMDD 比较）。
    """
    if d is None or str(d).strip() == "":
        return False
    return str(d).replace("-", "")[:8] >= SEALED_START


def check_date_range(start: str | None, end: str | None) -> None:
    """校验 [start, end] 不触及封存期；否则抛 SealedDataError。"""
    if _marker_exists():
        return
    if is_sealed_date(start) or is_sealed_date(end):
        raise _fail_date(start, end)


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (ROOT / p)


def _path_touches_sealed(path: Path) -> bool:
    """路径是否位于 data/sealed/ 之下**或就是封存目录本身**。

    按解析后的绝对路径判断（大小写不敏感）；目录本身（无尾分隔符）也算
    触及——列出封存目录清单同样是读取封存数据。
    """
    try:
        resolved = path.resolve()
        sealed = SEALED_DIR.resolve()
        rs, ss = str(resolved).lower(), str(sealed).lower()
        sep = os.sep.lower()
        return rs == ss or rs.startswith(ss + sep)
    except OSError:
        return False


def read_parquet(path: str | Path, columns: list[str] | None = None) -> pd.DataFrame:
    """唯一允许的 parquet 读取入口。data/sealed/ 路径在未开封时抛异常。"""
    p = _resolve(path)
    if _path_touches_sealed(p) and not _marker_exists():
        raise _fail_path(p)
    return pd.read_parquet(p, columns=columns)


def exists(path: str | Path) -> bool:
    p = _resolve(path)
    if _path_touches_sealed(p) and not _marker_exists():
        raise _fail_path(p)
    return p.exists()


def list_dir(path: str | Path) -> list[Path]:
    """列目录（同样过守卫；列 data/sealed/ 本身视为读取封存数据）。"""
    p = _resolve(path)
    if _path_touches_sealed(p) and not _marker_exists():
        raise _fail_path(p)
    return sorted(p.iterdir())


def assert_no_sealed_access() -> None:
    """自检入口：确认当前未开封。供审计员调用。"""
    if _marker_exists():
        raise RuntimeError("OPEN_SEALED 已存在：封存期处于开封状态，守卫放行中。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # CLI 自检：逐项演示守卫行为
    print(f"OPEN_SEALED 标记存在：{_marker_exists()}")
    try:
        check_date_range("20140101", "20221231")
        print("OK  区间 20140101~20221231 放行")
    except SealedDataError as e:
        print(f"ERR {e}")
    try:
        check_date_range("20230101", "20241231")
        print("OK  区间 20230101~20241231 放行")
    except SealedDataError as e:
        print(f"ERR {e}")
    try:
        check_date_range("20140101", "20250101")
        print("ERR 不应放行触及封存期的区间")
    except SealedDataError as e:
        print(f"OK  拒绝触及封存期的区间：{e}")
    try:
        read_parquet("data/sealed/daily.parquet")
        print("ERR 不应读到封存文件")
    except SealedDataError as e:
        print(f"OK  拒绝读取封存路径：{e}")
    try:
        read_parquet("data/raw/stock_basic.parquet", columns=["ts_code"])
        print("OK  raw 路径放行")
    except Exception as e:  # noqa: BLE001
        print(f"ERR raw 读取异常：{e!r}")
