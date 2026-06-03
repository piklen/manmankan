"""TuShare Pro 数据源 · 自写轻量 HTTP client（POST JSON 协议）。

不依赖官方 tushare SDK：旧 SDK `DataApi.__init__(token, timeout)` 把端点写死
在私有 `__http_url` 属性,要替端点只能 monkey-patch
`_DataApi__http_url`。自写 client 反而更简单、无 transitive deps、风格统一。

配 token 即顶优先（替 baostock 主路径），未配 token 行为零变化。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from kan.infra.log import debug_log, redact_text

if TYPE_CHECKING:
    import pandas as pd

_SYMBOL_PATTERN = re.compile(r"^\d{6}$")

DEFAULT_ENDPOINT = "https://api.tushare.pro"
ALLOW_INSECURE_ENDPOINT_ENV = "KAN_ALLOW_INSECURE_TUSHARE"

_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class TushareApiError:
    """TuShare API 失败的结构化错误 · 让上层 caller(diagnosis 渲染)能拿到真实 server msg。

    Fields:
      code:     TuShare 业务码 (40101 token 不对 / 40203 频率超限 / 40004 积分不足 /
                负数 = 客户端层失败: -1 网络 · -2 HTTP 非 2xx · -3 response 非 JSON)
      msg:      sanitized server msg (经 redact_text 处理 · token-like pattern → ***)·
                直接给用户看是安全的
      api_name: 失败的接口名 (e.g. 'ths_daily' · 'daily' · 'ths_index')·
                让 diagnosis 渲染能精确说明"哪个接口挂了"

    设计 trade-off:
    - 老版本 _post_tushare_api 失败时 return None · 把 server msg 吞进 debug_log
    - 用户看不到具体 code (积分/频率/token 三类问题 UI 全长一样)
    - 新版本 return (data, error) tuple · caller 可选择性透传给用户
    """

    code: int
    msg: str
    api_name: str


def _make_session() -> requests.Session:
    """带连接池 + 1 次自动重试的 Session。

    架构考量:
    - 付费 token 用户主动配置 TuShare Pro 当主路径 · 期望 production 级
    - 5xx / connection reset 应给 1 次重试 · 不立即降级 baostock(免费 · 慢 · 精度低)
    - fetch_batch 12 并发 · pool_maxsize=12 防 connection-pool-is-full 警告
    - allowed_methods 含 POST(TuShare 用 POST JSON)
    - backoff_factor=0.5 · 重试间隔 0.5s · 不过分阻塞用户
    """
    s = requests.Session()
    retry = Retry(
        total=1,  # 1 次重试(总 2 次请求)· 重试太多反而拖体感
        status_forcelist=[502, 503, 504],
        allowed_methods=["POST"],
        backoff_factor=0.5,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=12)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """lazy session · 避免顶层 import 时建 connection pool。"""
    global _session
    if _session is None:
        _session = _make_session()
    return _session


def _allow_insecure_endpoint() -> bool:
    """是否允许 http:// TuShare endpoint · 仅给内网/自建无 token 镜像显式开关。"""
    return os.environ.get(ALLOW_INSECURE_ENDPOINT_ENV, "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_FIELD_MAP = {
    "trade_date": "date",
    "vol": "volume",
}


def _normalize_symbol_to_ts(symbol: str) -> str:
    """6 位代码 → TuShare ts_code 格式。

    规则：
    - 60xxxx / 68xxxx / 90xxxx → .SH（上证主板 / 科创板 / B 股）
    - 00xxxx / 30xxxx → .SZ（深证主板 / 创业板）
    - 920xxx / 83xxxx / 43xxxx / 87xxxx / 82xxxx → .BJ（北交所 · 含 2024 新启用 920 段）
    - 其他 → .SZ（防御性回退）

    北交所 920 段必须**先于** 9 开头的 .SH 判断:否则 startswith("9") 会把
    920xxx 误吞为上证（9 开头实际两类:90x 上证 B 股 .SH / 92x 北交所 .BJ）。
    """
    if not _SYMBOL_PATTERN.match(symbol):
        raise ValueError(f"必须是 6 位股票代码，实际收到: {symbol!r}")
    # 北交所先判 (920 新段 + 83/43/87/82 老段) · 防 9 开头被后面 .SH 误吞
    if symbol[:2] == "92" or symbol[:2] in ("83", "43", "87", "82"):
        return f"{symbol}.BJ"
    p = symbol[0]
    if p == "6" or symbol[:2] in ("68", "90") or symbol.startswith("9"):
        return f"{symbol}.SH"
    if p in ("0", "3"):
        return f"{symbol}.SZ"
    return f"{symbol}.SZ"


