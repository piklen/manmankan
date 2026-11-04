import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CheckCircle2, CircleAlert } from "lucide-react";
import {
  api,
  type StudyEvidence,
  type TrendSearchQuery,
  type TrendComparisonRow,
  type TrendSearchRow,
} from "../api/client";
import { SwingEvidencePanel } from "./SwingEvidence";
import { ConditionChanges } from "./TrendComparison";
import { StudyChart, ShapeOverlay } from "./StudyChart";
import { Button, Loading, Notice } from "./ui";
import { conditionLabel, fieldValue, OP_SYMBOLS } from "../lib/study";
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
  selection,
  row,
  query,
  currentDate,
  revision,
  comparison,
  comparisonDate,
  onBack,
  onHistory,
  onShape,
  busy,
}: {
  selection: { symbol: string; name: string };
  row?: TrendSearchRow;
  query: TrendSearchQuery;
  currentDate: string;
  revision: number;
  comparison?: TrendComparisonRow;
  comparisonDate?: string;
  onBack: () => void;
  onHistory: () => void;
  onShape: (row: TrendSearchRow) => void;
  busy: boolean;
}) {
  const [swingWindow, setSwingWindow] = useState<number | null>(null);
  const [side, setSide] = useState<"current" | "previous">(
    comparison &&
      comparison.current.close == null &&
      comparison.previous.close != null
      ? "previous"
      : "current",
  );
  const at =
    side === "previous" && comparisonDate ? comparisonDate : currentDate;
  const snapshot = comparison?.[side];
  const noQuote = Boolean(comparison && snapshot?.close == null);
  const evidence = useQuery({
    queryKey: ["trend-evidence", query, selection.symbol, at, revision],
    queryFn: () => api.trendEvidence(query, selection.symbol, at),
    enabled: !noQuote,
    staleTime: Infinity,
    retry: false,
  });
  const data = noQuote ? undefined : evidence.data;
  const actual = data?.row ?? (at === currentDate ? row : undefined);
  const segment = actual?.current_segment;
  const swing = data?.swings?.find((item) => item.window === swingWindow) ?? data?.swings?.[0];
  const chart: StudyEvidence | undefined =
    data && actual
      ? {
          run_id: "current",
          symbol: actual.symbol,
          name: actual.name,
          event_date: data.as_of,
          source: actual.source,
          bars: data.bars,
          conditions: data.conditions,
          swings: data.swings,
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
          <span>{selection.symbol}</span>
          {selection.name}
        </h2>
        <p>
          {at}
          <span>
            收盘 <b>{number(actual?.close ?? snapshot?.close)}</b>
          </span>
          <strong
            className={
              (actual?.change_pct ?? 0) >= 0 ? "value-up" : "value-down"
            }
          >
            {percent(actual?.change_pct, 2)}
          </strong>
        </p>
      </header>
      {comparison && comparisonDate ? (
        <>
          <ConditionChanges
            row={comparison}
            currentDate={currentDate}
            previousDate={comparisonDate}
          />
          <div
            className="comparison-evidence-tabs"
            role="group"
            aria-label="选择图证日期"
          >
            <button
              type="button"
              aria-pressed={side === "previous"}
              onClick={() => setSide("previous")}
            >
              对照日 {comparisonDate}
            </button>
            <button
              type="button"
              aria-pressed={side === "current"}
              onClick={() => setSide("current")}
            >
              当前日 {currentDate}
            </button>
          </div>
          <p className="field-hint">下方日线、连续段与位置均截至 {at}。</p>
        </>
      ) : null}
      {noQuote ? (
        <Notice>
          {snapshot?.reason || "这个日期没有可展示的行情。"} ·
          可切换另一日期核对已有证据。
        </Notice>
      ) : evidence.isLoading ? (
        <Loading>读取日线与条件证据</Loading>
      ) : evidence.error ? (
        <Notice error>{errorMessage(evidence.error)}</Notice>
      ) : chart ? (
        <StudyChart
          key={`${selection.symbol}-${at}`}
          evidence={chart}
          context="market"
          tone="light"
          segmentStart={swing ? undefined : segment?.start_date}
          swing={swing}
        />
      ) : null}
      {actual ? (
        <>
          {swing ? <SwingEvidencePanel evidence={swing} windows={data?.swings?.map((item) => item.window) ?? []} onWindow={setSwingWindow} /> : null}
          {segment && !swing ? (
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
                  className={
                    segment.return_pct >= 0 ? "value-up" : "value-down"
                  }
                >
                  {percent(segment.return_pct, 2)}
                </strong>
              </div>
            </div>
          ) : null}
          {!swing && segment?.bound === "at_least" ? (
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
                      {fieldValue(check.condition.field, check.condition.value)}
                    </small>
                  </span>
                  <strong>
                    {check.bound === "at_least" ? "≥ " : ""}
                    {fieldValue(check.condition.field, check.actual)}
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
              onClick={() => onShape(actual)}
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
        </>
      ) : null}
    </aside>
  );
}
