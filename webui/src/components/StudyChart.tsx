import { useEffect, useRef, useState } from "react";
import { Crosshair } from "lucide-react";
import type {
  StudyDistribution,
  StudyEvidence,
  SwingEvidence,
} from "../api/client";
import { number, percent } from "../lib/format";

export function StudyChart({
  evidence,
  context = "study",
  tone = "dark",
  segmentStart,
  swing,
  observation,
}: {
  evidence: StudyEvidence;
  context?: "study" | "market";
  tone?: "dark" | "light";
  segmentStart?: string;
  swing?: SwingEvidence;
  observation?: {
    start: string | null;
    boundary: string | null;
    window: number;
  };
}) {
  const holder = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(820);
  const [nearEvent, setNearEvent] = useState(context === "market");
  const [hoveredDate, setHoveredDate] = useState(evidence.event_date);
  const eventOffset = evidence.bars.findIndex(
    (bar) => bar.date === evidence.event_date,
  );
  const segmentOffset = segmentStart
    ? evidence.bars.findIndex((bar) => bar.date >= segmentStart)
    : eventOffset;
  const nearStart = swing
    ? Math.max(0, eventOffset - swing.window + 1)
    : context === "market"
      ? Math.max(0, Math.min(eventOffset - 29, Math.max(0, segmentOffset) - 8))
      : Math.max(0, eventOffset - 30);
  const bars = observation
    ? observation.start
      ? evidence.bars.filter((bar) => bar.date >= observation.start!)
      : evidence.bars.slice(-(2 * observation.window + 1))
    : nearEvent
      ? evidence.bars.slice(nearStart)
      : evidence.bars;
  const eventIndex = bars.findIndex((bar) => bar.date === evidence.event_date);
  const hoveredIndex = Math.max(
    0,
    bars.findIndex((bar) => bar.date === hoveredDate),
  );
  const hovered = bars[hoveredIndex];
  const prices = bars
    .flatMap((bar) => [bar.high, bar.low])
    .filter(
      (value): value is number => value != null && Number.isFinite(value),
    );
  useEffect(() => {
    const element = holder.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.max(280, entry.contentRect.width));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  if (!prices.length)
    return <div className="candle-empty">这份证据没有可绘制的完整价格。</div>;
  const high = Math.max(...prices),
    low = Math.min(...prices);
  const range = high - low || Math.max(1, high * 0.02);
  const ceiling = high + range * 0.12,
    floor = low - range * 0.12;
  const inset = 18,
    right = width < 500 ? 43 : 56,
    plotWidth = width - inset - right;
  const step = plotWidth / Math.max(1, bars.length);
  const x = (index: number) => inset + (index + 0.5) * step;
  const y = (price: number) =>
    37 + ((ceiling - price) / (ceiling - floor)) * 205;
  const maxVolume = Math.max(1, ...bars.map((bar) => bar.volume ?? 0));
  const bodyWidth = Math.max(1, Math.min(9, step * 0.64));
  const gridPrices = Array.from(
    { length: 5 },
    (_, index) => ceiling - ((ceiling - floor) * index) / 4,
  );
  const axisIndexes = [
    ...new Set([
      0,
      Math.floor(bars.length / 3),
      Math.floor((bars.length * 2) / 3),
      bars.length - 1,
    ]),
  ];
  const eventX = x(eventIndex);
  const boundaryIndex = observation?.boundary
    ? bars.findIndex((bar) => bar.date === observation.boundary)
    : -1;
  const boundaryX = boundaryIndex >= 0 ? x(boundaryIndex) : null;
  const pivotPoints = (swing?.pivots ?? []).flatMap((pivot) => {
    const index = bars.findIndex((bar) => bar.date === pivot.date);
    return index < 0 ? [] : [{ ...pivot, x: x(index), y: y(pivot.price) }];
  });
  const currentPoints = swing?.current
    ? [
        { date: swing.current.start_date, price: swing.current.start_price },
        {
          date: swing.current.extreme_date,
          price: swing.current.extreme_price,
        },
        { date: evidence.event_date, price: evidence.bars[eventOffset]?.close },
      ].flatMap((point) => {
        const index = bars.findIndex((bar) => bar.date === point.date);
        return index < 0 || point.price == null
          ? []
          : [`${x(index)},${y(point.price)}`];
      })
    : [];
  const pointerDate = (clientX: number) => {
    const bounds = holder.current?.getBoundingClientRect();
    if (!bounds) return;
    const index = Math.max(
      0,
      Math.min(
        bars.length - 1,
        Math.floor((clientX - bounds.left - inset) / step),
      ),
    );
    const bar = bars[index];
    if (bar) setHoveredDate(bar.date);
  };
  return (
    <section className={`candle-panel candle-panel--${tone}`} ref={holder}>
      <div className="candle-heading">
        <div>
          <h2>{evidence.name}</h2>
          <span>{evidence.symbol}</span>
          <strong>
            {evidence.event_date}
            <small>{context === "study" ? "选中事件" : "数据日"}</small>
          </strong>
        </div>
        <div className="chart-controls">
          {observation ? (
            <span className="chart-observation-label">
              相邻两期 · 各 {observation.window} 个交易日
            </span>
          ) : (
            <>
              <button
                type="button"
                className={!nearEvent ? "active" : ""}
                aria-pressed={!nearEvent}
                onClick={() => setNearEvent(false)}
              >
                完整窗口
              </button>
              <button
                type="button"
                className={nearEvent ? "active" : ""}
                aria-pressed={nearEvent}
                onClick={() => setNearEvent(true)}
              >
                {swing
                  ? `${swing.window} 日波段`
                  : context === "study"
                    ? "事件附近"
                    : "本段附近"}
              </button>
              <Crosshair size={16} aria-hidden="true" />
            </>
          )}
        </div>
      </div>
      <div className="candle-readout" aria-live="polite">
        <strong>{hovered?.date}</strong>
        <span>
          开 <b>{number(hovered?.open)}</b>
        </span>
        <span>
          高 <b>{number(hovered?.high)}</b>
        </span>
        <span>
          低 <b>{number(hovered?.low)}</b>
        </span>
        <span>
          收 <b>{number(hovered?.close)}</b>
        </span>
        <span className="candle-volume-readout">
          量 <b>{number(hovered?.volume, 0)}</b>
        </span>
      </div>
      {context === "market" ? (
        <p className="chart-visible-range">
          {bars[0]?.date} — {bars.at(-1)?.date} · {bars.length} 个交易日
        </p>
      ) : null}
      <svg
        viewBox={`0 0 ${width} 328`}
        role="img"
        aria-label={`${evidence.name} 日K与成交量，事件日 ${evidence.event_date}。左右方向键查看逐日价格。`}
        tabIndex={0}
        onPointerMove={(event) => pointerDate(event.clientX)}
        onPointerDown={(event) => pointerDate(event.clientX)}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            const next =
              bars[
                Math.max(
                  0,
                  Math.min(
                    bars.length - 1,
                    hoveredIndex + (event.key === "ArrowLeft" ? -1 : 1),
                  ),
                )
              ];
            if (next) setHoveredDate(next.date);
          }
        }}
      >
        <rect
          x={inset}
          y={30}
          width={Math.max(0, eventX - inset)}
          height={272}
          className="chart-formation"
        />
        <rect
          x={eventX}
          y={30}
          width={Math.max(0, plotWidth - eventX + inset)}
          height={272}
          className={context === "study" ? "chart-outcome" : "chart-formation"}
        />
        {boundaryX != null ? (
          <>
            <rect
              x={inset}
              y={30}
              width={boundaryX - inset}
              height={272}
              className="chart-observation-previous"
            />
            <rect
              x={boundaryX}
              y={30}
              width={width - right - boundaryX}
              height={272}
              className="chart-observation-current"
            />
            <line
              x1={boundaryX}
              x2={boundaryX}
              y1={30}
              y2={302}
              className="chart-observation-boundary"
            />
          </>
        ) : null}
        {segmentStart && bars.some((bar) => bar.date >= segmentStart) ? (
          <rect
            x={x(bars.findIndex((bar) => bar.date >= segmentStart)) - step / 2}
            y={30}
            width={Math.max(
              0,
              eventX -
                x(bars.findIndex((bar) => bar.date >= segmentStart)) +
                step,
            )}
            height={272}
            className="chart-current-segment"
          />
        ) : null}
        {gridPrices.map((price) => (
          <g key={price}>
            <line
              x1={inset}
              x2={width - right}
              y1={y(price)}
              y2={y(price)}
              className="chart-grid"
            />
            <text x={width - right + 8} y={y(price) + 4} className="chart-axis">
              {number(price)}
            </text>
          </g>
        ))}
        {axisIndexes.map((index) => (
          <g key={index}>
            <line
              x1={x(index)}
              x2={x(index)}
              y1={31}
              y2={303}
              className="chart-grid chart-grid--vertical"
            />
            <text
              x={x(index)}
              y={321}
              textAnchor={
                index === 0
                  ? "start"
                  : index === bars.length - 1
                    ? "end"
                    : "middle"
              }
              className="chart-axis"
            >
              {(index === 0 || index === bars.length - 1) &&
              bars[0]?.date.slice(0, 4) !== bars.at(-1)?.date.slice(0, 4)
                ? bars[index]?.date
                : bars[index]?.date.slice(5)}
            </text>
          </g>
        ))}
        <text x={inset + 8} y={20} className="chart-window-label">
          {observation
            ? `前期 ${observation.window} 日`
            : context === "study"
              ? "条件形成（日线）"
              : "日线与成交量"}
        </text>
        <text
          x={
            boundaryX != null
              ? boundaryX + 8
              : Math.min(width - right - 68, Math.max(inset + 140, eventX + 10))
          }
          y={20}
          className="chart-event-label"
        >
          {observation && boundaryX != null
            ? `本期 ${observation.window} 日`
            : context === "study"
              ? "后续观察"
              : ""}
        </text>
        {bars.map((bar, index) => {
          if (
            bar.open == null ||
            bar.close == null ||
            bar.high == null ||
            bar.low == null
          )
            return null;
          const tone = bar.close >= bar.open ? "candle-up" : "candle-down";
          return (
            <g key={bar.date} className={tone}>
              <line
                x1={x(index)}
                x2={x(index)}
                y1={y(bar.high)}
                y2={y(bar.low)}
              />
              <rect
                x={x(index) - bodyWidth / 2}
                y={Math.min(y(bar.open), y(bar.close))}
                width={bodyWidth}
                height={Math.max(1.4, Math.abs(y(bar.open) - y(bar.close)))}
              />
              {bar.volume != null ? (
                <rect
                  className="chart-volume"
                  x={x(index) - bodyWidth / 2}
                  y={302 - (bar.volume / maxVolume) * 44}
                  width={bodyWidth}
                  height={(bar.volume / maxVolume) * 44}
                />
              ) : null}
            </g>
          );
        })}
        {swing ? (
          <g className="swing-chart-overlay">
            <polyline
              points={pivotPoints
                .map((point) => `${point.x},${point.y}`)
                .join(" ")}
              className="swing-confirmed-line"
            />
            {currentPoints.length > 1 ? (
              <polyline
                points={currentPoints.join(" ")}
                className="swing-current-line"
              />
            ) : null}
            {pivotPoints.map((point) => (
              <g key={point.date}>
                <circle
                  cx={point.x}
                  cy={point.y}
                  r={4}
                  className="swing-pivot-dot"
                >
                  <title>
                    {point.kind === "high" ? "波峰" : "波谷"} {point.date} ·
                    收盘 {number(point.price)} · 确认于 {point.confirmed_at}
                  </title>
                </circle>
                {pivotPoints.length <= 12 ? (
                  <text
                    x={point.x}
                    y={point.y + (point.kind === "high" ? -10 : 17)}
                    textAnchor="middle"
                    className="swing-pivot-label"
                  >
                    {point.kind === "high" ? "峰" : "谷"}
                  </text>
                ) : null}
              </g>
            ))}
          </g>
        ) : null}
        <line
          x1={inset}
          x2={width - right}
          y1={251}
          y2={251}
          className="chart-grid"
        />
        <line
          x1={eventX}
          x2={eventX}
          y1={30}
          y2={303}
          className="chart-event-line"
        />
        <circle cx={eventX} cy={31} r={3.5} className="chart-event-dot" />
        {hovered ? (
          <>
            <line
              x1={x(hoveredIndex)}
              x2={x(hoveredIndex)}
              y1={31}
              y2={303}
              className="chart-crosshair"
            />
            {hovered.close != null ? (
              <line
                x1={inset}
                x2={width - right}
                y1={y(hovered.close)}
                y2={y(hovered.close)}
                className="chart-crosshair"
              />
            ) : null}
          </>
        ) : null}
      </svg>
      <p className="chart-note">
        移动指针或使用左右方向键查看日期与价格；空缺保留为缺失。价格使用本次展示数据的复权口径。
      </p>
    </section>
  );
}

