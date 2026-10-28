import { ArrowRight, Info, Plus, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type StudyCondition, type StudyQuery } from "../api/client";
import { Button } from "./ui";
import {
  draftError,
  FIELDS,
  OPERATORS,
  SAMPLE_LABELS,
  type StudyDraft,
  UNIVERSE_LABELS,
} from "../lib/study";

export function StudyEditor({
  draft,
  onChange,
  onRun,
  busy,
  expanded,
  onToggle,
}: {
  draft: StudyDraft;
  onChange: (value: StudyDraft) => void;
  onRun: () => void;
  busy: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  const catalog = useQuery({
    queryKey: ["study-catalog"],
    queryFn: api.studyCatalog,
  });
  const error = draftError(draft);
  const update = (key: keyof StudyDraft, value: unknown) =>
    onChange({ ...draft, [key]: value });
  const hasShape = draft.conditions.some(
    (condition) => condition.field === "shape_distance",
  );
  return (
    <aside className={`study-editor${expanded ? " is-expanded" : ""}`}>
      <button
        className="editor-mobile-toggle"
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <strong>研究条件（{draft.conditions.length}）</strong>
        <span>{expanded ? "收起条件" : "编辑条件"}</span>
      </button>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!error) onRun();
        }}
      >
        <fieldset disabled={busy}>
          <h2>研究条件</h2>
          <label>
            研究标题
            <input
              maxLength={120}
              placeholder="为这次研究命名（可选）"
              value={draft.title}
              onChange={(event) => update("title", event.target.value)}
            />
          </label>
          <label>
            股票池
            <select
              value={draft.universe}
              onChange={(event) =>
                update("universe", event.target.value as StudyQuery["universe"])
              }
            >
              {Object.entries(UNIVERSE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {draft.universe === "codes" ? (
            <label>
              股票代码
              <textarea
                rows={2}
                placeholder="输入代码，用逗号分隔"
                value={draft.codes}
                onChange={(event) => update("codes", event.target.value)}
              />
            </label>
          ) : draft.universe === "personal" ? (
            <Link to="/data?tab=personal" className="small-link">
              管理个人股票池
              <ArrowRight size={12} />
            </Link>
          ) : (
            <p className="field-hint">
              使用当次股票池回看历史，不等于历史全市场。
            </p>
          )}
          <div className="field-row">
            <label>
              历史范围
              <span className="input-unit">
                <input
                  aria-label="历史范围交易日数"
                  type="number"
                  min={5}
                  max={1260}
                  value={draft.lookback}
                  onChange={(event) => update("lookback", event.target.value)}
                />
                <span>交易日</span>
              </span>
            </label>
            <label>
              截止日期
              <input
                aria-label="研究截止日期"
                type="date"
                value={draft.asOf}
                onChange={(event) => update("asOf", event.target.value)}
              />
            </label>
          </div>
          <p className="field-hint">截止日期留空时，使用最近完整交易日。</p>
          <div className="editor-section-heading">
            <h3>价格条件</h3>
            <span>全部满足</span>
          </div>
          <div className="condition-editor-list">
            {draft.conditions.map((condition, index) => (
              <div className="condition-editor" key={condition.id}>
                <div className="condition-editor-heading">
                  <label className="sr-only" htmlFor={`field-${condition.id}`}>
                    条件 {index + 1} 字段
                  </label>
                  <select
                    id={`field-${condition.id}`}
                    value={condition.field}
                    onChange={(event) =>
                      update(
                        "conditions",
                        draft.conditions.map((item) =>
                          item.id === condition.id
                            ? {
                                ...item,
                                field: event.target
                                  .value as StudyCondition["field"],
                                window: "",
                                value: "",
                              }
                            : item,
                        ),
                      )
                    }
                  >
                    <option value="">选择一个字段</option>
                    {(
                      catalog.data ??
                      Object.entries(FIELDS).map(([field, meta]) => ({
                        field,
                        ...meta,
                      }))
                    ).map((item) => (
                      <option key={item.field} value={item.field}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    aria-label={`删除条件 ${index + 1}`}
                    className="icon-button"
                    onClick={() =>
                      update(
                        "conditions",
                        draft.conditions.filter(
                          (item) => item.id !== condition.id,
                        ),
                      )
                    }
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
                {condition.field && FIELDS[condition.field].window ? (
                  <label className="condition-window">
                    区间窗口
                    <span className="input-unit">
                      <input
                        type="number"
                        aria-label={`条件 ${index + 1} 区间窗口`}
                        min={2}
                        max={360}
                        value={condition.window}
                        onChange={(event) =>
                          update(
                            "conditions",
                            draft.conditions.map((item) =>
                              item.id === condition.id
                                ? { ...item, window: event.target.value }
                                : item,
                            ),
                          )
                        }
                      />
                      <span>日</span>
                    </span>
                  </label>
                ) : null}
                <div className="condition-comparison">
                  <select
                    aria-label={`条件 ${index + 1} 比较关系`}
                    value={condition.operator}
                    onChange={(event) =>
                      update(
                        "conditions",
                        draft.conditions.map((item) =>
                          item.id === condition.id
                            ? {
                                ...item,
                                operator: event.target
                                  .value as StudyCondition["operator"],
                              }
                            : item,
                        ),
                      )
                    }
                  >
                    {Object.entries(OPERATORS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <span className="input-unit">
                    <input
                      aria-label={`条件 ${index + 1} 数值`}
                      type="number"
                      step="any"
                      value={condition.value}
                      onChange={(event) =>
                        update(
                          "conditions",
                          draft.conditions.map((item) =>
                            item.id === condition.id
                              ? { ...item, value: event.target.value }
                              : item,
                          ),
                        )
                      }
                    />
                    <span>
                      {condition.field ? FIELDS[condition.field].unit : ""}
                    </span>
                  </span>
                </div>
                {condition.field ? (
                  <p>
                    {catalog.data?.find(
                      (item) => item.field === condition.field,
                    )?.definition ?? FIELDS[condition.field].detail}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
          <button
            className="add-condition"
            type="button"
            disabled={draft.conditions.length >= 12}
            onClick={() =>
              update("conditions", [
                ...draft.conditions,
                {
                  id:
                    Math.max(0, ...draft.conditions.map((item) => item.id)) + 1,
                  field: "",
                  operator: "gte",
                  value: "",
                  window: "",
                },
              ])
            }
          >
            <Plus size={16} />
            添加条件
          </button>
          {hasShape ? (
            <div className="reference-editor">
              <h3>形态参照</h3>
              <label>
                参照股票
                <input
                  value={draft.referenceSymbol}
                  placeholder="6 位代码"
                  maxLength={6}
                  onChange={(event) =>
                    update("referenceSymbol", event.target.value)
                  }
                />
              </label>
              <label>
                参照截止日
                <input
                  type="date"
                  value={draft.referenceDate}
                  onChange={(event) =>
                    update("referenceDate", event.target.value)
                  }
                />
              </label>
              <p className="field-hint">
                这是使用已知参照进行的事后形态检索，不是历史可交易回测。
              </p>
            </div>
          ) : null}
          <label>
            样本选取
            <select
              value={draft.sample}
              onChange={(event) =>
                update(
                  "sample",
                  event.target.value as StudyQuery["sample_policy"],
                )
              }
            >
              {Object.entries(SAMPLE_LABELS).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            后续观察窗口
            <span className="input-unit">
              <input
                aria-label="后续观察窗口"
                type="number"
                min={1}
                max={60}
                value={draft.forward}
                onChange={(event) => update("forward", event.target.value)}
              />
              <span>个交易日</span>
            </span>
          </label>
          <p className="field-hint">
            <Info size={12} />
            历史样本占比，不代表未来概率。
          </p>
          <Button
            className="run-study"
            type="submit"
            disabled={Boolean(error) || busy}
          >
            {busy ? "正在核对日线" : "运行研究"}
            <ArrowRight size={16} />
          </Button>
          {error ? (
            <p className="editor-validation">{error}</p>
          ) : (
            <p className="field-hint">每次运行自动保存；只查询已获取的日线。</p>
          )}
          <Link to="/data" className="small-link">
            更新数据
            <ArrowRight size={12} />
          </Link>
        </fieldset>
      </form>
    </aside>
  );
}
