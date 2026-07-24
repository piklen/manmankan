"""A 股代码-名称映射缓存、刷新与解析。"""
from __future__ import annotations

import json
import re
from datetime import datetime

from kan.core.models import Stock
from kan.infra.log import debug_log
from kan.storage import paths
from kan.storage.watchlist_json import _atomic_write_json


def _load_stock_names() -> dict[str, str]:
    """加载 A 股代码-名称映射，带本地缓存。

    主用 baostock query_stock_basic · akshare stock_info_a_code_name 作为 fallback。
    `kan add` 数字代码快路径可只读本地 cache,避免交互命令同步等待上游源。
    """
    paths.ensure_dirs()
    cached = load_stock_names_cache(allow_stale=False)
    if cached is not None:
        return cached

    mapping = _fetch_names_baostock() or _fetch_names_akshare()
    if mapping is None:
        raise RuntimeError(
            "无法获取 A 股代码表 · baostock 和 akshare 均失败 · 请检查网络"
        )
    mapping = _augment_with_universe(mapping)
    _atomic_write_json(paths.STOCK_NAMES_CACHE, mapping)
    return mapping


def _augment_with_universe(mapping: dict[str, str]) -> dict[str, str]:
    """用全市场 universe(tushare stock_basic)补 baostock 缺失的代码(北交所 920 段)。

    baostock query_stock_basic 不覆盖北交所,universe 有 920xxx 带名称 ·
    只补缺不覆盖(baostock 名称优先);universe 不可用(无 token / 网络失败)
    静默跳过,代码表退回 baostock 覆盖范围。
    """
    try:
        from kan.data.universe import fetch_all_stocks

        universe = fetch_all_stocks()
    except Exception as e:  # 增强失败不拖垮主路径
        debug_log(__name__, "universe augment for stock names", e)
        return mapping
    for item in universe:
        try:
            code, name = str(item[0]), str(item[1]).strip()
        except (TypeError, IndexError):
            continue
        if re.fullmatch(r"\d{6}", code) and name and code not in mapping:
            mapping[code] = name
    return mapping


def load_stock_names_cache(*, allow_stale: bool = False) -> dict[str, str] | None:
    """只读本地股票名称 cache · 不触发网络刷新。"""
    if not paths.STOCK_NAMES_CACHE.exists():
        return None
    if not allow_stale:
        mtime = datetime.fromtimestamp(paths.STOCK_NAMES_CACHE.stat().st_mtime)
        if (datetime.now() - mtime).days >= paths.NAMES_CACHE_MAX_AGE_DAYS:
            return None
    try:
        raw = json.loads(paths.STOCK_NAMES_CACHE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    names = {
        str(code): str(name).strip()
        for code, name in raw.items()
        if re.fullmatch(r"\d{6}", str(code)) and str(name).strip()
    }
    return names or None


def _apply_cached_names(stocks: list[Stock]) -> list[Stock]:
    """用本地 cache 修正 `name == symbol` 的占位名 · 不触发网络。"""
    names = load_stock_names_cache(allow_stale=True)
    if not names:
        return stocks
    for stock in stocks:
        name = names.get(stock.symbol)
        if name and stock.name == stock.symbol:
            stock.name = name
    return stocks


def _fetch_names_baostock() -> dict[str, str] | None:
    """baostock query_stock_basic · 主路径 · 实测 5s · 比 akshare 快 3 倍。

    返回字段: code/code_name/ipoDate/outDate/type/status
      · type='1' = 股票 (排除指数/ETF)
      · status='1' = 上市 (排除退市)
      · code 格式 'sh.600519' → 取后 6 位
    """
    try:
        import io
        import sys

        import baostock as bs

        _stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            bs.login()
        finally:
            sys.stdout = _stdout

        rs = bs.query_stock_basic()
        if rs.error_code != "0":
            return None

        mapping: dict[str, str] = {}
        while rs.next():
            row = rs.get_row_data()
            if len(row) < 6:
                continue
            code, name, _ipo, _out, type_, status = row[:6]
            if type_ != "1" or status != "1":
                continue
            short_code = code.split(".")[-1]
            if len(short_code) == 6 and short_code.isdigit():
                mapping[short_code] = name

        return mapping if mapping else None
    except Exception as e:
        # baostock fallback · user-facing warn + debug log
        debug_log(__name__, "baostock stock name fetch", e)
        from rich.console import Console

        Console(stderr=True).print(
            "[yellow]⚠️ baostock 失败 · 切换 akshare 备用源（约 16s）[/yellow]"
        )
        return None


def _fetch_names_akshare() -> dict[str, str] | None:
    """akshare stock_info_a_code_name · fallback · 实测 ~16s · baostock 失败时兜底。

    Lazy import akshare · 不在 watchlist 顶层 import：akshare 拖 pandas/numpy/bs4/requests
    整窝进启动路径，单个就占 watchlist 冷启动成本 85%（~8s 冷启动 启动反馈）。
    本函数仅在 baostock 主路径失败时调用，95%+ 的常规启动不该付这个成本。

    内部 self-suppress akshare 的 tqdm 'n/16' 误导进度条（写到 stderr）。
    不依赖 cli.py 外层重定向 stderr · 避免干扰 cli 的 spinner Live Display。
    """
    import io
    import sys

    import akshare as ak  # lazy: 见 docstring

    _real_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        df = ak.stock_info_a_code_name()
        return dict(zip(df["code"], df["name"], strict=True))
    except Exception as e:
        # akshare fallback · 静默返 None · debug log 供排查
        debug_log(__name__, "akshare stock_info_a_code_name fallback", e)
        return None
    finally:
        sys.stderr = _real_stderr


def _lookup_name(symbol: str) -> str:
    """查询股票名称，未找到则抛异常。"""
    names = _load_stock_names()
    name = names.get(symbol)
    if not name:
        raise ValueError(f"未找到股票: {symbol}（不在 A 股代码表中）")
    return name


def search_by_name(
    query: str, _names_cache: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """按名称模糊搜索股票 · 返回 [(代码, 名称), ...]"""
    names = _names_cache if _names_cache is not None else _load_stock_names()
    query = query.strip()
    if not query:
        return []
    return [(code, name) for code, name in names.items() if query in name]


def resolve_symbol_or_name(raw: str) -> tuple[str, str]:
    """6 位代码 → 精确查名;非 6 位 → 名称模糊搜.返回 (code, name).

    多匹配 / 零匹配 / 空输入抛 ValueError + 散户引导.info / compare 共用 ·
    跟 add 的内联流程一致(单匹配通过 · 多匹配列候选 · 零匹配引导).
    """
    cleaned = re.sub(r"^(sh|sz|SH|SZ)", "", raw.strip())
    if re.match(r"^\d{6}$", cleaned):
        return cleaned, _lookup_name(cleaned)
    if not cleaned:
        raise ValueError(
            "空字符串不是有效股票名 / 代码 · 例: kan info 600519 或 kan info 茅台"
        )
    matches = search_by_name(cleaned)
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        raise ValueError(
            f"未找到包含「{raw}」的股票 · 试更短关键词或用 6 位代码"
        )
    preview = "; ".join(
        f"{code} {name.replace(' ', '')}" for code, name in matches[:8]
    )
    if len(matches) > 8:
        preview += f"; …等 {len(matches)} 只"
    raise ValueError(
        f"「{raw}」匹配到 {len(matches)} 只 · 候选: {preview} · 请用代码精确指定"
    )


def preload_stock_names() -> dict[str, str]:
    """Pre-load A-share stock name mapping. Triggers HTTP fetch if cache is stale."""
    return _load_stock_names()
