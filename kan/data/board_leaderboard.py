"""板块级资金 / 涨幅 / 位置榜 · `kan board rank` 数据层。

行业和题材都复用已有 catalog / 指数 K 线 / 成分股缓存:

- industry: 申万行业 catalog + index_hist_sw K 线;资金默认用申万一级映射聚合
- theme: 同花顺题材 catalog + EM 题材指数 K 线;资金按题材成分股聚合

本模块只输出客观裸值,不做评分 / 判断 / 推荐。
"""
from __future__ import annotations

import concurrent.futures
import os
from dataclasses import dataclass
from typing import Literal

from kan.core.models import Board, StockScanResult, Theme

BoardKind = Literal["industry", "theme"]
BoardMetric = Literal["moneyflow", "gain", "pos"]
_DEFAULT_PARALLEL = 16


@dataclass(frozen=True)
class BoardRankRow:
    kind: BoardKind
    code: str
    name: str
    close: float | None
    position_pct: float | None
    gain_pct: float | None
    moneyflow_net: float | None
    data_date: object | None


def _safe_scan_index(obj: Board | Theme, kind: BoardKind, period: int, *, force: bool):
    from kan.core.scanner import scan_stock
    from kan.data import boards

    try:
        if kind == "industry":
            df = boards.fetch_industry_kline(obj, force=force)  # type: ignore[arg-type]
        else:
            df = boards.fetch_theme_kline(obj, force=force)  # type: ignore[arg-type]
        if df is None or df.empty:
            return None
        return scan_stock(df, obj.code, obj.name, periods=[period])
    except Exception:
        return None


def _scan_theme_klines(
    themes: list[Theme],
    klines: dict[str, object],
    period: int,
) -> dict[str, StockScanResult]:
    """TuShare 批量题材 K 线 → {theme_code: StockScanResult}。"""
    from kan.core.scanner import scan_stock

    out: dict[str, StockScanResult] = {}
    for theme in themes:
        df = klines.get(theme.code)
        if df is None:
            continue
        try:
            scan = scan_stock(df, theme.code, theme.name, periods=[period])
        except Exception:
            continue
        out[theme.code] = scan
    return out


def _resolve_parallel(parallel: int | None) -> int:
    """决定板块指数 K 线并发数 · CLI 参数 > env > 默认 16 · clamp 到 [1, 32]。"""
    if parallel is None:
        env = os.environ.get("KAN_BOARD_RANK_PARALLEL")
        if env:
            try:
                parallel = int(env)
            except ValueError:
                parallel = _DEFAULT_PARALLEL
        else:
            parallel = _DEFAULT_PARALLEL
    return max(1, min(32, parallel))


def _industry_moneyflow_map() -> dict[str, float]:
    """申万一级行业 → 主力净额合计(万元)。无数据返回空 dict。"""
    from kan.data.industry_map import fetch_sw_l1_map
    from kan.data.moneyflow import fetch_moneyflow

    mf = fetch_moneyflow()
    if mf is None or mf.empty:
        return {}
    l1 = fetch_sw_l1_map()
    out: dict[str, float] = {}
    for _, row in mf.iterrows():
        code = str(row.get("symbol", "")).strip()
        industry = l1.get(code)
        value = row.get("net_amount")
        if not industry or value is None:
            continue
        try:
            out[industry] = out.get(industry, 0.0) + float(value)
        except (TypeError, ValueError):
            continue
    return out


def theme_moneyflow_map(themes: list[Theme], *, force: bool = False) -> dict[str, float]:
    """题材代码 → 成分股主力净额合计(万元)。"""
    from kan.data import boards
    from kan.data.moneyflow import fetch_moneyflow

    mf = fetch_moneyflow()
    if mf is None or mf.empty:
        return {}
    by_symbol = {
        str(r.get("symbol", "")).strip(): r.get("net_amount")
        for _, r in mf.iterrows()
    }
    out: dict[str, float] = {}
    for theme in themes:
        try:
            pairs = boards.get_theme_constituents(theme, force=force)
        except Exception:
            continue
        total = 0.0
        hit = False
        for code, _name in pairs:
            val = by_symbol.get(code)
            if val is None:
                continue
            try:
                total += float(val)
                hit = True
            except (TypeError, ValueError):
                continue
        if hit:
            out[theme.code] = total
    return out


