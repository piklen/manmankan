"""按请求维度组织研究事实、单位和质量信息，复用现有行情与指标服务。"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime
from typing import Any

from kan.core.models import StockScanResult
from kan.domain.research import (
    ResearchBundle,
    ResearchCoverage,
    ResearchDimension,
    ResearchEvidence,
    ResearchFact,
    ResearchFailure,
    ResearchRequest,
    ResearchSubject,
)

# 保持源字段与换算关系显式；金额统一为元，比例保持百分数而不是小数。
_FIELDS: dict[str, tuple[tuple[str, str, str, float], ...]] = {
    "valuation": (
        ("pe_ttm", "市盈率 TTM", "倍", 1),
        ("pb", "市净率", "倍", 1),
        ("ps_ttm", "市销率 TTM", "倍", 1),
        ("dv_ttm", "股息率 TTM", "%", 1),
        ("total_mv", "总市值", "元", 10_000),
        ("circ_mv", "流通市值", "元", 10_000),
        ("turnover_rate", "换手率", "%", 1),
        ("volume_ratio", "量比", "倍", 1),
    ),
    "fundamentals": (
        ("roe", "净资产收益率", "%", 1),
        ("netprofit_yoy", "净利润同比", "%", 1),
        ("or_yoy", "营业收入同比", "%", 1),
    ),
    "moneyflow": (
        ("net_amount", "当日主力净额", "元", 10_000),
        ("net_amount_5d", "近5日主力净额", "元", 10_000),
        ("inflow_days", "连续主力净流入", "天", 1),
        ("outflow_days", "连续主力净流出", "天", 1),
    ),
    "technical": (
        ("rsi_6", "RSI 6日", "指标值", 1),
        ("macd_dif", "MACD DIF", "元", 1),
        ("macd", "MACD 柱", "元", 1),
        ("kdj_j", "KDJ J", "指标值", 1),
        ("ma_5", "5日均线", "元", 1),
        ("ma_20", "20日均线", "元", 1),
        ("ma_60", "60日均线", "元", 1),
        ("atr_pct", "ATR 波动率", "%", 1),
    ),
    "sentiment": (
        ("limit_times", "连板天数", "天", 1),
        ("open_times", "开板/炸板次数", "次", 1),
        ("fd_amount", "封单金额原值", "源单位未核实", 1),
    ),
    "chip": (
        ("winner_rate", "获利盘比例", "%", 1),
        ("cost_5pct", "5分位成本", "元", 1),
        ("cost_50pct", "50分位成本", "元", 1),
        ("cost_95pct", "95分位成本", "元", 1),
    ),
    "shareholder": (
        ("holder_num", "股东户数", "户", 1),
        ("holder_chg_pct", "股东户数环比", "%", 1),
        ("top10_float_ratio", "十大流通股东占比", "%", 1),
        ("north_hold_ratio", "北向名义持有人季度占比", "%", 1),
    ),
}


def _hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _number(value: Any, multiplier: float = 1) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value) * multiplier
    except (TypeError, ValueError):
        return None
    return round(number, 8) if math.isfinite(number) else None


def _date(value: Any) -> date | None:
    return value if isinstance(value, date) else None


def _evidence(
    *, symbol: str, dimension: ResearchDimension, source: str | None,
    expected: date, facts: list[ResearchFact], data_date: date | None = None,
    report_period: date | None = None, announcement_date: date | None = None,
    fetched_at: str | None = None,
    notes: list[str] | None = None,
) -> ResearchEvidence:
    missing = [fact.field_id for fact in facts if fact.value is None]
    messages = list(notes or [])
    freshness: Any = "unknown"
    if len(missing) == len(facts):
        freshness = "unavailable"
    elif dimension is ResearchDimension.FUNDAMENTALS and report_period and announcement_date and fetched_at and source:
        # 财务服务只返回24小时内检查过的缓存；公告日不需要等于行情交易日。
        freshness = "fresh"
    elif data_date is not None and data_date < expected:
        freshness = "stale"
        messages.append("该维度早于最新完整交易日")
    elif data_date == expected and source:
        freshness = "fresh"
    elif data_date is not None and data_date > expected:
        messages.append("数据日晚于预期交易日，需复核日期口径")
    else:
        messages.append("缺少可核对的数据日期或来源，未认定为最新数据")
    section = ResearchEvidence(
        evidence_ref="", symbol=symbol, dimension=dimension, source=source,
        data_date=data_date, report_period=report_period, fetched_at=fetched_at,
        announcement_date=announcement_date,
        adjustment="qfq" if dimension in (ResearchDimension.MARKET, ResearchDimension.TECHNICAL) else None,
        freshness=freshness, facts=facts, missing_fields=missing, notes=messages,
    )
    # 引用绑定事实内容及来源/日期；抓取时间变化不应改变相同证据的身份。
    identity = section.model_dump(mode="json", exclude={"evidence_ref", "fetched_at"})
    return section.model_copy(update={"evidence_ref": f"evidence:{_hash(identity)}"})


def _market_evidence(
    result: StockScanResult, frame: Any, expected: date, fetched_at: str | None,
) -> ResearchEvidence:
    sources = (
        sorted(set(frame["_source"].dropna().astype(str)) - {"", "unknown", "nan"})
        if "_source" in frame else []
    )
    facts = [ResearchFact(
        field_id="market.close", label="前复权收盘价", value=_number(result.current_price), unit="元",
    )]
    for period in result.periods:
        for field, label, value in (
            ("position", "区间位置", period.position_pct),
            ("gain", "区间涨跌幅", period.gain_pct),
        ):
            facts.append(ResearchFact(
                field_id=f"market.{field}_{period.period}", label=f"{period.period}日{label}",
                value=None if period.insufficient else _number(value), unit="%", window=period.period,
            ))
    return _evidence(
        symbol=result.symbol, dimension=ResearchDimension.MARKET,
        source=",".join(sources) or None, expected=expected, facts=facts,
        data_date=result.scan_date, fetched_at=fetched_at,
        notes=["沿用行情缓存的前复权口径；本包未验证跨除权日的复权基准一致性"],
    )


def _metric_evidence(symbol: str, holder: Any, dimension: ResearchDimension, expected: date) -> ResearchEvidence:
    facts = []
    for field, label, unit, multiplier in _FIELDS[dimension.value]:
        value = getattr(holder, field, None)
        # ATR 百分比复用核心方法，不把方法对象当作缺失数值。
        if dimension is ResearchDimension.TECHNICAL and field == "atr_pct" and callable(value):
            value = value()
        facts.append(ResearchFact(
            field_id=f"{dimension.value}.{field}", label=label,
            value=_number(value, multiplier), unit=unit,
        ))
    notes: list[str] = []
    report_period = _date(getattr(holder, "end_date", None))
    announcement_date = _date(getattr(holder, "ann_date", None))
    if dimension is ResearchDimension.FUNDAMENTALS:
        notes.append("报告期、公告日和数据源检查时间分别记录；财务按需每日检查，可用 --refresh 立即更新")
        if announcement_date is None:
            notes.append("数据源未提供公告日，不用报告期推断发布时间")
    elif dimension is ResearchDimension.SHAREHOLDER:
        # 两种报告期可能不同，不能把它们合成一个看似统一的截止日。
        for name in ("holder_end_date", "top10_end_date"):
            period = _date(getattr(holder, name, None))
            if period:
                notes.append(f"{name}={period.isoformat()}")
        notes.append("股东数据按披露口径；北向名义持有人占比是季度代理，非实时资金流")
    elif dimension is ResearchDimension.SENTIMENT:
        facts.append(ResearchFact(
            field_id="sentiment.limit", label="事件类型", value=getattr(holder, "limit", None),
            unit="U涨停/D跌停/Z炸板",
        ))
        notes.append("涨跌停事件为稀疏数据；未取得事件不等于已确认未发生事件")
        notes.append("封单金额保留源原值；上游未明确单位，不能与元单位字段直接比较")
    elif dimension is ResearchDimension.CHIP:
        notes.append("筹码成本为上游估算口径，不代表真实账户持仓成本")
    return _evidence(
        symbol=symbol, dimension=dimension, source=getattr(holder, "source", None),
        expected=expected, facts=facts, data_date=_date(getattr(holder, "trade_date", None)),
        report_period=report_period, announcement_date=announcement_date,
        fetched_at=getattr(holder, "fetched_at", None), notes=notes,
    )


def build_research_bundle(request: ResearchRequest) -> ResearchBundle:
    """生成不含个人持仓的研究包；只补请求维度，缺口不会被填成零。"""
    from kan.core.enrich import fetch_enrichments
    from kan.core.scanner import scan_stock
    from kan.core.trading_calendar import latest_trade_date
    from kan.data.fetcher import DEFAULT_KLINE_DAYS, cache_age, fetch_batch
    from kan.render.base import DISCLAIMER
    from kan.storage.watchlist import load_stock_names_cache

    expected = latest_trade_date()
    frames: dict[str, Any] = {}
    fetch_errors: dict[str, str] = {}
    if ResearchDimension.MARKET in request.dimensions:
        try:
            # 180日涨幅需要181根日K，同时保留共享缓存的默认历史深度。
            frames, fetch_errors = fetch_batch(
                request.codes, days=max(181, DEFAULT_KLINE_DAYS), force=request.refresh,
            )
        except Exception:
            fetch_errors = dict.fromkeys(request.codes, "data_unavailable")
    try:
        names = load_stock_names_cache(allow_stale=True) or {}
    except Exception:
        names = {}
    errors: list[ResearchFailure] = []
    evidence: list[ResearchEvidence] = []
    dimensions = {item.value for item in request.dimensions if item is not ResearchDimension.MARKET}
    metrics: dict[str, dict[str, Any]] = {}
    if dimensions:
        try:
            metrics = fetch_enrichments(
                request.codes, dimensions=dimensions, force=request.refresh, require_source_dates=True,
            )
        except Exception:
            errors.append(ResearchFailure(code="enrichment_unavailable", message="指标补充失败，已保留其他可用事实"))
    subjects: list[ResearchSubject] = []
    for symbol in request.codes:
        sections = []
        for dimension in request.dimensions:
            if dimension is ResearchDimension.MARKET:
                frame = frames.get(symbol)
                if symbol in fetch_errors or frame is None or frame.empty:
                    errors.append(ResearchFailure(symbol=symbol, code="data_unavailable", message="未取得可用历史行情"))
                    continue
                try:
                    result = scan_stock(frame, symbol, names.get(symbol, symbol), periods=[20, 60, 180])
                    sections.append(_market_evidence(result, frame, expected, cache_age(symbol)))
                except (ValueError, KeyError, TypeError, IndexError):
                    errors.append(ResearchFailure(symbol=symbol, code="invalid_market_data", message="历史行情无法形成研究事实"))
            else:
                sections.append(_metric_evidence(symbol, metrics.get(symbol, {}).get(dimension.value), dimension, expected))
        evidence.extend(sections)
        if any(item.freshness != "unavailable" for item in sections):
            subjects.append(ResearchSubject(
                symbol=symbol, name=names.get(symbol, symbol),
                evidence_refs=[item.evidence_ref for item in sections],
            ))
    available = sum(item.freshness != "unavailable" for item in evidence)
    fresh = sum(item.freshness == "fresh" for item in evidence)
    missing = sum(len(item.missing_fields) for item in evidence)
    requested = len(request.codes) * len(request.dimensions)
    status: Any = "complete" if fresh == requested and not missing and not errors else "partial"
    if not subjects:
        status = "unavailable"
        if not errors:
            errors.append(ResearchFailure(code="data_unavailable", message="所请求维度暂无可用数据"))
    identity = {"request": request.model_dump(mode="json"), "evidence": [item.evidence_ref for item in evidence]}
    return ResearchBundle(
        ok=not errors, bundle_id=f"research:{_hash(identity)}", generated_at=datetime.now(UTC),
        expected_trade_date=expected, request=request, status=status, subjects=subjects, evidence=evidence,
        coverage=ResearchCoverage(
            requested_symbols=len(request.codes), available_symbols=len(subjects),
            requested_sections=requested, available_sections=available, fresh_sections=fresh, missing_facts=missing,
        ),
        errors=errors,
        limitations=[
            "这是事实包，没有调用模型；引用可定位证据，不代表证据已支持任何投资结论",
            "未请求的维度不在本包范围；公告、新闻、现金流量表和交易复盘尚未接入本入口",
            "生成时间不是数据时间；fresh 表示日频日期一致或财务来源近期已检查，不证明数值或复权基准无误",
            "没有源交易日的日频指标行不进入事实包，避免用查询日期补成最新数据",
        ],
        disclaimer=DISCLAIMER,
    )
