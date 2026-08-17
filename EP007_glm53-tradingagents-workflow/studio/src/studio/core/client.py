"""TradingAgents-CN HTTP API 客户端：登录、发起分析、轮询状态、取结果、SSE。

只读集成层，不向原项目写任何数据。
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator, Optional

import httpx

TERMINAL = {"completed", "failed", "cancelled", "cancelled_failed"}


class APIError(RuntimeError):
    pass


class TradingAgentsClient:
    def __init__(self, cfg):
        self.base: str = str(cfg.get("api.base_url", "http://localhost")).rstrip("/")
        self.username: str = cfg.get("api.username", "admin")
        self.password: str = cfg.get("api.password", "")
        self.timeout: float = float(cfg.get("api.timeout", 30))
        self._token: Optional[str] = None
        self._http = httpx.Client(base_url=self.base, timeout=self.timeout)

    # ---- 认证 ----
    def login(self) -> str:
        r = self._http.post(
            "/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        data = self._unwrap(r)
        self._token = data["data"]["access_token"]
        return self._token

    def _auth_header(self) -> dict[str, str]:
        if not self._token:
            self.login()
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _unwrap(r: httpx.Response) -> dict:
        r.raise_for_status()
        body = r.json()
        if body.get("success") is False:
            raise APIError(body.get("message") or body)
        return body

    def _request(self, method: str, url: str, **kw) -> dict:
        for attempt in (1, 2):  # 401 时重新登录一次
            r = self._http.request(method, url, headers=self._auth_header(), **kw)
            if r.status_code == 401 and attempt == 1:
                self._token = None
                continue
            return self._unwrap(r)
        raise APIError(f"{method} {url} 认证失败")

    # ---- 健康与任务 ----
    def health(self) -> dict:
        r = self._http.get("/api/health")
        r.raise_for_status()
        return r.json().get("data", {})

    def submit_analysis(
        self,
        symbol: str,
        depth: str = "标准",
        analysts: Optional[list[str]] = None,
        quick_model: Optional[str] = None,
        deep_model: Optional[str] = None,
        market: str = "A股",
        analysis_date: Optional[str] = None,
    ) -> str:
        params: dict[str, Any] = {
            "market_type": market,
            "research_depth": depth,
            **({"analysis_date": analysis_date} if analysis_date else {}),
            "selected_analysts": analysts or ["market", "fundamentals", "news"],
            "include_sentiment": True,
            "include_risk": True,
            "language": "zh-CN",
        }
        if quick_model:
            params["quick_analysis_model"] = quick_model
        if deep_model:
            params["deep_analysis_model"] = deep_model
        body = self._request("POST", "/api/analysis/single",
                             json={"symbol": symbol, "stock_code": symbol, "parameters": params})
        task_id = body.get("data", {}).get("task_id")
        if not task_id:
            raise APIError(f"未返回 task_id: {body}")
        return task_id

    def get_status(self, task_id: str) -> dict:
        return self._request("GET", f"/api/analysis/tasks/{task_id}/status").get("data", {}) or {}

    def get_result(self, task_id: str) -> dict:
        return self._request("GET", f"/api/analysis/tasks/{task_id}/result").get("data", {}) or {}

    def wait_for_task(
        self,
        task_id: str,
        on_update: Optional[Callable[[dict], None]] = None,
        poll_interval: float = 10.0,
        timeout: float = 3600.0,
    ) -> dict:
        """轮询到终态，返回最后一次 status。"""
        deadline = time.time() + timeout
        status: dict = {}
        while time.time() < deadline:
            status = self.get_status(task_id)
            if on_update:
                try:
                    on_update(status)
                except Exception:
                    pass
            if status.get("status") in TERMINAL:
                return status
            time.sleep(poll_interval)
        raise TimeoutError(f"任务 {task_id} 等待超时（{timeout}s）")

    # ---- SSE（实时进度，供 replay 抓取）----
    def iter_sse(self, task_id: str) -> Iterator[dict]:
        """产出 {'event': ..., **data}；连接断开时正常结束。"""
        with self._http.stream(
            "GET", f"/api/stream/tasks/{task_id}", headers=self._auth_header()
        ) as r:
            r.raise_for_status()
            event, data_lines = "message", []
            for line in r.iter_lines():
                if line is None:
                    continue
                if line == "":
                    if data_lines:
                        raw = "\n".join(data_lines)
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            payload = {"raw": raw}
                        yield {"event": event, **payload}
                    event, data_lines = "message", []
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())

    # ---- 股票元信息 ----
    _name_cache: dict[str, str] = {}

    def stock_name(self, symbol: str) -> str:
        """代码 -> 股票名称（走原项目 basic-info 接口，带进程内缓存）。"""
        if not symbol:
            return ""
        if symbol in self._name_cache:
            return self._name_cache[symbol]
        try:
            data = self._request("GET", f"/api/stock-data/basic-info/{symbol}").get("data", {}) or {}
            name = str(data.get("name") or "")
        except Exception:
            name = ""
        self._name_cache[symbol] = name
        return name

    # ---- 用量统计（compare 模块取 token 数）----
    def usage_records(
        self,
        model_name: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        params = {"limit": limit}
        if model_name:
            params["model_name"] = model_name
        if start:
            params["start_date"] = start
        if end:
            params["end_date"] = end
        body = self._request("GET", "/api/usage-statistics/records", params=params)
        return body.get("data", {}).get("records", []) or []

    def close(self):
        self._http.close()
