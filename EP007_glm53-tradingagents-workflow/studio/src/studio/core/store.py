"""SQLite 存储：runs / run_events / digests / benchmarks。零运维，单文件，线程安全。"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Callable, Optional, TypeVar

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    task_id     TEXT PRIMARY KEY,
    symbol      TEXT,
    depth       TEXT,
    quick_model TEXT,
    deep_model  TEXT,
    status      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    wall_s      REAL,
    error       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS run_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    ts      TEXT,
    phase   TEXT,
    agent   TEXT,
    content TEXT,
    meta    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_task ON run_events(task_id);
CREATE TABLE IF NOT EXISTS digests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT,
    symbol      TEXT,
    model       TEXT,
    input_chars INTEGER,
    output_text TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS benchmarks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT,
    depth       TEXT,
    results_json TEXT,
    table_md    TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

T = TypeVar("T")


def _locked(fn: Callable[..., T]) -> Callable[..., T]:
    """SQLite 连接跨线程共享（报告服务是多线程 HTTP），所有访问串行化。"""

    @wraps(fn)
    def wrapper(self: "Store", *args, **kwargs) -> T:
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(_SCHEMA)

    # ---- runs ----
    @_locked
    def upsert_run(self, task_id: str, **fields) -> None:
        cols = list(fields.keys())
        sets = ", ".join(f"{c}=?" for c in cols)
        self.conn.execute(
            f"INSERT INTO runs(task_id, {', '.join(cols)}) VALUES({', '.join('?' * (len(cols) + 1))}) "
            f"ON CONFLICT(task_id) DO UPDATE SET {sets}",
            [task_id, *fields.values(), *fields.values()],
        )
        self.conn.commit()

    @_locked
    def get_run(self, task_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM runs WHERE task_id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    @_locked
    def latest_runs(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- events ----
    @_locked
    def add_event(self, task_id: str, ts: str, phase: str, agent: str, content: str,
                  meta: Optional[dict] = None) -> None:
        self.conn.execute(
            "INSERT INTO run_events(task_id, ts, phase, agent, content, meta) VALUES(?,?,?,?,?,?)",
            (task_id, ts, phase, agent, content,
             json.dumps(meta, ensure_ascii=False) if meta else None),
        )
        self.conn.commit()

    @_locked
    def events(self, task_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM run_events WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- digests / benchmarks ----
    @_locked
    def save_digest(self, task_id: str, symbol: str, model: str, input_chars: int, text: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO digests(task_id, symbol, model, input_chars, output_text) VALUES(?,?,?,?,?)",
            (task_id, symbol, model, input_chars, text),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    @_locked
    def save_benchmark(self, symbol: str, depth: str, results: list[dict], table_md: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO benchmarks(symbol, depth, results_json, table_md) VALUES(?,?,?,?)",
            (symbol, depth, json.dumps(results, ensure_ascii=False), table_md),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    @_locked
    def close(self):
        self.conn.close()
