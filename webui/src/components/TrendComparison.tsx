import type {
  StudyCheck,
  TrendComparisonRow,
  TrendComparisonSnapshot,
  TrendSearchComparison,
} from "../api/client";
import { conditionLabel, FIELDS, OP_SYMBOLS } from "../lib/study";
import { number } from "../lib/format";
import { Empty } from "./ui";

export const CHANGE_LABELS = {
  entered: "新出现",
  continued: "持续匹配",
  exited: "已退出",
  uncertain: "无法确认",
} as const;
export type ChangeFilter = "all" | keyof typeof CHANGE_LABELS;

function actualText(check: StudyCheck | undefined) {
  if (!check || check.actual == null) return "资料不足";
  return `${check.bound === "at_least" ? "至少 " : ""}${number(check.actual, check.condition.field.includes("days") ? 0 : 2)}${FIELDS[check.condition.field].unit}`;
}
export function matchText(matched: boolean | null) {
  return matched == null ? "无法判断" : matched ? "符合" : "不符合";
}
function changeReason(row: TrendComparisonRow) {
  if (row.status === "uncertain") {
    const gaps = (
      [
        ["对照日", row.previous],
        ["当前日", row.current],
      ] as const
    )
      .filter(([, snapshot]) => snapshot.matched === null)
      .map(([label, snapshot]) => `${label}：${snapshot.reason || "资料不足"}`);
    return gaps.join("；");
  }
  const old = row.previous.conditions ?? [];
  const changed = (row.current.conditions ?? []).flatMap((check, index) => {
    const prior = old[index];
    if (
      !prior ||
      (prior.actual === check.actual &&
        prior.matched === check.matched &&
        prior.bound === check.bound)
    )
      return [];
    return [
      `${conditionLabel(check.condition)}：${actualText(prior)} → ${actualText(check)}`,
    ];
  });
  return changed.join("；") || "两日条件实际值相同";
}

export function ComparisonSummary({
  comparison,
  currentDate,
  active,
  onSelect,
}: {
  comparison: TrendSearchComparison;
  currentDate: string;
  active: ChangeFilter | null;
  onSelect: (filter: ChangeFilter) => void;
}) {
  const coverage = comparison.coverage;
  return (
    <section className="trend-comparison-summary" aria-label="两日变化概览">
      <header>
        <div>
          <strong>两日变化</strong>
          <span>
            {comparison.as_of} → {currentDate}
          </span>
        </div>
        <button
          type="button"
          className="small-link"
          onClick={() => onSelect("all")}
        >
          查看变化明细
        </button>
      </header>
      <div
        className="comparison-status-tabs"
        role="group"
        aria-label="按变化状态查看"
      >
        {Object.entries(CHANGE_LABELS).map(([status, label]) => (
          <button
            type="button"
            key={status}
            data-status={status}
            aria-pressed={active === status}
            onClick={() => onSelect(status as ChangeFilter)}
          >
            <span>{label}</span>
            <b>{number(coverage?.[status as keyof typeof CHANGE_LABELS], 0)}</b>
          </button>
        ))}
      </div>
      <p>
        同一股票范围 · 两日可判断 {number(coverage?.comparable, 0)} 只 ·
        两日均未匹配 {number(coverage?.unchanged, 0)} 只
      </p>
      {(coverage?.uncertain ?? 0) > 0 ? (
        <p>资料不足单列为“无法确认”，不计入新出现或已退出。</p>
      ) : null}
      {(comparison.excluded_rows?.length ?? 0) > 0 ? (
        <details>
          <summary>
            形态自匹配排除 {comparison.excluded_rows!.length} 只
          </summary>
          {comparison.excluded_rows!.map((row) => (
            <p key={row.symbol}>
              {row.name} {row.symbol} · {row.reason}
            </p>
          ))}
        </details>
      ) : null}
    </section>
  );
}

function SnapshotCell({ value }: { value: TrendComparisonSnapshot }) {
  return (
    <>
      <span className="comparison-match" data-match={String(value.matched)}>
        {matchText(value.matched)}
      </span>
      <small>收盘 {number(value.close)}</small>
    </>
  );
}

export function TrendChangesTable({
  rows,
  currentDate,
  previousDate,
  selected,
  onSelect,
}: {
  rows: TrendComparisonRow[];
  currentDate: string;
  previousDate: string;
  selected: string | null;
  onSelect: (symbol: string) => void;
}) {
  if (!rows.length)
    return (
      <Empty title="这个变化范围没有结果">
        <p>可选择其他变化状态或返回当前匹配。</p>
      </Empty>
    );
  return (
    <div className="table-scroll">
      <table className="trend-result-table trend-changes-table">
        <thead>
          <tr>
            <th>股票</th>
            <th>变化</th>
            <th>对照日 {previousDate}</th>
            <th>当前日 {currentDate}</th>
            <th>条件变化 / 缺口</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.symbol}
              className={selected === row.symbol ? "selected" : ""}
              onClick={() => onSelect(row.symbol)}
            >
              <td>
                <button
                  type="button"
                  className="stock-button"
                  aria-label={`查看变化 ${row.name} ${row.symbol}`}
                  onClick={() => onSelect(row.symbol)}
                >
                  <small>{row.symbol}</small>
                  <strong>{row.name}</strong>
                </button>
              </td>
              <td>
                <span className="change-tag" data-status={row.status}>
                  {CHANGE_LABELS[row.status]}
                </span>
              </td>
              <td>
                <SnapshotCell value={row.previous} />
              </td>
              <td>
                <SnapshotCell value={row.current} />
              </td>
              <td className="change-reason">{changeReason(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ConditionChanges({
  row,
  currentDate,
  previousDate,
}: {
  row: TrendComparisonRow;
  currentDate: string;
  previousDate: string;
}) {
  const conditions = row.current.conditions?.length
    ? row.current.conditions
    : (row.previous.conditions ?? []);
  return (
    <section className="condition-changes">
      <header>
        <h3>为什么{CHANGE_LABELS[row.status]}</h3>
        <span className="change-tag" data-status={row.status}>
          {CHANGE_LABELS[row.status]}
        </span>
      </header>
      <div className="comparison-day-status">
        <span>
          {previousDate}
          <b>{matchText(row.previous.matched)}</b>
        </span>
        <span aria-hidden="true">→</span>
        <span>
          {currentDate}
          <b>{matchText(row.current.matched)}</b>
        </span>
      </div>
      {conditions.length ? (
        <div className="comparison-checks">
          {conditions.map((check, index) => (
            <div className="comparison-check" key={index}>
              <div>
                <strong>{conditionLabel(check.condition)}</strong>
                <small>
                  要求 {OP_SYMBOLS[check.condition.operator]}{" "}
                  {check.condition.value}
                  {FIELDS[check.condition.field].unit}
                </small>
              </div>
              <span
                data-match={String(
                  row.previous.conditions?.[index]?.matched ?? null,
                )}
              >
                {actualText(row.previous.conditions?.[index])}
              </span>
              <span aria-hidden="true">→</span>
              <span
                data-match={String(
                  row.current.conditions?.[index]?.matched ?? null,
                )}
              >
                {actualText(row.current.conditions?.[index])}
              </span>
            </div>
          ))}
        </div>
      ) : null}
      {row.previous.reason ? (
        <p>
          {previousDate}：{row.previous.reason}
        </p>
      ) : null}
      {row.current.reason ? (
        <p>
          {currentDate}：{row.current.reason}
        </p>
      ) : null}
      {row.status === "uncertain" ? (
        <p>缺少可判断的事实，不能把它解释为新增或退出。</p>
      ) : null}
    </section>
  );
}
