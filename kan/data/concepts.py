"""题材数据适配器，统一 AkShare 与公开 HTTP 返回结构。"""
from __future__ import annotations

import io
import threading
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from functools import lru_cache
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from kan.data.tushare import _normalize_symbol_to_ts

if TYPE_CHECKING:
    import pandas as pd

    from kan.core.models import Theme


_EM_CODE_LOCK = threading.Lock()
_em_code_by_name: dict[str, str] | None = None
_P = ParamSpec("_P")
_R = TypeVar("_R")


def _quiet_call(
    func: Callable[_P, _R], /, *args: _P.args, **kwargs: _P.kwargs,
) -> _R:
    """屏蔽上游 tqdm，避免后台数据加载污染终端与 JSON 输出。"""
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


def fetch_theme_catalog() -> pd.DataFrame | None:
    """读取同花顺题材清单，标准化为 code/name 两列。"""
    import akshare as ak

    raw = _quiet_call(ak.stock_board_concept_name_ths)
    if raw is None or raw.empty:
        return raw
    return raw[["code", "name"]]


def _fetch_em_theme_catalog() -> pd.DataFrame | None:
    """读取东财题材清单，供 THS 名称映射到 BK 代码。"""
    import akshare as ak

    raw = _quiet_call(ak.stock_board_concept_name_em)
    if raw is None or raw.empty:
        return raw
    return raw.rename(columns={"板块代码": "code", "板块名称": "name"})[["code", "name"]]


def _load_em_code_map() -> dict[str, str]:
    global _em_code_by_name
    if _em_code_by_name is not None:
        return _em_code_by_name
    with _EM_CODE_LOCK:
        if _em_code_by_name is None:
            catalog = _fetch_em_theme_catalog()
            if catalog is None or catalog.empty:
                raise RuntimeError("东财题材清单为空")
            _em_code_by_name = {
                str(row["name"]).strip(): str(row["code"]).strip()
                for _, row in catalog.iterrows()
                if str(row["name"]).strip() and str(row["code"]).strip()
            }
    return _em_code_by_name


def _resolve_em_code(theme: Theme) -> str:
    if theme.code.startswith("BK"):
        return theme.code
    code = _load_em_code_map().get(theme.name)
    if not code:
        raise LookupError(f"东财题材清单未找到 {theme.name}")
    return code


@lru_cache(maxsize=1)
def _ths_headers() -> dict[str, str]:
    """用 AkShare 固定版本内置脚本生成同花顺访问 Cookie。"""
    from akshare.stock_feature.stock_board_concept_ths import _get_file_content_ths
    from py_mini_racer import MiniRacer

    with MiniRacer() as racer:
        racer.eval(_get_file_content_ths("ths.js"))
        value = str(racer.call("v"))
    return {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://q.10jqka.com.cn/gn/",
        "Cookie": f"v={value}",
    }


def fetch_ths_constituents(theme: Theme) -> pd.DataFrame | None:
    """读取同花顺题材成分；新清单使用东财代码时直接交给下一数据源。"""
    if not theme.code.startswith("3"):
        return None

    import pandas as pd
    import requests
    from bs4 import BeautifulSoup

    rows: list[dict[str, str]] = []
    total_pages = 1
    headers = _ths_headers()
    for page in range(1, 6):
        if page > total_pages:
            break
        url = (
            "https://q.10jqka.com.cn/gn/detail/field/199112/order/desc/"
            f"page/{page}/ajax/1/code/{theme.code}"
        )
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        page_info = soup.find("span", {"class": "page_info"})
        if page_info and "/" in page_info.text:
            total_pages = min(5, int(page_info.text.split("/", 1)[1]))
        for tr in soup.find_all("tr")[1:]:
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue
            code = cells[1].get_text(strip=True)
            name = cells[2].get_text(strip=True)
            if code and name:
                rows.append({"stock_code": code, "short_name": name})
    return pd.DataFrame(rows, columns=["stock_code", "short_name"])


def fetch_em_constituents(theme: Theme) -> pd.DataFrame | None:
    """读取东财题材成分，标准化为 stock_code/short_name。"""
    import akshare as ak

    raw = _quiet_call(ak.stock_board_concept_cons_em, symbol=_resolve_em_code(theme))
    if raw is None or raw.empty:
        return raw
    return raw.rename(columns={"代码": "stock_code", "名称": "short_name"})[
        ["stock_code", "short_name"]
    ]


def fetch_em_kline(theme: Theme) -> pd.DataFrame | None:
    """读取东财题材日 K，标准化为 manmankan 行情列。"""
    import akshare as ak

    raw = _quiet_call(
        ak.stock_board_concept_hist_em,
        symbol=_resolve_em_code(theme),
        period="daily",
        start_date="19900101",
        end_date="20500101",
        adjust="qfq",
    )
    if raw is None or raw.empty:
        return raw
    return raw.rename(columns={
        "日期": "trade_date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    })


def fetch_stock_themes(stock_code: str) -> pd.DataFrame:
    """从东财 F10 反查个股所属题材。"""
    import pandas as pd
    import requests

    secu_code = _normalize_symbol_to_ts(stock_code)
    response = requests.get(
        "https://datacenter.eastmoney.com/securities/api/data/v1/get",
        params={
            "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
            "columns": (
                "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,NEW_BOARD_CODE,"
                "BOARD_NAME,SELECTED_BOARD_REASON,IS_PRECISE,BOARD_RANK,"
                "BOARD_YIELD,DERIVE_BOARD_CODE"
            ),
            "quoteColumns": "f3~05~NEW_BOARD_CODE~BOARD_YIELD",
            "filter": f'(SECUCODE="{secu_code}")(IS_PRECISE="1")',
            "pageNumber": "1",
            "pageSize": "50",
            "sortTypes": "1",
            "sortColumns": "BOARD_RANK",
            "source": "HSF10",
            "client": "PC",
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    data = ((payload.get("result") or {}).get("data") or []) if payload.get("success") else []
    return pd.DataFrame(
        [
            {
                "stock_code": row.get("SECURITY_CODE"),
                "concept_code": row.get("NEW_BOARD_CODE"),
                "name": row.get("BOARD_NAME"),
                "source": "东方财富",
                "reason": row.get("SELECTED_BOARD_REASON"),
            }
            for row in data
        ],
        columns=["stock_code", "concept_code", "name", "source", "reason"],
    )
