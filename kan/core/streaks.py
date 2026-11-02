"""连续段唯一口径：平盘结束、缺行保留下界。"""

import pandas as pd


def streak_counts(flags: pd.Series, known: pd.Series) -> tuple[pd.Series, pd.Series]:
    """缺行后的连续段只知道下界，不能据此断言恰好 N 天。"""
    counts: list[float] = []
    exact_flags: list[bool] = []
    count, exact = 0, False
    for flag, valid in zip(flags.to_numpy(), known.to_numpy(), strict=True):
        if not valid:
            count, exact = 0, False
            counts.append(float("nan"))
        elif flag:
            count += 1
            counts.append(float(count))
        else:
            count, exact = 0, True
            counts.append(0.0)
        exact_flags.append(exact)
    return pd.Series(counts, index=flags.index), pd.Series(exact_flags, index=flags.index)
