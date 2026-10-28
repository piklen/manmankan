import { Check, CircleHelp, Database } from "lucide-react";
import type { StudyEvidence, StudyResult } from "../api/client";
import { conditionLabel, FIELDS, OP_SYMBOLS } from "../lib/study";
import { number, percent } from "../lib/format";

export function EvidencePanel({
  evidence,
  result,
}: {
  evidence?: StudyEvidence;
  result: StudyResult;
}) {
  return (
    <aside className="evidence-panel">
      <h2>这次如何满足条件</h2>
      {evidence ? (
        <>
          <div className="evidence-subject">
            <strong>{evidence.name}</strong>
            <span>{evidence.symbol}</span>
          </div>
          <p className="evidence-date">
            事件日期 <b>{evidence.event_date}</b>
          </p>
          <div className="condition-proofs">
            {evidence.conditions.map((check, index) => (
              <article key={index} className="condition-proof">
                <div className="proof-heading">
                  <span
                    className={check.matched ? "proof-check" : "proof-unknown"}
                  >
                    {check.matched ? (
                      <Check size={14} />
                    ) : (
                      <CircleHelp size={14} />
                    )}
                  </span>
                  <h3>{conditionLabel(check.condition)}</h3>
                </div>
                <div className="proof-values">
                  <span>
                    实际{" "}
                    <strong>
                      {check.bound === "at_least" ? "≥ " : ""}
                      {number(check.actual)}
                      {FIELDS[check.condition.field].unit}
                    </strong>
                  </span>
                  <span>
                    条件 {OP_SYMBOLS[check.condition.operator]}{" "}
                    {check.condition.value}
                    {FIELDS[check.condition.field].unit}
                  </span>
                </div>
                <p>{FIELDS[check.condition.field].detail}</p>
                {check.bound === "at_least" ? (
                  <small>缓存起点截断，只能确认至少达到该天数。</small>
                ) : null}
              </article>
            ))}
          </div>
          <h2>后续实际变化</h2>
          {evidence.outcome ? (
            <article className="outcome-proof">
              <div>
                <span>事件日收盘</span>
                <strong>{number(evidence.outcome.event_close)}</strong>
              </div>
              <div>
                <span>{result.query.forward_days}日涨跌</span>
                <strong
                  className={
                    evidence.outcome.return_pct != null &&
                    evidence.outcome.return_pct >= 0
                      ? "value-up"
                      : "value-down"
                  }
                >
                  {percent(evidence.outcome.return_pct, 2)}
                </strong>
              </div>
              <div className="outcome-dates">
                <span>
                  {evidence.event_date}
                  <small>事件日</small>
                </span>
                <span>
                  {evidence.outcome.forward_date ?? "尚未完成"}
                  <small>观察结束</small>
                </span>
              </div>
              {evidence.outcome.status !== "complete" ? (
                <p>
                  {evidence.outcome.status === "pending"
                    ? "观察窗口尚未结束，未计入历史分布。"
                    : "观察窗口存在缺失数据，未计入历史分布。"}
                </p>
              ) : (
                <p>
                  期间最高变化 {percent(evidence.outcome.max_return_pct)} ·
                  最低变化 {percent(evidence.outcome.min_return_pct)}
                </p>
              )}
            </article>
          ) : (
            <p className="evidence-hint">
              当前满足条件；尚未形成可用的后续观察样本。
            </p>
          )}
        </>
      ) : (
        <div className="evidence-empty">
          <CircleHelp size={28} />
          <p>选择一条当前匹配或历史样本，在这里核对实际值、条件与后续变化。</p>
        </div>
      )}
      <h2>样本与来源</h2>
      <dl className="evidence-source">
        <div>
          <dt>当前可评估</dt>
          <dd>
            {result.coverage.current_evaluated} /{" "}
            {result.coverage.total_symbols}
          </dd>
        </div>
        <div>
          <dt>当前缺失</dt>
          <dd>{result.coverage.current_missing}</dd>
        </div>
        <div>
          <dt>历史范围</dt>
          <dd>
            {result.start_date}
            <br />至 {result.as_of}
          </dd>
        </div>
        <div>
          <dt>
            <Database size={13} /> 来源
          </dt>
          <dd>{evidence?.source ?? "选择样本后查看"}</dd>
        </div>
      </dl>
      <p className="evidence-hint">{result.universe_note}</p>
      {[...(result.warnings ?? []), ...(evidence?.warnings ?? [])].map(
        (warning) => (
          <p className="evidence-hint" key={warning}>
            {warning}
          </p>
        ),
      )}
    </aside>
  );
}
