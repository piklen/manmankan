import { useEffect, useId, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import type { DiscoveryGroup } from "../api/client";
import { number, percent } from "../lib/format";

export function TransitionList({
  transitions,
  total,
  selected,
  onSelect,
}: {
  transitions: DiscoveryGroup["transitions"];
  total: number;
  selected: string | null;
  onSelect: (item: DiscoveryGroup["transitions"][number]) => void;
}) {
  return (
    <div className="transition-list">
      {transitions.map((item) => (
        <button
          type="button"
          key={item.key}
          aria-label={`${item.label}，${item.count}只，查看成员`}
          aria-pressed={selected === item.key}
          onClick={() => onSelect(item)}
          disabled={!item.count}
        >
          <span>{item.label}</span>
          <i>
            <b
              style={{ width: `${total ? (item.count / total) * 100 : 0}%` }}
            />
          </i>
          <strong>{number(item.count, 0)}</strong>
          <ChevronRight size={14} />
        </button>
      ))}
    </div>
  );
}

export function BreadthBar({ stats }: { stats: DiscoveryGroup["current"] }) {
  const parts = [
    { key: "up", label: "上涨", count: stats.up },
    { key: "flat", label: "持平", count: stats.flat },
    { key: "down", label: "下跌", count: stats.down },
  ];
  return (
    <div className="breadth-composition">
      <div
        className="breadth-bar"
        role="img"
        aria-label={parts.map((p) => `${p.label}${p.count}只`).join("，")}
      >
        {parts.map((part) => (
          <span
            key={part.key}
            className={`breadth-${part.key}`}
            style={{ flexGrow: part.count }}
          />
        ))}
      </div>
      <div className="breadth-legend">
        {parts.map((part) => (
          <span key={part.key}>
            <i className={`breadth-${part.key}`} />
            {part.label}
            <b>{number(part.count, 0)}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

export function BreadthHistory({
  group,
  window,
}: {
  group: DiscoveryGroup;
  window: number;
}) {
  const [metric, setMetric] = useState<"median_return" | "positive_share">(
    "median_return",
  );
  const [hover, setHover] = useState<number | null>(null);
  const gradientId = useId();
  const points = group.history;
  const activeIndex = Math.min(hover ?? points.length - 1, points.length - 1);
  const active = points[activeIndex];
  const title = metric === "median_return" ? "涨跌中位数" : "上涨占比";
  const plotContainer = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(500);
  useEffect(() => {
    if (!plotContainer.current) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry?.contentRect.width)
        setWidth(Math.max(160, entry.contentRect.width));
    });
    observer.observe(plotContainer.current);
    return () => observer.disconnect();
  }, []);
  const left = 38,
    right = 14,
    top = 12,
    bottom = 166;
  const values = points.flatMap((point) =>
    point[metric] == null ? [] : [point[metric]],
  );
  const low = Math.min(0, ...values),
    high = Math.max(0, ...values);
  const range = high - low;
  const rawStep = (range || 4) / 4;
  const scale = 10 ** Math.floor(Math.log10(rawStep));
  const step =
    ([1, 2, 2.5, 5, 10].find((n) => n * scale >= rawStep) ?? 10) * scale;
  const min = metric === "positive_share" ? 0 : Math.floor(low / step) * step;
  const max =
    metric === "positive_share"
      ? 100
      : Math.max(min + step, Math.ceil(high / step) * step);
  const interval = metric === "positive_share" ? 25 : step;
  const ticks = Array.from(
    { length: Math.round((max - min) / interval) + 1 },
    (_, i) => min + i * interval,
  );
  const x = (index: number) =>
    left + (index / Math.max(1, points.length - 1)) * (width - left - right);
  const y = (value: number) =>
    bottom - ((value - min) / (max - min)) * (bottom - top);
  let connected = false;
  const path = points
    .map((point, i) => {
      if (point[metric] == null) {
        connected = false;
        return "";
      }
      const command = connected ? "L" : "M";
      connected = true;
      return `${command}${x(i).toFixed(1)},${y(point[metric]).toFixed(1)}`;
    })
    .join(" ");
  const tickIndexes = [
    ...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]),
  ].filter((i) => i >= 0);
  return (
    <div ref={plotContainer} className="breadth-history chart-panel">
      <header className="panel-heading">
        <h2>趋势轨迹</h2>
        <div
          className="chart-toggle"
          role="group"
          aria-label={`${group.name}轨迹指标`}
        >
          {(["median_return", "positive_share"] as const).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={metric === key}
              onClick={() => setMetric(key)}
            >
              {key === "median_return" ? "涨跌中位数" : "上涨占比"}
            </button>
          ))}
        </div>
      </header>
      <p className="axis-title">
        {group.name} · 滚动 {window} 日 · 固定{" "}
        {number(group.history_available, 0)} 只
      </p>
      {values.length ? (
        <>
          <svg
            viewBox={`0 0 ${width} 198`}
            role="img"
            aria-label={`${group.name}${title}轨迹，固定${group.history_available}只成员，窗口${window}个交易日`}
            onMouseLeave={() => setHover(null)}
            onMouseMove={(event) => {
              const box = event.currentTarget.getBoundingClientRect();
              const position =
                (((event.clientX - box.left) / box.width) * width - left) /
                (width - left - right);
              setHover(
                Math.max(
                  0,
                  Math.min(
                    points.length - 1,
                    Math.round(position * (points.length - 1)),
                  ),
                ),
              );
            }}
          >
            {ticks.map((tick) => (
              <g key={tick}>
                <line
                  x1={left}
                  x2={width - right}
                  y1={y(tick)}
                  y2={y(tick)}
                  className={
                    tick === (metric === "positive_share" ? 50 : 0)
                      ? "history-midline"
                      : "history-grid"
                  }
                />
                <text x={left - 10} y={y(tick) + 4} textAnchor="end">
                  {number(tick, 3)}%
                </text>
              </g>
            ))}
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="0%"
                  stopColor="var(--chart-line)"
                  stopOpacity=".18"
                />
                <stop
                  offset="100%"
                  stopColor="var(--chart-line)"
                  stopOpacity=".01"
                />
              </linearGradient>
            </defs>
            {values.length === points.length && (
              <path
                d={`${path} L${x(points.length - 1)},${bottom} L${x(0)},${bottom} Z`}
                fill={`url(#${gradientId})`}
              />
            )}
            <path d={path} className="history-line" />
            {active?.[metric] != null ? (
              <g>
                <line
                  x1={x(activeIndex)}
                  x2={x(activeIndex)}
                  y1={top}
                  y2={bottom}
                  className="history-cursor"
                />
                <circle
                  cx={x(activeIndex)}
                  cy={y(active[metric])}
                  r="4"
                  className="history-dot"
                />
              </g>
            ) : null}
            {tickIndexes.map((i) => (
              <text
                key={i}
                x={x(i)}
                y="188"
                textAnchor={
                  i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"
                }
              >
                {points[i]?.date.slice(5)}
              </text>
            ))}
          </svg>
          <div className="history-readout">
            <span>{active?.date}</span>
            <strong>
              {title} {percent(active?.[metric], 2)}
            </strong>
            <span>
              {number(active?.up, 0)} / {number(active?.available, 0)} 只上涨
            </span>
          </div>
          <p className="history-explanation">
            曲线只看每一天资料都完整的成员，因此人数可能少于本期分布。
          </p>
          <details className="chart-data">
            <summary>逐日查看数值与分母</summary>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>截止日</th>
                    <th>上涨</th>
                    <th>下跌</th>
                    <th>持平</th>
                    <th>上涨占比</th>
                    <th>涨跌中位数</th>
                    <th>可比较成员</th>
                  </tr>
                </thead>
                <tbody>
                  {points.map((point) => (
                    <tr key={point.date}>
                      <td>{point.date}</td>
                      <td>{point.up}</td>
                      <td>{point.down}</td>
                      <td>{point.flat}</td>
                      <td>{percent(point.positive_share)}</td>
                      <td>{percent(point.median_return, 2)}</td>
                      <td>{point.available}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      ) : (
        <div className="chart-empty">
          历史窗口的完整成员不足，暂不绘制趋势。
        </div>
      )}
    </div>
  );
}

export function ReturnDistribution({
  group,
  active,
  onSelect,
}: {
  group: DiscoveryGroup;
  active: string | null;
  onSelect: (key: string, label: string) => void;
}) {
  const max = Math.max(1, ...group.distribution.map((bin) => bin.count));
  return (
    <div className="return-distribution">
      <div
        className="distribution-columns"
        role="group"
        aria-label="按区间涨跌查看成员"
      >
        {group.distribution.map((bin, i) => (
          <button
            type="button"
            key={bin.key}
            aria-pressed={active === bin.key}
            aria-label={`${bin.label}，${bin.count}只，查看成员`}
            onClick={() => onSelect(bin.key, bin.label)}
            disabled={!bin.count}
          >
            <span className="distribution-count">{bin.count}</span>
            <span className="distribution-track">
              <i
                className={
                  bin.key === "zero"
                    ? "breadth-flat"
                    : i < group.distribution.length / 2
                      ? "breadth-down"
                      : "breadth-up"
                }
                style={{ height: `${(bin.count / max) * 100}%` }}
              />
            </span>
            <span className="distribution-label">{bin.label}</span>
          </button>
        ))}
      </div>
      <p className="chart-note">
        点击柱子查看成员 · 数值为本观察窗口内的收盘变化
      </p>
    </div>
  );
}