def _resolve_config() -> tuple[str | None, str]:
    """解析 token + endpoint 配置。

    优先级（高 → 低）：
      TUSHARE_TOKEN    env > config["tushare_token"]    > None
      TUSHARE_ENDPOINT env > config["tushare_endpoint"] > DEFAULT_ENDPOINT

    校验：
    - token 去首尾空白；空串 / None → 未配置
    - endpoint 必须 http(s):// 前缀；否则回退默认（不抛异常）
    """
    from kan.storage import config as _config

    cfg = _config.load()
    token_raw = os.environ.get("TUSHARE_TOKEN") or cfg.get("tushare_token")
    token = token_raw.strip() if isinstance(token_raw, str) else None
    if not token:
        token = None

    endpoint_raw = os.environ.get("TUSHARE_ENDPOINT") or cfg.get("tushare_endpoint")
    endpoint = endpoint_raw.strip() if isinstance(endpoint_raw, str) else ""
    if not endpoint.startswith(("http://", "https://")):
        endpoint = DEFAULT_ENDPOINT
    elif endpoint.startswith("http://"):
        if _allow_insecure_endpoint():
            # 自部署镜像 / 内网测试可显式 opt-in；默认仍拒绝明文传 token。
            debug_log(
                __name__,
                "endpoint 走明文 HTTP · 已由 KAN_ALLOW_INSECURE_TUSHARE 显式放行",
                RuntimeWarning(endpoint),
            )
        else:
            debug_log(
                __name__,
                "拒绝明文 HTTP TuShare endpoint · 已回退官方 HTTPS",
                RuntimeWarning(endpoint),
            )
            endpoint = DEFAULT_ENDPOINT

    return token, endpoint


def _post_tushare_api(
    endpoint: str,
    token: str,
    api_name: str,
    params: dict,
    fields: str,
) -> tuple[dict | None, TushareApiError | None]:
    """POST JSON 到 TuShare Pro API · 返回 (data, error) tuple。

    成功:   (data_dict, None)
    失败:   (None, TushareApiError) · caller 可选择透传给用户(diagnosis 渲染)

    失败分类(都填 TushareApiError):
    - code=-1: 网络异常 / DNS / 超时
    - code=-2: HTTP 非 2xx
    - code=-3: response 非 JSON
    - code>0:  TuShare 业务码 (40101 token 不对 / 40203 频率超限 / 40004 积分不足 ...)

    关键不变量:
    - token 永不进入 logs / exceptions / 返回的 error.msg
    - error.msg 已经过 redact_text 处理(防 server msg 偶尔含 token 字符串)
    """
    payload = {
        "api_name": api_name,
        "token": token,
        "params": params,
        "fields": fields,
    }
    try:
        resp = _get_session().post(endpoint, json=payload, timeout=_TIMEOUT_SECONDS)
    except Exception as e:
        # 传真 Exception · log.py 的 redact_text 会兜底处理 path / token 模式
        debug_log(__name__, "tushare POST 失败", e)
        return None, TushareApiError(
            code=-1, msg=f"网络/连接错误: {type(e).__name__}", api_name=api_name,
        )
    if resp.status_code != 200:
        debug_log(
            __name__,
            f"tushare HTTP {resp.status_code}",
            RuntimeError(f"endpoint={endpoint}"),
        )
        return None, TushareApiError(
            code=-2, msg=f"HTTP {resp.status_code} (非 2xx)", api_name=api_name,
        )
    try:
        body = resp.json()
    except ValueError:
        return None, TushareApiError(
            code=-3, msg="response 非 JSON (代理转发错? endpoint URL 错?)", api_name=api_name,
        )
    biz_code = body.get("code", -1)
    if biz_code != 0:
        raw_msg = str(body.get("msg") or "(server msg 为空)")
        # redact 防 server msg 偶尔含 token 字符串("您的 token xxx 失效" 模式)
        sanitized_msg = redact_text(raw_msg)
        debug_log(
            __name__,
            f"tushare api code={biz_code} msg={sanitized_msg}",
            RuntimeError("api refused"),
        )
        return None, TushareApiError(
            code=biz_code, msg=sanitized_msg, api_name=api_name,
        )
    return body.get("data"), None


