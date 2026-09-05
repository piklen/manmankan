"""研究事实的人类可读视图，数值直接使用共享证据包。"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from kan.domain.research import ResearchBundle


def print_research_bundle(bundle: ResearchBundle) -> None:
    console = Console()
    labels = {"complete": "所请求字段完整且已核对", "partial": "存在缺口或待核对日期", "unavailable": "暂无可用数据"}
    freshness = {"fresh": "已核对", "stale": "陈旧", "unknown": "待核对", "unavailable": "不可用"}
    console.print(f"慢慢看 · 研究证据包 · {labels[bundle.status]}", markup=False)
    console.print(f"预期交易日 {bundle.expected_trade_date} · 覆盖 {bundle.coverage.available_symbols}/{bundle.coverage.requested_symbols} 只", markup=False)
    by_ref = {item.evidence_ref: item for item in bundle.evidence}
    for subject in bundle.subjects:
        console.print(f"\n{subject.name} · {subject.symbol}", markup=False)
        for ref in subject.evidence_refs:
            section = by_ref[ref]
            date_text = section.data_date or section.report_period or "未知"
            console.print(f"{section.dimension} · {section.source or '来源未知'} · {date_text} · {freshness[section.freshness]}", markup=False)
            if section.announcement_date is not None:
                console.print(f"公告日 {section.announcement_date} · 数据源检查 {section.fetched_at or '未知'}", markup=False)
            table = Table(show_header=True, box=None, padding=(0, 1))
            table.add_column("事实", no_wrap=True)
            table.add_column("数值", justify="right")
            table.add_column("单位")
            for fact in section.facts:
                value = fact.value
                text = "缺失" if value is None else (value if isinstance(value, str) else f"{value:,.4f}".rstrip("0").rstrip("."))
                table.add_row(fact.label, text, fact.unit)
            console.print(table)
            for note in section.notes:
                console.print(f"  {note}", markup=False)
            console.print(f"  引用 {ref}", markup=False)
    for error in bundle.errors:
        console.print(f"{error.symbol or '指标'} · {error.code} · {error.message}", markup=False)
    for limitation in bundle.limitations:
        console.print(limitation, markup=False)
    console.print(bundle.disclaimer, markup=False)
