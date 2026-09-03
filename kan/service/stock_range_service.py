"""单股日内偏离分布 application service。

服务只计算以前一有效交易日收盘价为基准的历史事实。Typer、HTTP、MCP 等
入口应复用本模块，不在渲染层重算经验分位或触发结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from math import ceil, floor, isfinite
from statistics import median
from typing import TYPE_CHECKING, Any, Literal

from kan.domain.stock_range import (
    DownsideThresholdStudy,
    StockRangeCoverage,
    StockRangeRequest,
    StockRangeStudy,
    StockRangeWindow,
    UpsideThresholdStudy,
)

if TYPE_CHECKING:
    import pandas as pd


_PCT_EPSILON = 1e-10


class StockRangeServiceError(RuntimeError):
    """可由 CLI/HTTP 稳定映射的单股 range 失败。"""

    def __init__(
        self,
        code: str,
        message: str,
        hint: str | None = None,
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


@dataclass(frozen=True)
class _PreparedHistory:
    frame: pd.DataFrame
    source: str
    coverage: StockRangeCoverage
    warnings: list[str]


@dataclass(frozen=True)
class _Observation:
    date: date
    open_pct: float
    high_pct: float
    low_pct: float
    close_pct: float


def _fetch_stock_history(symbol: str, *, days: int, force: bool) -> pd.DataFrame:
    """隔离 provider 边界，便于服务单测替换网络取数。"""

    from kan.data.fetcher import DEFAULT_KLINE_DAYS, fetch_kline

    # 短窗口命令不能用 16 根左右的响应覆盖原有 360 根逐股缓存。
    # fetcher 以 requested days 标记缓存完整度，因此刷新时至少维持公共默认深度。
    return fetch_kline(symbol, days=max(days, DEFAULT_KLINE_DAYS), force=force)


def _latest_complete_cutoff() -> date:
    """隔离交易日历边界，测试可固定最新完整交易日。"""

    from kan.core.trading_calendar import latest_trade_date

    return latest_trade_date()


def _resolve_stock_name(symbol: str) -> str:
    """复用现有 A 股代码表解析名称，入口测试可替换本地/网络边界。"""

    from kan.storage.watchlist import resolve_symbol_or_name

    _resolved_symbol, name = resolve_symbol_or_name(symbol)
    return name


def _round4(value: float) -> float:
    rounded = round(value, 4)
    return 0.0 if rounded == 0 else rounded


def _tick_reference_price(reference_close: float, threshold_pct: float) -> float:
    """把理论阈值价按 A 股 0.01 元价格档做十进制四舍五入。"""

    close = Decimal(str(reference_close))
    threshold = Decimal(str(threshold_pct))
    price = close * (Decimal("1") + threshold / Decimal("100"))
    return float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ratio(numerator: int, denominator: int) -> float | None:
    """比例分母为零时保留未知，不用 0% 代替无样本。"""

    if denominator == 0:
        return None
    return _round4(numerator / denominator * 100)


def _linear_percentile(values: list[float], level_pct: float) -> float:
    """线性插值经验分位；短窗口仍同步输出实际经验覆盖率。"""

    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * level_pct / 100
    low_index = floor(position)
    high_index = ceil(position)
    if low_index == high_index:
        return ordered[low_index]
    weight = position - low_index
    return ordered[low_index] * (1 - weight) + ordered[high_index] * weight


def _valid_price(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return isfinite(number) and number > 0


def _prepare_history(
    raw_frame: pd.DataFrame,
    *,
    latest_complete_cutoff: date,
    requested_bars: int,
) -> _PreparedHistory:
    """按日期、OHLC 和窗口边界把 provider 行归一化为有效日 K。"""

    import pandas as pd

    required = {"date", "open", "high", "low", "close"}
    if raw_frame is None or not hasattr(raw_frame, "columns"):
        raise StockRangeServiceError(
            "invalid_data",
            "日 K 数据格式无效",
            hint="刷新该股票日 K 后重试",
        )
    raw_rows = len(raw_frame)
    missing = sorted(required.difference(raw_frame.columns))
    if raw_rows == 0:
        raise StockRangeServiceError(
            "data_unavailable",
            "没有可用的日 K 数据",
            hint="检查股票代码、网络或数据源配置后重试",
        )
    if missing:
        raise StockRangeServiceError(
            "invalid_data",
            f"日 K 数据缺少字段: {', '.join(missing)}",
            hint="刷新该股票日 K 后重试",
        )

    columns = ["date", "open", "high", "low", "close"]
    if "_source" in raw_frame.columns:
        columns.append("_source")
    frame = raw_frame[columns].copy()
    frame["_row_order"] = range(len(frame))
    parsed_dates = pd.to_datetime(frame["date"], errors="coerce")
    frame["date"] = parsed_dates.dt.date

    invalid_date_mask = frame["date"].isna()
    invalid_date_rows = int(invalid_date_mask.sum())
    frame = frame.loc[~invalid_date_mask].copy()

    after_cutoff_mask = frame["date"].map(
        lambda value: value > latest_complete_cutoff,
    )
    after_cutoff_rows = int(after_cutoff_mask.sum())
    frame = frame.loc[~after_cutoff_mask].copy()

    frame = frame.sort_values(["date", "_row_order"], kind="stable")
    duplicate_mask = frame.duplicated(subset=["date"], keep="last")
    duplicate_date_rows = int(duplicate_mask.sum())
    frame = frame.loc[~duplicate_mask].copy()

    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    price_mask = frame[["open", "high", "low", "close"]].apply(
        lambda column: column.map(_valid_price),
    ).all(axis=1)
    structure_mask = (
        (frame["low"] <= frame["open"])
        & (frame["open"] <= frame["high"])
        & (frame["low"] <= frame["close"])
        & (frame["close"] <= frame["high"])
    )
    valid_ohlc_mask = price_mask & structure_mask
    invalid_ohlc_rows = int((~valid_ohlc_mask).sum())
    # 某日存在但 OHLC 损坏时，下一日不能跨过坏行拿更早 close 冒充前收。
    # 停牌日没有原始行，不会命中此标记，复牌日仍可对最后成交收盘计算。
    frame["_previous_bar_valid"] = valid_ohlc_mask.shift(1, fill_value=False)
    valid = frame.loc[valid_ohlc_mask].copy()

    older_valid_rows_ignored = max(0, len(valid) - requested_bars)
    valid = valid.tail(requested_bars).reset_index(drop=True)
    valid_bars = len(valid)
    invalid_reference_observations = int(
        (~valid.iloc[1:]["_previous_bar_valid"]).sum()
    ) if valid_bars > 1 else 0
    valid_observations = max(
        0,
        valid_bars - 1 - invalid_reference_observations,
    )
    excluded_rows = (
        invalid_date_rows
        + after_cutoff_rows
        + duplicate_date_rows
        + invalid_ohlc_rows
    )

    sources: list[str] = []
    if "_source" in valid.columns:
        sources = sorted({
            str(value).strip()
            for value in valid["_source"].dropna().tolist()
            if str(value).strip() and str(value).strip().lower() != "nan"
        })
    source = " + ".join(sources) if sources else "unknown"

    warnings: list[str] = []
    if invalid_date_rows:
        warnings.append(f"{invalid_date_rows} 行日期无效，未纳入计算")
    if after_cutoff_rows:
        warnings.append(
            f"{after_cutoff_rows} 行晚于最近完整交易日 "
            f"{latest_complete_cutoff.isoformat()}，未纳入计算",
        )
    if duplicate_date_rows:
        warnings.append(f"{duplicate_date_rows} 行日期重复，保留同日最后一行")
    if invalid_ohlc_rows:
        warnings.append(f"{invalid_ohlc_rows} 行 OHLC 无效，未纳入计算")
    if invalid_reference_observations:
        warnings.append(
            f"{invalid_reference_observations} 行缺少可信前收，未生成日内样本",
        )
    if len(sources) > 1:
        warnings.append(f"有效窗口包含多个数据源: {source}")
    if not sources:
        warnings.append("数据源标记不可用")

    coverage = StockRangeCoverage(
        requested_bars=requested_bars,
        raw_rows=raw_rows,
        invalid_date_rows=invalid_date_rows,
        after_cutoff_rows=after_cutoff_rows,
        duplicate_date_rows=duplicate_date_rows,
        invalid_ohlc_rows=invalid_ohlc_rows,
        invalid_reference_observations=invalid_reference_observations,
        excluded_rows=excluded_rows,
        older_valid_rows_ignored=older_valid_rows_ignored,
        valid_bars=valid_bars,
        valid_observations=valid_observations,
    )
    return _PreparedHistory(
        frame=valid,
        source=source,
        coverage=coverage,
        warnings=warnings,
    )


def _observations(frame: pd.DataFrame) -> list[_Observation]:
    observations: list[_Observation] = []
    for index in range(1, len(frame)):
        if not bool(frame.iloc[index]["_previous_bar_valid"]):
            continue
        previous_close = float(frame.iloc[index - 1]["close"])
        row = frame.iloc[index]
        observations.append(
            _Observation(
                date=row["date"],
                open_pct=(float(row["open"]) / previous_close - 1) * 100,
                high_pct=(float(row["high"]) / previous_close - 1) * 100,
                low_pct=(float(row["low"]) / previous_close - 1) * 100,
                close_pct=(float(row["close"]) / previous_close - 1) * 100,
            ),
        )
    return observations


def _downside_study(
    observations: list[_Observation],
    *,
    magnitude_pct: float,
    reference_close: float,
    basis: Literal["empirical_level", "custom"],
    level_pct: float | None,
) -> DownsideThresholdStudy:
    # 阈值以公开的 4 位精度分类，保证 JSON/终端显示值原样作为 --down
    # 回传时得到相同证据；分位本身仍先用全精度计算。
    threshold = _round4(-magnitude_pct)
    triggered = [
        item
        for item in observations
        if item.low_pct <= threshold + _PCT_EPSILON
    ]
    trigger_count = len(triggered)
    close_above_count = sum(
        item.close_pct > threshold + _PCT_EPSILON
        for item in triggered
    )
    close_at_or_below_count = trigger_count - close_above_count
    close_positive_count = sum(item.close_pct > 0 for item in triggered)
    gap_trigger_count = sum(
        item.open_pct <= threshold + _PCT_EPSILON
        for item in triggered
    )
    covered_count = sum(
        item.low_pct >= threshold - _PCT_EPSILON
        for item in observations
    )
    close_values = [item.close_pct for item in triggered]
    return DownsideThresholdStudy(
        basis=basis,
        level_pct=None if level_pct is None else _round4(level_pct),
        threshold_pct=threshold,
        reference_price=_tick_reference_price(reference_close, threshold),
        actual_coverage_pct=_ratio(covered_count, len(observations)),
        trigger_count=trigger_count,
        trigger_ratio_pct=_ratio(trigger_count, len(observations)),
        close_above_count=close_above_count,
        close_above_ratio_pct=_ratio(close_above_count, trigger_count),
        close_at_or_below_count=close_at_or_below_count,
        close_at_or_below_ratio_pct=_ratio(close_at_or_below_count, trigger_count),
        close_positive_count=close_positive_count,
        close_positive_ratio_pct=_ratio(close_positive_count, trigger_count),
        gap_trigger_count=gap_trigger_count,
        gap_trigger_ratio_pct=_ratio(gap_trigger_count, trigger_count),
        intraday_trigger_count=trigger_count - gap_trigger_count,
        close_median_pct=(
            None if not close_values else _round4(median(close_values))
        ),
    )


def _upside_study(
    observations: list[_Observation],
    *,
    magnitude_pct: float,
    reference_close: float,
    basis: Literal["empirical_level", "custom"],
    level_pct: float | None,
) -> UpsideThresholdStudy:
    # 同下行：统计证据必须与公开阈值可 round-trip，不能用隐藏小数分类。
    threshold = _round4(magnitude_pct)
    triggered = [
        item
        for item in observations
        if item.high_pct >= threshold - _PCT_EPSILON
    ]
    trigger_count = len(triggered)
    close_at_or_above_count = sum(
        item.close_pct >= threshold - _PCT_EPSILON
        for item in triggered
    )
    close_below_count = trigger_count - close_at_or_above_count
    close_positive_count = sum(item.close_pct > 0 for item in triggered)
    gap_trigger_count = sum(
        item.open_pct >= threshold - _PCT_EPSILON
        for item in triggered
    )
    covered_count = sum(
        item.high_pct <= threshold + _PCT_EPSILON
        for item in observations
    )
    close_values = [item.close_pct for item in triggered]
    pullbacks = [item.high_pct - item.close_pct for item in triggered]
    return UpsideThresholdStudy(
        basis=basis,
        level_pct=None if level_pct is None else _round4(level_pct),
        threshold_pct=threshold,
        reference_price=_tick_reference_price(reference_close, threshold),
        actual_coverage_pct=_ratio(covered_count, len(observations)),
        trigger_count=trigger_count,
        trigger_ratio_pct=_ratio(trigger_count, len(observations)),
        close_at_or_above_count=close_at_or_above_count,
        close_at_or_above_ratio_pct=_ratio(close_at_or_above_count, trigger_count),
        close_below_count=close_below_count,
        close_below_ratio_pct=_ratio(close_below_count, trigger_count),
        close_positive_count=close_positive_count,
        close_positive_ratio_pct=_ratio(close_positive_count, trigger_count),
        gap_trigger_count=gap_trigger_count,
        gap_trigger_ratio_pct=_ratio(gap_trigger_count, trigger_count),
        intraday_trigger_count=trigger_count - gap_trigger_count,
        close_median_pct=(
            None if not close_values else _round4(median(close_values))
        ),
        pullback_median_pct=(
            None if not pullbacks else _round4(median(pullbacks))
        ),
    )


def _window(
    all_observations: list[_Observation],
    *,
    period: int,
    levels: tuple[float, ...],
    reference_close: float,
    down_pct: float | None,
    up_pct: float | None,
) -> StockRangeWindow:
    observations = all_observations[-period:]
    downside_excursions = [max(0.0, -item.low_pct) for item in observations]
    upside_excursions = [max(0.0, item.high_pct) for item in observations]

    downside = [
        _downside_study(
            observations,
            magnitude_pct=_linear_percentile(downside_excursions, level),
            reference_close=reference_close,
            basis="empirical_level",
            level_pct=level,
        )
        for level in sorted(levels)
    ]
    upside = [
        _upside_study(
            observations,
            magnitude_pct=_linear_percentile(upside_excursions, level),
            reference_close=reference_close,
            basis="empirical_level",
            level_pct=level,
        )
        for level in sorted(levels)
    ]
    return StockRangeWindow(
        period=period,
        sample_count=len(observations),
        missing_sample_count=max(0, period - len(observations)),
        start_date=observations[0].date.isoformat() if observations else None,
        end_date=observations[-1].date.isoformat() if observations else None,
        downside=downside,
        upside=upside,
        custom_downside=(
            None
            if down_pct is None
            else _downside_study(
                observations,
                magnitude_pct=down_pct,
                reference_close=reference_close,
                basis="custom",
                level_pct=None,
            )
        ),
        custom_upside=(
            None
            if up_pct is None
            else _upside_study(
                observations,
                magnitude_pct=up_pct,
                reference_close=reference_close,
                basis="custom",
                level_pct=None,
            )
        ),
    )


def study_stock_range(request: StockRangeRequest) -> StockRangeStudy:
    """计算单股最近若干完整交易日的日内下探、上冲和收盘分布。"""

    requested_bars = max(request.periods) + 1
    latest_complete_cutoff = _latest_complete_cutoff()
    try:
        name = _resolve_stock_name(request.symbol)
    except ValueError as exc:
        raise StockRangeServiceError(
            "invalid_symbol",
            str(exc),
            hint="使用 6 位 A 股代码后重试",
            exit_code=2,
        ) from exc
    except Exception as exc:
        raise StockRangeServiceError(
            "symbol_catalog_unavailable",
            "股票代码表暂不可用",
            hint="检查网络或稍后重试",
        ) from exc
    try:
        raw_frame = _fetch_stock_history(
            request.symbol,
            days=requested_bars,
            force=request.force,
        )
    except StockRangeServiceError:
        raise
    except Exception as exc:
        raise StockRangeServiceError(
            "data_unavailable",
            f"{request.symbol} 的日 K 数据暂不可用",
            hint="检查股票代码、网络或数据源配置后重试",
        ) from exc

    prepared = _prepare_history(
        raw_frame,
        latest_complete_cutoff=latest_complete_cutoff,
        requested_bars=requested_bars,
    )
    observations = _observations(prepared.frame)
    if not observations:
        raise StockRangeServiceError(
            "insufficient_history",
            "至少需要两个有效交易日才能计算前收偏离",
            hint="刷新该股票日 K 或缩短查询周期后重试",
        )

    # reference_price 只依赖同一 JSON 中公开的 reference_close 与 threshold_pct。
    reference_close = _round4(float(prepared.frame.iloc[-1]["close"]))
    windows = [
        _window(
            observations,
            period=period,
            levels=request.levels,
            reference_close=reference_close,
            down_pct=request.down_pct,
            up_pct=request.up_pct,
        )
        for period in sorted(request.periods)
    ]
    warnings = list(prepared.warnings)
    if prepared.coverage.valid_observations < max(request.periods):
        warnings.append(
            f"有效样本 {prepared.coverage.valid_observations} 个，少于最长请求周期 "
            f"{max(request.periods)} 日",
        )
    for window in windows:
        if window.sample_count < 20:
            warnings.append(
                f"{window.period} 日窗口只有 {window.sample_count} 个样本，"
                "新增一个交易日就可能明显改变各档幅度",
            )
        if window.custom_downside is not None and window.custom_downside.trigger_count == 0:
            warnings.append(
                f"{window.period} 日窗口没有触及自定义下行幅度，触及后比例为空",
            )
        if window.custom_upside is not None and window.custom_upside.trigger_count == 0:
            warnings.append(
                f"{window.period} 日窗口没有触及自定义上行幅度，触及后比例为空",
            )

    data_cutoff = prepared.frame.iloc[-1]["date"]
    if data_cutoff < latest_complete_cutoff:
        warnings.append(
            f"行情数据截止 {data_cutoff.isoformat()}，早于最近完整交易日 "
            f"{latest_complete_cutoff.isoformat()}",
        )
    return StockRangeStudy(
        request=request,
        symbol=request.symbol,
        name=name,
        source=prepared.source,
        data_start=observations[0].date.isoformat(),
        data_cutoff=data_cutoff.isoformat(),
        latest_complete_cutoff=latest_complete_cutoff.isoformat(),
        reference_close=reference_close,
        coverage=prepared.coverage,
        windows=windows,
        warnings=warnings,
    )


__all__ = [
    "StockRangeServiceError",
    "study_stock_range",
]