def _to_kline_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare data 块 → DataFrame，列名映射到 manmankan KLINE 标准。"""
    import pandas as pd
    if not data:
        return None
    fields = data.get("fields") or []
    items = data.get("items") or []
    if not items:
        return None
    df = pd.DataFrame(items, columns=fields)
    df = df.rename(columns=_FIELD_MAP)
    return df


_QFQ_KLINE_FIELDS = "trade_date,open_qfq,high_qfq,low_qfq,close_qfq,vol,amount"
"""stk_factor_pro 前复权 K 线字段 · 用于 TuShare KlineSource 顶档。

daily 接口返回未复权价格,会在除权除息日前后制造位置百分位跳变;scan/fetch 的
K 线缓存必须保持前复权口径,与 baostock / akshare qfq fallback 对齐。
"""

_QFQ_FIELD_MAP = {
    "trade_date": "date",
    "open_qfq": "open",
    "high_qfq": "high",
    "low_qfq": "low",
    "close_qfq": "close",
    "vol": "volume",
}


def _to_qfq_kline_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare stk_factor_pro data 块 → manmankan KLINE 标准列 (前复权)。"""
    import pandas as pd

    if not data:
        return None
    fields = data.get("fields") or []
    items = data.get("items") or []
    if not items:
        return None
    df = pd.DataFrame(items, columns=fields)
    if "trade_date" not in df.columns:
        return None
    return df.rename(columns=_QFQ_FIELD_MAP)


def _fetch_tushare(symbol: str, start: str) -> pd.DataFrame | None:
    """TuShare Pro 前复权日 K 入口 · fetch_kline 顶优先调用。

    Args:
      symbol: 6 位股票代码
      start:  YYYYMMDD 起始日期（与 fetcher.py 其它 _fetch_* 函数一致）

    Returns:
      DataFrame（manmankan KLINE 标准列,前复权）或 None（未配 token / 熔断 / 失败）。
      失败时上游 fetch_kline 会 fallback 到 baostock → akshare → 腾讯。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None

    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare"):
        return None

    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None

    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="stk_factor_pro",
            params={"ts_code": ts_code, "start_date": start},
            fields=_QFQ_KLINE_FIELDS,
        )
        # 个股 daily 走多源 fallback chain (TuShare → baostock → akshare → 腾讯)
        # · error 已被 _post_tushare_api 写进 debug_log · 不上抛 caller
        if data is None:
            cb.record("tushare", ok=False)
            return None
        df = _to_qfq_kline_df(data)
        if df is None or df.empty:
            cb.record("tushare", ok=False)
            return None
        cb.record("tushare", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare 失败", e)
        cb.record("tushare", ok=False)
        return None


_DAILY_BARS_FIELDS = "ts_code,trade_date,open_qfq,high_qfq,low_qfq,close_qfq,vol,amount"
"""stk_factor_pro 按交易日拉全市场前复权日 K 字段 · 供 --all K 线类 filter 的批量预计算缓存。"""


def _to_daily_bars_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare stk_factor_pro(trade_date=...) data 块 → 标准日 K 截面 DataFrame。"""
    import pandas as pd

    if not data:
        return None
    fields = data.get("fields") or []
    items = data.get("items") or []
    if not items:
        return None
    df = pd.DataFrame(items, columns=fields)
    if "ts_code" not in df.columns:
        return None
    df["symbol"] = df["ts_code"].map(_strip_ts_suffix)
    df = df.drop(columns=["ts_code"]).rename(columns=_QFQ_FIELD_MAP)
    return df


