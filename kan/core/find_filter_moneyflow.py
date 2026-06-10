"""资金流维度 matcher。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kan.core.find_dsl import MoneyflowDailyFilter, MoneyflowDaysFilter, MoneyflowFilter, apply_op
from kan.core.find_filter_models import TriggeredFilter

if TYPE_CHECKING:
    from kan.core.models import MoneyflowMetrics


def _match_moneyflow(
    filter: MoneyflowFilter, moneyflow: MoneyflowMetrics | None
) -> TriggeredFilter | None:
    """匹配主力资金 filter · 5 日合计优先，缺失回落单日净额。"""
    if moneyflow is None:
        return None
    actual = moneyflow.net_amount_5d
    if actual is None:
        actual = moneyflow.net_amount
    if actual is None:
        return None
    if apply_op(filter.op, actual, filter.value):
        return TriggeredFilter(
            filter_type="moneyflow",
            param=f"{filter.op}:{filter.value:g}",
            value=actual,
        )
    return None


def _match_moneyflow_daily(
    filter: MoneyflowDailyFilter, moneyflow: MoneyflowMetrics | None
) -> TriggeredFilter | None:
    """匹配单日主力净额 filter · net_amount 缺失不命中。"""
    if moneyflow is None or moneyflow.net_amount is None:
        return None
    if apply_op(filter.op, moneyflow.net_amount, filter.value):
        return TriggeredFilter(
            filter_type="moneyflow_daily",
            param=f"{filter.op}:{filter.value:g}",
            value=moneyflow.net_amount,
        )
    return None


def _match_moneyflow_days(
    filter: MoneyflowDaysFilter, moneyflow: MoneyflowMetrics | None
) -> TriggeredFilter | None:
    """匹配连续主力净流入天数 filter · inflow_days 缺失不命中。"""
    if moneyflow is None or moneyflow.inflow_days is None:
        return None
    if apply_op(filter.op, float(moneyflow.inflow_days), filter.value):
        return TriggeredFilter(
            filter_type="moneyflow_days",
            param=f"{filter.op}:{filter.value:g}",
            value=float(moneyflow.inflow_days),
        )
    return None
