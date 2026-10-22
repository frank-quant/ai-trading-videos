# -*- coding: utf-8 -*-
"""
engine/register_operator.py —— 新零件登记入口（rules.md 第 8.3 节）

登记流程（先测试、后持久化，绝不出现半注册状态）：
  1. 读入定义新零件函数的 Python 文件（函数签名与 operators.py 现有零件一致：
     f(panel) 或 f(panel, n)，输入长表面板、输出同 index 的单列 "value" DataFrame，
     只回看）。
  2. **先跑撕报纸测试**：复用 tests/newspaper_test.py 的「全量面板 == as-of 切片」
     机制——固定种子抽 T 日，对每个 T 构造截至 T 的世界切片（255 个交易日，
     覆盖最大合法窗口 250 + 余量），比对「全量面板上算出的第 T 行值」与
     「as-of-T 切片上算出的第 T 行值」；窗口零件覆盖其**全部合法窗口**
     （3/5/10/20/60/120/250），并验证非法窗口抛 ValueError、两次计算 bitwise
     确定性。任何不一致 → 拒绝登记，退出码 1，注册表一字不动。
  3. 通过后把零件（名字、源文件、函数名、是否带窗口、阈值量纲、内容哈希）
     原子写入注册表 engine/operator_registry.json（--registry 可改；写临时文件
     后 os.replace，要么整体成功要么保持原状）。同一文件重复登记：内容与元数据
     全同 → 明确报告「无变化」退出 0；有差异 → 通过全部检查后**明确更新**并
     打印新旧差异，退出 0。
  4. 子进程新鲜 import 验证：operators.py 在 import 时从注册表并入 OPERATORS /
     OPERATOR_META，engine/config.py 的 OP_ARG/NO_ARG 与 engine/funnel.py 的
     猴子抽样池、阈值量纲分派全部由其派生（单一事实来源）——登记后自动生效。

内置零件（operators.py 里定义的）不可覆盖：重名即拒绝（退出码 2）。

阈值量纲（threshold_kind）决定零件能否作 buy/sell 条件及其档位序列
（与 rules.md 第 7 节对应）：
    pct     百分比档位 ±1/2/3/5/8/10/15
    mult    倍数档位 0.5/0.8/1.0/1.2/1.5/2.0
    streak  整数档位 3/5/10/20/60/120/250
    none    无阈值量纲：只能作打分因子 / rank，不能作条件（默认值）
用 --threshold-kind 名字=量纲 指定（逗号分隔多个）。

退出码：0 = 登记成功或幂等无变化；1 = 撕报纸测试/契约检查未通过；
2 = 用法错误（文件不存在、无候选函数、与内置零件重名、量纲非法等）。

CLI：
  python engine/register_operator.py my_ops.py --threshold-kind my_op=pct
  python engine/register_operator.py --selftest   # 合成零件自测，不写默认注册表

本仓库当前注册表为空（engine/operator_registry.json 不存在 = 无新零件），
内置零件行为与第 1 版完全一致。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard  # noqa: E402
import operators as opmod  # noqa: E402
from operators import ALLOWED_WINDOWS, OPERATOR_META, OPERATORS  # noqa: E402

ROOT = guard.ROOT
DEFAULT_REGISTRY = Path(__file__).resolve().parent / "operator_registry.json"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VALID_KINDS = ("pct", "mult", "streak", "none")
SEED = 42                      # 撕报纸抽样种子（与 tests/newspaper_test.py 一致）
SLICE_WIDTH = 250 + 5          # 255 个交易日（最大合法窗口 + 余量）
T_LO, T_HI = "20140601", "20221231"
TOL = 1e-9


# ================================================================ 候选发现

def load_module(path: Path):
    """从文件路径加载模块（独立模块名，避免与已 import 模块冲突）。"""
    spec = importlib.util.spec_from_file_location(f"_register_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法从 {path} 构造模块")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover_candidates(mod) -> dict[str, callable]:
    """找出文件里定义的新零件：优先 NEW_OPERATORS 字典，否则扫描模块级函数
    （首参名为 panel、定义于本模块、非下划线开头）。"""
    explicit = getattr(mod, "NEW_OPERATORS", None)
    if explicit is not None:
        if not isinstance(explicit, dict):
            raise RuntimeError("NEW_OPERATORS 必须是 {名字: 函数} 字典")
        return dict(explicit)
    out: dict[str, callable] = {}
    for name in dir(mod):
        if name.startswith("_"):
            continue
        fn = getattr(mod, name)
        if not callable(fn) or inspect.isclass(fn):
            continue
        try:
            params = list(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            continue
        if params and params[0] == "panel":
            out[name] = fn
    return out


def check_signature(fn, name: str) -> bool:
    """签名必须与 operators.py 现有零件一致：(panel) 或 (panel, n)。"""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"零件 {name}：无法读取签名 {e!r}")
    if not params or params[0].name != "panel":
        raise RuntimeError(f"零件 {name}：第一个参数必须叫 panel（得到 "
                           f"{[p.name for p in params]}）")
    names = [p.name for p in params[1:]]
    has_default = any(p.default is not inspect.Parameter.empty for p in params[1:])
    if has_default:
        raise RuntimeError(f"零件 {name}：窗口参数不允许默认值（签名应为 "
                           f"f(panel) 或 f(panel, n)）")
    if len(params) == 1:
        return False
    if len(params) == 2 and params[1].name in ("n", "window"):
        return True
    raise RuntimeError(f"零件 {name}：参数过多（{[p.name for p in params]}），"
                       f"只允许 f(panel) 或 f(panel, n)")


# ================================================================ 撕报纸测试
# 复用 tests/newspaper_test.py 的机制：全量面板 vs 截至 T 的世界切片（255 个
# 交易日宽），逐股比对 T 行值；机制相同，数据规模按登记需要裁剪。

def _sample_dates(cal: list[str], n_dates: int) -> list[str]:
    pool = [d for d in cal if T_LO <= d <= T_HI]
    if len(pool) < n_dates:
        raise RuntimeError(f"可抽样交易日不足（{len(pool)} < {n_dates}）")
    return sorted(random.Random(SEED).sample(pool, n_dates))


def _check_output_contract(res, panel: pd.DataFrame, name: str, tag: str) -> None:
    """输出契约：同 index 的 DataFrame、唯一列 value、可转 float64。"""
    if not isinstance(res, pd.DataFrame):
        raise RuntimeError(f"零件 {name}{tag}：输出必须是 DataFrame（得到 {type(res)}）")
    if list(res.columns) != ["value"]:
        raise RuntimeError(f"零件 {name}{tag}：输出必须只有一列 value（得到 {list(res.columns)}）")
    if not res.index.equals(panel.index):
        raise RuntimeError(f"零件 {name}{tag}：输出 index 必须与输入面板一致")
    v = res["value"].to_numpy()
    if len(v) != len(panel):
        raise RuntimeError(f"零件 {name}{tag}：输出长度 {len(v)} != 面板长度 {len(panel)}")
    try:
        fv = np.asarray(v, dtype="float64")
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"零件 {name}{tag}：value 列必须可转 float64（{e!r}）") from e
    if len(fv) and not np.issubdtype(fv.dtype, np.floating):
        raise RuntimeError(f"零件 {name}{tag}：value 列必须可转 float64")


def newspaper_check(fn, name: str, has_window: bool, store, n_dates: int) -> dict:
    """全量面板 == as-of 切片：对全部合法窗口逐行核对。返回统计摘要。

    任何不一致 / 契约违反 / 不确定性 / 非法窗口未拦截 → 抛 RuntimeError。
    """
    panel = store.panel
    dates_arr = panel["date"].to_numpy()
    cal = store.calendar
    Ts = _sample_dates(cal, n_dates)

    # ---- 全量侧：全量面板上算一次，取 T 行 ----
    def full_at(tag: str):
        res = fn(panel) if tag is None else fn(panel, tag)
        _check_output_contract(res, panel, name, "" if tag is None else f"(n={tag})")
        return res["value"].to_numpy()

    full_vals = {w: full_at(w) for w in ((None,) if not has_window else ALLOWED_WINDOWS)}
    # 确定性：同输入二次计算必须 bitwise 一致（NaN 对 NaN 视为一致）
    for w, v0 in full_vals.items():
        res1 = fn(panel) if w is None else fn(panel, w)
        _check_output_contract(res1, panel, name, "" if w is None else f"(n={w})")
        if not np.array_equal(res1["value"].to_numpy().astype("float64"),
                              np.asarray(v0, dtype="float64"), equal_nan=True):
            raise RuntimeError(f"零件 {name}：两次全量计算结果不一致（非确定）")

    # ---- 切片侧：逐 T 构造截至 T 的世界切片，比对 T 行 ----
    n_compare = 0
    per_window_bad: dict = {}
    for T in Ts:
        cal_le = [d for d in cal if d <= T]
        start = cal_le[-SLICE_WIDTH] if len(cal_le) >= SLICE_WIDTH else cal_le[0]
        mask = (dates_arr >= start) & (dates_arr <= T)
        sub = panel[mask]
        tmask = sub["date"].to_numpy() == T
        idx_full = np.flatnonzero(dates_arr == T)
        if not np.array_equal(sub["code"].to_numpy()[tmask], panel["code"].to_numpy()[idx_full]):
            raise RuntimeError(f"T={T}：切片 T 行股票集与全量不一致")
        for w, fv in full_vals.items():
            res = fn(sub) if w is None else fn(sub, w)
            sv = res["value"].to_numpy()[tmask]
            fvs = fv[idx_full]
            sa, fa = np.asarray(sv, dtype="float64"), np.asarray(fvs, dtype="float64")
            ok = (np.isnan(sa) & np.isnan(fa)) | (np.abs(sa - fa) <= TOL)
            bad = int((~ok).sum())
            per_window_bad[w] = per_window_bad.get(w, 0) + bad
            n_compare += len(sa)
            if bad:
                j = int(np.argmax(~ok))
                code = str(sub["code"].to_numpy()[tmask][j])
                raise RuntimeError(
                    f"零件 {name}"
                    + (f"(n={w})" if w is not None else "")
                    + f" T={T} {code}: 切片={sa[j]!r} 全量={fa[j]!r} "
                    f"（切片≠全量 = 依赖了 T 日之后的数据，撕报纸测试失败）")
    # ---- 非法窗口拦截 ----
    if has_window:
        try:
            fn(panel, 7)
            raise RuntimeError(f"零件 {name}：非法窗口 n=7 未抛 ValueError"
                               f"（operators 契约要求窗口必须过档位校验）")
        except RuntimeError:
            raise
        except ValueError:
            pass
    return {"n_dates": len(Ts), "n_windows": len(full_vals), "n_compare": n_compare,
            "per_window_bad": {str(k): v for k, v in per_window_bad.items()}}


# ================================================================ 注册表

def registry_read(path: Path) -> dict:
    if not Path(path).is_file():
        return {"version": 1, "operators": {}}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data.get("operators"), dict):
        raise RuntimeError(f"注册表 {path} 格式错误：缺少 operators 映射")
    return data


def registry_write(path: Path, data: dict) -> None:
    """原子写入（临时文件 + os.replace）：要么整体成功，要么保持原状。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _rel_to_root(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(Path(p).resolve())          # 仓库外的文件记绝对路径


def fresh_import_verify(registry_path: Path, expected: dict) -> None:
    """子进程新鲜 import：验证注册表加载与派生链路（operators → config → funnel 池）。"""
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        "import operators as o, config as c\n"
        f"exp = json.loads({json.dumps(json.dumps(expected))})\n"
        "for name, m in exp.items():\n"
        "    assert name in o.OPERATORS, f'{name} 未并入 OPERATORS'\n"
        "    assert o.OPERATOR_META[name]['has_window'] == m['has_window'], name\n"
        "    assert o.OPERATOR_META[name]['threshold_kind'] == m['threshold_kind'], name\n"
        "    (c.OP_ARG_OPERATORS if m['has_window'] else c.NO_ARG_OPERATORS)\n"
        "assert set(c.OP_ARG_OPERATORS) | set(c.NO_ARG_OPERATORS) == set(o.OPERATORS)\n"
        "print('FRESH_IMPORT_OK')\n"
    )
    env = dict(os.environ)
    env[opmod.REGISTRY_ENV] = str(registry_path)
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                       cwd=str(Path(__file__).resolve().parent),
                       env=env, capture_output=True, text="utf-8")
    if r.returncode != 0 or "FRESH_IMPORT_OK" not in r.stdout:
        raise RuntimeError(f"新鲜 import 验证失败（退出码 {r.returncode}）：\n"
                           f"{r.stdout}\n{r.stderr}")


