"""一次读取日线，形成群体分布与相邻等长窗口的变化剖面。"""

import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from math import isclose

import numpy as np

from kan.core.returns import rolling_returns
from kan.domain.discovery import (
    DiscoveryBin,
    DiscoveryComparison,
    DiscoveryDataGap,
    DiscoveryGroup,
    DiscoveryHistoryPoint,
    DiscoveryMember,
    DiscoveryObservation,
    DiscoveryQuery,
    DiscoveryResult,
    DiscoveryStats,
    DiscoveryTransition,
    TransitionKey,
)
from kan.service.market_study import resolve_market_calendar
from kan.service.trend_search import TrendSearchQuery, _scope, prepare_cached_history

_TRANSITIONS: tuple[tuple[TransitionKey, str], ...] = (
    ("up_up", "两段均上涨"), ("down_up", "前段下跌 · 本段上涨"),
    ("up_down", "前段上涨 · 本段下跌"), ("down_down", "两段均下跌"),
    ("flat", "至少一段持平"), ("unknown", "两段无法比较"),
)
_BINS = (
    ("below_m10", "低于 −10%"), ("m10_m5", "−10% 至 −5%（不含）"),
    ("m5_0", "−5% 至 0%（不含）"), ("zero", "持平"),
    ("0_5", "0%（不含）至 5%"), ("5_10", "5%（不含）至 10%"),
    ("above_10", "高于 10%"),
)


