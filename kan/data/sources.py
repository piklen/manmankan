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


# ── 数据源 1: 东方财富（最快 · 单次 HTTP） ───────────────────────────

def _fetch_eastmoney(symbol: str, start: str) -> pd.DataFrame | None:
    cb = circuit_breaker.get_breaker()
    if cb.is_down("eastmoney"):
        return None
    try:
        import akshare as ak

        raw = ak.stock_zh_a_hist(
            symbol=symbol, period="daily", adjust="qfq",
            start_date=start, timeout=5,
        )
        cb.record("eastmoney", ok=True)
        if raw is None or raw.empty or "日期" not in raw.columns:
            return None
        return raw.rename(columns=_EM_COLUMN_MAP)
    except Exception as e:
        # broad catch 是 legitimate (akshare 第三方不保 exception type) ·
        # 但加 debug log · 用户开 KAN_DEBUG=1 可见诊断 · 排查 fallback 触发原因
        debug_log(__name__, "fetch eastmoney", e)
        cb.record("eastmoney", ok=False)
        return None


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
        bs.login()
    finally:
        sys.stdout = _stdout
    _bs_logged_in = True


def _fetch_baostock(symbol: str, start: str) -> pd.DataFrame | None:
    try:
        import baostock as bs
        import pandas as pd
    except ImportError:
        return None

    cb = circuit_breaker.get_breaker()
    if cb.is_down("baostock"):
        return None

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
            if rs.error_code != "0":
                cb.record("baostock", ok=True)
                return None
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
        except Exception as e:
            # baostock 第三方 · broad catch + debug log
            debug_log(__name__, "fetch baostock", e)
            cb.record("baostock", ok=False)
            return None

    cb.record("baostock", ok=True)
    if not rows:
        return None

    return pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "volume", "amount"],
    )


# ── 数据源 3: 新浪财经（akshare stock_zh_a_daily · 免登录 · 数值精度高） ──

def _fetch_sina(symbol: str, start: str) -> pd.DataFrame | None:
    """新浪财经历史日 K · akshare 官方 fallback。

    返回 schema: date/open/high/low/close/volume/amount/outstanding_share/turnover
    其中 volume 单位「股」、amount 单位「元」，跟 baostock 完全对齐（实测）。
    免登录；东财 push2his 被 ban 时最稳的路径之一。
    """
    import io
    import sys

    import akshare as ak

    cb = circuit_breaker.get_breaker()
    if cb.is_down("sina"):
        return None

    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    end = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")

    _real_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        raw = ak.stock_zh_a_daily(
            symbol=f"{prefix}{symbol}",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
    except Exception as e:
        # 新浪 akshare · broad catch + debug log
        debug_log(__name__, "fetch sina", e)
        cb.record("sina", ok=False)
        return None
    finally:
        sys.stderr = _real_stderr

    cb.record("sina", ok=True)
    if raw is None or raw.empty:
        return None
    return raw


# ── 数据源 4: 腾讯证券（备用 · 按年分片 · 价格可信 · 量额不可信） ────

def _fetch_tencent(symbol: str, start: str) -> pd.DataFrame | None:
    """腾讯 K 线 fallback。

    akshare.stock_zh_a_hist_tx 返回 6 列：date/open/close/high/low/amount。
    其中 "amount" 字段语义在不同板块不一致（实测 2026-05-08）：
      - 主板/创业板：amount 实际是「成交手数」(volume / 100)
      - 科创板（688/689）：amount 实际是「成交股数」(等于 volume)
    既然语义不可移植，我们**保守只取价格列**（date/open/high/low/close），
    丢弃 amount，让 _normalize_kline 把 volume/amount 都填 NaN。
    下游看到 NaN 会跳过相关计算（成交量异动相关），比错值安全。
    """
    import io
    import sys

    import akshare as ak

    cb = circuit_breaker.get_breaker()
    if cb.is_down("tencent"):
        return None

    _real_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        raw = ak.stock_zh_a_hist_tx(
            symbol=_market_prefix(symbol),
            start_date=start,
            adjust="qfq",
            timeout=15,
        )
    except Exception as e:
        # 腾讯 akshare · broad catch + debug log
        debug_log(__name__, "fetch tencent", e)
        cb.record("tencent", ok=False)
        return None
    finally:
        sys.stderr = _real_stderr

    cb.record("tencent", ok=True)
    if raw is None or raw.empty:
        return None

    if "amount" in raw.columns:
        raw = raw.drop(columns=["amount"])
    return raw


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

    def is_available(self) -> bool:
        try:
            import baostock  # noqa: F401
        except ImportError:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return _fetch_baostock(symbol, start)


class EastmoneyKlineSource:
    """东方财富 (akshare.stock_zh_a_hist) K 线源 · priority=30 · 与 sina race。"""

    name = "eastmoney"
    priority = 30

    def is_available(self) -> bool:
        try:
            import akshare  # noqa: F401
        except ImportError:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return _fetch_eastmoney(symbol, start)


class SinaKlineSource:
    """新浪 (akshare.stock_zh_a_daily) K 线源 · priority=30 · 与 eastmoney race。

    免登录 · 东财 push2his 被 ban 时最稳路径之一。
    """

    name = "sina"
    priority = 30

    def is_available(self) -> bool:
        try:
            import akshare  # noqa: F401
        except ImportError:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return _fetch_sina(symbol, start)


class TencentKlineSource:
    """腾讯 (akshare.stock_zh_a_hist_tx) K 线源 · priority=40 · 兜底 · volume 不可信已 drop。"""

    name = "tencent"
    priority = 40

    def is_available(self) -> bool:
        try:
            import akshare  # noqa: F401
        except ImportError:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return _fetch_tencent(symbol, start)