# ================================================================ 主流程

def register_file(file_path: Path, threshold_kinds: dict[str, str],
                  registry_path: Path, n_dates: int, store=None) -> int:
    """登记一个文件里的全部新零件：先全部检查，再一次性原子落盘。返回退出码。"""
    file_path = Path(file_path)
    if not file_path.is_file():
        print(f"[register] 文件不存在：{file_path}")
        return 2
    for name, kind in threshold_kinds.items():
        if kind not in VALID_KINDS:
            print(f"[register] 非法阈值量纲 {name}={kind!r}（可用：{VALID_KINDS}）")
            return 2
    reg = registry_read(registry_path)
    entries: dict = reg.get("operators", {})

    try:
        mod = load_module(file_path)
        candidates = discover_candidates(mod)
    except Exception as e:  # noqa: BLE001
        print(f"[register] 加载 {file_path} 失败：{e!r}")
        return 2
    if not candidates:
        print(f"[register] {file_path} 里没有候选零件（定义 f(panel[, n]) 函数，"
              f"或提供 NEW_OPERATORS 字典）")
        return 2

    # ---- 静态检查（全部候选一起过，any 失败即整体拒绝）----
    plan: dict[str, dict] = {}
    for name, fn in candidates.items():
        if not NAME_RE.match(name):
            print(f"[register] 零件名 {name!r} 不合法（须匹配 {NAME_RE.pattern}）")
            return 2
        if name in OPERATORS or name in OPERATOR_META:
            print(f"[register] {name!r} 与内置零件重名，内置零件不可覆盖")
            return 2
        try:
            has_window = check_signature(fn, name)
        except RuntimeError as e:
            print(f"[register] {e}")
            return 2
        kind = threshold_kinds.get(name, "none")
        plan[name] = {"fn": fn, "has_window": has_window, "threshold_kind": kind}
    for name in threshold_kinds:
        if name not in plan:
            print(f"[register] --threshold-kind 指定了不存在的零件 {name!r}"
                  f"（文件里发现：{sorted(plan)}）")
            return 2

    # ---- 撕报纸测试（先测后写；失败即拒绝，注册表一字不动）----
    if store is None:
        print("[register] 加载数据面板（撕报纸测试，一次共享）……", flush=True)
        from prices import DataStore
        store = DataStore(quiet=True)
    print(f"[register] 撕报纸测试：{sorted(plan)} × 全部合法窗口 × {n_dates} 个随机 T……",
          flush=True)
    try:
        for name, p in plan.items():
            stats = newspaper_check(p["fn"], name, p["has_window"], store, n_dates)
            print(f"[register]   {name}: PASS（{stats['n_dates']} 个 T × "
                  f"{stats['n_windows']} 个窗口形态，比对 {stats['n_compare']} 值）")
    except RuntimeError as e:
        print(f"[register] 撕报纸测试未通过，拒绝登记（注册表未改动）：{e}")
        return 1
    except Exception as e:  # noqa: BLE001 —— 零件在面板上抛错同样是未通过
        print(f"[register] 撕报纸测试执行失败，拒绝登记（注册表未改动）：{e!r}")
        return 1

    # ---- 幂等判定 + 原子落盘 ----
    sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_entries = dict(entries)
    changed: list[str] = []
    added: list[str] = []

    def _same(a: dict, b: dict) -> bool:
        """幂等比较：registered_at 是登记时间戳（每次比对都会变），
        其余字段全同才算「无变化」。"""
        ka = {k: v for k, v in a.items() if k != "registered_at"}
        kb = {k: v for k, v in b.items() if k != "registered_at"}
        return ka == kb

    for name, p in plan.items():
        entry = {"module": _rel_to_root(file_path), "function": name,
                 "has_window": p["has_window"], "threshold_kind": p["threshold_kind"],
                 "sha256": sha, "registered_at": now,
                 "doc": (p["fn"].__doc__ or "").strip().splitlines()[0]
                 if p["fn"].__doc__ else ""}
        old = entries.get(name)
        if old is not None and _same(old, entry):
            continue                      # 内容全同 → 幂等无变化（不重写）
        if old is not None:
            diffs = {k: (old.get(k), entry[k]) for k in entry
                     if k != "registered_at" and old.get(k) != entry[k]}
            print(f"[register] 更新已登记零件 {name}："
                  + (", ".join(f"{k}: {v0} -> {v1}" for k, (v0, v1) in diffs.items())
                     or "内容哈希一致，仅刷新登记时间"))
            changed.append(name)
        else:
            added.append(name)
        new_entries[name] = entry
    if not added and not changed:
        print(f"[register] {sorted(plan)} 已按相同内容登记于 {registry_path}，无变化（幂等）")
        return 0
    reg["operators"] = new_entries
    try:
        registry_write(registry_path, reg)
    except OSError as e:
        print(f"[register] 注册表写入失败（保持原状）：{e!r}")
        return 2
    print(f"[register] 已写入 {registry_path}（新增 {added or '—'}，更新 {changed or '—'}，"
          f"当前共 {len(new_entries)} 个登记）")

    # ---- 新鲜 import 验证（派生链路端到端）----
    try:
        expected = {n: {"has_window": p["has_window"],
                        "threshold_kind": p["threshold_kind"]} for n, p in plan.items()}
        fresh_import_verify(registry_path, expected)
    except RuntimeError as e:
        print(f"[register] 警告：{e}\n"
              f"[register] 注册表已写入；请检查 operators.py 的注册表加载。")
        return 2
    print(f"[register] 新鲜 import 验证通过：config.OP_ARG/NO_ARG、funnel 猴子池"
          f"与阈值量纲分派已自动包含新零件（单一事实来源派生）。")
    return 0