def _number(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _distribution_bin(value: float | None) -> str | None:
    if value is None:
        return None
    # 只消除端点比值在分桶边界的浮点尾差，不改变原始收益或涨跌方向。
    for boundary in (-10, -5, 5, 10):
        if isclose(value, boundary, rel_tol=1e-12, abs_tol=0):
            value = boundary
            break
    if value < -10:
        return "below_m10"
    if value < -5:
        return "m10_m5"
    if value < 0:
        return "m5_0"
    if value == 0:
        return "zero"
    if value <= 5:
        return "0_5"
    if value <= 10:
        return "5_10"
    return "above_10"


def return_transition(previous: float | None, current: float | None) -> TransitionKey:
    if previous is None or current is None:
        return "unknown"
    if previous == 0 or current == 0:
        return "flat"
    if previous > 0:
        return "up_up" if current > 0 else "up_down"
    return "down_up" if current > 0 else "down_down"


def _stats(values: np.ndarray, total: int) -> DiscoveryStats:
    values = values[np.isfinite(values)]
    count = len(values)
    up = int(np.count_nonzero(values > 0))
    down = int(np.count_nonzero(values < 0))
    return DiscoveryStats(
        total=total, available=count, missing=total - count,
        up=up, down=down, flat=count - up - down,
        positive_share=up / count * 100 if count else None,
        median_return=float(np.median(values)) if count else None,
        q25=float(np.quantile(values, .25)) if count else None,
        q75=float(np.quantile(values, .75)) if count else None,
    )


def compare_returns(previous: np.ndarray, current: np.ndarray) -> DiscoveryComparison:
    """同一成员顺序的两组收益，只比较两端均完整者。"""
    paired = np.isfinite(current) & np.isfinite(previous)
    current_pair, previous_pair = _stats(current[paired], len(current)), _stats(previous[paired], len(current))
    return DiscoveryComparison(
        available=int(paired.sum()), missing=int((~paired).sum()),
        current_positive_share=current_pair.positive_share,
        previous_positive_share=previous_pair.positive_share,
        breadth_delta_pp=current_pair.positive_share - previous_pair.positive_share if paired.any() else None,  # type: ignore[operator]
        current_median=current_pair.median_return, previous_median=previous_pair.median_return,
    )


def _observations(stats: DiscoveryStats, comparison: DiscoveryComparison, window: int) -> list[DiscoveryObservation]:
    if not stats.available:
        return [DiscoveryObservation(kind="coverage", title="本窗口还没有可判断的成员", detail=f"完整范围 {stats.total} 只；需要最近 {window + 1} 个市场交易日的完整日线。缺失不算下跌或持平。")]
    observations = [DiscoveryObservation(
        kind="breadth", title=f"{stats.up} / {stats.available} 只在本窗口上涨",
        detail=f"上涨占比 {stats.positive_share:.1f}%；下跌 {stats.down} 只，持平 {stats.flat} 只，另有 {stats.missing} 只资料不足。",
    )]
    if comparison.available:
        delta = comparison.breadth_delta_pp
        assert delta is not None
        observations.append(DiscoveryObservation(
            kind="comparison", title=f"同一批成员的上涨占比{'增加' if delta > 0 else '减少' if delta < 0 else '不变'}{f' {abs(delta):.1f} 个百分点' if delta else ''}",
            detail=f"两个相邻 {window} 交易日窗口、同一批 {comparison.available} 只：前段 {comparison.previous_positive_share:.1f}%，本段 {comparison.current_positive_share:.1f}%。这是已发生的参与范围变化。",
        ))
    else:
        observations.append(DiscoveryObservation(kind="coverage", title="暂不能比较两个窗口", detail=f"需要两段均有完整日线；{comparison.missing} 只暂不参与变化判断。"))
    observations.append(DiscoveryObservation(
        kind="distribution", title=f"中间一半成员的涨跌在 {stats.q25:+.2f}% 至 {stats.q75:+.2f}%",
        detail=f"本窗口收益中位数 {stats.median_return:+.2f}%。区间为第 25–75 分位，描述成员差异，不是行业指数或未来区间。",
    ))
    return observations


def _group(
    name: str, members: list[DiscoveryMember], history: np.ndarray, days: list[date], window: int,
    as_of: date, previous_as_of: date | None, previous_start: date | None,
) -> DiscoveryGroup:
    total = len(members)
    current = np.array([item.return_pct if item.return_pct is not None else np.nan for item in members])
    previous = np.array([item.previous_return_pct if item.previous_return_pct is not None else np.nan for item in members])
    stats = _stats(current, total)
    comparison = compare_returns(previous, current)
    # 每个轨迹点都用相同成员，防止新上市或缺数据造成虚假的扩散/收缩。
    fixed = history[np.isfinite(history).all(axis=1)]
    points = []
    for index, day in enumerate(days):
        point = _stats(fixed[:, index], len(fixed))
        points.append(DiscoveryHistoryPoint(
            date=day, available=point.available, up=point.up, down=point.down, flat=point.flat,
            positive_share=point.positive_share, median_return=point.median_return,
        ))
    transitions = Counter(item.transition for item in members)
    bins = Counter(item.distribution_bin for item in members)
    # 识别用户看到的事实，而非查询入口；行业下钻与同范围查询必须得到同一指纹。
    facts = {
        "window": window, "as_of": as_of.isoformat(),
        "current_start": previous_as_of.isoformat() if previous_as_of else None,
        "previous_as_of": previous_as_of.isoformat() if previous_as_of else None,
        "previous_start": previous_start.isoformat() if previous_start else None,
        "members": [item.model_dump(mode="json") for item in sorted(members, key=lambda item: item.symbol)],
        "current": stats.model_dump(mode="json"),
        "comparison": comparison.model_dump(mode="json"),
        "history": [point.model_dump(mode="json") for point in points],
        "history_available": len(fixed),
    }
    fingerprint = hashlib.sha256(json.dumps(
        facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()[:24]
    return DiscoveryGroup(
        name=name, fingerprint=fingerprint, total=total, current=stats, comparison=comparison,
        history=points, history_available=len(fixed),
        transitions=[DiscoveryTransition(key=key, label=label, count=transitions[key]) for key, label in _TRANSITIONS],
        distribution=[DiscoveryBin(key=key, label=label, count=bins[key]) for key, label in _BINS],
        observations=_observations(stats, comparison, window),
    )


def discover_market(query: DiscoveryQuery) -> DiscoveryResult:
    """不筛股票、不保存任务；以完整成员范围观察事实，再允许显式下钻。"""
    calendar, as_of = resolve_market_calendar(query.as_of)
    sessions = [day for day in calendar if day <= as_of]
    previous_as_of = sessions[-query.window - 1] if len(sessions) > query.window else None
    previous_start = sessions[-2 * query.window - 1] if len(sessions) > 2 * query.window else None
    days = sessions[-query.window:]
    scope, industries, _choices = _scope(TrendSearchQuery(
        universe=query.universe, codes=query.codes, industries=query.industries, as_of=as_of,
    ))
    scope.sort(key=lambda item: item[0])
    history = np.full((len(scope), len(days)), np.nan)
    members: list[DiscoveryMember] = []
    cutoffs: Counter[date] = Counter()
    missing_dates: Counter[date] = Counter()
    industry_indices: dict[str, list[int]] = defaultdict(list)
    for index, (symbol, name) in enumerate(scope):
        current = previous = change = None
        available = False
        source = ""
        reason = None
        try:
            frame = prepare_cached_history(symbol, sessions)
            valid_dates = frame.index[frame.valid]
            if len(valid_dates):
                cutoffs[valid_dates[-1]] += 1
                source = " / ".join(dict.fromkeys(frame.loc[frame.valid, "_source"].astype(str)))
                # 仅统计已经有过有效行情之后、两个所需窗口内的缺日；不猜上市前历史。
                gap_start = max(valid_dates[0], previous_start or sessions[0])
                missing_dates.update(day for day in frame.index[~frame.valid] if day >= gap_start)
            close, valid = frame.close.to_numpy(dtype=float), frame.valid.to_numpy(dtype=bool)
            returns = rolling_returns(close, valid, query.window)
            changes = rolling_returns(close, valid, 1)
            if len(frame):
                current, change = _number(returns[-1]), _number(changes[-1])
                available = bool(valid[-1])
                previous_index = len(frame) - query.window - 1
                previous = _number(returns[previous_index]) if previous_index >= 0 else None
                # 工作帧已经逐市场日对齐且止于 as_of；较晚上市成员的前部继续留空。
                shown = min(len(days), len(frame))
                history[index, -shown:] = returns[-shown:]
            if current is None:
                reason = f"最近 {query.window + 1} 个市场交易日的完整日线不足"
            elif previous is None:
                reason = "前一窗口资料不足；本窗口事实仍可查看"
        except (ValueError, OSError) as exc:
            reason = str(exc)
        industry = industries.get(symbol, "未分类")
        members.append(DiscoveryMember(
            symbol=symbol, name=name, industry=industry, latest_available=available,
            return_pct=current, previous_return_pct=previous, change_pct=change,
            transition=return_transition(previous, current), distribution_bin=_distribution_bin(current),
            source=source, reason=reason,
        ))
        industry_indices[industry].append(index)
    common_date = max(cutoffs, key=lambda day: (cutoffs[day], day)) if cutoffs else None
    data_gaps = [
        DiscoveryDataGap(date=day, missing=missing_dates[day])
        for day in sorted(missing_dates, key=lambda day: (missing_dates[day], day), reverse=True)
    ]
    gap_warnings = []
    if data_gaps:
        concentrated = data_gaps[:3]
        details = "；".join(f"{gap.date} 有 {gap.missing} 只股票缺少有效日线" for gap in concentrated)
        other_dates = f"，另有 {len(data_gaps) - len(concentrated)} 个交易日有缺口" if len(data_gaps) > len(concentrated) else ""
        gap_warnings.append(
            f"所需窗口的共同缺口：{details}{other_dates}。请核对这些日期的来源截面；"
            "仅统计已有有效行情之后的缺日，缺失仍按未知处理，不推断停牌或涨跌。"
        )
    return DiscoveryResult(
        query=query, as_of=as_of, current_start=previous_as_of, previous_as_of=previous_as_of,
        previous_start=previous_start, common_data_date=common_date,
        common_data_count=cutoffs[common_date] if common_date else 0,
        market=_group("全部范围", members, history, days, query.window, as_of, previous_as_of, previous_start),
        industries=[_group(name, [members[index] for index in indices], history[indices], days, query.window, as_of, previous_as_of, previous_start) for name, indices in sorted(industry_indices.items())],
        members=members, data_gaps=data_gaps,
        warnings=[
            *gap_warnings,
            "使用当前上市范围与当前行业归属回溯，不代表历史时点全市场。",
            "当前分布使用本窗口完整成员；两段变化仅使用两个相邻等长窗口均完整的同一批成员。",
            "轨迹在每个日期计算同一长度的滚动收益，所有点使用整条轨迹均可判断的固定成员；其分母可能小于当前分布。",
            "区间涨跌使用同一复权基准的端点比值，缺市场交易日不跳过、不填零。中位数与分位数不是行业指数。",
            "仅描述历史价格事实，不推断原因、预测或生成股票推荐。",
        ],
    )