def _fetch_tushare_daily_bars(trade_date: str) -> pd.DataFrame | None:
    """TuShare 前复权单日全市场日 K 截面 · `kan find --all` 时序预计算原料。

    与 `_fetch_tushare(symbol, start)` 不同:这里按 trade_date 一次拉全市场 OHLC，
    用于批量计算位置 / 涨幅 / 连阳等裸值。熔断 key 独立，避免影响逐股 K 线源。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None

    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_daily_bars"):
        return None

    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="stk_factor_pro",
            params={"trade_date": trade_date},
            fields=_DAILY_BARS_FIELDS,
        )
        if data is None:
            cb.record("tushare_daily_bars", ok=False)
            return None
        df = _to_daily_bars_df(data)
        if df is None or df.empty:
            cb.record("tushare_daily_bars", ok=False)
            return None
        cb.record("tushare_daily_bars", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare daily bars 失败", e)
        cb.record("tushare_daily_bars", ok=False)
        return None


# ══════════════════════════════════════════════════════════════════
# KlineSource Protocol 适配 (v0.0.6) · 顶档付费源 · is_available 含 token 检查
# ══════════════════════════════════════════════════════════════════


class TushareKlineSource:
    """TuShare Pro K 线源 · priority=10 · 配 token 时顶档优先。

    is_available 三重检查:
    1. token 配置 (env TUSHARE_TOKEN 或 config tushare_token) · 缺则 skip 整源
    2. 熔断器 (持续失败时 skip)
    3. requests 必须 import-able (打包必然有 · 防御性检查省略)

    与其他源不同之处: 未配 token 时 is_available 直接 False · chain 跳过 ·
    不浪费一次 fetch 调用 (fetch 内部也有 token 检查兜底 · 但 is_available 先短路)。
    """

    name = "tushare"
    priority = 10

    def is_available(self) -> bool:
        token, _ = _resolve_config()
        if not token:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(self, symbol: str, start: str) -> pd.DataFrame | None:
        return _fetch_tushare(symbol, start)


def _strip_ts_suffix(ts_code: str) -> str:
    """ts_code '600519.SH' → 6 位 '600519' (跟 manmankan symbol 标准对齐)。"""
    return str(ts_code).split(".", 1)[0]


def _to_metrics_df(data: dict | None) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.metrics`."""
    from kan.data.metrics import _to_tushare_metrics_df
    return _to_tushare_metrics_df(data)


def _fetch_tushare_metrics(
    trade_date: str, symbols: list[str] | None = None,
) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.metrics`."""
    from kan.data.metrics import _fetch_tushare_metrics as _impl
    return _impl(trade_date, symbols)


class TushareMetricsSource:
    """Compatibility shim. Use `kan.data.metrics.TushareMetricsSource`."""

    def __new__(cls):
        from kan.data.metrics import TushareMetricsSource as _Impl
        return _Impl()


# ══════════════════════════════════════════════════════════════════
# 估值历史时序 + 申万行业反查 (地基-3) · 估值分位 + 行业中位对照原料
# ══════════════════════════════════════════════════════════════════

def _fetch_tushare_metrics_history(
    symbol: str, start_date: str,
) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.metrics`."""
    from kan.data.metrics import _fetch_tushare_metrics_history as _impl
    return _impl(symbol, start_date)


def _fetch_tushare_sw_l1_members() -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.industry_map`."""
    from kan.data.industry_map import _fetch_tushare_sw_l1_members as _impl
    return _impl()


def _fetch_tushare_stock_basic_all() -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.universe`."""
    from kan.data.universe import _fetch_tushare_stock_basic_all as _impl
    return _impl()


def _fetch_tushare_fundamentals(symbol: str) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.fundamentals`."""
    from kan.data.fundamentals import _fetch_tushare_fundamentals as _impl
    return _impl(symbol)


def _fetch_tushare_holdernumber(symbol: str) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.shareholder`."""
    from kan.data.shareholder import _fetch_tushare_holdernumber as _impl
    return _impl(symbol)


def _fetch_tushare_top10float(symbol: str) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.shareholder`."""
    from kan.data.shareholder import _fetch_tushare_top10float as _impl
    return _impl(symbol)


def _fetch_tushare_moneyflow(trade_date: str) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.moneyflow`."""
    from kan.data.moneyflow import _fetch_tushare_moneyflow as _impl
    return _impl(trade_date)


def _fetch_tushare_dividend(symbol: str) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.dividend`."""
    from kan.data.dividend import _fetch_tushare_dividend as _impl
    return _impl(symbol)


def _fetch_tushare_technical(trade_date: str) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.technical`."""
    from kan.data.technical import _fetch_tushare_technical as _impl
    return _impl(trade_date)


def _fetch_tushare_sentiment(trade_date: str) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.sentiment`."""
    from kan.data.sentiment import _fetch_tushare_sentiment as _impl
    return _impl(trade_date)


def _fetch_tushare_cyq(trade_date: str) -> pd.DataFrame | None:
    """Compatibility shim. Implementation lives in `kan.data.chip`."""
    from kan.data.chip import _fetch_tushare_cyq as _impl
    return _impl(trade_date)