def load_board_leaderboard(
    *,
    kind: BoardKind = "industry",
    metric: BoardMetric = "moneyflow",
    period: int = 30,
    level: int = 1,
    limit: int | None = None,
    force: bool = False,
    parallel: int | None = None,
) -> tuple[list[BoardRankRow], list[tuple[str, Exception]]]:
    """加载板块榜 · 返回 (rows, errors)。

    `metric` 只决定排序口径,行里尽量带齐 moneyflow/gain/pos 三类裸值。
    题材指数 K 线数量较多,默认受控并发扫描,避免 `--limit` 小但全量串行拖慢。
    """
    from kan.data import boards

    errors: list[tuple[str, Exception]] = []
    scan_by_code: dict[str, StockScanResult] = {}
    if kind == "industry":
        catalog = [b for b in boards.load_industry_catalog(force=force) if b.level == level]
        mf_map = _industry_moneyflow_map()
    else:
        catalog = []
        if metric in ("gain", "pos"):
            from kan.data.tushare_themes import (
                tushare_load_theme_catalog,
                tushare_load_theme_klines,
            )

            ts_catalog, _catalog_err = tushare_load_theme_catalog()
            if ts_catalog:
                # 区间涨幅需要 period+1 根；位置需要 period 根。下限 35 天复用 theme trend 缓存。
                ts_klines, _klines_err = tushare_load_theme_klines(
                    ts_catalog,
                    n_trading_days=max(period + 1, 35),
                )
                if ts_klines:
                    catalog = ts_catalog
                    scan_by_code = _scan_theme_klines(ts_catalog, ts_klines, period)
        if not catalog:
            catalog = boards.load_theme_catalog(force=force)
        mf_map = theme_moneyflow_map(catalog, force=force) if metric == "moneyflow" else {}

    def build_row(item: Board | Theme) -> tuple[BoardRankRow | None, tuple[str, Exception] | None]:
        scan = scan_by_code.get(item.code)
        if scan is None and not (kind == "theme" and getattr(item, "source", "") == "tushare"):
            scan = _safe_scan_index(item, kind, period, force=force)
        close = None
        pos = None
        gain = None
        data_date = None
        if scan is not None and scan.periods:
            pr = scan.periods[0]
            close = scan.current_price
            data_date = scan.scan_date
            if not pr.insufficient:
                pos = pr.position_pct
                gain = pr.gain_pct
        moneyflow = mf_map.get(item.name if kind == "industry" else item.code)
        if scan is None and moneyflow is None:
            return None, (item.name, RuntimeError("无板块 K 线且无资金数据"))
        return (
            BoardRankRow(
                kind=kind,
                code=item.code,
                name=item.name,
                close=close,
                position_pct=pos,
                gain_pct=gain,
                moneyflow_net=moneyflow,
                data_date=data_date,
            ),
            None,
        )

    rows: list[BoardRankRow] = []
    workers = min(_resolve_parallel(parallel), max(1, len(catalog)))
    if workers <= 1 or len(catalog) <= 1:
        built = [build_row(item) for item in catalog]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            built = list(ex.map(build_row, catalog))
    for row, error in built:
        if row is not None:
            rows.append(row)
        if error is not None:
            errors.append(error)

    def value(row: BoardRankRow):
        if metric == "moneyflow":
            return row.moneyflow_net
        if metric == "gain":
            return row.gain_pct
        return row.position_pct

    if metric == "pos":
        rows.sort(key=lambda r: (value(r) is None, value(r) if value(r) is not None else 101.0))
    else:
        rows.sort(key=lambda r: (value(r) is None, -(value(r) or 0.0)))

    if limit is not None:
        rows = rows[:limit]
    return rows, errors


__all__ = [
    "BoardKind",
    "BoardMetric",
    "BoardRankRow",
    "load_board_leaderboard",
    "theme_moneyflow_map",
]
