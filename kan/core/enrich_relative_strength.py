"""相对强度 enrich: 个股区间涨幅与指数/行业对照差值。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kan.core.cross_section import CrossSectionRow
    from kan.core.models import EnrichedResult, RelativeStrengthMetrics, StockScanResult


def _compute_rs_benchmarks(
    index_periods: set[int],
    board_periods: set[int],
    index_code: str,
) -> tuple[
    dict[int, float], str | None, str | None, dict[str, dict[int, float]], dict[str, str]
]:
    """算 RS 对照原料 (一次 · 两路径共用) · 大盘指数 gain + 各行业 gain + 个股→行业映射。

    index_periods 空 → 不拉指数 (idx_gains={} · idx_code/name=None);board_periods 空 →
    不拉行业 / 不查映射。返回 (idx_gains, idx_code, idx_name, board_by_industry, sw_map)。
    """
    from kan.data.relative_strength import index_gains, industry_gains

    if index_periods:
        idx_gains, idx_code, idx_name = index_gains(index_periods, index_code=index_code)
    else:
        idx_gains, idx_code, idx_name = {}, None, None

    if board_periods:
        from kan.data.industry_map import fetch_sw_l1_map

        board_by_ind = industry_gains(board_periods)
        sw_map = fetch_sw_l1_map()
    else:
        board_by_ind = {}
        sw_map = {}
    return idx_gains, idx_code, idx_name, board_by_ind, sw_map


def attach_relative_strength(
    results: Sequence[StockScanResult],
    *,
    index_periods: set[int],
    board_periods: set[int],
    index_code: str,
) -> list[EnrichedResult]:
    """给 scan 结果挂相对强度子对象 (个股区间涨幅 − 大盘/行业区间涨幅 · 趋势/动量扩展)。

    个股 gain 取自 result.periods[N].gain_pct;对照 gain 取自 relative_strength.index_gains /
    industry_gains。任一侧缺 (周期不足 / 个股行业未知 / 对照指数或行业 K 线缺) → 该周期差值
    不入 rs_* (matcher 不命中 · 不静默当 0)。输入可为 StockScanResult 或 EnrichedResult ·
    统一返回 EnrichedResult (已 enrich 的用 model_copy 挂载 · 未 enrich 的用 from_scan 提升)。

    Args:
        results: scan / enriched 结果 (原序保持)
        index_periods: --rs-index 请求周期 (空 → 不拉指数 · 不标 index_*)
        board_periods: --rs-board 请求周期 (空 → 不拉行业 / 不查申万映射)
        index_code: 大盘对照指数 (ts_code 或别名 · 由 CLI 解析 · 默认沪深300)

    Returns:
        list[EnrichedResult] · 与 results 等长同序 · 每只挂 relative_strength 子对象。
        空 results → 空列表 (不触网)。
    """
    from kan.core.models import EnrichedResult

    if not results:
        return []

    idx_gains, idx_code, idx_name, board_by_ind, sw_map = _compute_rs_benchmarks(
        index_periods, board_periods, index_code
    )

    out: list[EnrichedResult] = []
    for r in results:
        rsm = _build_rs_metrics(
            r,
            idx_gains=idx_gains,
            idx_code=idx_code,
            idx_name=idx_name,
            board_by_ind=board_by_ind,
            sw_map=sw_map,
            index_periods=index_periods,
            board_periods=board_periods,
        )
        if isinstance(r, EnrichedResult):
            out.append(r.model_copy(update={"relative_strength": rsm}))
        else:
            out.append(EnrichedResult.from_scan(r, relative_strength=rsm))
    return out


def _stock_gains(result: StockScanResult, periods: set[int]) -> dict[int, float]:
    """个股各周期区间涨幅 (从 scan periods 取 · insufficient / gain None 跳过)。"""
    out: dict[int, float] = {}
    for pr in result.periods:
        if pr.period in periods and not pr.insufficient and pr.gain_pct is not None:
            out[pr.period] = pr.gain_pct
    return out


def _build_rs_metrics(
    result: StockScanResult,
    *,
    idx_gains: dict[int, float],
    idx_code: str | None,
    idx_name: str | None,
    board_by_ind: dict[str, dict[int, float]],
    sw_map: dict[str, str],
    index_periods: set[int],
    board_periods: set[int],
) -> RelativeStrengthMetrics:
    """单股相对强度差值 · 个股 gain − 对照 gain · 缺一侧该周期不入 rs_* (不静默当 0)。"""
    from kan.core.models import RelativeStrengthMetrics

    stock_gain = _stock_gains(result, index_periods | board_periods)
    industry = sw_map.get(result.symbol) or None
    board_gain = board_by_ind.get(industry, {}) if industry else {}

    rs_index: dict[int, float] = {}
    for p in index_periods:
        sg, ig = stock_gain.get(p), idx_gains.get(p)
        if sg is not None and ig is not None:
            rs_index[p] = round(sg - ig, 2)

    rs_board: dict[int, float] = {}
    for p in board_periods:
        sg, bg = stock_gain.get(p), board_gain.get(p)
        if sg is not None and bg is not None:
            rs_board[p] = round(sg - bg, 2)

    return RelativeStrengthMetrics(
        industry=industry,
        index_code=idx_code,
        index_name=idx_name,
        stock_gain=stock_gain,
        index_gain={p: idx_gains[p] for p in index_periods if p in idx_gains},
        board_gain={p: board_gain[p] for p in board_periods if p in board_gain},
        rs_index=rs_index,
        rs_board=rs_board,
        source="tushare_index+sw",
    )


def attach_relative_strength_cross_section(
    rows: list[CrossSectionRow],
    *,
    index_periods: set[int],
    board_periods: set[int],
    index_code: str,
) -> list[CrossSectionRow]:
    """给截面行 (--all 路径) 挂相对强度子对象 · 复用 row.scan 的个股 gain + 同一对照原料。

    row.scan 为 None (无 K 线快照) → 该行不挂 (relative_strength 保持 None · matcher 不命中)。
    对照原料 (指数/行业 gain + 映射) 池无关 · 一次算好供全市场 rows 共用。
    """
    import dataclasses

    if not rows:
        return []
    idx_gains, idx_code, idx_name, board_by_ind, sw_map = _compute_rs_benchmarks(
        index_periods, board_periods, index_code
    )
    out: list[CrossSectionRow] = []
    for row in rows:
        if row.scan is None:
            out.append(row)
            continue
        rsm = _build_rs_metrics(
            row.scan,
            idx_gains=idx_gains,
            idx_code=idx_code,
            idx_name=idx_name,
            board_by_ind=board_by_ind,
            sw_map=sw_map,
            index_periods=index_periods,
            board_periods=board_periods,
        )
        out.append(dataclasses.replace(row, relative_strength=rsm))
    return out


__all__ = [
    "attach_relative_strength",
    "attach_relative_strength_cross_section",
]