export function DistributionChart({
  data,
  days,
}: {
  data: StudyDistribution;
  days: number;
}) {
  const bins = data.bins ?? [];
  const max = Math.max(1, ...bins.map((bin) => bin.count));
  return (
    <section className="distribution">
      <div className="section-heading">
        <h3>{days}日后涨跌分布</h3>
        <span>完整观察样本：{data.count}</span>
      </div>
      {bins.length ? (
        <div
          className="histogram"
          role="img"
          aria-label={`${days}日后涨跌分布，${data.count}个完整样本，中位数${percent(data.median_pct)}`}
        >
          <div className="histogram-bars">
            {bins.map((bin) => (
              <div
                className="histogram-bin"
                key={bin.label}
                title={`${bin.label}：${bin.count} 个样本`}
              >
                <span>{bin.count || ""}</span>
                <i style={{ height: `${(bin.count / max) * 84}px` }} />
                <small>{bin.label}</small>
              </div>
            ))}
          </div>
          <p>
            中位数 <strong>{percent(data.median_pct, 2)}</strong>
            <span>P10 {percent(data.p10_pct, 2)}</span>
            <span>P90 {percent(data.p90_pct, 2)}</span>
          </p>
        </div>
      ) : (
        <p className="muted">
          暂时没有完整观察样本。未完成窗口与缺失数据不计入分布。
        </p>
      )}
    </section>
  );
}

