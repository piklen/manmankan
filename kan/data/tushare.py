"""TuShare Pro 数据源 · 自写轻量 HTTP client（POST JSON 协议）。

不依赖官方 tushare SDK：SDK `DataApi.__init__(token, timeout)` 把端点写死
在私有 `__http_url = 'http://api.tushare.pro'` 属性,要替端点只能 monkey-patch
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
        # 自部署镜像 / 内网测试走 http 是合法选择 · 但默认必须 https
        # 这里 warn · 提醒用户明文传 token 风险(咖啡店 wifi / 透明代理 / ISP 镜像)
        debug_log(
            __name__,
            "endpoint 走明文 HTTP · token 可能被中间节点截获 · 推荐改 https",
            RuntimeWarning(endpoint),
        )

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


def _fetch_tushare(symbol: str, start: str) -> pd.DataFrame | None:
    """TuShare Pro 日 K 入口 · fetch_kline 顶优先调用。

    Args:
      symbol: 6 位股票代码
      start:  YYYYMMDD 起始日期（与 fetcher.py 其它 _fetch_* 函数一致）

    Returns:
      DataFrame（manmankan KLINE 标准列）或 None（未配 token / 熔断 / 失败）。
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
            api_name="daily",
            params={"ts_code": ts_code, "start_date": start},
            fields="trade_date,open,high,low,close,vol,amount",
        )
        # 个股 daily 走多源 fallback chain (TuShare → baostock → akshare → 腾讯)
        # · error 已被 _post_tushare_api 写进 debug_log · 不上抛 caller
        if data is None:
            cb.record("tushare", ok=False)
            return None
        df = _to_kline_df(data)
        if df is None or df.empty:
            cb.record("tushare", ok=False)
            return None
        cb.record("tushare", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare 失败", e)
        cb.record("tushare", ok=False)
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


# ══════════════════════════════════════════════════════════════════
# MetricsSource Protocol 适配 (地基-1) · 截面式市场指标 · daily_basic
# ══════════════════════════════════════════════════════════════════

_METRICS_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,volume_ratio,"
    "pe_ttm,pb,ps_ttm,dv_ttm,total_mv,circ_mv"
)
"""daily_basic 拉取字段 · 估值 (PE/PB/PS/股息率) + 量价 (换手/量比) + 市值。

分位 / 行业中位在输出层算 (地基-2/3) · 数据层只取原始指标 (compliance §6/§7)。
"""


def _strip_ts_suffix(ts_code: str) -> str:
    """ts_code '600519.SH' → 6 位 '600519' (跟 manmankan symbol 标准对齐)。"""
    return str(ts_code).split(".", 1)[0]


