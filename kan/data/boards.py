"""申万行业板块数据子系统 · catalog / 模糊搜索 / 成分股 / 板块指数 K 线。

数据源:申万(akshare)单源。同花顺无成分股接口、东财被反爬封 —— 不建假 fallback,
申万失败直接抛 BoardDataUnavailableError。
冷启动规则:akshare / pandas 一律函数内延迟 import。
"""
from __future__ import annotations

import json
import time
from functools import partial
from typing import TYPE_CHECKING

from kan.core.models import Board
from kan.infra.log import debug_log
from kan.storage.paths import BOARDS_DIR, atomic_write_json, ensure_dirs

if TYPE_CHECKING:
    import pandas as pd

    from kan.core.models import Theme
    from kan.data.theme_constituents import ThemeConstituentSource
    from kan.infra.lifecycle import OperationLifecycle

_CATALOG_TTL = 24 * 3600  # 24h
_CONS_TTL = 24 * 3600

_SW_LEVEL_FUNCS = {
    1: "sw_index_first_info",
    2: "sw_index_second_info",
    3: "sw_index_third_info",
}


class BoardNotFoundError(Exception):
    """search_industry 未命中任何行业。"""


class BoardDataUnavailableError(Exception):
    """申万数据源不可用(网络/接口失败/空数据)。"""


class ThemeNotFoundError(Exception):
    """search_theme 未命中任何题材。"""


class ThemeDataUnavailableError(Exception):
    """题材数据源全部不可用。"""


def _cache_fresh(path, ttl: float) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl


# ── catalog + 搜索 ────────────────────────────────────────────────────

def load_industry_catalog(force: bool = False) -> list[Board]:
    """申万一(31)+二(131)+三(336)级合并清单 · JSON cache 24h TTL。"""
    ensure_dirs()
    cache = BOARDS_DIR / "catalog_sw.json"
    if not force and _cache_fresh(cache, _CATALOG_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [Board(**b) for b in data]
        except Exception as e:
            debug_log(__name__, f"industry catalog cache {cache.name} 损坏 · 重新拉", e)
    boards_list = _fetch_catalog()
    atomic_write_json(cache, [b.model_dump() for b in boards_list], ensure_ascii=False)
    return boards_list


def _fetch_catalog() -> list[Board]:
    import akshare as ak

    boards_list: list[Board] = []
    for level, fn_name in _SW_LEVEL_FUNCS.items():
        try:
            df = getattr(ak, fn_name)()
        except Exception as e:
            debug_log(__name__, f"申万 {fn_name} 单级拉取失败 · 用其它级兜底", e)
            continue  # 单级失败不致命 · 用其它级
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            raw_code = str(row["行业代码"])
            boards_list.append(Board(
                code=raw_code.split(".")[0],
                name=str(row["行业名称"]).strip(),
                level=level,
                size=int(row["成份个数"]),
            ))
    if not boards_list:
        raise BoardDataUnavailableError("申万行业 catalog 三级全部拉取失败")
    return boards_list


def search_industry(query: str) -> Board:
    """模糊匹配行业名或代码 → Board。未命中抛 BoardNotFoundError。

    优先级:精确代码 > 精确名 > 含匹配(二级 > 一级 > 三级)。
    空白 query("" / "   ") 直接拒绝 · 防 `q in name` 短路误匹配第一只 board。
    """
    q = query.strip()
    if not q:
        raise BoardNotFoundError(query)
    catalog = load_industry_catalog()
    code_q = q.split(".")[0]
    for b in catalog:
        if b.code == code_q:
            return b
    for b in catalog:
        if b.name == q:
            return b
    for lvl in (2, 1, 3):
        for b in catalog:
            if b.level == lvl and q in b.name:
                return b
    raise BoardNotFoundError(query)


# ── 成分股 ────────────────────────────────────────────────────────────

def get_industry_constituents(
    board: Board, force: bool = False,
) -> list[tuple[str, str]]:
    """行业成分股 (代码, 名称) 列表 · JSON cache 24h TTL。

    akshare: index_component_sw(symbol=board.code) → 证券代码 / 证券名称。
    """
    ensure_dirs()
    cache = BOARDS_DIR / f"cons_{board.code}.json"
    if not force and _cache_fresh(cache, _CONS_TTL):
        try:
            return [
                (str(c), str(n))
                for c, n in json.loads(cache.read_text(encoding="utf-8"))
            ]
        except Exception as e:
            debug_log(__name__, f"industry constituents cache {cache.name} 损坏 · 重新拉", e)
    import akshare as ak

    try:
        df = ak.index_component_sw(symbol=board.code)
    except Exception as e:
        debug_log(__name__, f"申万成分股拉取失败 {board.code}", e)
        raise BoardDataUnavailableError(f"申万成分股暂不可用: {board.code}") from e
    if df is None or df.empty:
        raise BoardDataUnavailableError(f"申万成分股为空: {board.code}")
    pairs = [
        (str(row["证券代码"]).strip(), str(row["证券名称"]).strip())
        for _, row in df.iterrows()
    ]
    atomic_write_json(cache, pairs, ensure_ascii=False)
    return pairs


# ── 板块指数 K 线 ─────────────────────────────────────────────────────

_SW_KLINE_RENAME = {
    "日期": "date", "开盘": "open", "最高": "high",
    "最低": "low", "收盘": "close", "成交量": "volume", "成交额": "amount",
}
_KLINE_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]