export function ShapeOverlay({
  evidence,
  context = "study",
}: {
  evidence: StudyEvidence;
  context?: "study" | "market";
}) {
  const condition = evidence.conditions.find(
    (item) => item.condition.field === "shape_distance",
  );
  const window = condition?.condition.window;
  if (!window || !evidence.reference_bars?.length) return null;
  const reference = evidence.reference_bars.slice(-window);
  const current = evidence.bars
    .filter((bar) => bar.date <= evidence.event_date)
    .slice(-window);
  const normalize = (bars: typeof current) =>
    bars.map((bar) =>
      bar.close != null && bars[0]?.close
        ? (bar.close / bars[0].close) * 100
        : null,
    );
  const first = normalize(reference),
    second = normalize(current);
  const values = [...first, ...second].filter(
    (value): value is number => value != null,
  );
  if (!values.length) return null;
  const min = Math.min(...values),
    max = Math.max(...values),
    range = Math.max(1, max - min);
  const x = (index: number) => 38 + (index / Math.max(1, window - 1)) * 590;
  const y = (value: number) =>
    25 + ((max + range * 0.1 - value) / (range * 1.2)) * 110;
  const path = (series: Array<number | null>) => {
    let connected = false;
    return series
      .map((value, index) => {
        if (value == null) {
          connected = false;
          return "";
        }
        const command = connected ? "L" : "M";
        connected = true;
        return `${command}${x(index)},${y(value)}`;
      })
      .join(" ");
  };
  return (
    <section className="shape-overlay">
      <div className="section-heading">
        <h3>与参照形态叠加</h3>
        <span>{window}日 · 各自首日 = 100</span>
      </div>
      <svg
        viewBox="0 0 660 170"
        role="img"
        aria-label={`${window}日归一化收盘形态对比`}
      >
        <line
          x1={38}
          x2={628}
          y1={y(100)}
          y2={y(100)}
          className="overlay-grid"
        />
        <text x={4} y={y(100) + 4}>
          100
        </text>
        <path d={path(first)} className="overlay-reference" />
        <path d={path(second)} className="overlay-current" />
        <text x={38} y={160}>
          第1日
        </text>
        <text x={628} y={160} textAnchor="end">
          第{window}日
        </text>
      </svg>
      <div className="overlay-legend">
        <span>
          <i />
          {context === "study" ? "冻结的参照" : "参照形态"}
        </span>
        <span>
          <i />
          {context === "study" ? "选中事件" : "当前对象"}
        </span>
        <strong>均方根距离 {number(condition?.actual, 2)} 个百分点</strong>
      </div>
      <p className="field-hint">
        比较已经发生的价格形态；相似不表示后续走势相同。
      </p>
    </section>
  );
}
