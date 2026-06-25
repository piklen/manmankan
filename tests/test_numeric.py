"""kan/numeric.py · to_numeric_checked 单元测试"""

import pandas as pd

from kan.infra.numeric import to_numeric_checked


def test_clean_strings_no_bad():
    converted, bad = to_numeric_checked(pd.Series(["1", "2", "3"]))
    assert bad == 0
    assert converted.tolist() == [1, 2, 3]


def test_unparseable_value_counted():
    converted, bad = to_numeric_checked(pd.Series(["1", "bad", "3"]))
    assert bad == 1
    assert pd.isna(converted.iloc[1])
    assert converted.iloc[0] == 1


def test_preexisting_none_not_counted():
    converted, bad = to_numeric_checked(pd.Series(["1", None, "3"]))
    assert bad == 0
    assert pd.isna(converted.iloc[1])


def test_blank_string_treated_as_missing_not_bad():
    converted, bad = to_numeric_checked(pd.Series(["1", "", "   ", "3"]))
    assert bad == 0
    assert pd.isna(converted.iloc[1])
    assert pd.isna(converted.iloc[2])
