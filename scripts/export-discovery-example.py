"""从已有全市场日线导出官网和本地共用的历史行业样本。"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from kan.domain.discovery import DiscoveryGroup, DiscoveryQuery
from kan.service.discovery import discover_market


def aggregate(group: DiscoveryGroup) -> dict:
    return {
        "name": group.name,
        "total": group.total,
        "available": group.current.available,
        "median": group.current.median_return,
        "relative_return_pp": group.relative_return_pp,
        "up": group.current.up,
        "paired": group.comparison.available,
        "previous_share": group.comparison.previous_positive_share,
        "current_share": group.comparison.current_positive_share,
        "comparison": {"breadth_delta_pp": group.comparison.breadth_delta_pp},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    windows = []
    for window in (5, 20, 60):
        result = discover_market(DiscoveryQuery(as_of=args.as_of, window=window))
        if not result.market.current.available or len(result.industries) < 2:
            parser.error(f"{window} 日窗口缺少可比较的市场或行业行情")
        windows.append({
            "days": window, "start": str(result.current_start),
            "as_of": str(result.as_of), "market": aggregate(result.market),
            "industries": [aggregate(group) for group in result.industries],
        })
    args.output.write_text(json.dumps(windows, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