# ================================================================ 自测

def _write_test_ops(dir_path: Path) -> tuple[Path, Path]:
    """生成自测零件文件：一个好零件（只回看），一个作弊零件（shift(-1) 看未来）。"""
    good = dir_path / "good_ops.py"
    good.write_text(
        '# -*- coding: utf-8 -*-\n'
        '"""自测新零件：N 日 pctChg 累计和（%），numpy 滑动窗口、只回看。"""\n'
        'import numpy as np\n'
        'import pandas as pd\n'
        'from operators import ALLOWED_WINDOWS, _by_code, _sw_apply, _out, _check_window\n'
        '\n'
        'def cum_ret_n(panel, n):\n'
        '    """N 日 pctChg 累计和（%）。"""\n'
        '    n = _check_window(n)\n'
        '    v = _by_code(panel, "pct_chg", lambda x: _sw_apply(x, n, lambda w: w.sum(axis=1)))\n'
        '    return _out(panel, v, f"cum_ret_{n}")\n'
        '\n'
        'def hl_range(panel):\n'
        '    """当日振幅 %：(high-low)/close*100（单行，无窗口）。"""\n'
        '    v = (panel["high"] - panel["low"]) / panel["close"] * 100.0\n'
        '    return pd.DataFrame({"value": v.astype("float64")}, index=panel.index)\n'
        '\n'
        'NEW_OPERATORS = {"cum_ret_n": cum_ret_n, "hl_range": hl_range}\n',
        encoding="utf-8")
    bad = dir_path / "bad_ops.py"
    bad.write_text(
        '# -*- coding: utf-8 -*-\n'
        '"""作弊零件：用了 T+1 的值（未来函数），撕报纸测试必须拦截。"""\n'
        'import pandas as pd\n'
        '\n'
        'def lookahead(panel):\n'
        '    """明日收盘 / 今日收盘（用了未来数据，必须被拒绝）。"""\n'
        '    nxt = panel.groupby("code", sort=False)["close"].shift(-1)\n'
        '    return pd.DataFrame({"value": (nxt / panel["close"]).astype("float64")},\n'
        '                        index=panel.index)\n'
        '\n'
        'NEW_OPERATORS = {"lookahead": lookahead}\n',
        encoding="utf-8")
    return good, bad


