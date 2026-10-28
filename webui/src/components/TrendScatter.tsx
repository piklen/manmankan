import { useEffect, useRef, useState } from "react";
import { MousePointer2, RotateCcw, Scan, Workflow } from "lucide-react";
import type { TrendMapRow } from "../api/client";
import { number, percent } from "../lib/format";

export type MapBounds = {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
};
export const inBounds = (row: TrendMapRow, bounds: MapBounds | null) =>
  row.available &&
  row.x != null &&
  row.y != null &&
  (!bounds ||
    (row.x >= bounds.xMin &&
      row.x <= bounds.xMax &&
      row.y >= bounds.yMin &&
      row.y <= bounds.yMax));

export function TrendScatter({
  rows,
  selected,
  positionWindow,
  momentumWindow,
  bounds,
  onBounds,
  onSelect,
}: {
  rows: TrendMapRow[];
  selected: TrendMapRow | null;
  positionWindow: number;
  momentumWindow: number;
  bounds: MapBounds | null;
  onBounds: (value: MapBounds | null) => void;
  onSelect: (row: TrendMapRow) => void;
}) {
  const wrapper = useRef<HTMLDivElement>(null),
    canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 800, height: 480 });
  const [brushMode, setBrushMode] = useState(false),
    [trail, setTrail] = useState(true);
  const [hover, setHover] = useState<{
    row: TrendMapRow;
    x: number;
    y: number;
  } | null>(null);
  const [drag, setDrag] = useState<{
    start: [number, number];
    end: [number, number];
  } | null>(null);
  const points = rows.filter(
    (row): row is TrendMapRow & { x: number; y: number } =>
      row.available && row.x != null && row.y != null,
  );
  const minY = Math.min(0, ...points.map((row) => row.y)),
    maxY = Math.max(0, ...points.map((row) => row.y));
  const span = Math.max(10, maxY - minY),
    step = Math.max(1, 10 ** Math.floor(Math.log10(span / 5)) * 2);
  const yMin = Math.floor((minY - span * 0.06) / step) * step,
    yMax = Math.ceil((maxY + span * 0.06) / step) * step;
  const left = size.width < 500 ? 42 : 54,
    right = 20,
    top = 26,
    bottom = 46;
  const plotWidth = size.width - left - right,
    plotHeight = size.height - top - bottom;
  const x = (value: number) => left + (value / 100) * plotWidth;
  const y = (value: number) =>
    top + ((yMax - value) / (yMax - yMin)) * plotHeight;
  const fromPixel = ([px, py]: [number, number]): [number, number] => [
    Math.max(0, Math.min(100, ((px - left) / plotWidth) * 100)),
    Math.max(
      yMin,
      Math.min(yMax, yMax - ((py - top) / plotHeight) * (yMax - yMin)),
    ),
  ];
  const coordinates = (event: {
    clientX: number;
    clientY: number;
  }): [number, number] => {
    const rect = canvas.current!.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  };
  const nearest = ([px, py]: [number, number]) => {
    let found: (typeof points)[number] | null = null,
      distance = 14 * 14;
    for (const row of points) {
      const delta = (x(row.x) - px) ** 2 + (y(row.y) - py) ** 2;
      if (delta < distance) {
        found = row;
        distance = delta;
      }
    }
    return found;
  };
  useEffect(() => {
    const element = wrapper.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry)
        setSize({
          width: Math.max(280, entry.contentRect.width),
          height: entry.contentRect.width < 500 ? 370 : 480,
        });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext("2d");
    if (!element || !context) return;
    const ratio = window.devicePixelRatio || 1;
    element.width = Math.round(size.width * ratio);
    element.height = Math.round(size.height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, size.width, size.height);
    context.font =
      '11px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif';
    context.fillStyle = "#b9cbd6";
    context.strokeStyle = "#243e50";
    context.lineWidth = 1;
    for (let index = 0; index <= 5; index++) {
      const value = index * 20;
      context.beginPath();
      context.moveTo(x(value), top);
      context.lineTo(x(value), size.height - bottom);
      context.stroke();
      context.textAlign = "center";
      context.fillText(`${value}%`, x(value), size.height - 25);
    }
    for (let index = 0; index <= 4; index++) {
      const value = yMin + ((yMax - yMin) * index) / 4;
      context.beginPath();
      context.moveTo(left, y(value));
      context.lineTo(size.width - right, y(value));
      context.stroke();
      context.textAlign = "right";
      context.fillText(`${number(value, 1)}%`, left - 8, y(value) + 4);
    }
    context.strokeStyle = "#6b8493";
    context.beginPath();
    context.moveTo(left, y(0));
    context.lineTo(size.width - right, y(0));
    context.stroke();
    context.save();
    context.beginPath();
    context.rect(left, top, plotWidth, plotHeight);
    context.clip();
    for (const row of points) {
      const within = inBounds(row, bounds);
      context.globalAlpha = bounds && !within ? 0.15 : 0.62;
      context.fillStyle =
        row.y > 0 ? "#e16a70" : row.y < 0 ? "#47aebd" : "#8da0ad";
      context.beginPath();
      context.arc(
        x(row.x),
        y(row.y),
        points.length > 1200 ? 2.2 : 3.1,
        0,
        Math.PI * 2,
      );
      context.fill();
    }
    context.globalAlpha = 1;
    if (selected?.available && selected.x != null && selected.y != null) {
      if (trail) {
        context.strokeStyle = "#f0b553";
        context.fillStyle = "#f0b553";
        context.lineWidth = 1.8;
        let previous: { x: number; y: number } | null = null;
        for (const point of selected.trail ?? []) {
          if (point.x == null || point.y == null) {
            previous = null;
            continue;
          }
          const current = { x: x(point.x), y: y(point.y) };
          if (previous) {
            context.beginPath();
            context.moveTo(previous.x, previous.y);
            context.lineTo(current.x, current.y);
            context.stroke();
            const angle = Math.atan2(
              current.y - previous.y,
              current.x - previous.x,
            );
            context.beginPath();
            context.moveTo(current.x, current.y);
            context.lineTo(
              current.x - 6 * Math.cos(angle - 0.5),
              current.y - 6 * Math.sin(angle - 0.5),
            );
            context.lineTo(
              current.x - 6 * Math.cos(angle + 0.5),
              current.y - 6 * Math.sin(angle + 0.5),
            );
            context.closePath();
            context.fill();
          }
          context.beginPath();
          context.arc(current.x, current.y, 3.7, 0, Math.PI * 2);
          context.fill();
          previous = current;
        }
      }
      context.strokeStyle = "#ffc76c";
      context.lineWidth = 1.2;
      context.beginPath();
      context.arc(x(selected.x), y(selected.y), 10, 0, Math.PI * 2);
      context.stroke();
      context.fillStyle = "#ffc76c";
      context.beginPath();
      context.arc(x(selected.x), y(selected.y), 4.5, 0, Math.PI * 2);
      context.fill();
    }
    context.restore();
    const rectangle = drag
      ? {
          xMin: Math.min(...[drag.start[0], drag.end[0]]),
          xMax: Math.max(...[drag.start[0], drag.end[0]]),
          yMin: Math.min(...[drag.start[1], drag.end[1]]),
          yMax: Math.max(...[drag.start[1], drag.end[1]]),
        }
      : bounds
        ? {
            xMin: x(bounds.xMin),
            xMax: x(bounds.xMax),
            yMin: y(bounds.yMax),
            yMax: y(bounds.yMin),
          }
        : null;
    if (rectangle) {
      context.fillStyle = "rgba(243,179,77,.12)";
      context.fillRect(
        rectangle.xMin,
        rectangle.yMin,
        rectangle.xMax - rectangle.xMin,
        rectangle.yMax - rectangle.yMin,
      );
      context.strokeStyle = "#f2b84d";
      context.setLineDash([5, 4]);
      context.strokeRect(
        rectangle.xMin,
        rectangle.yMin,
        rectangle.xMax - rectangle.xMin,
        rectangle.yMax - rectangle.yMin,
      );
      context.setLineDash([]);
    }
  });
  return (
    <div className="trend-scatter">
      <div className="map-canvas-toolbar">
        <span>近{momentumWindow}日涨跌</span>
        <div>
          <button
            type="button"
            aria-pressed={brushMode}
            className={brushMode ? "active" : ""}
            onClick={() => setBrushMode(!brushMode)}
          >
            <Scan size={15} />
            框选范围
          </button>
          <button
            type="button"
            aria-pressed={trail}
            className={trail ? "active" : ""}
            onClick={() => setTrail(!trail)}
          >
            <Workflow size={15} />
            显示轨迹
          </button>
          <button
            type="button"
            onClick={() => {
              onBounds(null);
              setBrushMode(false);
            }}
            disabled={!bounds && !brushMode}
          >
            <RotateCcw size={15} />
            清除框选
          </button>
        </div>
      </div>
      <div className="map-canvas-container" ref={wrapper}>
        <canvas
          ref={canvas}
          style={{
            width: "100%",
            height: size.height,
            touchAction: brushMode ? "none" : "pan-y",
            cursor: brushMode ? "crosshair" : "default",
          }}
          tabIndex={0}
          role="img"
          aria-label={`趋势地图：横轴${positionWindow}日位置，纵轴${momentumWindow}日涨跌，${points.length}只股票。也可在下方表格选择股票。`}
          onPointerDown={(event) => {
            const point = coordinates(event);
            if (brushMode) {
              event.currentTarget.setPointerCapture(event.pointerId);
              setDrag({ start: point, end: point });
              setHover(null);
            } else {
              const row = nearest(point);
              if (row) onSelect(row);
            }
          }}
          onPointerMove={(event) => {
            const point = coordinates(event);
            if (drag) setDrag({ ...drag, end: point });
            else {
              const row = nearest(point);
              setHover(row ? { row, x: point[0], y: point[1] } : null);
            }
          }}
          onPointerUp={(event) => {
            if (!drag) return;
            const end = coordinates(event);
            event.currentTarget.releasePointerCapture(event.pointerId);
            if (
              Math.abs(end[0] - drag.start[0]) > 5 &&
              Math.abs(end[1] - drag.start[1]) > 5
            ) {
              const first = fromPixel(drag.start),
                second = fromPixel(end);
              const round = (value: number) => Math.round(value * 100) / 100;
              onBounds({
                xMin: round(Math.min(first[0], second[0])),
                xMax: round(Math.max(first[0], second[0])),
                yMin: round(Math.min(first[1], second[1])),
                yMax: round(Math.max(first[1], second[1])),
              });
            }
            setDrag(null);
          }}
          onPointerCancel={() => setDrag(null)}
          onPointerLeave={() => setHover(null)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setDrag(null);
              setBrushMode(false);
              return;
            }
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
              event.preventDefault();
              const index = points.findIndex(
                (row) => row.symbol === selected?.symbol,
              );
              const row =
                points[
                  Math.max(
                    0,
                    Math.min(
                      points.length - 1,
                      index + (event.key === "ArrowRight" ? 1 : -1),
                    ),
                  )
                ];
              if (row) onSelect(row);
            }
          }}
        />
        {hover ? (
          <div
            className="map-point-tooltip"
            style={{
              left: Math.min(size.width - 170, Math.max(8, hover.x + 12)),
              top: Math.max(8, hover.y - 66),
            }}
          >
            <strong>
              {hover.row.name}
              <small>{hover.row.symbol}</small>
            </strong>
            <span>
              {positionWindow}日位置 {percent(hover.row.x)} · {momentumWindow}
              日涨跌 {percent(hover.row.y)}
            </span>
          </div>
        ) : null}
        {selected?.available && selected.x != null && selected.y != null ? (
          <div
            className="map-selected-label"
            style={{
              left: Math.max(
                left + 5,
                Math.min(size.width - 145, x(selected.x) + 14),
              ),
              top: Math.max(10, Math.min(size.height - 80, y(selected.y) - 43)),
            }}
          >
            <strong>{selected.name}</strong>
            <span>
              {selected.symbol} · {selected.data_cutoff?.slice(5)}
            </span>
          </div>
        ) : null}
        <span className="map-x-label">{positionWindow}日区间位置</span>
      </div>
      <p className="map-canvas-hint">
        <MousePointer2 size={12} />
        点击点查看个股；框选后可验证范围。轨迹向右表示区间位置上移，向上表示区间涨幅增加。
      </p>
    </div>
  );
}
