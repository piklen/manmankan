"""K 线数据源单点封装 · 4 数据源 + akshare 双源并发 race。

每个 `_fetch_<source>` 拉单只股票 raw K 线(列名未归一)· 失败返 None ·
异常 broad catch + debug_log + 熔断器记账。归一化由 fetcher._normalize_kline
统一做(出口) · 这一层只管 "网络 I/O + source-specific 列映射"。

从 fetcher.py 抽出 · fetcher.py 保留 cache + 编排 + 公开 API ·
本模块只放数据源 fetcher · 解耦"网络访问"与"缓存编排"。

加入 `*KlineSource` class (实现 KlineSource Protocol) · 作为责任链 (KlineSourceChain)
中的元数据携带 (name / priority / is_available)。class 是 thin Protocol 适配 ·
内部仍调 module function `_fetch_<source>` (保持 SOT · 测试 monkeypatch 路径不破)。

monkeypatch 路径:测试 patch 在本模块 namespace
(例:`monkeypatch.setattr("kan.data.sources._fetch_sina", ...)`)· `_fetch_via_akshare`
通过 module globals 查 `_fetch_sina` / `_fetch_eastmoney` · patch 生效。
KlineSource class 的 fetch() 也通过 module globals 调 `_fetch_*` · patch 同样生效。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import requests

from kan.data.provider_contracts import (
    FetchFailure,
    FetchFailureKind,
    ProviderCapabilities,
    ProviderFetchResult,
)
from kan.infra import circuit_breaker
from kan.infra.log import debug_log

if TYPE_CHECKING:
    import pandas as pd


# 东方财富中文列名 → 标准列名
_EM_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}


def _market_prefix(symbol: str, sep: str = "") -> str:
    """6 位代码 → 带市场前缀（sh600519 / sz.000001）"""
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    return f"{prefix}{sep}{symbol}"


def _record_success(source: str, record_breaker: bool) -> bool:
    if record_breaker:
        circuit_breaker.get_breaker().record(source, ok=True)
    return record_breaker


def _failure_result(
    source: str,
    kind: FetchFailureKind,
    *,
    message: str,
    record_breaker: bool,
    retryable: bool = False,
    affects_circuit: bool = False,
) -> ProviderFetchResult[pd.DataFrame]:
    breaker_recorded = record_breaker and affects_circuit
    if breaker_recorded:
        circuit_breaker.get_breaker().record(source, ok=False)
    return ProviderFetchResult.failed(
        FetchFailure(
            kind,
            message=message,
            retryable=retryable,
            affects_circuit=affects_circuit,
        ),
        breaker_recorded=breaker_recorded,
    )


# ── 数据源 1: 东方财富（最快 · 单次 HTTP） ───────────────────────────

def _fetch_eastmoney_detailed(
    symbol: str,
    start: str,
    *,
    record_breaker: bool = True,
) -> ProviderFetchResult[pd.DataFrame]:
    source = "eastmoney"
    if circuit_breaker.get_breaker().is_down(source):
        return _failure_result(
            source,
            FetchFailureKind.CIRCUIT_OPEN,
            message="eastmoney circuit is open",
            record_breaker=False,
        )
    try:
        import akshare as ak
    except ImportError as exc:
        return _failure_result(
            source,
            FetchFailureKind.UNAVAILABLE,
            message=type(exc).__name__,
            record_breaker=False,
        )
    try:
        raw = ak.stock_zh_a_hist(
            symbol=symbol, period="daily", adjust="qfq",
            start_date=start, timeout=5,
        )
    except requests.Timeout as exc:
        debug_log(__name__, "fetch eastmoney", exc)
        return _failure_result(
            source,
            FetchFailureKind.TIMEOUT,
            message=type(exc).__name__,
            record_breaker=record_breaker,
            retryable=True,
            affects_circuit=True,
        )
    except Exception as exc:
        # akshare 不保证异常类型，剩余异常统一归为传输失败。
        debug_log(__name__, "fetch eastmoney", exc)
        return _failure_result(
            source,
            FetchFailureKind.TRANSPORT,
            message=type(exc).__name__,
            record_breaker=record_breaker,
            retryable=True,
            affects_circuit=True,
        )
    breaker_recorded = _record_success(source, record_breaker)
    if raw is None or raw.empty:
        return ProviderFetchResult.failed(
            FetchFailure(FetchFailureKind.EMPTY, message="eastmoney returned no data"),
        )
    if "日期" not in raw.columns:
        return ProviderFetchResult.failed(
            FetchFailure(
                FetchFailureKind.INVALID_SCHEMA,
                message="eastmoney response is missing 日期",
            ),
        )
    return ProviderFetchResult.succeeded(
        raw.rename(columns=_EM_COLUMN_MAP),
        breaker_recorded=breaker_recorded,
    )


def _fetch_eastmoney(symbol: str, start: str) -> pd.DataFrame | None:
    return _fetch_eastmoney_detailed(symbol, start).data


# ── 数据源 2: baostock（独立服务器 · 最稳 · 线程安全锁） ─────────────

_bs_lock = threading.Lock()
_bs_logged_in = False


def _ensure_bs_login() -> None:
    global _bs_logged_in
    if _bs_logged_in:
        return
    import io
    import sys

    import baostock as bs

    _stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        result = bs.login()
    finally:
        sys.stdout = _stdout
    if result is None:
        raise RuntimeError("baostock login failed: empty result")
    error_code = str(getattr(result, "error_code", ""))
    if error_code != "0":
        raise RuntimeError(f"baostock login failed: error_code={error_code or 'missing'}")
    _bs_logged_in = True


def _fetch_baostock_detailed(
    symbol: str,
    start: str,
    *,
    record_breaker: bool = True,
) -> ProviderFetchResult[pd.DataFrame]:
    source = "baostock"
    try:
        import baostock as bs
        import pandas as pd
    except ImportError as exc:
        return _failure_result(
            source,
            FetchFailureKind.UNAVAILABLE,
            message=type(exc).__name__,
            record_breaker=False,
        )
    if circuit_breaker.get_breaker().is_down(source):
        return _failure_result(
            source,
            FetchFailureKind.CIRCUIT_OPEN,
            message="baostock circuit is open",
            record_breaker=False,
        )

    start_fmt = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
    with _bs_lock:
        try:
            _ensure_bs_login()
            rs = bs.query_history_k_data_plus(
                _market_prefix(symbol, sep="."),
                "date,open,high,low,close,volume,amount",
                start_date=start_fmt,
                frequency="d",
                adjustflag="2",
            )
            if str(rs.error_code) != "0":
                _record_success(source, record_breaker)
                return ProviderFetchResult.failed(
                    FetchFailure(
                        FetchFailureKind.EMPTY,
                        message=f"baostock error_code={rs.error_code}",
                    ),
                )
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
        except TimeoutError as exc:
            debug_log(__name__, "fetch baostock", exc)
            return _failure_result(
                source,
                FetchFailureKind.TIMEOUT,
                message=type(exc).__name__,
                record_breaker=record_breaker,
                retryable=True,
                affects_circuit=True,
            )
        except Exception as exc:
            debug_log(__name__, "fetch baostock", exc)
            return _failure_result(
                source,
                FetchFailureKind.TRANSPORT,
                message=type(exc).__name__,
                record_breaker=record_breaker,
                retryable=True,
                affects_circuit=True,
            )

    breaker_recorded = _record_success(source, record_breaker)
    if not rows:
        return ProviderFetchResult.failed(
            FetchFailure(FetchFailureKind.EMPTY, message="baostock returned no data"),
        )
    return ProviderFetchResult.succeeded(
        pd.DataFrame(
            rows,
            columns=["date", "open", "high", "low", "close", "volume", "amount"],
        ),
        breaker_recorded=breaker_recorded,
    )


def _fetch_baostock(symbol: str, start: str) -> pd.DataFrame | None:
    return _fetch_baostock_detailed(symbol, start).data


# ── 数据源 3: 新浪财经（akshare stock_zh_a_daily · 免登录 · 数值精度高） ──

def _fetch_sina_detailed(
    symbol: str,
    start: str,
    *,
    record_breaker: bool = True,
) -> ProviderFetchResult[pd.DataFrame]:
    """新浪财经历史日 K · 单次调用详细结果。"""
    source = "sina"
    if circuit_breaker.get_breaker().is_down(source):
        return _failure_result(
            source,
            FetchFailureKind.CIRCUIT_OPEN,
            message="sina circuit is open",
            record_breaker=False,
        )
    try:
        import akshare as ak
    except ImportError as exc:
        return _failure_result(
            source,
            FetchFailureKind.UNAVAILABLE,
            message=type(exc).__name__,
            record_breaker=False,
        )

    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    end = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    try:
        raw = ak.stock_zh_a_daily(
            symbol=f"{prefix}{symbol}",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
    except requests.Timeout as exc:
        debug_log(__name__, "fetch sina", exc)
        return _failure_result(
            source,
            FetchFailureKind.TIMEOUT,
            message=type(exc).__name__,
            record_breaker=record_breaker,
            retryable=True,
            affects_circuit=True,
        )
    except Exception as exc:
        debug_log(__name__, "fetch sina", exc)
        return _failure_result(
            source,
            FetchFailureKind.TRANSPORT,
            message=type(exc).__name__,
            record_breaker=record_breaker,
            retryable=True,
            affects_circuit=True,
        )

    breaker_recorded = _record_success(source, record_breaker)
    if raw is None or raw.empty:
        return ProviderFetchResult.failed(
            FetchFailure(FetchFailureKind.EMPTY, message="sina returned no data"),
        )
    return ProviderFetchResult.succeeded(raw, breaker_recorded=breaker_recorded)


def _fetch_sina(symbol: str, start: str) -> pd.DataFrame | None:
    """保留旧 DataFrame | None 契约和 monkeypatch 路径。"""
    return _fetch_sina_detailed(symbol, start).data


# ── 数据源 4: 腾讯证券（备用 · 按年分片 · 价格可信 · 量额不可信） ────

def _fetch_tencent_detailed(
    symbol: str,
    start: str,
    *,
    record_breaker: bool = True,
) -> ProviderFetchResult[pd.DataFrame]:
    """腾讯 K 线 fallback · 只保留语义可信的价格列。"""
    source = "tencent"
    if circuit_breaker.get_breaker().is_down(source):
        return _failure_result(
            source,
            FetchFailureKind.CIRCUIT_OPEN,
            message="tencent circuit is open",
            record_breaker=False,
        )
    try:
        import akshare as ak
    except ImportError as exc:
        return _failure_result(
            source,
            FetchFailureKind.UNAVAILABLE,
            message=type(exc).__name__,
            record_breaker=False,
        )

    try:
        raw = ak.stock_zh_a_hist_tx(
            symbol=_market_prefix(symbol),
            start_date=start,
            adjust="qfq",
            timeout=15,
        )
    except requests.Timeout as exc:
        debug_log(__name__, "fetch tencent", exc)
        return _failure_result(
            source,
            FetchFailureKind.TIMEOUT,
            message=type(exc).__name__,
            record_breaker=record_breaker,
            retryable=True,
            affects_circuit=True,
        )
    except Exception as exc:
        debug_log(__name__, "fetch tencent", exc)
        return _failure_result(
            source,
            FetchFailureKind.TRANSPORT,
            message=type(exc).__name__,
            record_breaker=record_breaker,
            retryable=True,
            affects_circuit=True,
        )

    breaker_recorded = _record_success(source, record_breaker)
    if raw is None or raw.empty:
        return ProviderFetchResult.failed(
            FetchFailure(FetchFailureKind.EMPTY, message="tencent returned no data"),
        )
    if "amount" in raw.columns:
        raw = raw.drop(columns=["amount"])
    return ProviderFetchResult.succeeded(raw, breaker_recorded=breaker_recorded)


def _fetch_tencent(symbol: str, start: str) -> pd.DataFrame | None:
    return _fetch_tencent_detailed(symbol, start).data


# ── akshare 双源并发（东财 + 新浪 · race · baostock 挂掉后第二档） ──────

def _fetch_via_akshare(symbol: str, start: str) -> tuple[pd.DataFrame, str] | None:
    """东财 + 新浪 两个 akshare 源并发拉取 · 谁先返回有效数据用谁。

    串行试时慢/挂的源会拖累总延迟；并发跑 + as_completed 取第一个成功的，
    失败的被淘汰。中标源名随 (df, source) 返回，经 _normalize_kline 落到
    _source 列可回查。两源都失败返回 None，由调用方降级下一档。

    不用 `with ThreadPoolExecutor`：其 __exit__ 的 shutdown(wait=True) 会
    阻塞等所有线程，某源 hang 时整个调用挂死。改 shutdown(wait=False)，
    拿到结果即返回，慢/hang 的线程后台自生自灭，不阻塞调用方。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates = {"sina": _fetch_sina, "eastmoney": _fetch_eastmoney}
    executor = ThreadPoolExecutor(max_workers=2)
    try:
        future_to_source = {
            executor.submit(fn, symbol, start): name
            for name, fn in candidates.items()
        }
        try:
            for future in as_completed(future_to_source, timeout=15):
                name = future_to_source[future]
                try:
                    df = future.result()
                except Exception as e:
                    # 与各 _fetch_* 一致:第三方源不保异常类型 · broad catch + debug log
                    debug_log(__name__, f"fetch via akshare {name}", e)
                    continue
                if df is not None:
                    return df, name
        except TimeoutError:
            # as_completed 超时 · 双源都没及时返回 · 降级下一档
            pass
        return None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


