"""把 scan 结果按需 enrich 多维指标。

`StockScanResult` (K 线衍生位置 / 共振) + 按需挂载的截面/财务子对象 → `EnrichedResult`:
- valuation (daily_basic 截面 · 扫描默认挂载，研究按需请求)
- moneyflow (moneyflow_dc 截面 · need_moneyflow · 同截面廉价)
- fundamentals (fina_indicator 逐股 · need_fundamentals · 逐股 HTTP 贵 · 严格按需)

设计要点:
- 成本分级:截面 (valuation/moneyflow) 一次拉全市场切子集 · 逐股 (fundamentals) N 次 HTTP ·
  fundamentals 仅 need_fundamentals=True (用户传 --roe) 才拉 · 避免无谓逐股
- 优雅降级:无 token / 失败 → 对应子对象 None · AI 消费契约仍成立 (结构 + disclaimer 在)
- 顺序保持:返回顺序与入参 results 一致 (find 命中排序不被打乱)

合规 (compliance §6/§7):本层只把原始指标值挂到对象上 · 不算分位 / 不判断。
输出层负责把已请求维度序列化为 JSON / Markdown。
"""
from __future__ import annotations

# ruff: noqa: F401
from kan.core.enrich_index import (
    _index_chip,
    _index_moneyflow,
    _index_sentiment,
    _index_technical,
    _index_valuations,
    _resolve_fallback_date,
)
from kan.core.enrich_relative_strength import (
    _build_rs_metrics,
    _compute_rs_benchmarks,
    _stock_gains,
    attach_relative_strength,
    attach_relative_strength_cross_section,
)
from kan.core.enrich_results import enrich_results, fetch_enrichments
from kan.core.enrich_rows import (
    _opt_float,
    _row_to_chip,
    _row_to_fundamentals,
    _row_to_moneyflow,
    _row_to_sentiment,
    _row_to_shareholder,
    _row_to_technical,
    _row_to_valuation,
)
from kan.core.enrich_scan import (
    _ex_reference_price,
    _latest_corporate_action_marker,
    _moneyflow_5d_by_symbol,
    _recent_trade_dates,
    enrich_scan_rows,
)

__all__ = [
    "attach_relative_strength",
    "attach_relative_strength_cross_section",
    "enrich_results",
    "enrich_scan_rows",
    "fetch_enrichments",
]
