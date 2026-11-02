import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CheckCircle2, CircleAlert } from "lucide-react";
import {
  api,
  type StudyEvidence,
  type TrendSearchQuery,
  type TrendSearchRow,
} from "../api/client";
import { StudyChart, ShapeOverlay } from "./StudyChart";
import { Button, Loading, Notice } from "./ui";
import { conditionLabel, FIELDS, OP_SYMBOLS } from "../lib/study";
import { errorMessage, number, percent } from "../lib/format";

export function segmentLabel(row: TrendSearchRow) {
  const segment = row.current_segment;
  if (!segment) return "段长待核";
  if (segment.direction === "flat") return "当日平盘";
  return `连${segment.direction === "up" ? "涨" : "跌"} ${segment.bound === "at_least" ? "≥" : ""}${segment.days} 天`;
}
export function PriceSparkline({
  points,
}: {
  points: TrendSearchRow["sparkline"];
}) {
  const values = points.flatMap((point) =>
    point.close == null ? [] : [point.close],
  );
  if (values.length < 2) return <span className="muted">行情不足</span>;
  const min = Math.min(...values),
    max = Math.max(...values),
    span = max - min || 1;
  let previous = false;
  const path = points
    .map((point, i) => {
      if (point.close == null) {
        previous = false;
        return "";
      }
      const command = previous ? "L" : "M";
      previous = true;
      return `${command}${((i / Math.max(1, points.length - 1)) * 108 + 2).toFixed(1)},${(34 - ((point.close - min) / span) * 28).toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      className="price-sparkline"
      viewBox="0 0 112 40"
      role="img"
      aria-label={`近${points.length}个交易日收盘走势，${points[0]?.date}至${points.at(-1)?.date}`}
    >
      <path
        d={path}
        fill="none"
        stroke={values.at(-1)! >= values[0]! ? "var(--up)" : "var(--down)"}
        strokeWidth="1.7"
      />
      <title>真实收盘价走势；缺失日期断线</title>
    </svg>
  );
}

export function TrendStockDetail({
  row,
  query,
  onBack,
  onHistory,
  onShape,
  busy,
}: {
  row: TrendSearchRow;
  query: TrendSearchQuery;
  onBack: () => void;
  onHistory: () => void;
  onShape: () => void;
  busy: boolean;
}) {
  const evidence = useQuery({
    queryKey: ["trend-evidence", query, row.symbol],
    queryFn: () => api.trendEvidence(query, row.symbol),
    staleTime: Infinity,
    retry: false,
  });
  const data = evidence.data;
  const actual = data?.row ?? row;
  const segment = actual.current_segment;
  const chart: StudyEvidence | undefined = data
    ? {
        run_id: "current",
        symbol: actual.symbol,
        name: actual.name,
        event_date: data.as_of,
        source: actual.source,
        bars: data.bars,
        conditions: data.conditions,
        outcome: null,
        warnings: data.warnings,
        reference_bars: data.reference_bars,
        reference_source: data.reference_source,
      }
    : undefined;
  return (
    <aside className="trend-detail">
      <button
        className="small-link mobile-detail-back"
        type="button"
        onClick={onBack}
      >
        <ArrowLeft size={16} />
        返回筛选结果
      </button>
      <header className="trend-detail-heading">
        <h2>
          <span>{actual.symbol}</span>
          {actual.name}
        </h2>
        <p>
          {actual.date}
          <span>
            收盘 <b>{number(actual.close)}</b>
          </span>
          <strong
            className={
              (actual.change_pct ?? 0) >= 0 ? "value-up" : "value-down"
            }
          >
            {percent(actual.change_pct, 2)}
          </strong>
        </p>
      </header>
      {evidence.isLoading ? (
        <Loading>读取日线与条件证据</Loading>
      ) : evidence.error ? (
        <Notice error>{errorMessage(evidence.error)}</Notice>
      ) : chart ? (
        <StudyChart
          key={`${actual.symbol}-${actual.date}`}
          evidence={chart}
          context="market"
          tone="light"
          segmentStart={segment?.start_date}
        />
      ) : null}
      {segment ? (
        <div className="segment-facts">
          <div>
            <span>本段首日</span>
            <strong>{segment.start_date}</strong>
          </div>
          <div>
            <span>{segmentLabel(actual)}</span>
            <small>基准收盘 {segment.base_date}</small>
          </div>
          <div>
            <span>本段变化</span>
            <strong
              className={segment.return_pct >= 0 ? "value-up" : "value-down"}
            >
              {percent(segment.return_pct, 2)}
            </strong>
          </div>
        </div>
      ) : null}
      {segment?.bound === "at_least" ? (
        <p className="field-hint">
          缓存开始或行情缺口前的段长不可确认；这里显示的是已知下界。
        </p>
      ) : null}
      <section className="trend-checks">
        <h3>条件验证</h3>
        {data?.conditions.length ? (
          data.conditions.map((check, i) => (
            <div key={i}>
              <span>
                {conditionLabel(check.condition)}
                <small>
                  要求 {OP_SYMBOLS[check.condition.operator]}{" "}
                  {check.condition.value}
                  {FIELDS[check.condition.field].unit}
                </small>
              </span>
              <strong>
                {check.bound === "at_least" ? "≥ " : ""}
                {number(
                  check.actual,
                  check.condition.field.includes("days") ? 0 : 2,
                )}
                {FIELDS[check.condition.field].unit}
              </strong>
              {check.matched === true ? (
                <CheckCircle2 size={16} />
              ) : (
                <CircleAlert size={16} />
              )}
            </div>
          ))
        ) : (
          <p className="field-hint">当前是无条件浏览，尚未设置筛选规则。</p>
        )}
      </section>
      <section className="trend-position">
        <h3>
          多周期位置 <small>收盘价在区间高低点之间的位置</small>
        </h3>
        {[30, 60, 180].map((window) => (
          <div key={window}>
            <span>{window}日</span>
            <strong>{percent(actual.positions[String(window)], 0)}</strong>
            <i>
              <b
                style={{
                  width: `${Math.max(0, Math.min(100, actual.positions[String(window)] ?? 0))}%`,
                }}
              />
            </i>
          </div>
        ))}
      </section>
      {chart && (chart.reference_bars?.length ?? 0) > 0 ? (
        <ShapeOverlay evidence={chart} context="market" />
      ) : null}
      <div className="trend-detail-actions">
        <Button
          variant="secondary"
          onClick={onHistory}
          disabled={busy || !query.conditions?.length}
        >
          核对历史
        </Button>
        <button
          type="button"
          className="small-link"
          onClick={onShape}
          disabled={busy}
        >
          按这段形态查找 <ArrowRight size={14} />
        </button>
      </div>
      <details className="daily-evidence">
        <summary>逐日核对收盘与涨跌</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>收盘</th>
                <th>较前日</th>
                <th>实体涨跌</th>
              </tr>
            </thead>
            <tbody>
              {data?.bars
                .slice(-20)
                .reverse()
                .map((bar) => (
                  <tr key={bar.date}>
                    <td>{bar.date}</td>
                    <td>{number(bar.close)}</td>
                    <td>{percent(bar.change_pct, 2)}</td>
                    <td>{percent(bar.body_pct, 2)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
      {data?.warnings.map((warning) => (
        <Notice key={warning}>{warning}</Notice>
      ))}
      <p className="field-hint">
        来源：{actual.source} · 当前缓存事实；核对历史后才保存研究证据。
      </p>
    </aside>
  );
}
