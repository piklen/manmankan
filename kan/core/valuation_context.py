"""估值分位 + 行业中位对照 (地基-3 · 输出层合规呈现)。

把原始估值比率 (pe_ttm / pb · 数据层 · 易误读裸值) 转成位置型表达:
- 历史分位:当前 PE/PB 在自身近 N 年序列的百分位 (temporal · 同价格位置%)
- 行业内分位:当前 PE/PB 在申万一级同行的百分位 (cross-sectional · 50=中位)
- 行业中位:申万一级同行 PE/PB 中位 (aggregate 参照值)

合规 (compliance · PRD §6 · 维护者反复明示"估值用分位非裸值"):
- 对外只出分位 + 行业中位对照 · **绝不出个股估值裸值** · 绝不出判断词
- 估值位置 = 价格位置的同构延伸 (PRD §1.1)

纯函数 (compute_*) 与编排 (build_valuation_context) 分离 · 前者离线可测 ·
后者负责拉 history / 行业映射 / 截面 (无 token → None 优雅降级)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from kan.core.models import ValuationContext

_MIN_HISTORY = 30
"""历史分位最低样本 · 不足则该分位 None (避免少量点给出误导分位)。"""
_MIN_INDUSTRY = 5
"""行业内分位/中位最低样本 · 不足则 None (小行业中位无统计意义)。"""


def pct_rank(value: float | None, series: list[float]) -> float | None:
    """value 在 series 中的百分位 (0-100) · ≤value 的占比 · 空/None 返 None。

    与价格位置% 同构:0 = 序列最低档 · 100 = 序列最高档 · 纯客观位置 · 无判断。
    """
    if value is None:
        return None
    clean = [v for v in series if v is not None]
    if not clean:
        return None
    le = sum(1 for v in clean if v <= value)
    return round(100.0 * le / len(clean), 1)


def _median(series: list[float]) -> float | None:
    clean = sorted(v for v in series if v is not None)
    n = len(clean)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return round(clean[mid], 2)
    return round((clean[mid - 1] + clean[mid]) / 2.0, 2)


def _col_values(df: pd.DataFrame, col: str) -> list[float]:
    """DataFrame 列 → 有效 float list (NaN/None 剔除)。"""
    import pandas as pd

    if df is None or df.empty or col not in df.columns:
        return []
    return [float(v) for v in df[col] if v is not None and not pd.isna(v)]


def compute_valuation_context(
    symbol: str,
    *,
    pe: float | None,
    pb: float | None,
    history_df: pd.DataFrame,
    cross_section_df: pd.DataFrame,
    l1_map: dict[str, str],
    lookback_days: int,
) -> ValuationContext:
    """纯计算 · 由原料 (当前 pe/pb + 历史时序 + 全市场截面 + 行业映射) 算估值对照。

    个股 pe/pb 裸值仅作输入 · 输出只含分位 + 行业中位 (绝不回吐裸值)。
    样本不足的维度返 None (优雅降级)。
    """
    from kan.core.models import ValuationContext

    industry = l1_map.get(symbol)

    # 历史分位 (temporal) · 样本足才给
    pe_pct = pb_pct = None
    if history_df is not None and not history_df.empty:
        pe_hist = _col_values(history_df, "pe_ttm")
        pb_hist = _col_values(history_df, "pb")
        if len(pe_hist) >= _MIN_HISTORY:
            pe_pct = pct_rank(pe, pe_hist)
        if len(pb_hist) >= _MIN_HISTORY:
            pb_pct = pct_rank(pb, pb_hist)

    # 行业内分位 + 中位 (cross-sectional) · 申万一级同行
    pe_ind_pct = pb_ind_pct = pe_ind_med = pb_ind_med = sample = None
    if industry and cross_section_df is not None and not cross_section_df.empty:
        peers = {s for s, l1 in l1_map.items() if l1 == industry}
        sub = cross_section_df[cross_section_df["symbol"].isin(peers)]
        pe_peers = _col_values(sub, "pe_ttm")
        pb_peers = _col_values(sub, "pb")
        n = max(len(pe_peers), len(pb_peers))
        if n >= _MIN_INDUSTRY:
            sample = n
            if len(pe_peers) >= _MIN_INDUSTRY:
                pe_ind_pct = pct_rank(pe, pe_peers)
                pe_ind_med = _median(pe_peers)
            if len(pb_peers) >= _MIN_INDUSTRY:
                pb_ind_pct = pct_rank(pb, pb_peers)
                pb_ind_med = _median(pb_peers)

    return ValuationContext(
        industry=industry,
        lookback_days=lookback_days,
        industry_sample=sample,
        pe_pct_rank=pe_pct,
        pb_pct_rank=pb_pct,
        pe_industry_pct=pe_ind_pct,
        pb_industry_pct=pb_ind_pct,
        pe_industry_median=pe_ind_med,
        pb_industry_median=pb_ind_med,
    )


def build_valuation_context(symbol: str) -> ValuationContext | None:
    """编排:拉 当前截面 + 历史时序 + 申万映射 → 估值对照 (无数据返 None)。

    无 token / 全空 → None (info 输出层据此跳过 valuation_context · 优雅降级)。
    """
    from kan.data.industry_map import fetch_sw_l1_map
    from kan.data.metrics import _DEFAULT_LOOKBACK_DAYS, fetch_metrics, fetch_valuation_history

    cross = fetch_metrics()  # 全市场截面 (地基-2 已缓存 · 复用)
    if cross is None or cross.empty:
        return None  # 无 token / 无截面 → 估值对照不可算

    row = cross[cross["symbol"] == symbol]
    pe = pb = None
    if not row.empty:
        import pandas as pd
        pe_v = row.iloc[0].get("pe_ttm")
        pb_v = row.iloc[0].get("pb")
        pe = None if pe_v is None or pd.isna(pe_v) else float(pe_v)
        pb = None if pb_v is None or pd.isna(pb_v) else float(pb_v)

    history = fetch_valuation_history(symbol)
    l1_map = fetch_sw_l1_map()

    ctx = compute_valuation_context(
        symbol, pe=pe, pb=pb, history_df=history,
        cross_section_df=cross, l1_map=l1_map,
        lookback_days=_DEFAULT_LOOKBACK_DAYS,
    )
    # 全维度皆 None → 视作无对照 (避免空壳对象)
    if all(
        v is None
        for v in (
            ctx.pe_pct_rank, ctx.pb_pct_rank, ctx.pe_industry_pct,
            ctx.pb_industry_pct, ctx.industry,
        )
    ):
        return None
    return ctx


__all__ = ["build_valuation_context", "compute_valuation_context", "pct_rank"]
