"""scan 快照保存、读取和差异计算。"""
from __future__ import annotations

import json
from datetime import date, timedelta

from kan.core.models import StockScanResult

_SNAPSHOT_KEEP_DAYS = 240


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
