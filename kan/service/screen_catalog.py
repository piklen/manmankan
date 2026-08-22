"""选股条件与结果字段目录。

目录以核心 `FILTER_SPECS` 为存在性与数据来源真相，补充 UI/AI 所需的中文标签、
单位和输入形状。React SPA、CLI schema、HTTP 与 MCP 都从这里读取。
"""

from __future__ import annotations

from typing import TypedDict

from kan.core.find_registry import FILTER_SPECS
from kan.domain.screen import FilterInputKind, ScreenFilterType


class FilterCatalogEntry(TypedDict):
    type: str
    label: str
    unit: str
    input: str
    flag: str
    supports_all: bool
    source: str
    frequency: str
    missing_semantics: str


_GROUPS = (
    (
        "价格位置与趋势",
        (
            ("pos", "价格区间位置", "%", FilterInputKind.PERIOD),
            ("resonance", "多周期位置共振", "周期", FilterInputKind.RESONANCE),
            ("gain", "区间涨跌幅", "%", FilterInputKind.PERIOD),
            ("up_days", "连续阳线天数", "天", FilterInputKind.SCALAR),
            ("ma_bias", "均线乖离率", "%", FilterInputKind.PERIOD),
            ("rs_index", "相对大盘涨幅差", "百分点", FilterInputKind.PERIOD),
            ("rs_board", "相对行业涨幅差", "百分点", FilterInputKind.PERIOD),
        ),
    ),
    (
        "估值、质量与交易",
        (
            ("pe", "市盈率 PE TTM", "倍", FilterInputKind.SCALAR),
            ("pb", "市净率 PB", "倍", FilterInputKind.SCALAR),
            ("dv", "股息率 TTM", "%", FilterInputKind.SCALAR),
            ("roe", "净资产收益率 ROE", "%", FilterInputKind.SCALAR),
            ("turnover", "换手率", "%", FilterInputKind.SCALAR),
            ("market_cap", "总市值", "亿元", FilterInputKind.SCALAR),
            ("volume_ratio", "量比", "倍", FilterInputKind.SCALAR),
        ),
    ),
    (
        "资金、技术与筹码",
        (
            ("moneyflow", "主力净额（近5日优先）", "万元", FilterInputKind.SCALAR),
            ("moneyflow_daily", "单日主力净额", "万元", FilterInputKind.SCALAR),
            ("moneyflow_days", "连续主力净流入", "天", FilterInputKind.SCALAR),
            ("rsi", "RSI（6日）", "", FilterInputKind.SCALAR),
            ("macd_dif", "MACD DIF", "", FilterInputKind.SCALAR),
            ("macd", "MACD 柱", "", FilterInputKind.SCALAR),
            ("kdj_j", "KDJ J值", "", FilterInputKind.SCALAR),
            ("atr_pct", "ATR 波动率", "%", FilterInputKind.SCALAR),
            ("winner", "获利盘比例", "%", FilterInputKind.SCALAR),
            ("streak", "连板天数", "天", FilterInputKind.SCALAR),
        ),
    ),
    (
        "股东与持股结构",
        (
            ("holders", "股东户数环比", "%", FilterInputKind.SCALAR),
            ("top10", "前十大流通集中度", "%", FilterInputKind.SCALAR),
            ("north", "北向持股比例", "%", FilterInputKind.SCALAR),
        ),
    ),
)


def _entry(filter_type: str, label: str, unit: str, input_kind: FilterInputKind) -> FilterCatalogEntry:
    spec = FILTER_SPECS[filter_type]
    return {
        "type": filter_type,
        "label": label,
        "unit": unit,
        "input": input_kind.value,
        "flag": spec.flag,
        "supports_all": spec.supports_all,
        "source": spec.source,
        "frequency": spec.frequency,
        "missing_semantics": spec.missing_semantics,
    }


SCREEN_FILTER_CATALOG: dict[str, FilterCatalogEntry] = {
    filter_type: _entry(filter_type, label, unit, input_kind)
    for _group, entries in _GROUPS
    for filter_type, label, unit, input_kind in entries
}


def screen_filter_groups() -> list[dict[str, object]]:
    """返回前端和 AI 可发现的分组条件目录。"""
    return [
        {
            "label": label,
            "options": [SCREEN_FILTER_CATALOG[filter_type] for filter_type, *_ in entries],
        }
        for label, entries in _GROUPS
    ]


def assert_catalog_complete() -> None:
    expected = set(FILTER_SPECS) - {"exclude_st"}
    enum_values = {item.value for item in ScreenFilterType}
    actual = set(SCREEN_FILTER_CATALOG)
    if actual != expected or enum_values != expected:
        raise RuntimeError(
            "选股条件目录与核心 FILTER_SPECS 漂移: "
            f"catalog_missing={sorted(expected - actual)}, "
            f"catalog_extra={sorted(actual - expected)}, "
            f"enum_missing={sorted(expected - enum_values)}, "
            f"enum_extra={sorted(enum_values - expected)}"
        )


assert_catalog_complete()