# ══════════════════════════════════════════════════════════════════
# KlineSource Protocol 适配 · 每个 class 是 thin wrapper
# 调对应 _fetch_<source> module function (SOT) · 元数据携带 name / priority
# is_available · chain 内统一接管 fallback / race / 熔断 / debug_log
# ══════════════════════════════════════════════════════════════════


class BaostockKlineSource:
    """Baostock 独立服务器 K 线源 · priority=20 · tushare 之后 / akshare 之前。

    is_available 检查:
    - baostock 软依赖 (try import)
    - 熔断器 (baostock 不可用时 skip)
    """

    name = "baostock"
    priority = 20
    capabilities = ProviderCapabilities(
        max_concurrency=1,
        initial_concurrency=1,
        max_attempts=2,
        timeout_seconds=30,
        serializes_requests=True,
    )

    def is_available(self) -> bool:
        try:
            import baostock  # noqa: F401
        except ImportError:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return _fetch_baostock(symbol, start)

    def fetch_detailed(
        self, symbol: str, start: str, *, record_breaker: bool = True,
    ) -> ProviderFetchResult[pd.DataFrame]:
        return _fetch_baostock_detailed(symbol, start, record_breaker=record_breaker)


class EastmoneyKlineSource:
    """东方财富 (akshare.stock_zh_a_hist) K 线源 · priority=30 · 与 sina race。"""

    name = "eastmoney"
    priority = 30
    capabilities = ProviderCapabilities(
        max_concurrency=4,
        initial_concurrency=2,
        max_attempts=2,
        timeout_seconds=5,
    )

    def is_available(self) -> bool:
        try:
            import akshare  # noqa: F401
        except ImportError:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return _fetch_eastmoney(symbol, start)

    def fetch_detailed(
        self, symbol: str, start: str, *, record_breaker: bool = True,
    ) -> ProviderFetchResult[pd.DataFrame]:
        return _fetch_eastmoney_detailed(symbol, start, record_breaker=record_breaker)


