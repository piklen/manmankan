import { Plus, Trash2 } from "lucide-react";
import type { StudyCondition } from "../api/client";
import { ENUM_VALUES, FIELDS, OPERATORS, type ConditionDraft } from "../lib/study";
import { DAY_OPERATORS } from "../lib/screener";

const daysFields = new Set([
  "up_days",
  "down_days",
  "previous_up_days",
  "previous_down_days",
  "rising_days",
  "falling_days",
  "bull_days",
  "bear_days",
  "joint_up_days",
  "bull_count",
  "bear_count",
]);
const labels: Partial<Record<StudyCondition["field"], string>> = {
  up_days: "连续上涨",
  down_days: "连续下跌",
  previous_up_days: "先连续上涨",
  previous_down_days: "先连续下跌",
  rising_days: "区间上涨天数",
  falling_days: "区间下跌天数",
  bull_days: "连续收阳",
  bear_days: "连续收阴",
  bull_count: "区间阳线数量",
  bear_count: "区间阴线数量",
  candle_balance: "阳线与阴线数量差",
  swing_structure: "波段结构",
  swing_direction: "当前波段方向",
};
export function TrendConditionBuilder({
  conditions,
  onChange,
}: {
  conditions: ConditionDraft[];
  onChange: (items: ConditionDraft[]) => void;
}) {
  const update = (id: number, changes: Partial<ConditionDraft>) =>
    onChange(
      conditions.map((item) =>
        item.id === id ? { ...item, ...changes } : item,
      ),
    );
  return (
    <div className="trend-condition-builder">
      {conditions.map((item, index) => (
        <div className="trend-condition-row" key={item.id}>
          <div className="trend-condition-label">
            {item.field && labels[item.field] ? (
              <strong>{labels[item.field]}</strong>
            ) : (
              <select
                aria-label={`条件 ${index + 1} 字段`}
                value={item.field}
                onChange={(e) =>
                  update(item.id, {
                    field: e.target.value as StudyCondition["field"],
                    operator: ENUM_VALUES[e.target.value as StudyCondition["field"]] ? "eq" : "gte",
                    value: "",
                    window: "",
                  })
                }
              >
                <option value="">选择条件</option>
                {Object.entries(FIELDS).map(([field, meta]) => (
                  <option key={field} value={field}>
                    {meta.label}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              className="icon-button"
              aria-label={`删除条件 ${index + 1}`}
              onClick={() =>
                onChange(
                  conditions.filter((condition) => condition.id !== item.id),
                )
              }
            >
              <Trash2 size={14} />
            </button>
          </div>
          {["up_days", "down_days", "bull_days", "bear_days"].includes(
            item.field,
          ) ? (
            <label>
              判断方式
              <select
                aria-label={`条件 ${index + 1} 判断方式`}
                value={item.field}
                onChange={(e) =>
                  update(item.id, {
                    field: e.target.value as StudyCondition["field"],
                  })
                }
              >
                {item.field === "up_days" || item.field === "bull_days" ? (
                  <>
                    <option value="up_days">收盘高于前收（上涨）</option>
                    <option value="bull_days">收盘高于开盘（收阳）</option>
                  </>
                ) : (
                  <>
                    <option value="down_days">收盘低于前收（下跌）</option>
                    <option value="bear_days">收盘低于开盘（收阴）</option>
                  </>
                )}
              </select>
            </label>
          ) : null}
          {item.field === "rising_days" || item.field === "falling_days" ? (
            <select
              aria-label={`条件 ${index + 1} 涨跌方向`}
              value={item.field}
              onChange={(e) =>
                update(item.id, {
                  field: e.target.value as StudyCondition["field"],
                })
              }
            >
              <option value="rising_days">统计上涨天数</option>
              <option value="falling_days">统计下跌天数</option>
            </select>
          ) : null}
          {["bull_count", "bear_count", "candle_balance"].includes(item.field) ? (
            <select aria-label={`条件 ${index + 1} 阳阴统计`} value={item.field}
              onChange={(event) => update(item.id, { field: event.target.value as StudyCondition["field"], value: "" })}>
              <option value="candle_balance">阳线减阴线数量</option>
              <option value="bull_count">统计阳线数量</option>
              <option value="bear_count">统计阴线数量</option>
            </select>
          ) : null}
          {item.field && FIELDS[item.field].window ? (
            <label className="trend-window">
              观察最近
              <span className="input-unit">
                <input
                  aria-label={`条件 ${index + 1} 观察窗口`}
                  type="number"
                  min="2"
                  max="360"
                  value={item.window}
                  placeholder="天数"
                  onChange={(e) => update(item.id, { window: e.target.value })}
                />
                <span>交易日</span>
              </span>
            </label>
          ) : null}
          {item.field && ENUM_VALUES[item.field] ? (
            <select aria-label={`条件 ${index + 1} 波段状态`} value={item.value}
              onChange={(event) => update(item.id, { operator: "eq", value: event.target.value })}>
              <option value="">选择要找的状态</option>
              {Object.entries(ENUM_VALUES[item.field]!).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          ) : <div className="trend-comparison">
            <select
              aria-label={`条件 ${index + 1} 比较关系`}
              value={item.operator}
              onChange={(e) =>
                update(item.id, {
                  operator: e.target.value as StudyCondition["operator"],
                })
              }
            >
              {Object.entries(
                item.field && daysFields.has(item.field)
                  ? {
                      ...DAY_OPERATORS,
                      ...(item.operator === "gt" ? { gt: "多于" } : {}),
                      ...(item.operator === "lt" ? { lt: "少于" } : {}),
                    }
                  : OPERATORS,
              ).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <span className="input-unit">
              <input
                aria-label={`条件 ${index + 1} 数值`}
                type="number"
                step={item.field && daysFields.has(item.field) ? "1" : "any"}
                value={item.value}
                placeholder="填写"
                onChange={(e) => update(item.id, { value: e.target.value })}
              />
              <span>{item.field ? FIELDS[item.field].unit : ""}</span>
            </span>
          </div>}
          {item.operator === "lte" &&
          [
            "up_days",
            "down_days",
            "previous_up_days",
            "previous_down_days",
            "bull_days",
            "bear_days",
            "joint_up_days",
          ].includes(item.field) ? (
            <p className="field-hint">
              该方向须已持续：1–{item.value || "N"} 天。
            </p>
          ) : null}
          {item.field ? (
            <p className="field-hint">{FIELDS[item.field].detail}</p>
          ) : null}
        </div>
      ))}
      <button
        className="add-condition"
        type="button"
        disabled={conditions.length >= 10}
        onClick={() =>
          onChange([
            ...conditions,
            {
              id: Math.max(0, ...conditions.map((item) => item.id)) + 1,
              field: "",
              operator: "gte",
              value: "",
              window: "",
            },
          ])
        }
      >
        <Plus size={15} />
        叠加位置、涨幅或其他条件
      </button>
    </div>
  );
}
