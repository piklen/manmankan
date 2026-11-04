import type { StudyCondition, StudyQuery } from "../api/client";
import { number } from "./format";

export const FIELDS: Record<
  StudyCondition["field"],
  { label: string; unit: string; window?: boolean; detail: string }
> = {
  shape_distance: {
    label: "与参照形态的距离",
    unit: "个百分点",
    window: true,
    detail: "两段收盘按各自首日归一为100后，逐日差的均方根；用于事后形态检索",
  },
  change_pct: {
    label: "当日涨跌幅",
    unit: "%",
    detail: "收盘价相对上一交易日收盘价的变化",
  },
  gap_pct: {
    label: "开盘缺口",
    unit: "%",
    detail: "开盘价相对上一交易日收盘价的变化",
  },
  body_pct: {
    label: "日内实体涨跌",
    unit: "%",
    detail: "收盘价相对当日开盘价的变化",
  },
  return_pct: {
    label: "区间涨跌幅",
    unit: "%",
    window: true,
    detail: "相对指定交易日前收盘价的变化",
  },
  position: {
    label: "区间位置",
    unit: "%",
    window: true,
    detail: "收盘价在区间最低与最高价之间的位置：0%为最低，100%为最高",
  },
  low_age: {
    label: "区间低点距今",
    unit: "个交易日",
    window: true,
    detail: "指定窗口内最近一次最低价距离事件日的交易日数，事件日为0",
  },
  up_days: {
    label: "连续收盘上涨",
    unit: "天",
    detail: "收盘价连续高于上一交易日收盘价",
  },
  down_days: {
    label: "连续收盘下跌",
    unit: "天",
    detail: "收盘价连续低于上一交易日收盘价",
  },
  previous_up_days: {
    label: "紧邻前一涨段",
    unit: "天",
    detail: "当前下跌段之前紧邻的连续上涨天数；不跨过平盘或缺失行情",
  },
  previous_down_days: {
    label: "紧邻前一跌段",
    unit: "天",
    detail: "当前上涨段之前紧邻的连续下跌天数；不跨过平盘或缺失行情",
  },
  rising_days: {
    label: "区间上涨天数",
    unit: "天",
    window: true,
    detail: "最近 N 个市场交易日中，收盘高于前一交易日的天数；平盘不计",
  },
  falling_days: {
    label: "区间下跌天数",
    unit: "天",
    window: true,
    detail: "最近 N 个市场交易日中，收盘低于前一交易日的天数；平盘不计",
  },
  bull_count: {
    label: "区间阳线数量", unit: "天", window: true,
    detail: "最近 N 根日 K 中收盘高于当日开盘的数量；十字线不计",
  },
  bear_count: {
    label: "区间阴线数量", unit: "天", window: true,
    detail: "最近 N 根日 K 中收盘低于当日开盘的数量；十字线不计",
  },
  candle_balance: {
    label: "阳线与阴线数量差", unit: "天", window: true,
    detail: "阳线数量减阴线数量；大于 0 表示阳线更多，小于 0 表示阴线更多",
  },
  trend_slope: {
    label: "价格趋势斜率", unit: "%/日", window: true,
    detail: "N 次收盘变化（N+1 个收盘）的对数回归斜率，换算为每交易日百分比；不是未来收益",
  },
  trend_efficiency: {
    label: "趋势效率", unit: "", window: true,
    detail: "N 次收盘变化的净位移绝对值 ÷ 累计绝对变化，0–1；越接近 1 路径越直接，不表示方向或概率",
  },
  swing_structure: {
    label: "波段结构", unit: "", window: true,
    detail: "窗口内至少两个已确认波峰和两个波谷；高低点同向抬高为上升、同向降低为下降，否则混合；不足时不判断",
  },
  swing_direction: {
    label: "当前波段方向", unit: "", window: true,
    detail: "最后一个确认转折之后的当前波段方向；反向收盘幅度未达阈值时不改变方向",
  },
  swing_count: {
    label: "已完成波段数量", unit: "段", window: true,
    detail: "相邻已确认转折点之间的段数；窗口边界和当前未完成段不计入",
  },
  bull_days: {
    label: "连续收阳",
    unit: "天",
    detail: "收盘价连续高于当日开盘价",
  },
  bear_days: {
    label: "连续收阴",
    unit: "天",
    detail: "收盘价连续低于当日开盘价",
  },
  joint_up_days: {
    label: "连续收阳且上涨",
    unit: "天",
    detail: "每天同时满足收盘高于开盘、收盘高于前收",
  },
  volume_ratio: {
    label: "成交量相对均量",
    unit: "倍",
    window: true,
    detail: "当日成交量除以前N个交易日的平均成交量",
  },
};
export const OPERATORS: Record<StudyCondition["operator"], string> = {
  gte: "不低于",
  lte: "不高于",
  gt: "高于",
  lt: "低于",
  eq: "等于",
};
export const OP_SYMBOLS: Record<StudyCondition["operator"], string> = {
  gte: "≥",
  lte: "≤",
  gt: ">",
  lt: "<",
  eq: "=",
};
export const SAMPLE_LABELS: Record<StudyQuery["sample_policy"], string> = {
  first: "首次满足",
  every: "每次满足",
  non_overlapping: "观察窗口不重叠",
};
export const UNIVERSE_LABELS: Record<StudyQuery["universe"], string> = {
  all: "当前 A 股股票池",
  personal: "我的个人池",
  codes: "指定股票代码",
};
export const SWING_FIELDS = new Set<StudyCondition["field"]>([
  "swing_structure", "swing_direction", "swing_count",
]);
export const ENUM_VALUES: Partial<Record<StudyCondition["field"], Record<string, string>>> = {
  swing_structure: { "1": "上升结构", "-1": "下降结构", "0": "混合结构" },
  swing_direction: { "1": "当前上行", "-1": "当前下行", "0": "尚未形成方向" },
};
export const fieldValue = (field: StudyCondition["field"], value: number | null | undefined) => {
  if (value == null) return "无法确认";
  const label = ENUM_VALUES[field]?.[String(value)];
  return label ?? `${number(value, FIELDS[field].unit === "天" || FIELDS[field].unit === "段" ? 0 : field === "trend_slope" ? 3 : 2)}${FIELDS[field].unit}`;
};
export const conditionLabel = (condition: StudyCondition) =>
  `${condition.window ? `${condition.window}日` : ""}${FIELDS[condition.field].label}`;
