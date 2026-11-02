import type {
  StudyCondition,
  StudyQuery,
  TrendSearchQuery,
  TrendSearchResult,
} from "../api/client";
import { FIELDS, parseCodes, type ConditionDraft } from "./study";

export type TrendTask = "up" | "down" | "down_up" | "up_down" | "count";
export const TREND_TASKS: Record<TrendTask, string> = {
  up: "连续上涨",
  down: "连续下跌",
  down_up: "先跌后涨",
  up_down: "先涨后跌",
  count: "区间涨跌天数",
};
const taskFields: Record<TrendTask, StudyCondition["field"][]> = {
  up: ["up_days"],
  down: ["down_days"],
  down_up: ["previous_down_days", "up_days"],
  up_down: ["previous_up_days", "down_days"],
  count: ["rising_days"],
};
export const DAY_OPERATORS = { gte: "至少", eq: "恰好", lte: "最多" } as const;
export type ScreenerDraft = {
  universe: StudyQuery["universe"];
  codes: string;
  industries: string[];
  asOf: string;
  conditions: ConditionDraft[];
  referenceSymbol: string;
  referenceDate: string;
};
export const blankScreenDraft = (): ScreenerDraft => ({
  universe: "all",
  codes: "",
  industries: [],
  asOf: "",
  conditions: [],
  referenceSymbol: "",
  referenceDate: "",
});
const directionalDays = new Set<StudyCondition["field"]>([
  "up_days",
  "down_days",
  "previous_up_days",
  "previous_down_days",
  "bull_days",
  "bear_days",
  "joint_up_days",
]);
const countedDays = new Set<StudyCondition["field"]>([
  "rising_days",
  "falling_days",
]);

export const taskConditions = (task: TrendTask): ConditionDraft[] =>
  taskFields[task].map((field, index) => ({
    id: index + 1,
    field,
    operator: "gte",
    value: "",
    window: "",
  }));

export function conditionInputError(
  conditions: ConditionDraft[],
): string | null {
  if (!conditions.length) return "选择想查的趋势，填写自己的条件。";
  for (const item of conditions) {
    if (!item.field) return "请选择条件字段。";
    if (!item.value.trim() || !Number.isFinite(Number(item.value)))
      return "请填写每个条件的数值。";
    const value = Number(item.value);
    if (
      directionalDays.has(item.field) &&
      (!Number.isInteger(value) || value < 1)
    )
      return "连续段天数请填写至少 1 天的整数。";
    if (countedDays.has(item.field) && (!Number.isInteger(value) || value < 0))
      return "区间涨跌天数请填写非负整数。";
    if (
      FIELDS[item.field].window &&
      (!item.window.trim() ||
        !Number.isInteger(Number(item.window)) ||
        Number(item.window) < 2 ||
        Number(item.window) > 360)
    )
      return "窗口请填写 2–360 个交易日。";
    if (countedDays.has(item.field) && value > Number(item.window))
      return "区间涨跌天数不能超过观察窗口。";
  }
  return null;
}

export function compileConditions(
  conditions: ConditionDraft[],
): StudyCondition[] {
  return conditions.flatMap((item) => {
    const field = item.field as StudyCondition["field"];
    const condition: StudyCondition = {
      field,
      operator: item.operator,
      value: Number(item.value),
      window: FIELDS[field].window ? Number(item.window) : null,
    };
    // “最多 N 天的上涨段”仍须是上涨段，界面同时显示 1–N 天的范围。
    return directionalDays.has(field) && item.operator === "lte"
      ? [{ field, operator: "gt" as const, value: 0, window: null }, condition]
      : [condition];
  });
}

export function conditionsToDraft(
  conditions: StudyCondition[],
): ConditionDraft[] {
  return conditions
    .filter(
      (item) =>
        !(
          directionalDays.has(item.field) &&
          item.operator === "gt" &&
          item.value === 0 &&
          conditions.some(
            (other) =>
              other.field === item.field &&
              other.operator === "lte" &&
              other.value >= 1,
          )
        ),
    )
    .map((item, index) => ({
      id: index + 1,
      field: item.field,
      operator: item.operator,
      value: String(item.value),
      window: item.window ? String(item.window) : "",
    }));
}

export function screenInputError(draft: ScreenerDraft): string | null {
  if (
    draft.universe === "codes" &&
    (!parseCodes(draft.codes).length ||
      parseCodes(draft.codes).some((code) => !/^\d{6}$/.test(code)))
  )
    return "请填写至少一个 6 位股票代码。";
  const error = conditionInputError(draft.conditions);
  if (error) return error;
  if (
    draft.conditions.some((item) => item.field === "shape_distance") &&
    (!/^\d{6}$/.test(draft.referenceSymbol) || !draft.referenceDate)
  )
    return "形态筛选需要明确的参照股票与日期。";
  if (compileConditions(draft.conditions).length > 12)
    return "最多支持 12 项条件，请减少条件。";
  return null;
}

export function screenDraftToQuery(draft: ScreenerDraft): TrendSearchQuery {
  return {
    universe: draft.universe,
    codes: draft.universe === "codes" ? parseCodes(draft.codes) : [],
    industries: draft.industries,
    as_of: draft.asOf || null,
    conditions: compileConditions(draft.conditions),
    reference: draft.conditions.some((item) => item.field === "shape_distance")
      ? { symbol: draft.referenceSymbol, as_of: draft.referenceDate }
      : null,
  };
}

export function screenQueryToDraft(query: TrendSearchQuery): ScreenerDraft {
  return {
    universe: query.universe,
    codes: (query.codes ?? []).join(", "),
    industries: query.industries ?? [],
    asOf: query.as_of ?? "",
    conditions: conditionsToDraft(query.conditions ?? []),
    referenceSymbol: query.reference?.symbol ?? "",
    referenceDate: query.reference?.as_of ?? "",
  };
}

export function historicalQuery(
  result: TrendSearchResult,
  title: string,
): StudyQuery {
  const scoped = Boolean(result.query.industries?.length);
  return {
    title,
    universe: scoped ? "codes" : result.query.universe,
    codes: scoped ? result.scope_codes : (result.query.codes ?? []),
    as_of: result.as_of,
    conditions: result.query.conditions ?? [],
    reference: result.query.reference ?? null,
    lookback_days: 120,
    forward_days: 5,
    sample_policy: "first",
  };
}
