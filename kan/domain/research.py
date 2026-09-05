"""终端与 AI 共用的研究事实包，不承载模型推断。"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from kan.domain.screen import StrictModel


class ResearchDimension(StrEnum):
    MARKET = "market"
    VALUATION = "valuation"
    FUNDAMENTALS = "fundamentals"
    MONEYFLOW = "moneyflow"
    TECHNICAL = "technical"
    SENTIMENT = "sentiment"
    CHIP = "chip"
    SHAREHOLDER = "shareholder"
    INCOME = "income"
    BALANCESHEET = "balancesheet"
    CASHFLOW = "cashflow"


# 三表入口只取这些金额科目；来源字段、中文标签由取数和证据组织共用。
STATEMENT_FIELDS: dict[ResearchDimension, tuple[tuple[str, str], ...]] = {
    ResearchDimension.INCOME: (
        ("total_revenue", "营业总收入"), ("revenue", "营业收入"),
        ("oper_cost", "营业成本"), ("operate_profit", "营业利润"),
        ("total_profit", "利润总额"), ("income_tax", "所得税费用"),
        ("n_income", "净利润"), ("n_income_attr_p", "归母净利润"),
    ),
    ResearchDimension.BALANCESHEET: (
        ("money_cap", "货币资金"), ("accounts_receiv", "应收账款"),
        ("inventories", "存货"), ("total_cur_assets", "流动资产合计"),
        ("total_nca", "非流动资产合计"), ("total_assets", "资产总计"),
        ("total_cur_liab", "流动负债合计"), ("total_ncl", "非流动负债合计"),
        ("total_liab", "负债合计"),
        ("total_hldr_eqy_exc_min_int", "归母股东权益"),
        ("total_hldr_eqy_inc_min_int", "股东权益合计（含少数股东）"),
    ),
    ResearchDimension.CASHFLOW: (
        ("net_profit", "净利润"), ("c_fr_sale_sg", "销售商品、提供劳务收到的现金"),
        ("n_cashflow_act", "经营活动现金流量净额"),
        ("n_cashflow_inv_act", "投资活动现金流量净额"),
        ("n_cash_flows_fnc_act", "筹资活动现金流量净额"),
        ("c_pay_acq_const_fiolta", "购建长期资产支付的现金"),
        ("n_incr_cash_cash_equ", "现金及现金等价物净增加额"),
        ("c_cash_equ_beg_period", "期初现金及现金等价物余额"),
        ("c_cash_equ_end_period", "期末现金及现金等价物余额"),
    ),
}


class ResearchRequest(StrictModel):
    codes: list[str] = Field(min_length=1, max_length=20)
    refresh: bool = Field(default=False, description="跳过所请求维度的缓存，重新检查数据源。")
    dimensions: list[ResearchDimension] = Field(
        default_factory=lambda: [
            ResearchDimension.MARKET,
            ResearchDimension.VALUATION,
            ResearchDimension.FUNDAMENTALS,
        ],
        min_length=1,
        max_length=len(ResearchDimension),
        description="按需选择事实维度，单独研究财务或其他指标不依赖行情。",
    )

    @field_validator("codes")
    @classmethod
    def normalize_codes(cls, codes: list[str]) -> list[str]:
        from kan.storage.positions import normalize_symbol

        return list(dict.fromkeys(normalize_symbol(code) for code in codes))

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, values: list[ResearchDimension]) -> list[ResearchDimension]:
        return list(dict.fromkeys(values))


class ResearchFact(StrictModel):
    field_id: str
    label: str
    value: float | str | None
    unit: str
    window: int | None = None


class ResearchEvidence(StrictModel):
    evidence_ref: str
    symbol: str
    dimension: ResearchDimension
    source: str | None
    data_date: date | None = None
    report_period: date | None = None
    announcement_date: date | None = None
    actual_announcement_date: date | None = None
    report_type: str | None = None
    period_basis: Literal["year_to_date", "period_end"] | None = Field(
        default=None,
        description="报表口径：year_to_date为年初累计报表，其中现金期初/期末项仍为余额；period_end为期末余额。",
    )
    fetched_at: str | None = None
    adjustment: Literal["qfq"] | None = None
    freshness: Literal["fresh", "stale", "unknown", "unavailable"]
    facts: list[ResearchFact]
    missing_fields: list[str]
    notes: list[str] = Field(default_factory=list)


class ResearchSubject(StrictModel):
    symbol: str
    name: str
    evidence_refs: list[str]


class ResearchFailure(StrictModel):
    symbol: str | None = None
    dimension: ResearchDimension | None = None
    code: str
    message: str


class ResearchCoverage(StrictModel):
    requested_symbols: int
    available_symbols: int
    requested_sections: int
    available_sections: int
    fresh_sections: int
    missing_facts: int


class ResearchBundle(StrictModel):
    ok: bool
    command: Literal["research"] = "research"
    schema_version: Literal[1] = 1
    bundle_id: str
    generated_at: datetime
    expected_trade_date: date
    request: ResearchRequest
    status: Literal["complete", "partial", "unavailable"]
    subjects: list[ResearchSubject]
    evidence: list[ResearchEvidence]
    coverage: ResearchCoverage
    errors: list[ResearchFailure]
    limitations: list[str]
    disclaimer: str