export const conditionText = (condition: StudyCondition) =>
  `${conditionLabel(condition)} ${OP_SYMBOLS[condition.operator]} ${fieldValue(condition.field, condition.value)}`;
export const parseCodes = (value: string) => [
  ...new Set(
    value
      .split(/[\s,，;；]+/)
      .map((code) => code.trim())
      .filter(Boolean),
  ),
];

export type ConditionDraft = {
  id: number;
  field: StudyCondition["field"] | "";
  operator: StudyCondition["operator"];
  value: string;
  window: string;
};
export interface StudyDraft {
  title: string;
  universe: StudyQuery["universe"];
  codes: string;
  lookback: string;
  asOf: string;
  forward: string;
  sample: StudyQuery["sample_policy"];
  conditions: ConditionDraft[];
  referenceSymbol: string;
  referenceDate: string;
  swingReversal: string;
}
export const blankDraft = (): StudyDraft => ({
  title: "",
  universe: "codes",
  codes: "",
  lookback: "120",
  asOf: "",
  forward: "5",
  sample: "first",
  conditions: [],
  referenceSymbol: "",
  referenceDate: "",
  swingReversal: "5",
});
export const queryToDraft = (query: StudyQuery): StudyDraft => ({
  title: query.title,
  universe: query.universe,
  codes: (query.codes ?? []).join(", "),
  lookback: String(query.lookback_days),
  asOf: query.as_of ?? "",
  forward: String(query.forward_days),
  sample: query.sample_policy,
  referenceSymbol: query.reference?.symbol ?? "",
  referenceDate: query.reference?.as_of ?? "",
  swingReversal: String(query.swing_reversal_pct ?? 5),
  conditions: query.conditions.map((condition, index) => ({
    id: index + 1,
    field: condition.field,
    operator: condition.operator,
    value: String(condition.value),
    window: condition.window ? String(condition.window) : "",
  })),
});

