import { useState } from "react";
import type { DiscoveryGroup } from "../api/client";
import { number, percent } from "../lib/format";

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
  const [hover, setHover] = useState<number | null>(null);
  const points = group.history;
  const active = points[hover ?? points.length - 1];
  const width = 600,
    left = 38,
    right = 18,
    top = 18,
    bottom = 175;
  const x = (index: number) =>
    left + (index / Math.max(1, points.length - 1)) * (width - left - right);
  const y = (value: number) => bottom - (value / 100) * (bottom - top);
  let connected = false;
  const path = points
    .map((point, i) => {
      if (point.positive_share == null) {
        connected = false;
        return "";
      }
      const command = connected ? "L" : "M";
      connected = true;
      return `${command}${x(i).toFixed(1)},${y(point.positive_share).toFixed(1)}`;
    })
    .join(" ");
  const tickIndexes = [
    ...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]),
  ].filter((i) => i >= 0);
  return (
    <div className="breadth-history">
      <div className="chart-heading">
        <h3>上涨占比的变化</h3>
        <span>
          滚动 {window} 日 · 固定 {number(group.history_available, 0)} 只
        </span>
      </div>
      {group.history_available ? (
        <>
          <svg
            viewBox={`0 0 ${width} 205`}
            role="img"
            aria-label={`${group.name}上涨占比轨迹，固定${group.history_available}只成员，窗口${window}个交易日`}
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
            {[0, 25, 50, 75, 100].map((tick) => (
              <g key={tick}>
                <line
                  x1={left}
                  x2={width - right}
                  y1={y(tick)}
                  y2={y(tick)}
                  className={tick === 50 ? "history-midline" : "history-grid"}
                />
                <text x={left - 10} y={y(tick) + 4} textAnchor="end">
                  {tick}%
                </text>
              </g>
            ))}
            <path d={path} className="history-line" />
            {active?.positive_share != null ? (
              <g>
                <line
                  x1={x(hover ?? points.length - 1)}
                  x2={x(hover ?? points.length - 1)}
                  y1={top}
                  y2={bottom}
                  className="history-cursor"
                />
                <circle
                  cx={x(hover ?? points.length - 1)}
                  cy={y(active.positive_share)}
                  r="4"
                  className="history-dot"
                />
              </g>
            ) : null}
            {tickIndexes.map((i) => (
              <text
                key={i}
                x={x(i)}
                y="199"
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
            <strong>{percent(active?.positive_share)}</strong>
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
