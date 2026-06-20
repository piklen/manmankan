"""Agent summary helpers for `kan find` JSON."""

from __future__ import annotations

from numbers import Number


def _nested_get(source: dict, path: tuple[str, ...]) -> object:
    current: object = source
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _flatten_values(value: object, *, prefix: str = "") -> dict[str, object]:
    """Flatten result rows for coverage/distribution summaries."""
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten_values(item, prefix=child))
        return out
    if isinstance(value, list):
        return {prefix: value} if prefix else {}
    return {prefix: value} if prefix else {}


def _field_coverage(rows: list[dict]) -> dict[str, dict[str, object]]:
    total = len(rows)
    seen: dict[str, int] = {}
    for row in rows:
        for path, value in _flatten_values(row).items():
            if value is not None and value != {} and value != []:
                seen[path] = seen.get(path, 0) + 1
    return {
        path: {
            "available": count,
            "missing": total - count,
            "coverage": None if total == 0 else round(count / total, 4),
        }
        for path, count in sorted(seen.items())
    }


def _numeric_distribution(rows: list[dict], path: str) -> dict | None:
    values: list[float] = []
    path_parts = tuple(path.split("."))
    for row in rows:
        value = _nested_get(row, path_parts)
        if isinstance(value, Number) and not isinstance(value, bool):
            values.append(float(value))
    if not values:
        return None
    values.sort()
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    return {
        "count": len(values),
        "min": values[0],
        "median": median,
        "max": values[-1],
    }


def agent_summary(
    rows: list[dict],
    *,
    stats: dict,
    data_availability: dict,
    sample_size: int = 5,
) -> dict:
    """Low-context factual summary for agent first-pass reads."""
    distribution_paths = (
        "price",
        "context.low_resonance",
        "context.high_resonance",
        "valuation.pe_ttm",
        "valuation.pb",
        "valuation.turnover_rate",
        "moneyflow.net_amount",
        "moneyflow.net_amount_5d",
        "technical.rsi_6",
        "technical.macd",
        "sentiment.limit_times",
        "chip.winner_rate",
    )
    distributions = {
        path: dist
        for path in distribution_paths
        if (dist := _numeric_distribution(rows, path)) is not None
    }
    return {
        "basis": "matched_results",
        "stats": stats,
        "data_availability": data_availability,
        "field_coverage": _field_coverage(rows),
        "distributions": distributions,
        "sample_size": min(sample_size, len(rows)),
        "next_command": "kan find ... --format json --limit 50 --offset <shown>",
    }


__all__ = ["agent_summary"]