export function swingInputError(conditions: ConditionDraft[], reversal: string): string | null {
  if (!conditions.some((condition) => condition.field && SWING_FIELDS.has(condition.field))) return null;
  return !reversal.trim() || !Number.isFinite(Number(reversal)) || Number(reversal) <= 0 || Number(reversal) >= 100
    ? "转折确认幅度需要大于 0%、小于 100%。" : null;
}
export function draftError(draft: StudyDraft): string | null {
  const swingError = swingInputError(draft.conditions, draft.swingReversal);
  if (swingError) return swingError;
  if (
    draft.universe === "codes" &&
    (!parseCodes(draft.codes).length ||
      parseCodes(draft.codes).some((code) => !/^\d{6}$/.test(code)))
  )
    return "请填写至少一个 6 位股票代码。";
  if (!draft.conditions.length) return "请添加你要验证的价格条件。";
  for (const condition of draft.conditions) {
    if (!condition.field) return "请选择条件字段。";
    if (ENUM_VALUES[condition.field] && (condition.operator !== "eq" || !ENUM_VALUES[condition.field]?.[condition.value]))
      return "请选择明确的波段结构或方向。";
    if (!condition.value.trim() || !Number.isFinite(Number(condition.value)))
      return "请明确填写每个条件的数值。";
    if (
      FIELDS[condition.field].window &&
      (!condition.window.trim() ||
        !Number.isInteger(Number(condition.window)) ||
        Number(condition.window) < 2 ||
        Number(condition.window) > 360)
    )
      return "区间窗口需要填写 2–360 个交易日。";
  }
  if (
    draft.conditions.some(
      (condition) => condition.field === "shape_distance",
    ) &&
    (!/^\d{6}$/.test(draft.referenceSymbol) || !draft.referenceDate)
  )
    return "形态检索需要明确的参照股票与日期。";
  if (
    !Number.isInteger(Number(draft.lookback)) ||
    Number(draft.lookback) < 5 ||
    Number(draft.lookback) > 1260
  )
    return "历史范围需要填写 5–1260 个交易日。";
  if (
    !Number.isInteger(Number(draft.forward)) ||
    Number(draft.forward) < 1 ||
    Number(draft.forward) > 60
  )
    return "后续观察窗口需要填写 1–60 个交易日。";
  return null;
}
export function draftToQuery(draft: StudyDraft): StudyQuery {
  return {
    title: draft.title.trim() || "日线研究",
    universe: draft.universe,
    codes: draft.universe === "codes" ? parseCodes(draft.codes) : [],
    lookback_days: Number(draft.lookback),
    as_of: draft.asOf || null,
    forward_days: Number(draft.forward),
    sample_policy: draft.sample,
    swing_reversal_pct: draft.conditions.some((item) => item.field && SWING_FIELDS.has(item.field)) ? Number(draft.swingReversal) : 5,
    reference: draft.conditions.some(
      (condition) => condition.field === "shape_distance",
    )
      ? { symbol: draft.referenceSymbol, as_of: draft.referenceDate }
      : null,
    conditions: draft.conditions.map((condition) => ({
      field: condition.field as StudyCondition["field"],
      operator: condition.operator,
      value: Number(condition.value),
      window:
        condition.field && FIELDS[condition.field].window
          ? Number(condition.window)
          : null,
    })),
  };
}