def _kline_cache_fresh(path) -> bool:
    """板块 K 线 cache 是否含最近交易日(复用个股的 freshness 判据)。"""
    if not path.exists():
        return False
    try:
        import pandas as pd

        last = pd.read_parquet(path, columns=["date"])["date"].iloc[-1]
        last_d = last if hasattr(last, "isoformat") else pd.Timestamp(last).date()
        from kan.core.trading_calendar import latest_trade_date

        return last_d >= latest_trade_date()
    except Exception as e:
        debug_log(__name__, "industry kline freshness check 失败 · 视为 stale", e)
        return False


def fetch_industry_kline(board: Board, force: bool = False) -> pd.DataFrame:
    """板块指数 K 线 · 归一化到与个股 K 线同 schema · parquet cache。

    akshare: index_hist_sw(symbol=board.code, period="day")。
    """
    import pandas as pd

    from kan.storage.paths import atomic_write_parquet

    ensure_dirs()
    cache = BOARDS_DIR / f"kline_{board.code}.parquet"
    if not force and _kline_cache_fresh(cache):
        return pd.read_parquet(cache)
    import akshare as ak

    try:
        raw = ak.index_hist_sw(symbol=board.code, period="day")
    except Exception as e:
        debug_log(__name__, f"申万指数 K 线拉取失败 {board.code}", e)
        raise BoardDataUnavailableError(f"申万指数 K 线暂不可用: {board.code}") from e
    if raw is None or raw.empty:
        raise BoardDataUnavailableError(f"申万指数K线为空: {board.code}")
    df = raw.rename(columns=_SW_KLINE_RENAME)
    for col in _KLINE_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[_KLINE_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = (
        df.sort_values("date")
        .dropna(subset=["date", "close"])
        .reset_index(drop=True)
    )
    atomic_write_parquet(df, cache)
    return df

# ══════════════════════════════════════════════════════════════════
# 题材(theme)数据子系统
# ══════════════════════════════════════════════════════════════════

_THEME_CATALOG_TTL = 24 * 3600
_THEME_CONS_TTL = 24 * 3600
_STOCK_THEMES_TTL = 12 * 3600  # 个股反查 TTL 更短(公司频繁变题材归属)


def _load_themes_from_cache(cache) -> list[Theme] | None:
    """题材 catalog 陈旧 cache 退化读取 · 失败返回 None(由调用方决定 raise 还是 raise from)。"""
    from kan.core.models import Theme

    if not cache.exists():
        return None
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        return [Theme(**t) for t in data]
    except Exception as e:
        debug_log(__name__, f"theme cache {cache.name} 损坏 · 视为不存在", e)
        return None


def load_theme_catalog(force: bool = False) -> list[Theme]:
    """同花顺题材 catalog · 24h JSON cache · 失败退化到陈旧 cache。

    返回 list[Theme] · 391 个题材左右(2026-05-23 spike 实测)。
    """
    from kan.core.models import Theme

    ensure_dirs()
    cache = BOARDS_DIR / "catalog_concept_ths.json"
    if not force and _cache_fresh(cache, _THEME_CATALOG_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [Theme(**t) for t in data]
        except Exception as e:
            debug_log(__name__, f"theme catalog cache {cache.name} 损坏 · 重新拉", e)

    from kan.data.concepts import fetch_theme_catalog

    try:
        df = fetch_theme_catalog()
    except Exception as e:
        # 失败时退化到陈旧 cache(若存在),否则抛
        stale = _load_themes_from_cache(cache)
        if stale is not None:
            debug_log(__name__, "load concept catalog", e)
            return stale
        debug_log(__name__, "题材清单首次拉取失败", e)
        raise ThemeDataUnavailableError("题材清单暂不可用 · 请稍后重试") from e

    if df is None or df.empty:
        stale = _load_themes_from_cache(cache)
        if stale is not None:
            return stale
        raise ThemeDataUnavailableError("题材清单返回空数据")

    themes = [
        Theme(
            code=str(row["code"]).strip(),
            name=str(row["name"]).strip(),
            source="ths",
            size=None,
        )
        for _, row in df.iterrows()
    ]
    atomic_write_json(cache, [t.model_dump() for t in themes], ensure_ascii=False)
    return themes


def normalize_theme_name(name: str) -> str:
    """规范化题材名 · 去全角半角空格 · alias 表后续累积。

    THS 'AI应用' / 'AI 应用' / 'AI　应用' → 'AI应用'。
    EM 'AI应用' / THS 'AI应用' → 同字串(本期不做跨源 alias)。
    """
    return name.replace(" ", "").replace("　", "").strip()


def search_theme(query: str) -> Theme:
    """模糊匹配题材名或代码 → Theme · 未命中抛 ThemeNotFoundError。

    优先级:精确代码 > 精确名(normalize) > 含匹配(normalize)。
    空白 query 直接拒绝 · 同 search_industry 防 `in name` 短路误匹配。
    """
    q = query.strip()
    if not q:
        raise ThemeNotFoundError(query)
    q_norm = normalize_theme_name(q)
    catalog = load_theme_catalog()
    for t in catalog:
        if t.code == q:
            return t
    for t in catalog:
        if normalize_theme_name(t.name) == q_norm:
            return t
    for t in catalog:
        if q_norm in normalize_theme_name(t.name):
            return t
    raise ThemeNotFoundError(query)


def _theme_constituent_cache(theme: Theme):
    """返回与单题材旧路径一致的成分股 cache 文件。"""
    src_prefix = "THS" if theme.source == "ths" else "EM"
    return BOARDS_DIR / f"cons_{src_prefix}{theme.code}.json"


def _read_theme_constituent_cache(theme: Theme, *, force: bool) -> list[tuple[str, str]] | None:
    """读取仍在 TTL 内的题材成分股 cache；损坏时回源。"""
    if force:
        return None
    cache = _theme_constituent_cache(theme)
    if not _cache_fresh(cache, _THEME_CONS_TTL):
        return None
    try:
        return [
            (str(code), str(name))
            for code, name in json.loads(cache.read_text(encoding="utf-8"))
        ]
    except Exception as exc:
        debug_log(__name__, f"theme constituents cache {cache.name} 损坏 · 重新拉", exc)
        return None


def get_theme_constituents(theme, force: bool = False) -> list[tuple[str, str]]:
    """题材成分股 (代码, 名称) 列表 · 走 ThemeConstituentSourceChain。

    chain 内置 2 源 (THS priority=10 → EM priority=20 with em_push2_concept 5min 熔断):
    - ThsConstituentSource · 同花顺公开页面 · 兼容旧 THS cache
    - EmConstituentSource  · AkShare 东财题材成分 · 默认路径

    JSON cache 24h · cache key 按 src_prefix (THS vs EM) 区分 ·
    避免两源成分股结果互相覆盖。

    用户可通过 kan.api.register_theme_constituent_source 加自定义源。
    """
    from kan.data.theme_constituents import default_theme_constituent_chain

    ensure_dirs()
    cache = _theme_constituent_cache(theme)
    cached = _read_theme_constituent_cache(theme, force=force)
    if cached is not None:
        return cached

    result = default_theme_constituent_chain().fetch(theme)
    if result is None:
        # chain 全失败 · inspect 熔断器决定 error 文案 (保留旧版语义)
        from kan.infra.circuit_breaker import get_breaker
        if get_breaker().is_down("em_push2_concept"):
            raise ThemeDataUnavailableError(
                f"题材成分股 {theme.code} 不可用 · THS 失败 · EM push2 在 5min 熔断冷却中"
            )
        raise ThemeDataUnavailableError(
            f"题材成分股 {theme.code} 不可用 · 全源失败"
        )

    pairs, _source_name = result
    atomic_write_json(cache, pairs, ensure_ascii=False)
    return pairs


def _theme_source_capabilities(source: ThemeConstituentSource):
    """读取 source 自声明能力；自定义源缺省使用保守并发。"""
    from kan.data.provider_contracts import ProviderCapabilities

    declared = getattr(source, "capabilities", None)
    if isinstance(declared, ProviderCapabilities):
        return declared
    return ProviderCapabilities(max_concurrency=4, initial_concurrency=2, max_attempts=1)


def _fetch_theme_constituent_source(source: ThemeConstituentSource, theme: Theme):
    """把旧 source 的 None 契约适配为通用 provider result。"""
    from kan.data.provider_contracts import (
        FetchFailure,
        FetchFailureKind,
        ProviderFetchResult,
    )

    pairs = source.fetch(theme)
    if pairs is None:
        return ProviderFetchResult.failed(FetchFailure(
            FetchFailureKind.EMPTY,
            message=f"{source.name} returned no constituents",
        ))
    return ProviderFetchResult.succeeded(pairs)


def _theme_source_groups(
    sources: list[ThemeConstituentSource],
) -> list[list[ThemeConstituentSource]]:
    """按 priority 分组，保留同档 race、跨档 fallback 语义。"""
    groups: list[list[ThemeConstituentSource]] = []
    for source in sources:
        if not groups or groups[-1][0].priority != source.priority:
            groups.append([source])
        else:
            groups[-1].append(source)
    return groups


def get_theme_constituents_batch(
    themes: list[Theme],
    *,
    force: bool = False,
    max_workers: int | None = None,
    lifecycle: OperationLifecycle | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """批量拉题材成分股：cache → provider priority groups → fallback。"""
    from kan.data.provider_batch import ProviderJob, run_provider_jobs
    from kan.data.provider_contracts import FetchFailure
    from kan.data.theme_constituents import default_theme_constituent_chain

    ensure_dirs()
    unique = list({theme.code: theme for theme in themes}.values())
    out: dict[str, list[tuple[str, str]]] = {}
    unresolved: dict[str, Theme] = {}
    for theme in unique:
        cached = _read_theme_constituent_cache(theme, force=force)
        if cached is None:
            unresolved[theme.code] = theme
        else:
            out[theme.code] = cached
    if not unresolved:
        return out

    if lifecycle is not None:
        lifecycle.phase(
            "拉取题材成分股",
            total=len(unique),
            cached=len(out),
            pending=len(unresolved),
        )

    groups = _theme_source_groups(default_theme_constituent_chain().sources)
    for group_index, group in enumerate(groups):
        available: list[ThemeConstituentSource] = []
        for source in group:
            try:
                if source.is_available():
                    available.append(source)
            except Exception as exc:
                debug_log(__name__, f"is_available {source.name}", exc)
        if not available:
            continue

        pending = list(unresolved.values())
        if not pending:
            break
        provider_names = ",".join(source.name for source in available)
        if lifecycle is not None:
            lifecycle.phase(
                "尝试题材成分股 provider",
                providers=provider_names,
                pending=len(pending),
            )

        metadata: dict[str, tuple[Theme, str]] = {}
        jobs = []
        for source_index, source in enumerate(available):
            capabilities = _theme_source_capabilities(source)
            for theme in pending:
                key = f"{group_index}:{source_index}:{theme.code}"
                metadata[key] = (theme, source.name)
                jobs.append(ProviderJob(
                    key=key,
                    provider=source.name,
                    call=partial(_fetch_theme_constituent_source, source, theme),
                    capabilities=capabilities,
                ))

        failures = 0

        def on_result(result, completed: int, total: int) -> None:
            nonlocal failures
            if result.result.failure is not None:
                failures += 1
            if lifecycle is not None:
                lifecycle.progress(
                    completed,
                    total,
                    "拉取题材成分股",
                    provider=result.provider,
                    resolved=len(out),
                    failure_count=failures,
                )

        def on_wait(provider: str, failure: FetchFailure, attempt: int) -> None:
            if lifecycle is not None:
                lifecycle.wait(
                    "题材成分股 provider 退避重试",
                    provider=provider,
                    reason=failure.kind.value,
                    attempt=attempt,
                    retry_after=failure.retry_after or 0.0,
                )

        def report_heartbeat(active: int, queued: int) -> None:
            if lifecycle is not None:
                lifecycle.heartbeat(active_calls=active, queued=queued)

        results = run_provider_jobs(
            jobs,
            max_workers=max_workers,
            on_result=on_result,
            on_wait=on_wait,
            heartbeat=report_heartbeat if lifecycle is not None else None,
        )
        for key, job_result in results.items():
            pairs = job_result.result.data
            if pairs is None:
                continue
            theme, _provider = metadata[key]
            if theme.code not in unresolved:
                continue
            atomic_write_json(_theme_constituent_cache(theme), pairs, ensure_ascii=False)
            out[theme.code] = pairs
            unresolved.pop(theme.code, None)

        if unresolved and lifecycle is not None:
            lifecycle.wait(
                "切换题材成分股备用 provider",
                attempted=provider_names,
                unresolved=len(unresolved),
            )

    if unresolved and lifecycle is not None:
        lifecycle.degraded(
            "部分题材成分股不可用",
            failure_count=len(unresolved),
            total=len(unique),
        )
    return out


# ── 题材指数 K 线 ──────────────────────────────────────────────────────────

_EM_KLINE_RENAME = {
    "trade_date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
}


def fetch_theme_kline(theme: Theme, force: bool = False) -> pd.DataFrame:
    """题材指数 K 线 · AkShare 东财源 · parquet cache。

    AkShare stock_board_concept_hist_em 返回 11 列 →
    rename 成 manmankan 标准 7 列(同个股 K · 同 _KLINE_COLUMNS)。

    不调用 THS V8 接口，避免把 JavaScript 运行库带入题材路径。
    """
    import pandas as pd

    from kan.storage.paths import atomic_write_parquet

    ensure_dirs()
    src_prefix = "EM"  # K 线统一走 EM(见 docstring)
    cache = BOARDS_DIR / f"kline_{src_prefix}{theme.code}.parquet"
    if not force and _kline_cache_fresh(cache):
        return pd.read_parquet(cache)

    from kan.data.concepts import fetch_em_kline

    try:
        raw = fetch_em_kline(theme)
    except Exception as e:
        debug_log(__name__, f"题材指数 K 线拉取失败 {theme.code}", e)
        raise ThemeDataUnavailableError(f"题材指数 K 线暂不可用: {theme.code}") from e

    if raw is None or raw.empty:
        raise ThemeDataUnavailableError(f"题材指数 K 线为空: {theme.code}")

    df = raw.rename(columns=_EM_KLINE_RENAME)
    for col in _KLINE_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    df = df[_KLINE_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = (
        df.sort_values("date")
        .dropna(subset=["date", "close"])
        .reset_index(drop=True)
    )
    atomic_write_parquet(df, cache)
    return df


def get_themes_of_stock(stock_code: str, force: bool = False) -> list[Theme]:
    """股票反查所属题材 · EM datacenter HTTP · 12h JSON cache。

    内部适配器返回 5 列:
    stock_code / concept_code / name / source / reason → list[Theme(source='em')]。

    返回空列表表示无任何题材归属(不抛)。
    """
    from kan.core.models import Theme

    ensure_dirs()
    cache = BOARDS_DIR / f"stock_themes_{stock_code}.json"
    if not force and _cache_fresh(cache, _STOCK_THEMES_TTL):
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return [Theme(**t) for t in data]
        except Exception:
            pass

    from kan.data.concepts import fetch_stock_themes

    try:
        df = fetch_stock_themes(stock_code)
    except Exception:
        return []

    if df is None or df.empty:
        atomic_write_json(cache, [], ensure_ascii=False)
        return []

    themes = [
        Theme(
            code=str(row["concept_code"]).strip(),
            name=str(row["name"]).strip(),
            source="em",
            size=None,
        )
        for _, row in df.iterrows()
    ]
    atomic_write_json(cache, [t.model_dump() for t in themes], ensure_ascii=False)
    return themes