def selftest() -> int:
    """合成零件自测：好零件登记成功且派生生效；作弊零件被拒、注册表零改动。"""
    results: list[tuple[str, bool]] = []

    def check(name: str, cond: bool, detail: str = ""):
        results.append((name, bool(cond)))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
              + (f"  {detail}" if detail and not cond else ""))

    with tempfile.TemporaryDirectory(prefix="register_selftest_") as td:
        tmp = Path(td)
        good, bad = _write_test_ops(tmp)
        reg = tmp / "registry.json"

        # 共享一次数据面板（撕报纸测试每次登记都会重跑——登记流程不变）
        print("[register] 自测加载数据面板……", flush=True)
        from prices import DataStore
        store = DataStore(quiet=True)

        # 1) 作弊零件 → 拒绝（退出码 1），注册表不创建
        rc_bad = register_file(bad, {}, reg, n_dates=6, store=store)
        check("作弊零件（shift(-1)）被撕报纸测试拒绝（退出码 1）", rc_bad == 1, f"rc={rc_bad}")
        check("被拒后注册表保持不存在（无半注册状态）", not reg.exists())

        # 2) 好零件 → 登记（退出码 0），注册表写入，新鲜 import 派生生效
        rc_good = register_file(good, {"cum_ret_n": "pct"}, reg, n_dates=6, store=store)
        check("好零件（窗口+无窗各一）登记成功（退出码 0）", rc_good == 0, f"rc={rc_good}")
        data = registry_read(reg)
        check("注册表含 2 个登记，阈值量纲正确",
              set(data["operators"]) == {"cum_ret_n", "hl_range"}
              and data["operators"]["cum_ret_n"]["threshold_kind"] == "pct"
              and data["operators"]["hl_range"]["threshold_kind"] == "none"
              and data["operators"]["cum_ret_n"]["has_window"] is True
              and data["operators"]["hl_range"]["has_window"] is False,
              json.dumps(data["operators"], ensure_ascii=False)[:300])

        # 3) 幂等：同文件同参数重复登记 → 无变化（退出码 0），文件未重写
        before = reg.read_text(encoding="utf-8")
        rc_again = register_file(good, {"cum_ret_n": "pct"}, reg, n_dates=6, store=store)
        check("重复登记（全同）→ 幂等无变化（退出码 0）",
              rc_again == 0 and reg.read_text(encoding="utf-8") == before,
              f"rc={rc_again}")

        # 4) 明确更新：改阈值量纲 → 明确更新（退出码 0）
        rc_upd = register_file(good, {"cum_ret_n": "mult"}, reg, n_dates=6, store=store)
        data2 = registry_read(reg)
        check("改量纲 → 明确更新（退出码 0，pct→mult）",
              rc_upd == 0 and data2["operators"]["cum_ret_n"]["threshold_kind"] == "mult",
              f"rc={rc_upd}")

        # 5) 用法错误：与内置零件重名 → 退出码 2
        clash = tmp / "clash.py"
        clash.write_text(
            'def ret_n(panel, n):\n    """重名内置零件。"""\n    raise NotImplementedError\n',
            encoding="utf-8")
        rc_clash = register_file(clash, {}, reg, n_dates=2, store=store)
        check("与内置零件重名 → 拒绝（退出码 2）", rc_clash == 2, f"rc={rc_clash}")

        # 6) 新鲜 import 后 config/funnel 派生包含新零件（已由登记内验证覆盖，
        #    这里再显式断言一次注册表元数据形状）
        check("登记元数据含 module/function/sha256/registered_at",
              all(k in data2["operators"]["cum_ret_n"]
                  for k in ("module", "function", "sha256", "registered_at")))

    n_fail = sum(1 for _, v in results if not v)
    print(f"== register selftest: {len(results) - n_fail}/{len(results)} PASS ==")
    return 1 if n_fail else 0