def _to_metrics_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare daily_basic data 块 → DataFrame · ts_code → symbol (strip 后缀)。

    不在此填 _source / 补缺列 / 数值清洗 (编排层 metrics._normalize_metrics 接管)。
    """
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
    return df.drop(columns=["ts_code"])


def _fetch_tushare_metrics(
    trade_date: str, symbols: list[str] | None = None,
) -> pd.DataFrame | None:
    """TuShare Pro daily_basic 单日截面入口 · MetricsSourceChain 顶档调用。

    截面语义:按 trade_date 一次拉全市场 (一次 HTTP) · symbols 参数忽略
    (过滤交给编排层 metrics.fetch_metrics · 全市场缓存利于复用)。

    熔断器 key 'tushare_metrics' 独立于 K 线 'tushare':daily_basic 与 daily
    是不同接口 / 频率门槛 · 一个失败不该误熔断另一个。

    Args:
      trade_date: YYYYMMDD 交易日
      symbols:    Protocol 一致性保留 · 本实现忽略 (总拉全市场)

    Returns:
      DataFrame (含 symbol 列 + 各指标) 或 None (未配 token / 熔断 / 失败)。
      失败时上游 MetricsSourceChain 会 fallback 下一档 (地基-1 暂无降级源)。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None

    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_metrics"):
        return None

    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint,
            token=token,
            api_name="daily_basic",
            params={"trade_date": trade_date},
            fields=_METRICS_FIELDS,
        )
        # error 已被 _post_tushare_api 写进 debug_log · 不上抛 caller
        if data is None:
            cb.record("tushare_metrics", ok=False)
            return None
        df = _to_metrics_df(data)
        if df is None or df.empty:
            cb.record("tushare_metrics", ok=False)
            return None
        cb.record("tushare_metrics", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare metrics 失败", e)
        cb.record("tushare_metrics", ok=False)
        return None


class TushareMetricsSource:
    """TuShare Pro 截面指标源 · priority=10 · 配 token 时顶档优先 · daily_basic。

    is_available 检查:token 配置 + 熔断器 (key 'tushare_metrics' 独立于 K 线)。
    与 TushareKlineSource 同 priority 但不同领域 / 不同熔断 key · 互不干扰
    (各领域独立 MetricsSourceChain / KlineSourceChain · priority 只在领域内比较)。
    """

    name = "tushare_metrics"
    priority = 10

    def is_available(self) -> bool:
        token, _ = _resolve_config()
        if not token:
            return False
        from kan.infra import circuit_breaker
        return not circuit_breaker.get_breaker().is_down(self.name)

    def fetch(
        self, trade_date: str, symbols: list[str] | None = None,
    ) -> pd.DataFrame | None:
        return _fetch_tushare_metrics(trade_date, symbols)


# ══════════════════════════════════════════════════════════════════
# 估值历史时序 + 申万行业反查 (地基-3) · 估值分位 + 行业中位对照原料
# ══════════════════════════════════════════════════════════════════

_HISTORY_FIELDS = "trade_date,pe_ttm,pb,ps_ttm,dv_ttm"
"""daily_basic 单股时序字段 · 估值历史分位用 (与截面正交:单股多日 vs 单日全市场)。"""


def _fetch_tushare_metrics_history(
    symbol: str, start_date: str,
) -> pd.DataFrame | None:
    """TuShare daily_basic 单股估值时序 (ts_code + start_date) · 历史分位原料 (地基-3)。

    与截面 _fetch_tushare_metrics 正交:截面=单日全市场 · 时序=单股多日。
    复用 'tushare_metrics' 熔断 key (同 daily_basic 接口 · 频率门槛一致)。

    Returns:
        DataFrame (trade_date + pe_ttm/pb/ps_ttm/dv_ttm) 或 None (未配 token / 熔断 / 失败)。
    """
    import pandas as pd

    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_metrics"):
        return None
    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="daily_basic",
            params={"ts_code": ts_code, "start_date": start_date},
            fields=_HISTORY_FIELDS,
        )
        if data is None:
            cb.record("tushare_metrics", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_metrics", ok=False)
            return None
        cb.record("tushare_metrics", ok=True)
        return pd.DataFrame(items, columns=fields)
    except Exception as e:
        debug_log(__name__, "fetch tushare metrics history 失败", e)
        cb.record("tushare_metrics", ok=False)
        return None


def _fetch_tushare_sw_l1_members() -> pd.DataFrame | None:
    """TuShare index_member_all 申万成分 · symbol → 申万一级 (地基-3 行业中位反查)。

    一次拉全市场最新成分 (is_new=Y) · 熔断 key 'tushare_sw' 独立于截面 daily_basic。

    Returns:
        DataFrame (symbol + l1_name · ts_code 已 strip) 或 None (未配 token / 熔断 / 失败)。
    """
    import pandas as pd

    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_sw"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="index_member_all",
            params={"is_new": "Y"},
            fields="l1_name,ts_code",
        )
        if data is None:
            cb.record("tushare_sw", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_sw", ok=False)
            return None
        df = pd.DataFrame(items, columns=fields)
        if "ts_code" not in df.columns or "l1_name" not in df.columns:
            cb.record("tushare_sw", ok=False)
            return None
        df["symbol"] = df["ts_code"].map(_strip_ts_suffix)
        cb.record("tushare_sw", ok=True)
        return df[["symbol", "l1_name"]]
    except Exception as e:
        debug_log(__name__, "fetch tushare sw members 失败", e)
        cb.record("tushare_sw", ok=False)
        return None


# ══════════════════════════════════════════════════════════════════
# 全市场股票列表 (地基-3) · AllStocksSet 截面池原料 · stock_basic
# ══════════════════════════════════════════════════════════════════


def _fetch_tushare_stock_basic_all() -> pd.DataFrame | None:
    """TuShare stock_basic 全市场上市股 · AllStocksSet 截面池原料 (地基-3)。

    一次拉全部 list_status=L 上市股 (symbol + name + market) · 熔断 key
    'tushare_basic' 独立于截面 daily_basic / 申万 (不同接口 / 频率门槛)。

    market 字段供 universe.fetch_all_stocks 排北交所 (真数据 920xxx 段统一
    market="北交所" · 比代码段正则稳 · 详见 universe.py)。

    Returns:
        DataFrame (含 symbol / name / market 列) 或 None (未配 token / 熔断 / 失败)。
    """
    import pandas as pd

    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_basic"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="stock_basic",
            params={"list_status": "L"},
            fields="ts_code,symbol,name,market,list_status",
        )
        if data is None:
            cb.record("tushare_basic", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_basic", ok=False)
            return None
        df = pd.DataFrame(items, columns=fields)
        if "symbol" not in df.columns or "market" not in df.columns:
            cb.record("tushare_basic", ok=False)
            return None
        cb.record("tushare_basic", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare stock_basic 失败", e)
        cb.record("tushare_basic", ok=False)
        return None


# ══════════════════════════════════════════════════════════════════
# 质量·成长 (整合-1) · fina_indicator 逐股财务指标 · ROE / 增速
# ══════════════════════════════════════════════════════════════════

_FUNDAMENTALS_FIELDS = "end_date,roe,netprofit_yoy,or_yoy"
"""fina_indicator 拉取字段 · 净资产收益率 ROE + 净利同比 + 营收同比增速 (%)。

逐股 (ts_code) 维度 · 不传 period 返回全历史报告期 · 编排层取最新一期
(fundamentals.fetch_fundamentals)。原始指标值 · 命名中性 (compliance §6/§7)。
"""


def _fetch_tushare_fundamentals(symbol: str) -> pd.DataFrame | None:
    """TuShare fina_indicator 单股财务指标 (ROE / 增速) · 逐股质量维度 (整合-1)。

    与截面 daily_basic 正交:fina_indicator 按 ts_code 拉单股全历史报告期 (无截面
    全市场拉法 · 全市场逐股代价高 · PRD §3.2)。熔断 key 'tushare_fina' 独立
    (fina_indicator 接口 / 频率门槛不同于 daily_basic)。

    Returns:
        DataFrame (end_date + roe / netprofit_yoy / or_yoy · 多报告期) 或 None
        (未配 token / 熔断 / 失败)。编排层 fetch_fundamentals 取最新一期。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_fina"):
        return None
    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="fina_indicator",
            params={"ts_code": ts_code},
            fields=_FUNDAMENTALS_FIELDS,
        )
        if data is None:
            cb.record("tushare_fina", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_fina", ok=False)
            return None
        cb.record("tushare_fina", ok=True)
        return pd.DataFrame(items, columns=fields)
    except Exception as e:
        debug_log(__name__, "fetch tushare fundamentals 失败", e)
        cb.record("tushare_fina", ok=False)
        return None


# ══════════════════════════════════════════════════════════════════
# 股东·持股结构 (整合-3) · stk_holdernumber + top10_floatholders 逐股 · 季度披露
# ══════════════════════════════════════════════════════════════════

_HOLDERNUM_FIELDS = "ann_date,end_date,holder_num"
"""stk_holdernumber 拉取字段 · 股东户数 (季度定期披露 · 同 end_date 可能多 ann_date)。

逐股 (ts_code) 维度 · 不传 period 返回全历史报告期 · 编排层 shareholder._derive_holders
去重 + 取相邻两期算环比。已披露客观事实 (compliance §7 整合-3 守则 · 裸值衍生可出)。
"""

_TOP10FLOAT_FIELDS = "end_date,holder_name,hold_ratio"
"""top10_floatholders 拉取字段 · 十大流通股东持股占流通比 + 持有人名 (季度披露)。

逐股 (ts_code · 接口 required · 无截面全市场拉法) · 不传 period 返回全历史报告期 ×
每期 ≤10 行 · 编排层取最新一期算集中度 (求和) + 北向代理 (筛"香港中央结算")。
"""


def _fetch_tushare_holdernumber(symbol: str) -> pd.DataFrame | None:
    """TuShare stk_holdernumber 单股股东户数 (季度披露 · 逐股 · 整合-3)。

    逐股 (ts_code) 全历史报告期 (无截面全市场拉法 · 全市场逐股代价高 · 同 fina_indicator)。
    熔断 key 'tushare_holdernum' 独立 (接口 / 频率门槛不同)。编排层 shareholder 去重
    (同 end_date 多 ann_date) + 取相邻两期算环比。

    Returns:
        DataFrame (ann_date / end_date / holder_num · 多报告期) 或 None
        (未配 token / 熔断 / 失败 / 无披露)。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_holdernum"):
        return None
    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="stk_holdernumber",
            params={"ts_code": ts_code},
            fields=_HOLDERNUM_FIELDS,
        )
        if data is None:
            cb.record("tushare_holdernum", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_holdernum", ok=False)
            return None
        cb.record("tushare_holdernum", ok=True)
        return pd.DataFrame(items, columns=fields)
    except Exception as e:
        debug_log(__name__, "fetch tushare holdernumber 失败", e)
        cb.record("tushare_holdernum", ok=False)
        return None


def _fetch_tushare_top10float(symbol: str) -> pd.DataFrame | None:
    """TuShare top10_floatholders 单股十大流通股东 (季度披露 · 逐股 · 整合-3)。

    逐股 (ts_code · 接口 required) 全历史报告期 × 每期 ≤10 行。熔断 key
    'tushare_top10float' 独立。编排层 shareholder._derive_top10 取最新一期算集中度
    (hold_ratio 求和) + 北向代理 (筛"香港中央结算" · hk_hold 日频 2024-08 断供后降级)。

    Returns:
        DataFrame (end_date / holder_name / hold_ratio · 多期×≤10) 或 None
        (未配 token / 熔断 / 失败 / 无披露)。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_top10float"):
        return None
    try:
        ts_code = _normalize_symbol_to_ts(symbol)
    except ValueError:
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="top10_floatholders",
            params={"ts_code": ts_code},
            fields=_TOP10FLOAT_FIELDS,
        )
        if data is None:
            cb.record("tushare_top10float", ok=False)
            return None
        fields = data.get("fields") or []
        items = data.get("items") or []
        if not items:
            cb.record("tushare_top10float", ok=False)
            return None
        cb.record("tushare_top10float", ok=True)
        return pd.DataFrame(items, columns=fields)
    except Exception as e:
        debug_log(__name__, "fetch tushare top10float 失败", e)
        cb.record("tushare_top10float", ok=False)
        return None


# ══════════════════════════════════════════════════════════════════
# 主力资金 (整合-1) · moneyflow_dc 截面 · 主力净额
# ══════════════════════════════════════════════════════════════════

_MONEYFLOW_FIELDS = "ts_code,trade_date,net_amount,buy_elg_amount,buy_lg_amount"
"""moneyflow_dc 拉取字段 · 主力净额 + 超大单 / 大单净额 (东财口径 · 单位万元)。

截面 (trade_date) 维度 · 一次拉全市场 · 数据从 20230911 起 (早期缺失)。
客观资金事实 (compliance §2 安全区 · 同 OHLCV · 裸值可出)。
"""


def _to_moneyflow_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare moneyflow_dc data 块 → DataFrame · ts_code → symbol (strip 后缀)。

    不在此填 _source / 数值清洗 (编排层 moneyflow._normalize_moneyflow 接管)。
    """
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
    return df.drop(columns=["ts_code"])


def _fetch_tushare_moneyflow(trade_date: str) -> pd.DataFrame | None:
    """TuShare moneyflow_dc 单日截面 · 主力资金净额 (整合-1)。

    截面语义:按 trade_date 一次拉全市场 (一次 HTTP · 同 daily_basic 截面廉价)。
    熔断 key 'tushare_moneyflow' 独立 (moneyflow_dc 接口 / 频率门槛不同)。
    数据从 20230911 起 · 早期交易日返回空 (编排层降级)。

    Returns:
        DataFrame (symbol + net_amount / buy_elg_amount / buy_lg_amount) 或 None
        (未配 token / 熔断 / 失败 / 早期无数据)。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_moneyflow"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="moneyflow_dc",
            params={"trade_date": trade_date},
            fields=_MONEYFLOW_FIELDS,
        )
        if data is None:
            cb.record("tushare_moneyflow", ok=False)
            return None
        df = _to_moneyflow_df(data)
        if df is None or df.empty:
            cb.record("tushare_moneyflow", ok=False)
            return None
        cb.record("tushare_moneyflow", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare moneyflow 失败", e)
        cb.record("tushare_moneyflow", ok=False)
        return None


# ══════════════════════════════════════════════════════════════════
# 技术面 (整合-2) · stk_factor_pro 截面 · MACD/KDJ/RSI/均线/BOLL (前复权)
# ══════════════════════════════════════════════════════════════════

_TECHNICAL_FIELDS = (
    "ts_code,trade_date,close_qfq,atr_qfq,"
    "macd_dif_qfq,macd_dea_qfq,macd_qfq,"
    "kdj_k_qfq,kdj_d_qfq,kdj_qfq,"
    "rsi_qfq_6,rsi_qfq_12,rsi_qfq_24,"
    "ma_qfq_5,ma_qfq_10,ma_qfq_20,ma_qfq_60,"
    "boll_upper_qfq,boll_mid_qfq,boll_lower_qfq"
)
"""stk_factor_pro 拉取字段 · 前复权 (_qfq) 技术指标。

⚠️ stk_factor_pro 默认返回上百字段 · 必须显式 fields (否则 trade_date 截面 =
全市场 ~5500 只 × 上百列 · 拉爆)。取前复权 (技术分析标准) · _to_technical_df
rename 去 _qfq 后缀成中性名。
"""

# stk_factor_pro 原始 _qfq 字段 → manmankan 中性字段名 (去复权后缀)。
# 注意:tushare kdj_qfq = J 值 (K/D 是 kdj_k_qfq / kdj_d_qfq)。
_TECHNICAL_RENAME = {
    "close_qfq": "close",
    "atr_qfq": "atr",
    "macd_dif_qfq": "macd_dif",
    "macd_dea_qfq": "macd_dea",
    "macd_qfq": "macd",
    "kdj_k_qfq": "kdj_k",
    "kdj_d_qfq": "kdj_d",
    "kdj_qfq": "kdj_j",
    "rsi_qfq_6": "rsi_6",
    "rsi_qfq_12": "rsi_12",
    "rsi_qfq_24": "rsi_24",
    "ma_qfq_5": "ma_5",
    "ma_qfq_10": "ma_10",
    "ma_qfq_20": "ma_20",
    "ma_qfq_60": "ma_60",
    "boll_upper_qfq": "boll_upper",
    "boll_mid_qfq": "boll_mid",
    "boll_lower_qfq": "boll_lower",
}


def _to_technical_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare stk_factor_pro data 块 → DataFrame · ts_code → symbol + 去 _qfq 后缀。

    不在此填 _source / 数值清洗 (编排层 technical._normalize_technical 接管)。
    """
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
    df = df.drop(columns=["ts_code"])
    return df.rename(columns=_TECHNICAL_RENAME)


def _fetch_tushare_technical(trade_date: str) -> pd.DataFrame | None:
    """TuShare stk_factor_pro 单日截面 · 技术面因子 (前复权 · 整合-2)。

    截面语义:按 trade_date 一次拉全市场 (一次 HTTP · 同 daily_basic 截面廉价)。
    熔断 key 'tushare_factor' 独立 (stk_factor_pro 接口 / 频率门槛不同)。

    Returns:
        DataFrame (symbol + macd/kdj/rsi/ma/boll 中性名) 或 None
        (未配 token / 熔断 / 失败)。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_factor"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="stk_factor_pro",
            params={"trade_date": trade_date},
            fields=_TECHNICAL_FIELDS,
        )
        if data is None:
            cb.record("tushare_factor", ok=False)
            return None
        df = _to_technical_df(data)
        if df is None or df.empty:
            cb.record("tushare_factor", ok=False)
            return None
        cb.record("tushare_factor", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare technical 失败", e)
        cb.record("tushare_factor", ok=False)
        return None


# ══════════════════════════════════════════════════════════════════
# 情绪 (整合-2) · limit_list_d 截面 · 涨跌停/连板 (稀疏事件型)
# ══════════════════════════════════════════════════════════════════

_SENTIMENT_FIELDS = "ts_code,trade_date,limit_times,open_times,limit,up_stat"
"""limit_list_d 拉取字段 · 连板天数 + 炸板次数 + 涨跌停类型 + 涨停统计。

稀疏事件型:只返回当日有涨跌停/炸板的票 (不在榜 = 未涨跌停) · 不含 ST ·
数据从 2020 起。客观市场事实 (compliance §2 安全区 · 裸值可出)。
"""


def _to_sentiment_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare limit_list_d data 块 → DataFrame · ts_code → symbol (strip 后缀)。

    不在此填 _source / 数值清洗 (编排层 sentiment._normalize_sentiment 接管)。
    """
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
    return df.drop(columns=["ts_code"])


def _fetch_tushare_sentiment(trade_date: str) -> pd.DataFrame | None:
    """TuShare limit_list_d 单日截面 · 涨跌停/连板情绪 (整合-2)。

    截面语义:按 trade_date 一次拉当日涨跌停榜 (稀疏 · 只有涨跌停票 · 截面廉价)。
    熔断 key 'tushare_limit' 独立。数据从 2020 起 · 不含 ST (接口本身不统计)。

    Returns:
        DataFrame (symbol + limit_times / open_times / limit / up_stat) 或 None
        (未配 token / 熔断 / 失败 / 当日无涨跌停)。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_limit"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="limit_list_d",
            params={"trade_date": trade_date},
            fields=_SENTIMENT_FIELDS,
        )
        if data is None:
            cb.record("tushare_limit", ok=False)
            return None
        df = _to_sentiment_df(data)
        if df is None or df.empty:
            cb.record("tushare_limit", ok=False)
            return None
        cb.record("tushare_limit", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare sentiment 失败", e)
        cb.record("tushare_limit", ok=False)
        return None


# ══════════════════════════════════════════════════════════════════
# 筹码 (整合-2) · cyq_perf 截面 · 获利盘/成本分布
# ══════════════════════════════════════════════════════════════════

_CYQ_FIELDS = "ts_code,trade_date,winner_rate,cost_5pct,cost_50pct,cost_95pct,weight_avg"
"""cyq_perf 拉取字段 · 获利盘比例 + 成本分位 + 加权平均成本。

截面 (trade_date) 维度 · 数据从 2018 起 · 单次上限 5000 条 (A股 ~5500 · 可能截断
少数票 → 该票降级 None)。客观计算值 (compliance §2/§7 · 裸值可出)。
"""


def _to_cyq_df(data: dict | None) -> pd.DataFrame | None:
    """TuShare cyq_perf data 块 → DataFrame · ts_code → symbol (strip 后缀)。

    不在此填 _source / 数值清洗 (编排层 chip._normalize_chip 接管)。
    """
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
    return df.drop(columns=["ts_code"])


def _fetch_tushare_cyq(trade_date: str) -> pd.DataFrame | None:
    """TuShare cyq_perf 单日截面 · 筹码获利盘/成本分布 (整合-2)。

    截面语义:按 trade_date 一次拉全市场 (官方支持 trade_date 截面 · 单次上限 5000)。
    熔断 key 'tushare_cyq' 独立。数据从 2018 起。

    若实测 cyq_perf 不支持 trade_date 截面 (需 ts_code) → 改逐股 (params={ts_code})
    + 编排层 chip.py 仿 fundamentals.py · 见 PRD 整合-2。

    Returns:
        DataFrame (symbol + winner_rate / cost_5pct / cost_50pct / cost_95pct /
        weight_avg) 或 None (未配 token / 熔断 / 失败)。
    """
    from kan.infra import circuit_breaker

    token, endpoint = _resolve_config()
    if not token:
        return None
    cb = circuit_breaker.get_breaker()
    if cb.is_down("tushare_cyq"):
        return None
    try:
        data, _err = _post_tushare_api(
            endpoint=endpoint, token=token, api_name="cyq_perf",
            params={"trade_date": trade_date},
            fields=_CYQ_FIELDS,
        )
        if data is None:
            cb.record("tushare_cyq", ok=False)
            return None
        df = _to_cyq_df(data)
        if df is None or df.empty:
            cb.record("tushare_cyq", ok=False)
            return None
        cb.record("tushare_cyq", ok=True)
        return df
    except Exception as e:
        debug_log(__name__, "fetch tushare cyq 失败", e)
        cb.record("tushare_cyq", ok=False)
        return None