class SinaKlineSource:
    """新浪 (akshare.stock_zh_a_daily) K 线源 · priority=30 · 与 eastmoney race。

    免登录 · 东财 push2his 被 ban 时最稳路径之一。
    """

    name = "sina"
    priority = 30
    capabilities = ProviderCapabilities(
        max_concurrency=4,
        initial_concurrency=2,
        max_attempts=2,
        timeout_seconds=15,
    )

    def is_available(self) -> bool:
        try:
            import akshare  # noqa: F401
        except ImportError:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return _fetch_sina(symbol, start)

    def fetch_detailed(
        self, symbol: str, start: str, *, record_breaker: bool = True,
    ) -> ProviderFetchResult[pd.DataFrame]:
        return _fetch_sina_detailed(symbol, start, record_breaker=record_breaker)


class TencentKlineSource:
    """腾讯 (akshare.stock_zh_a_hist_tx) K 线源 · priority=40 · 兜底 · volume 不可信已 drop。"""

    name = "tencent"
    priority = 40
    capabilities = ProviderCapabilities(
        max_concurrency=2,
        initial_concurrency=1,
        max_attempts=2,
        timeout_seconds=15,
    )

    def is_available(self) -> bool:
        try:
            import akshare  # noqa: F401
        except ImportError:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return _fetch_tencent(symbol, start)

    def fetch_detailed(
        self, symbol: str, start: str, *, record_breaker: bool = True,
    ) -> ProviderFetchResult[pd.DataFrame]:
        return _fetch_tencent_detailed(symbol, start, record_breaker=record_breaker)
