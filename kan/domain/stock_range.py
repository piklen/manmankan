"""单股日内偏离分布的稳定领域模型。

所有百分比都以前一有效交易日收盘价为基准。领域对象只描述可复核的历史
事实，不生成止损、止盈或其他交易动作。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StockRangeModel(BaseModel):
    """range 契约统一拒绝未知字段，避免入口间静默漂移。"""

    model_config = ConfigDict(extra="forbid")


Period = Annotated[int, Field(ge=2, le=360)]
Level = Annotated[float, Field(gt=0, lt=100)]


class StockRangeRequest(StockRangeModel):
    """由入口显式给出的单股日内偏离查询。"""

    symbol: Annotated[str, Field(pattern=r"^\d{6}$")]
    periods: Annotated[tuple[Period, ...], Field(min_length=1, max_length=12)]
    levels: Annotated[tuple[Level, ...], Field(min_length=1, max_length=12)]
    down_pct: Annotated[float | None, Field(gt=0, le=100)] = None
    up_pct: Annotated[float | None, Field(gt=0, le=1000)] = None
    force: bool = False

    @model_validator(mode="after")
    def validate_unique_values(self) -> StockRangeRequest:
        if len(set(self.periods)) != len(self.periods):
            raise ValueError("periods 不能包含重复周期")
        if len(set(self.levels)) != len(self.levels):
            raise ValueError("levels 不能包含重复档位")
        return self


class StockRangeCoverage(StockRangeModel):
    """从 provider 原始行到最终日内样本的可审计计数。"""

    requested_bars: int = Field(ge=2)
    raw_rows: int = Field(ge=0)
    invalid_date_rows: int = Field(ge=0)
    after_cutoff_rows: int = Field(ge=0)
    duplicate_date_rows: int = Field(ge=0)
    invalid_ohlc_rows: int = Field(ge=0)
    invalid_reference_observations: int = Field(ge=0)
    excluded_rows: int = Field(ge=0)
    older_valid_rows_ignored: int = Field(ge=0)
    valid_bars: int = Field(ge=0)
    valid_observations: int = Field(ge=0)


class DownsideThresholdStudy(StockRangeModel):
    """一条下行幅度线在指定历史窗口内的触及与收盘事实。"""

    basis: Literal["empirical_level", "custom"]
    level_pct: float | None = None
    threshold_pct: float = Field(le=0)
    actual_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    trigger_count: int = Field(ge=0)
    trigger_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    close_above_count: int = Field(ge=0)
    close_above_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    close_at_or_below_count: int = Field(ge=0)
    close_at_or_below_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    close_positive_count: int = Field(ge=0)
    close_positive_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    gap_trigger_count: int = Field(ge=0)
    gap_trigger_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    intraday_trigger_count: int = Field(ge=0)
    close_median_pct: float | None = None


class UpsideThresholdStudy(StockRangeModel):
    """一条上行幅度线在指定历史窗口内的触及与收盘事实。"""

    basis: Literal["empirical_level", "custom"]
    level_pct: float | None = None
    threshold_pct: float = Field(ge=0)
    actual_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    trigger_count: int = Field(ge=0)
    trigger_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    close_at_or_above_count: int = Field(ge=0)
    close_at_or_above_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    close_below_count: int = Field(ge=0)
    close_below_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    close_positive_count: int = Field(ge=0)
    close_positive_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    gap_trigger_count: int = Field(ge=0)
    gap_trigger_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    intraday_trigger_count: int = Field(ge=0)
    close_median_pct: float | None = None
    pullback_median_pct: float | None = None


class StockRangeWindow(StockRangeModel):
    """一个回看窗口内的经验档位与可选自定义幅度。"""

    period: int = Field(ge=2, le=360)
    sample_count: int = Field(ge=0)
    missing_sample_count: int = Field(ge=0)
    start_date: str | None = None
    end_date: str | None = None
    downside: list[DownsideThresholdStudy] = Field(default_factory=list)
    upside: list[UpsideThresholdStudy] = Field(default_factory=list)
    custom_downside: DownsideThresholdStudy | None = None
    custom_upside: UpsideThresholdStudy | None = None


class StockRangeStudy(StockRangeModel):
    """单股历史日内偏离研究快照。"""

    schema_version: int = 1
    request: StockRangeRequest
    symbol: str
    name: str
    source: str
    data_start: str
    data_cutoff: str
    latest_complete_cutoff: str
    reference_close: float
    coverage: StockRangeCoverage
    windows: list[StockRangeWindow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "DownsideThresholdStudy",
    "StockRangeCoverage",
    "StockRangeRequest",
    "StockRangeStudy",
    "StockRangeWindow",
    "UpsideThresholdStudy",
]
