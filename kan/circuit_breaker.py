"""数据源熔断器 · 跨进程持久化 · 跳过近期挂掉的源。

每个数据源（baostock/sina/eastmoney/tencent）的 down 状态记在
~/.local/share/kan/circuit.json，跨 `kan` 进程保留。失败的源在
DOWN_TTL 窗口内被跳过，过期后自动重新探测。

设计：
- 只记 down 源 · ok 源 = 不在表里（或表里但 TTL 已过）。
- fail-open：circuit.json 损坏/缺失 → 视作空 · 所有源都试。
  熔断器是优化层，绝不让 fetch 比"没有熔断器"更糟。
- 原子写（写 .tmp + os.replace）· 不上文件锁：并发写丢更新对
  熔断器无害（顶多某源多探一次），os.replace 跨平台 atomic。

并发首调 race 行为(***REMOVED*** · 文档化 · 实施优化推 v0.0.6):
- fetch_batch 用 ThreadPoolExecutor 并发(默认上限 12)
- 12 个 worker 同步进 _fetch_<source>(N) · is_down("X") 同时返 False
- 12 个 HTTP 全发出 · 其中 1 个 fail record 后 · 剩余 11 个仍 in-flight
- 结果:首次失败 cooldown 触发前 · 顶多 N 倍探测(N = 并发上限)
- 当前 fail-open 设计可接受 · 进入 cooldown 后 5min 内单 worker fast-fail
- v0.0.6 优化候选:in-flight set 收 thundering herd
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from kan._log import debug_log

DOWN_TTL = timedelta(minutes=5)


class CircuitBreaker:
    """单个熔断器实例 · 持久化到指定 circuit.json 路径。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._down: dict[str, datetime] | None = None  # None = 未加载

    def is_down(self, source: str) -> bool:
        """source 是否在 down 窗口内（应跳过）· 未加载先 lazy load。"""
        with self._lock:
            self._ensure_loaded()
            since = self._down.get(source)
            if since is None:
                return False
            return datetime.now() - since < DOWN_TTL

    def record(self, source: str, ok: bool) -> None:
        """记录一次探测结果 · 仅状态变化时落盘。"""
        with self._lock:
            self._ensure_loaded()
            if ok:
                if self._down.pop(source, None) is None:
                    return  # 本就 ok · 无变化 · 不写盘
            else:
                self._down[source] = datetime.now()
            self._save()

    # ── 内部 ──────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._down is None:
            self._down = self._load()

    def _load(self) -> dict[str, datetime]:
        """读 circuit.json · 任何问题 → 空 dict（fail-open）。"""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, datetime] = {}
        for source, iso in raw.items():
            try:
                result[source] = datetime.fromisoformat(iso)
            except (TypeError, ValueError):
                continue  # 跳过坏条目 · 不让一条脏数据废掉整个文件
        return result

    def _save(self) -> None:
        """原子写 circuit.json + chmod 0o600 · 写失败不抛(内存态仍有效)。"""
        from kan.paths import atomic_write_json

        payload = {s: dt.isoformat() for s, dt in self._down.items()}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self._path, payload, indent=2)
        except OSError as e:
            debug_log(__name__, f"circuit save ({self._path.name})", e)


_default: CircuitBreaker | None = None
_default_lock = threading.Lock()


def get_breaker() -> CircuitBreaker:
    """进程级单例 · 路径 paths.CIRCUIT_PATH。"""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                from kan.paths import CIRCUIT_PATH
                _default = CircuitBreaker(CIRCUIT_PATH)
    return _default
