import { useState } from "react";
import { number } from "../lib/format";

function axisLimit(values: number[]) {
  const max = Math.max(1, ...values.map((n) => Math.abs(n) * 1.06));
  const magnitude = 10 ** Math.floor(Math.log10(max));
  return Math.ceil(max / magnitude) * magnitude;
}

export function IndustryStrengthMap({
  groups,
  selected,
  onSelect,
}: {
  groups: readonly {
    name: string;
    relative_return_pp?: number | null;
    comparison: { breadth_delta_pp: number | null };
  }[];
  selected: string | null;
  onSelect: (name: string) => void;
}) {
  const [active, setActive] = useState<string | null>(null);
  const points = groups.flatMap((group) => {
    const x = group.relative_return_pp;
    const y = group.comparison.breadth_delta_pp;
    return x == null || y == null ? [] : [{ name: group.name, x, y }];
  });
  const xMax = axisLimit(points.map((point) => point.x));
  const yMax = axisLimit(points.map((point) => point.y));
  const focused = points.find((point) => point.name === (active ?? selected));
  const missing = groups.length - points.length;
  // 在图上选分散的位置放标签，完整名单和具体数值始终可从表格读取。
  const anchors: typeof points = [];
  for (const point of points) {
    if (anchors.length === 4) break;
    if (Math.abs(point.y / yMax) > 0.8 || Math.abs(point.x / xMax) > 0.9)
      continue;
    if (
      anchors.every(
        (other) =>
          Math.abs(other.x - point.x) > 0.52 * xMax ||
          Math.abs(other.y - point.y) > 0.36 * yMax,
      )
    )
      anchors.push(point);
  }
  return (
    <section className="strength-map chart-panel" aria-label="行业强度分布">
      <header className="panel-heading">
        <h2>行业强度分布</h2>
        <span>{points.length} 个行业可比</span>
      </header>
      <p className="axis-title">上涨占比较前期变化（百分点）</p>
      {points.length ? (
        <div className="strength-plot">
          <span className="plot-y top">{number(yMax, 1)}</span>
          <span className="plot-y middle">0</span>
          <span className="plot-y bottom">{number(-yMax, 1)}</span>
          <div className="plot-grid">
            <span className="plot-quadrant left">低于基准 · 参与扩大</span>
            <span className="plot-quadrant right">高于基准 · 参与扩大</span>
            {points.map((point) => (
              <button
                key={point.name}
                type="button"
                className={`plot-point ${point.y > 0 ? "widening" : ""}${point.name === focused?.name ? " focused" : ""}`}
                style={{
                  left: 50 + (point.x / xMax) * 50 + "%",
                  top: 50 - (point.y / yMax) * 50 + "%",
                }}
                aria-label={`查看${point.name}，相对范围${number(point.x, 2)}个百分点，上涨占比变化${number(point.y, 2)}个百分点`}
                title={point.name}
                onFocus={() => setActive(point.name)}
                onBlur={() => setActive(null)}
                onMouseEnter={() => setActive(point.name)}
                onMouseLeave={() => setActive(null)}
                onClick={() => onSelect(point.name)}
              >
                {(point.name === focused?.name || anchors.includes(point)) && (
                  <span
                    className={`plot-name ${point.x > xMax / 2 ? "align-left" : ""}`}
                  >
                    {point.name}
                  </span>
                )}
              </button>
            ))}
          </div>
          <div className="plot-x">
            <span>{number(-xMax, 1)}</span>
            <span>0</span>
            <span>+{number(xMax, 1)}</span>
          </div>
        </div>
      ) : (
        <div className="chart-empty">当前范围暂无两项数据均完整的行业。</div>
      )}
      <p className="axis-title x-title">
        行业涨跌中位数 − 原范围中位数（百分点）
      </p>
      <div className="map-readout">
        {focused ? (
          <>
            <strong>{focused.name}</strong>
            <span>
              相对范围 {number(focused.x, 2)} · 占比变化 {number(focused.y, 2)}{" "}
              个百分点
            </span>
          </>
        ) : (
          <span>选择圆点查看行业数据</span>
        )}
        {missing > 0 && <small>{missing} 个行业资料不足，未绘入图中</small>}
      </div>
    </section>
  );
}
