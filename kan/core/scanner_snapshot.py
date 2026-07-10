"""scan 快照保存、读取和差异计算。"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from kan.core.models import StockScanResult

_SNAPSHOT_KEEP_DAYS = 240
_WEB_SNAPSHOT_SCHEMA_VERSION = 1


def save_snapshot(results: list[StockScanResult]) -> None:
    """保存本次 scan 结果快照（last_scan.json + 按日归档）。"""
    from kan.storage.paths import SNAPSHOT_PATH, SNAPSHOTS_DIR, atomic_write_json, ensure_dirs

    ensure_dirs()
    data = []
    for r in results:
        data.append({
            "symbol": r.symbol,
            "name": r.name,
            "periods": {
                str(p.period): {"pct": p.position_pct, "at_low": p.at_low, "at_high": p.at_high}
                for p in r.periods if not p.insufficient
            },
        })
    atomic_write_json(SNAPSHOT_PATH, data, ensure_ascii=False)

    daily = SNAPSHOTS_DIR / f"{date.today().isoformat()}.json"
    atomic_write_json(daily, data, ensure_ascii=False)

    cutoff = date.today() - timedelta(days=_SNAPSHOT_KEEP_DAYS)
    for old in SNAPSHOTS_DIR.glob("*.json"):
        try:
            file_date = date.fromisoformat(old.stem)
            if file_date < cutoff:
                old.unlink()
        except ValueError:
            pass


def save_web_daily_snapshot(
    results: list[StockScanResult],
    *,
    data_cutoff: date,
) -> None:
    """保存 Web 每日概览快照，不触碰 CLI diff/history 命名空间。"""
    from kan.storage.paths import WEB_SNAPSHOTS_DIR, atomic_write_json, ensure_dirs

    ensure_dirs()
    rows = _snapshot_rows(results)
    payload = {
        "schema_version": _WEB_SNAPSHOT_SCHEMA_VERSION,
        "surface": "web",
        "data_cutoff": data_cutoff.isoformat(),
        "observed_at": datetime.now(UTC).isoformat(),
        "periods": sorted({int(period) for row in rows for period in row["periods"]}),
        "results": rows,
    }
    daily = WEB_SNAPSHOTS_DIR / f"{data_cutoff.isoformat()}.json"
    atomic_write_json(daily, payload, ensure_ascii=False)

    cutoff = date.today() - timedelta(days=_SNAPSHOT_KEEP_DAYS)
    for old in WEB_SNAPSHOTS_DIR.glob("*.json"):
        try:
            if date.fromisoformat(old.stem) < cutoff:
                old.unlink()
        except ValueError:
            pass


def load_previous_web_daily_snapshot(
    before: date,
) -> tuple[date, dict[str, dict[str, dict]]] | None:
    """读取当前行情日之前最近一份有效 Web 快照。"""
    from kan.storage.paths import WEB_SNAPSHOTS_DIR

    candidates: list[tuple[date, Path]] = []
    for path in WEB_SNAPSHOTS_DIR.glob("*.json"):
        try:
            snapshot_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if snapshot_date < before:
            candidates.append((snapshot_date, path))
    if not candidates:
        return None

    for snapshot_date, path in sorted(candidates, reverse=True):
        parsed = _load_web_snapshot(path, expected_date=snapshot_date)
        if parsed is not None:
            return snapshot_date, parsed
    return None


def _load_web_snapshot(
    path: Path,
    *,
    expected_date: date,
) -> dict[str, dict[str, dict]] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _WEB_SNAPSHOT_SCHEMA_VERSION
            or payload.get("surface") != "web"
            or payload.get("data_cutoff") != expected_date.isoformat()
            or not isinstance(payload.get("results"), list)
        ):
            return None
        parsed: dict[str, dict[str, dict]] = {}
        for item in payload["results"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("symbol"), str)
                or not isinstance(item.get("periods"), dict)
            ):
                return None
            periods: dict[str, dict] = {}
            for period, values in item["periods"].items():
                if not isinstance(period, str) or not isinstance(values, dict):
                    return None
                pct = values.get("pct")
                if not isinstance(pct, int | float):
                    return None
                periods[period] = values
            parsed[item["symbol"]] = periods
        return parsed
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _snapshot_rows(results: list[StockScanResult]) -> list[dict]:
    rows: list[dict] = []
    for result in results:
        rows.append({
            "symbol": result.symbol,
            "name": result.name,
            "periods": {
                str(period.period): {
                    "pct": period.position_pct,
                    "at_low": period.at_low,
                    "at_high": period.at_high,
                }
                for period in result.periods if not period.insufficient
            },
        })
    return rows


def load_snapshot() -> dict[str, dict[str, dict]] | None:
    """加载上次快照。返回 {symbol: {period_str: {pct, at_low, at_high}}}"""
    from kan.storage.paths import SNAPSHOT_PATH

    if not SNAPSHOT_PATH.exists():
        return None
    with open(SNAPSHOT_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {item["symbol"]: item["periods"] for item in data}


def compute_diff(
    current: list[StockScanResult], prev: dict[str, dict[str, dict]]
) -> list[tuple[str, str, int, str]]:
    """对比当前和上次快照，找出进入/离开极值区的变化。

    返回 [(symbol, name, period, change_desc), ...]
    """
    changes: list[tuple[str, str, int, str]] = []

    for r in current:
        prev_stock = prev.get(r.symbol, {})
        for p in r.periods:
            if p.insufficient:
                continue
            pkey = str(p.period)
            old = prev_stock.get(pkey)

            if old is None:
                continue

            if p.at_low and not old["at_low"]:
                changes.append((r.symbol, r.name, p.period, f"新进入 {p.period} 日低点区 [{p.position_pct:.0f}%]"))
            elif not p.at_low and old["at_low"]:
                changes.append((r.symbol, r.name, p.period, f"离开 {p.period} 日低点区 → {p.position_pct:.0f}%"))
            if p.at_high and not old["at_high"]:
                changes.append((r.symbol, r.name, p.period, f"新进入 {p.period} 日高点区 [{p.position_pct:.0f}%]"))
            elif not p.at_high and old["at_high"]:
                changes.append((r.symbol, r.name, p.period, f"离开 {p.period} 日高点区 → {p.position_pct:.0f}%"))

    return changes
