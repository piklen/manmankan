"""Tests for kan/core/find_dsl.py · DSL parser (历史背景)."""

from dataclasses import FrozenInstanceError

import pytest

from kan.core.find_dsl import (
    ALLOWED_OPS,
    ALLOWED_PERIODS,
    ConditionSet,
    FilterParseError,
    PosFilter,
    ResonanceFilter,
    apply_op,
)


class TestPosFilter:
    def test_parse_basic(self):
        f = PosFilter.parse("180:lt:5")
        assert f.period == 180
        assert f.op == "lt"
        assert f.value == 5.0

    @pytest.mark.parametrize("op", ALLOWED_OPS)
    def test_parse_all_ops(self, op):
        f = PosFilter.parse(f"60:{op}:50")
        assert f.op == op

    @pytest.mark.parametrize("period", ALLOWED_PERIODS)
    def test_parse_all_periods(self, period):
        f = PosFilter.parse(f"{period}:lt:50")
        assert f.period == period

    def test_parse_uppercase_op(self):
        f = PosFilter.parse("180:LT:5")
        assert f.op == "lt"

    def test_parse_too_few_parts(self):
        with pytest.raises(FilterParseError, match="格式错误"):
            PosFilter.parse("180:lt")

    def test_parse_too_many_parts(self):
        with pytest.raises(FilterParseError, match="格式错误"):
            PosFilter.parse("180:lt:5:extra")

    def test_parse_invalid_period_string(self):
        with pytest.raises(FilterParseError, match="周期非整数"):
            PosFilter.parse("abc:lt:5")

    def test_parse_any_period_in_range(self):
        assert PosFilter.parse("200:lt:5").period == 200

    def test_parse_period_below_range(self):
        with pytest.raises(FilterParseError, match=r"周期 1 不支持.*最接近的是 2"):
            PosFilter.parse("1:lt:5")

    def test_parse_period_above_range(self):
        with pytest.raises(FilterParseError, match=r"周期 361 不支持.*最接近的是 360"):
            PosFilter.parse("361:lt:5")

    def test_parse_invalid_op(self):
        with pytest.raises(FilterParseError, match="运算符 'xx' 不支持"):
            PosFilter.parse("180:xx:5")

    def test_parse_value_not_number(self):
        with pytest.raises(FilterParseError, match="数值非数字"):
            PosFilter.parse("180:lt:abc")

    def test_parse_value_above_range(self):
        with pytest.raises(FilterParseError, match=r"数值 150"):
            PosFilter.parse("180:lt:150")

    def test_parse_value_below_range(self):
        with pytest.raises(FilterParseError, match=r"数值 -1"):
            PosFilter.parse("180:lt:-1")

    def test_parse_boundary_zero(self):
        f = PosFilter.parse("180:lt:0")
        assert f.value == 0.0

    def test_parse_boundary_hundred(self):
        f = PosFilter.parse("180:lte:100")
        assert f.value == 100.0

    def test_parse_float_value(self):
        f = PosFilter.parse("180:lt:5.5")
        assert f.value == 5.5

    def test_immutable(self):
        f = PosFilter.parse("180:lt:5")
        with pytest.raises(FrozenInstanceError):
            f.period = 60  # frozen dataclass


class TestResonanceFilter:
    def test_parse_basic_low(self):
        f = ResonanceFilter.parse("low:gte:3")
        assert f.level == "low"
        assert f.op == "gte"
        assert f.value == 3

    def test_parse_basic_high(self):
        f = ResonanceFilter.parse("high:eq:5")
        assert f.level == "high"
        assert f.value == 5

    def test_parse_uppercase_level(self):
        f = ResonanceFilter.parse("LOW:gte:3")
        assert f.level == "low"

    def test_parse_invalid_level(self):
        with pytest.raises(FilterParseError, match="级别 'mid' 不支持"):
            ResonanceFilter.parse("mid:gte:3")

    def test_parse_invalid_op(self):
        with pytest.raises(FilterParseError, match="运算符 'xx'"):
            ResonanceFilter.parse("low:xx:3")

    def test_parse_value_must_be_int(self):
        with pytest.raises(FilterParseError, match="数值非整数"):
            ResonanceFilter.parse("low:gte:3.5")

    def test_parse_value_above_range(self):
        with pytest.raises(FilterParseError, match=r"数值 15"):
            ResonanceFilter.parse("low:gte:15")

    def test_parse_value_below_range(self):
        with pytest.raises(FilterParseError, match=r"数值 -1"):
            ResonanceFilter.parse("low:gte:-1")

    def test_parse_boundary_zero(self):
        f = ResonanceFilter.parse("low:gte:0")
        assert f.value == 0

    def test_parse_boundary_ten(self):
        f = ResonanceFilter.parse("low:gte:10")
        assert f.value == 10


class TestConditionSet:
    def test_empty_default(self):
        cs = ConditionSet.from_flags()
        assert cs.is_empty()
        assert cs.pos_filters == ()
        assert cs.resonance_filters == ()
        assert cs.exclude_st is False

    def test_with_pos_only(self):
        cs = ConditionSet.from_flags(pos=["180:lt:5"])
        assert not cs.is_empty()
        assert len(cs.pos_filters) == 1

    def test_with_multiple_pos(self):
        cs = ConditionSet.from_flags(pos=["180:lt:5", "60:lt:10"])
        assert len(cs.pos_filters) == 2
        assert cs.pos_filters[0].period == 180
        assert cs.pos_filters[1].period == 60

    def test_with_resonance(self):
        cs = ConditionSet.from_flags(resonance=["low:gte:3"])
        assert len(cs.resonance_filters) == 1
        assert not cs.is_empty()

    def test_with_exclude_st_only(self):
        cs = ConditionSet.from_flags(exclude_st=True)
        assert cs.exclude_st
        assert not cs.is_empty()

    def test_with_all_filters(self):
        cs = ConditionSet.from_flags(
            pos=["180:lt:5"],
            resonance=["low:gte:3"],
            exclude_st=True,
        )
        assert len(cs.pos_filters) == 1
        assert len(cs.resonance_filters) == 1
        assert cs.exclude_st

    def test_parse_error_propagates(self):
        with pytest.raises(FilterParseError):
            ConditionSet.from_flags(pos=["bad:format"])

    def test_resonance_parse_error_propagates(self):
        with pytest.raises(FilterParseError):
            ConditionSet.from_flags(resonance=["mid:gte:3"])

    def test_immutable(self):
        cs = ConditionSet.from_flags(pos=["180:lt:5"])
        with pytest.raises(FrozenInstanceError):
            cs.exclude_st = True  # frozen


class TestApplyOp:
    @pytest.mark.parametrize(
        "op,lhs,rhs,expected",
        [
            ("lt", 1, 2, True),
            ("lt", 2, 1, False),
            ("lt", 1, 1, False),
            ("lte", 1, 1, True),
            ("lte", 2, 1, False),
            ("gt", 2, 1, True),
            ("gt", 1, 1, False),
            ("gte", 1, 1, True),
            ("eq", 1, 1, True),
            ("eq", 1, 2, False),
            ("ne", 1, 2, True),
            ("ne", 1, 1, False),
        ],
    )
    def test_ops(self, op, lhs, rhs, expected):
        assert apply_op(op, lhs, rhs) is expected

    def test_unknown_op_raises(self):
        with pytest.raises(ValueError, match="unsupported op"):
            apply_op("foo", 1, 2)

    def test_with_float(self):
        assert apply_op("lt", 1.5, 2.5) is True
        assert apply_op("gte", 3.14, 3.14) is True
