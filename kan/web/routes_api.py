"""Web JSON API 路由。"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from kan.cli.helpers import _parse_codes
from kan.core.models import Stock
from kan.core.pipeline import StockSetResolveError
from kan.core.scanner_snapshot import (
    load_previous_web_daily_snapshot,
    save_web_daily_snapshot,
)
from kan.core.stock_set import from_flags
from kan.service.daily_service import build_daily_overview
from kan.service.history_service import HistoryRequest, HistoryServiceError, get_symbol_history
from kan.service.hold_service import build_hold_summary
from kan.service.index_service import IndexRequest, get_index_reference
from kan.service.info_service import (
    InfoDataUnavailableError,
    InfoFetchError,
    InfoRequest,
    InfoServiceResult,
    enrich_info_results_best_effort,
    get_stock_info,
)
from kan.service.scan_service import ScanRequest, run_scan
from kan.storage import config, positions, watchlist
from kan.storage.watchlist_store import watchlist_lock
from kan.web.fetch_jobs import get_fetch_job, iter_sse, start_fetch_job
from kan.web.find_adapter import run_web_find
from kan.web.security import host_allowed
from kan.web.serialize import (
    empty_hold_payload,
    serialize_daily_overview,
    serialize_history,
    serialize_hold,
    serialize_index,
    serialize_info,
    serialize_scan,
)

router = APIRouter(prefix="/api")
_COMPARE_MIN = 2
_COMPARE_MAX = 5


def default_scan_payload() -> dict:
    """默认池 scan · 只读本地缓存。"""
    try:
        result = run_scan(ScanRequest(
            stock_set=from_flags(),
            periods=[30, 60, 180],
            show_progress=False,
            allow_auto_fetch=False,
            include_external_context=False,
        ))
    except StockSetResolveError as e:
        raise HTTPException(status_code=400, detail=e.message) from e
    freshness = result.ctx.freshness
    comparison = (
        load_previous_web_daily_snapshot(freshness.data_cutoff)
        if freshness.data_cutoff and not freshness.is_stale else None
    )
    comparison_date = comparison[0] if comparison else None
    previous_snapshot = comparison[1] if comparison else None
    overview = build_daily_overview(
        result,
        previous_snapshot=previous_snapshot,
        comparison_date=comparison_date,
    )
    payload = serialize_scan(result)
    payload["overview"] = serialize_daily_overview(overview)
    # 为每行添加 180 日位置变化（对比上一份快照）
    if previous_snapshot:
        for row in payload.get("rows", []):
            prev = previous_snapshot.get(row["code"], {})
            prev_period = prev.get("180")
            prev_180 = prev_period.get("pct") if isinstance(prev_period, dict) else None
            cur_180 = row.get("p180_pct")
            if prev_180 is not None and cur_180 is not None:
                row["p180_change"] = round(cur_180 - prev_180, 1)
            else:
                row["p180_change"] = None
    if freshness.data_cutoff and not freshness.is_stale:
        try:
            save_web_daily_snapshot(
                result.all_results,
                data_cutoff=freshness.data_cutoff,
            )
        except OSError as e:
            from kan.infra.log import debug_log

            debug_log(__name__, "web daily snapshot unavailable", e)
    payload["pool_trend"] = _pool_trend_payload()
    return payload


def _pool_trend_payload(*, period: int = 180, max_days: int = 10) -> dict | None:
    """首页池级位置趋势卡 · 读每日快照聚合 · 任何异常 → None(卡片隐藏,不拖垮首页)。

    days 按旧→新排列 · direction 用词与 CLI history --pool 一致(纯状态描述)。
    """
    try:
        from kan.core.scanner_history import load_pool_history
        from kan.infra.formatting import format_date_compact

        entries = load_pool_history(period)
    except Exception as e:  # 可选卡片 fail-open
        from kan.infra.log import debug_log

        debug_log(__name__, "pool trend card unavailable", e)
        return None
    if len(entries) < 2:
        return None
    days: list[dict[str, Any]] = [
        {
            "date": format_date_compact(e.snapshot_date),
            "median": round(e.median_pct, 1),
            "low": e.low_count,
            "high": e.high_count,
            "count": e.stock_count,
        }
        for e in reversed(entries[-max_days:])
    ]
    trend_text = " → ".join(f"{d['median']:.0f}%" for d in days)
    first, last = days[0]["median"], days[-1]["median"]
    if last < first - 5:
        direction = "整体下行"
    elif last > first + 5:
        direction = "整体上行"
    else:
        direction = "横盘整理"
    return {
        "period": period,
        "days": days,
        "trend_text": trend_text,
        "direction": direction,
    }


@router.get("/search")
def search_stocks(q: str = Query("", min_length=1, max_length=20)) -> dict:
    """全局搜索：支持代码前缀和名称模糊匹配。"""
    from kan.storage.watchlist_names import load_stock_names_cache

    query = q.strip()
    if not query:
        return {"ok": True, "results": []}
    names = load_stock_names_cache(allow_stale=True)
    if not names:
        return {"ok": True, "results": []}
    results: list[dict[str, str]] = []
    # 代码前缀匹配优先
    if query.isdigit():
        for code, name in names.items():
            if code.startswith(query):
                results.append({"code": code, "name": name})
                if len(results) >= 10:
                    break
    # 名称包含匹配
    if len(results) < 10:
        for code, name in names.items():
            if query in name and not any(r["code"] == code for r in results):
                results.append({"code": code, "name": name})
                if len(results) >= 10:
                    break
    return {"ok": True, "results": results}


@router.get("/scan")
def scan() -> dict:
    return default_scan_payload()


@router.post("/find")
def find(payload: Annotated[dict[str, Any], Body()]) -> dict:
    return run_web_find(payload)


@router.post("/watchlist")
def add_watchlist(payload: Annotated[dict[str, Any], Body()]) -> dict:
    raw = payload.get("codes")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="请填写股票代码")
    tokens = [part for part in raw.replace(",", " ").replace("，", " ").split() if part]
    if not tokens:
        raise HTTPException(status_code=400, detail="请填写股票代码")
    if any(len(token) != 6 or not token.isdigit() for token in tokens):
        raise HTTPException(
            status_code=400,
            detail="请输入 6 位股票代码，例如 600519；多个代码用空格分隔",
        )
    try:
        symbols = [watchlist._normalize_symbol(token) for token in tokens]
        repeated = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
        if repeated:
            raise ValueError(f"重复代码: {', '.join(repeated)}")
        # 锁包住 load→mutate→save 整段:防 web 多 tab / web 与 CLI 并发写丢更新。
        with watchlist_lock():
            gw = watchlist.load_grouped_watchlist()
            target = gw.default
            if target not in gw.groups:
                raise watchlist.GroupNotFoundError(
                    f"组「{target}」不存在 · 跑 `kan group create {target}` 新建"
                )
            existing = {stock.symbol for stock in gw.groups[target]}
            duplicates = [symbol for symbol in symbols if symbol in existing]
            if duplicates:
                raise ValueError(f"代码已在自选列表中: {', '.join(duplicates)}")
            cached_names = watchlist.load_stock_names_cache(allow_stale=True) or {}
            names = {symbol: cached_names.get(symbol, symbol) for symbol in symbols}
            for symbol in symbols:
                gw.groups[target].append(Stock(
                    symbol=symbol,
                    name=names[symbol],
                    added_at=date.today(),
                ))
            watchlist._save_grouped_watchlist(gw)
            messages = [
                f"✅ 已添加 {names[symbol]} ({symbol})"
                if names[symbol] != symbol
                else f"✅ 已添加 {symbol}（名称加载中）"
                for symbol in symbols
            ]
    except (ValueError, watchlist.GroupNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "messages": messages}


@router.delete("/watchlist/{code}")
def remove_watchlist(code: str) -> dict:
    try:
        removed, msg = watchlist.remove(code)
    except (ValueError, watchlist.GroupNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    status = 200 if removed else 404
    if not removed:
        raise HTTPException(status_code=status, detail=msg)
    return {"ok": True, "message": msg}


@router.get("/watchlist/groups")
def watchlist_groups() -> dict:
    """获取自选股分组列表。"""
    try:
        gw = watchlist.load_grouped_watchlist()
        groups = []
        for name, stocks in gw.groups.items():
            groups.append({
                "name": name,
                "count": len(stocks),
                "is_default": name == gw.default,
            })
        return {"ok": True, "groups": groups, "default": gw.default}
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "watchlist groups unavailable", e)
        return {"ok": False, "groups": [], "default": "自选"}


@router.post("/fetch")
def fetch() -> dict:
    job = start_fetch_job()
    return {"ok": True, "job": job.id, "status": job.status}


@router.get("/fetch/events")
def fetch_events(request: Request, job: str = Query(..., min_length=1)) -> StreamingResponse:
    if not host_allowed(request.headers.get("host")):
        raise HTTPException(status_code=403, detail="host not allowed")
    fetch_job = get_fetch_job(job)
    if fetch_job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return StreamingResponse(
        iter_sse(fetch_job),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/info/{code}")
def info(code: str) -> dict:
    try:
        result = get_stock_info(InfoRequest(
            symbol_or_name=code,
            allow_fetch=False,
            include_external_context=False,
            include_valuation_context=False,
            include_board_context=False,
        ))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InfoDataUnavailableError as e:
        raise HTTPException(status_code=404, detail="本地缓存没有该股票数据") from e
    return serialize_info(result)


@router.post("/info/{code}/refresh")
def refresh_info(code: str) -> dict:
    """为对比等显式交互补单股 K 线；只写本地缓存，不改自选。"""
    try:
        result = get_stock_info(InfoRequest(
            symbol_or_name=code,
            allow_fetch=True,
            include_external_context=False,
            include_valuation_context=False,
            include_board_context=False,
        ))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InfoFetchError as e:
        raise HTTPException(
            status_code=502,
            detail=f"{e.symbol} 行情更新失败，请检查网络后重试",
        ) from e
    except InfoDataUnavailableError as e:
        raise HTTPException(status_code=404, detail="更新后仍没有该股票行情") from e
    return serialize_info(result)


@router.post("/compare")
def compare_stocks(payload: Annotated[dict[str, Any], Body()]) -> dict:
    """批量读取 2-5 只股票，并只拉一次估值/资金流截面。"""
    raw_codes = payload.get("codes")
    if not isinstance(raw_codes, list):
        raise HTTPException(status_code=400, detail="请提交 2-5 个股票代码")
    if not (_COMPARE_MIN <= len(raw_codes) <= _COMPARE_MAX):
        raise HTTPException(status_code=400, detail="请选择 2-5 只股票进行对比")
    codes: list[str] = []
    for raw_code in raw_codes:
        normalized, invalid = _parse_codes(str(raw_code).strip())
        if invalid or len(normalized) != 1:
            raise HTTPException(status_code=400, detail="请输入有效的 6 位股票代码")
        codes.append(normalized[0])
    if len(set(codes)) != len(codes):
        raise HTTPException(status_code=400, detail="请删除重复的股票代码")

    results: list[InfoServiceResult] = []
    errors: list[dict[str, str]] = []
    for code in codes:
        request = InfoRequest(
            symbol_or_name=code,
            allow_fetch=False,
            include_external_context=False,
            include_valuation_context=False,
            include_board_context=False,
        )
        try:
            result = get_stock_info(request)
        except InfoDataUnavailableError:
            try:
                result = get_stock_info(replace(request, allow_fetch=True))
            except (ValueError, InfoDataUnavailableError, InfoFetchError):
                errors.append({"code": code, "message": "行情加载失败"})
                continue
        except (ValueError, InfoFetchError):
            errors.append({"code": code, "message": "股票代码或行情不可用"})
            continue
        results.append(result)

    results = enrich_info_results_best_effort(results)
    return {
        "ok": True,
        "stocks": [serialize_info(result) for result in results],
        "errors": errors,
    }


@router.get("/history/{code}")
def history(
    code: str,
    # 不在 Query 层夹 ge/le:交给 service 的 MIN_PERIOD/MAX_PERIOD 校验,
    # 让 web 与 CLI 的越界报错文案一致(带范围 hint),而非 FastAPI 通用 422。
    period: int = Query(60),
) -> dict:
    try:
        result = get_symbol_history(HistoryRequest(symbol_or_name=code, period=period))
    except HistoryServiceError as e:
        if e.code in {"history_unavailable", "history_not_found"}:
            return {
                "ok": True,
                "code": code,
                "name": code,
                "period": period,
                "series": [],
                "stats": {"shown": 0},
                "message": e.message,
            }
        status = 400 if e.exit_code == 2 else 404
        detail = f"{e.message} · {e.hint}" if e.hint else e.message
        raise HTTPException(status_code=status, detail=detail) from e
    return serialize_history(result)


@router.get("/kline/{code}")
def kline(code: str, days: int = Query(120, ge=30, le=360)) -> dict:
    """K 线数据：返回 OHLC + 成交量，用于绘制 K 线图。"""
    import re

    from kan.data.fetcher import get_cached

    cleaned = re.sub(r"^(sh|sz|SH|SZ)", "", code.strip())
    if not re.match(r"^\d{6}$", cleaned):
        raise HTTPException(status_code=400, detail="请输入 6 位股票代码")
    df = get_cached(cleaned)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail="本地没有该股票的 K 线缓存，请先更新数据")
    # 取最近 N 天
    df = df.tail(days)
    rows = []
    for _, row in df.iterrows():
        d = row["date"]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        rows.append({
            "date": date_str,
            "open": round(float(row["open"]), 2) if row["open"] == row["open"] else None,
            "high": round(float(row["high"]), 2) if row["high"] == row["high"] else None,
            "low": round(float(row["low"]), 2) if row["low"] == row["low"] else None,
            "close": round(float(row["close"]), 2) if row["close"] == row["close"] else None,
            "volume": int(row["volume"]) if row.get("volume") == row.get("volume") else None,
        })
    return {"ok": True, "code": cleaned, "days": len(rows), "rows": rows}


@router.get("/hold")
def hold() -> dict:
    try:
        return serialize_hold(build_hold_summary())
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web hold unavailable", e)
        return empty_hold_payload(error="持仓数据不可用")


@router.post("/positions/cash")
def set_position_cash(payload: Annotated[dict[str, Any], Body()]) -> dict:
    amount = _non_negative_number(payload.get("cash"), label="可用现金")
    try:
        book = positions.set_cash(amount)
    except positions.PositionsCorruptError as e:
        raise HTTPException(status_code=409, detail=_positions_corrupt_detail()) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "cash": book.cash, "message": "可用现金已保存"}


@router.post("/positions")
def add_position(payload: Annotated[dict[str, Any], Body()]) -> dict:
    code = str(payload.get("code") or "").strip()
    cost = _positive_number(
        payload.get("cost"),
        label="持仓成本",
        minimum=positions.MIN_POSITION_COST,
        maximum=positions.MAX_POSITION_COST,
    )
    shares = _positive_integer(payload.get("shares"), label="持股数量")
    try:
        row = positions.add_position(code, cost=cost, shares=shares)
    except positions.PositionsCorruptError as e:
        raise HTTPException(status_code=409, detail=_positions_corrupt_detail()) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "ok": True,
        "code": row.symbol,
        "message": f"已添加 {row.name} {row.symbol}",
    }


@router.put("/positions/{code}")
def update_position(code: str, payload: Annotated[dict[str, Any], Body()]) -> dict:
    cost = _positive_number(
        payload.get("cost"),
        label="持仓成本",
        minimum=positions.MIN_POSITION_COST,
        maximum=positions.MAX_POSITION_COST,
    )
    shares = _positive_integer(payload.get("shares"), label="持股数量")
    try:
        row = positions.update_position(code, cost=cost, shares=shares)
    except positions.PositionsCorruptError as e:
        raise HTTPException(status_code=409, detail=_positions_corrupt_detail()) from e
    except positions.PositionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "ok": True,
        "code": row.symbol,
        "message": f"已更新 {row.name} {row.symbol}",
    }


@router.delete("/positions/{code}")
def delete_position(code: str) -> dict:
    try:
        row = positions.remove_position(code)
    except positions.PositionsCorruptError as e:
        raise HTTPException(status_code=409, detail=_positions_corrupt_detail()) from e
    except positions.PositionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "ok": True,
        "code": row.symbol,
        "message": f"已删除 {row.name} {row.symbol}",
    }


@router.get("/index")
def index_reference() -> dict:
    try:
        result = get_index_reference(IndexRequest(periods=[30, 60, 180]))
        payload = serialize_index(result)
    except Exception as e:
        from kan.infra.log import debug_log

        debug_log(__name__, "web index unavailable", e)
        payload = {"ok": False, "periods": [30, 60, 180], "rows": [], "stats": {"shown": 0}}
    if not payload["ok"]:
        payload["message"] = "指数数据不可用"
    return payload


@router.get("/market")
def market_sentiment() -> dict:
    """市场情绪面板：涨跌家数、涨停跌停、中位位置。"""
    from kan.service.market_service import get_market_sentiment, serialize_market_sentiment

    sentiment = get_market_sentiment()
    return serialize_market_sentiment(sentiment)


@router.get("/config/token")
def config_token() -> dict:
    return _token_status()


@router.post("/config/token")
def set_config_token(payload: Annotated[dict[str, Any], Body()]) -> dict:
    raw = payload.get("token")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="token 无效")
    config.update(tushare_token=raw.strip())
    return _token_status()


@router.delete("/config/token")
def delete_config_token() -> dict:
    config.update(tushare_token=None)
    return _token_status()


def _token_status() -> dict[str, Any]:
    token = config.load().get("tushare_token")
    token_text = token.strip() if isinstance(token, str) else ""
    configured = bool(token_text)
    return {
        "ok": True,
        "configured": configured,
        "masked": config.mask_token(token_text) if configured else None,
    }


def settings_facts() -> dict[str, Any]:
    """设置页只读事实。"""
    import os

    from kan.data.tushare import DEFAULT_ENDPOINT
    from kan.storage import paths

    cfg = config.load()
    endpoint_raw = os.environ.get("TUSHARE_ENDPOINT") or cfg.get("tushare_endpoint") or DEFAULT_ENDPOINT
    endpoint = endpoint_raw.strip() if isinstance(endpoint_raw, str) else DEFAULT_ENDPOINT
    if not endpoint.startswith(("http://", "https://")):
        endpoint = DEFAULT_ENDPOINT
    return {
        "data_dir": str(paths.DATA_DIR),
        "kline_cache_files": _kline_cache_count(paths.DATA_DIR),
        "tushare_endpoint_domain": _endpoint_domain(endpoint),
    }


def _kline_cache_count(data_dir) -> int:
    try:
        return sum(
            1 for path in data_dir.glob("*.parquet")
            if path.stem.isdigit() and len(path.stem) == 6
        )
    except OSError:
        return 0


def _endpoint_domain(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        return ""
    return parsed.hostname or ""


def _positive_number(
    value: Any,
    *,
    label: str,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label}必须是数字")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as e:
        raise HTTPException(status_code=400, detail=f"{label}必须是数字") from e
    if not math.isfinite(parsed) or parsed < minimum or (minimum == 0 and parsed <= 0):
        minimum_text = f"至少为 {minimum:g}" if minimum else "必须大于 0"
        raise HTTPException(status_code=400, detail=f"{label}{minimum_text}")
    if maximum is not None and parsed > maximum:
        raise HTTPException(status_code=400, detail=f"{label}超出可录入范围")
    return parsed


def _non_negative_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label}必须是数字")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as e:
        raise HTTPException(status_code=400, detail=f"{label}必须是数字") from e
    if not math.isfinite(parsed) or parsed < 0:
        raise HTTPException(status_code=400, detail=f"{label}不能小于 0")
    if parsed > positions.MAX_ACCOUNT_VALUE:
        raise HTTPException(status_code=400, detail=f"{label}超出可录入范围")
    return parsed


def _positive_integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label}必须是整数")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as e:
        raise HTTPException(status_code=400, detail=f"{label}必须是整数") from e
    if not math.isfinite(parsed) or parsed <= 0 or not parsed.is_integer():
        raise HTTPException(status_code=400, detail=f"{label}必须是正整数")
    if parsed > positions.MAX_POSITION_SHARES:
        raise HTTPException(status_code=400, detail=f"{label}超出可录入范围")
    return int(parsed)


def _positions_corrupt_detail() -> str:
    return "持仓文件无法读取 · 请先备份 positions.json，再到数据设置查看数据目录"
