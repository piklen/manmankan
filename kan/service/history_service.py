"""history 用例服务 · 纯离线读取扫描快照。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from kan.core.scanner import SymbolHistoryEntry


class HistoryServiceError(RuntimeError):
    """history 领域错误,由 CLI/API 边界映射成各自输出。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        hint: str | None = None,
        exit_code: int = 1,
    ) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code
        super().__init__(message)


@dataclass(frozen=True)
class HistoryRequest:
    """history 输入。"""

    symbol_or_name: str
    period: int = 30


@dataclass(frozen=True)
class HistoryServiceResult:
    """history 领域结果。"""

    symbol: str
    name: str
    entries: list[SymbolHistoryEntry]
    period: int


def get_symbol_history(request: HistoryRequest) -> HistoryServiceResult:
    """读取单只股票位置历史 · 只读 snapshots/。"""
    from kan.core.scanner import MAX_PERIOD, MIN_PERIOD, load_symbol_history, snapshot_symbol_names

    if request.period < MIN_PERIOD or request.period > MAX_PERIOD:
        raise HistoryServiceError(
            code="invalid_period",
            message=f"周期不支持: {request.period}",
            hint=f"周期范围 {MIN_PERIOD}-{MAX_PERIOD} · 例: kan history 600519 --period 20",
            exit_code=2,
        )

    universe = snapshot_symbol_names()
    if not universe:
        raise HistoryServiceError(
            code="history_unavailable",
            message="还没有任何扫描历史",
            hint="例: 先运行 kan scan 积累每日快照,之后再运行 kan history 600519",
            exit_code=1,
        )

    symbol, name = resolve_in_snapshots(request.symbol_or_name, universe)
    entries = load_symbol_history(symbol)
    if not entries:
        raise HistoryServiceError(
            code="history_not_found",
            message=f"没有「{name} {symbol}」的历史快照",
            hint="例: 先运行 kan scan 积累每日快照",
            exit_code=1,
        )

    return HistoryServiceResult(
        symbol=symbol,
        name=name,
        entries=entries,
        period=request.period,
    )


def resolve_in_snapshots(raw: str, universe: dict[str, str]) -> tuple[str, str]:
    """把用户输入(代码 / 名称)解析成 (symbol, name) · 解析域 = 有历史的股票。"""
    cleaned = re.sub(r"^(sh|sz|SH|SZ)", "", raw.strip())
    if re.match(r"^\d{6}$", cleaned):
        if cleaned in universe:
            return cleaned, universe[cleaned]
        raise HistoryServiceError(
            code="history_not_found",
            message=(
                f"没有「{raw}」的历史 · kan history 只能看曾在自选、"
                "且跑过 kan scan 的股票"
            ),
            hint="例: kan scan；然后 kan history 600519",
            exit_code=1,
        )
    if not cleaned:
        raise HistoryServiceError(
            code="invalid_symbol",
            message="空字符串不是有效股票名 / 代码",
            hint="例: kan history 600519 或 kan history 茅台",
            exit_code=2,
        )
    q = cleaned.replace(" ", "")
    matches = [(s, n) for s, n in universe.items() if q in n.replace(" ", "")]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        raise HistoryServiceError(
            code="history_not_found",
            message=(
                f"快照历史里没有匹配「{raw}」的股票 · kan history 只覆盖曾在自选、"
                "且跑过 kan scan 的股票"
            ),
            hint="例: 试 6 位代码,或先运行 kan scan 积累快照",
            exit_code=1,
        )
    preview = "; ".join(f"{s} {n.replace(' ', '')}" for s, n in matches[:8])
    if len(matches) > 8:
        preview += f"; …等 {len(matches)} 只"
    raise HistoryServiceError(
        code="ambiguous_symbol",
        message=f"「{raw}」匹配到 {len(matches)} 只",
        hint=f"候选: {preview} · 请用代码精确指定",
        exit_code=1,
    )