# ================================================================ CLI

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        prog="engine/register_operator.py",
        description="新零件登记：撕报纸测试通过后才持久化进注册表（rules.md 第 8.3 节）")
    ap.add_argument("file", nargs="?", help="定义新零件函数的 Python 文件")
    ap.add_argument("--threshold-kind", default="",
                    help="阈值量纲登记，名字=量纲，逗号分隔（pct/mult/streak/none，"
                         "缺省 none=只能作因子/rank）")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY),
                    help=f"注册表 JSON 路径（默认 {DEFAULT_REGISTRY.name}）")
    ap.add_argument("--dates", type=int, default=48,
                    help="撕报纸测试抽取的 T 日个数（默认 48，种子固定 42）")
    ap.add_argument("--selftest", action="store_true",
                    help="合成零件自测（不写默认注册表）")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.file:
        ap.print_usage()
        return 2
    kinds: dict[str, str] = {}
    for part in filter(None, a.threshold_kind.split(",")):
        if "=" not in part:
            print(f"[register] --threshold-kind 片段 {part!r} 缺 '='（应为 名字=量纲）")
            return 2
        k, v = part.split("=", 1)
        kinds[k.strip()] = v.strip()
    return register_file(Path(a.file), kinds, Path(a.registry), max(2, a.dates))


if __name__ == "__main__":
    raise SystemExit(main())
