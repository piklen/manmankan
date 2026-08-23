import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowDown,
  ArrowUp,
  CalendarDays,
  CircleHelp,
  History,
  Layers3,
  LineChart,
  RefreshCw,
  SlidersHorizontal,
  TrendingUp,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type BoardPulseSnapshot,
  type BoardTrendParams,
  type BoardTrendRow,
} from "../api/client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Loading,
  PageHeader,
  Segmented,
} from "../components/ui";
import { errorMessage, number, percent } from "../lib/format";

const SOURCE_LABELS: Record<string, string> = {
  sw: "申万行业指数",
  ths: "同花顺概念指数",
  em: "东方财富概念指数",
};

const PULSE_SOURCE_LABELS: Record<string, string> = {
  tushare_daily_bars: "全市场日线截面 · TuShare 兼容",
  individual_cache: "本地个股缓存",
};

const KIND_OPTIONS = [
  { value: "industry", label: "行业" },
  { value: "theme", label: "题材" },
] satisfies Array<{ value: BoardTrendParams["kind"]; label: string }>;

const MODE_OPTIONS = [
  { value: "close", label: "收盘连续" },
  { value: "candle", label: "阳线连续" },
] satisfies Array<{ value: BoardTrendParams["mode"]; label: string }>;

const DIRECTION_OPTIONS = [
  { value: "up", label: "连续上涨" },
  { value: "down", label: "连续下跌" },
  { value: "all", label: "全部" },
] satisfies Array<{ value: BoardTrendParams["direction"]; label: string }>;

function boardPath(row: BoardTrendRow): string {
  const params = new URLSearchParams({
    universe: row.kind,
    value: row.name,
    source: "trends",
  });
  return `/screen?${params}`;
}

function boardHistoryPath(
  row: BoardTrendRow,
  mode: BoardTrendParams["mode"],
  level: number,
): string {
  const params = new URLSearchParams({
    kind: row.kind,
    value: row.code,
    name: row.name,
    level: String(row.kind === "industry" ? level : 1),
    mode,
    direction: row.streak < 0 ? "down" : "up",
    days: String(Math.max(2, Math.min(30, Math.abs(row.streak) || 2))),
    forward: "5",
    years: "5",
    sample: "first_hit",
  });
  return `/history/board?${params}`;
}

function signedDays(value: number): string {
  if (value > 0) return `连涨 ${value} 天`;
  if (value < 0) return `连跌 ${Math.abs(value)} 天`;
  return "当前平盘";
}

function moneyflow(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) >= 10_000) return `${number(value / 10_000, 2)} 亿`;
  return `${number(value, 0)} 万`;
}

function relativeSeries(row: BoardTrendRow): Array<{ date: string; value: number; change: number }> {
  const changes = [...(row.daily_changes ?? [])].slice(0, 16).reverse();
  let value = 100;
  return changes.map((item) => {
    value *= 1 + item.change_pct / 100;
    return { date: item.date, value, change: item.change_pct };
  });
}

function TrendChart({ row }: { row: BoardTrendRow }) {
  const series = useMemo(() => relativeSeries(row), [row]);
  if (series.length < 2) {
    return (
      <div className="trend-chart trend-chart--empty">
        <span>近日日涨跌数据不足，暂不能绘制轨迹</span>
      </div>
    );
  }

  const width = 640;
  const height = 220;
  const insetX = 18;
  const insetY = 20;
  const values = series.map((item) => item.value);
  const rawMin = Math.min(100, ...values);
  const rawMax = Math.max(100, ...values);
  const span = Math.max(rawMax - rawMin, 0.8);
  const min = rawMin - span * 0.12;
  const max = rawMax + span * 0.12;
  const x = (index: number) =>
    insetX + (index / Math.max(series.length - 1, 1)) * (width - insetX * 2);
  const y = (value: number) =>
    insetY + ((max - value) / (max - min)) * (height - insetY * 2);
  const points = series.map((item, index) => `${x(index)},${y(item.value)}`).join(" ");
  const area = `${insetX},${height - insetY} ${points} ${width - insetX},${height - insetY}`;
  const finalPoint = series.at(-1)!;

  return (
    <div className="trend-chart">
      <div className="trend-chart__heading">
        <div>
          <span>近 {series.length} 日相对轨迹</span>
          <strong>{number(finalPoint.value, 2)}</strong>
        </div>
        <small>首日基准 = 100 · 由每日涨跌复原</small>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${row.name}近 ${series.length} 日相对走势`}
      >
        <defs>
          <linearGradient id={`trend-fill-${row.code}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-board)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--chart-board)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line
          className="trend-chart__baseline"
          x1={insetX}
          x2={width - insetX}
          y1={y(100)}
          y2={y(100)}
        />
        <polygon points={area} fill={`url(#trend-fill-${row.code})`} />
        <polyline className="trend-chart__line" points={points} />
        <circle
          className="trend-chart__point"
          cx={x(series.length - 1)}
          cy={y(finalPoint.value)}
          r="5"
        />
      </svg>
      <div className="trend-chart__bars" aria-label="每日涨跌">
        {series.map((item) => (
          <span
            key={item.date}
            className={item.change >= 0 ? "is-up" : "is-down"}
            style={{ height: `${Math.max(4, Math.min(30, Math.abs(item.change) * 8))}px` }}
            title={`${item.date} ${percent(item.change)}`}
          />
        ))}
      </div>
      <div className="trend-chart__dates">
        <span>{series[0]?.date}</span>
        <span>{finalPoint.date}</span>
      </div>
    </div>
  );
}

function BoardPulsePanel({
  pulse,
  isLoading,
  error,
  onRetry,
  onOpenMarket,
}: {
  pulse?: BoardPulseSnapshot;
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  onOpenMarket: () => void;
}) {
  if (isLoading) {
    return (
      <section className="trend-pulse">
        <Loading label="读取板块内部结构" />
      </section>
    );
  }
  if (error) {
    return (
      <section className="trend-pulse trend-pulse--error">
        <div>
          <strong>板块内部结构暂不可用</strong>
          <p>{errorMessage(error)}</p>
        </div>
        <div>
          <Button size="sm" variant="secondary" onClick={onRetry}>再试一次</Button>
          <Button size="sm" variant="ghost" onClick={onOpenMarket}>更新行情</Button>
        </div>
      </section>
    );
  }
  if (!pulse) return null;

  const evaluated = Math.max(pulse.coverage.evaluated, 1);
  const flatRatio = pulse.coverage.flat / evaluated * 100;
  const source = PULSE_SOURCE_LABELS[pulse.source] ?? pulse.source;
  const topUp = pulse.top_up ?? [];
  const topDown = pulse.top_down ?? [];

  return (
    <section className="trend-pulse">
      <div className="trend-pulse__heading">
        <div>
          <span className="panel-kicker">成员结构</span>
          <h3>最新交易日，板块内部怎么动</h3>
          <p>
            {source} · {pulse.previous_date} → {pulse.data_cutoff} ·
            已比较 {pulse.coverage.evaluated}/{pulse.coverage.total} 只
          </p>
        </div>
        {pulse.partial ? <Badge tone="warning">部分覆盖</Badge> : <Badge tone="neutral">完整覆盖</Badge>}
      </div>

      <div className="trend-pulse__metrics">
        <div>
          <span>上涨成员</span>
          <strong>{pulse.coverage.up} 只</strong>
          <small>{number(pulse.up_ratio_pct, 1)}%</small>
        </div>
        <div>
          <span>下跌成员</span>
          <strong>{pulse.coverage.down} 只</strong>
          <small>{number(pulse.down_ratio_pct, 1)}%</small>
        </div>
        <div>
          <span>平盘成员</span>
          <strong>{pulse.coverage.flat} 只</strong>
          <small>{number(flatRatio, 1)}%</small>
        </div>
        <div>
          <span>成员中位涨跌</span>
          <strong>{percent(pulse.median_change_pct)}</strong>
          <small>不按指数权重</small>
        </div>
      </div>

      <div className="trend-pulse__breadth" aria-label="板块成员涨跌家数分布">
        <span
          className="is-up"
          style={{ width: `${pulse.up_ratio_pct}%` }}
          title={`上涨 ${pulse.coverage.up} 只`}
        />
        <span
          className="is-flat"
          style={{ width: `${flatRatio}%` }}
          title={`平盘 ${pulse.coverage.flat} 只`}
        />
        <span
          className="is-down"
          style={{ width: `${pulse.down_ratio_pct}%` }}
          title={`下跌 ${pulse.coverage.down} 只`}
        />
      </div>
      <div className="trend-pulse__legend">
        <span><i className="is-up" /> 上涨 {pulse.coverage.up}</span>
        <span><i className="is-flat" /> 平盘 {pulse.coverage.flat}</span>
        <span><i className="is-down" /> 下跌 {pulse.coverage.down}</span>
      </div>

      <div className="trend-pulse__movers">
        <div>
          <h4><ArrowUp size={14} /> 涨幅靠前成员</h4>
          {topUp.length ? (
            <ol>
              {topUp.map((member) => (
                <li key={member.code}>
                  <span><strong>{member.name}</strong><small>{member.code}</small></span>
                  <b>{percent(member.change_pct)}</b>
                </li>
              ))}
            </ol>
          ) : <p>没有上涨成员</p>}
        </div>
        <div>
          <h4><ArrowDown size={14} /> 跌幅靠前成员</h4>
          {topDown.length ? (
            <ol>
              {topDown.map((member) => (
                <li key={member.code}>
                  <span><strong>{member.name}</strong><small>{member.code}</small></span>
                  <b>{percent(member.change_pct)}</b>
                </li>
              ))}
            </ol>
          ) : <p>没有下跌成员</p>}
        </div>
      </div>

      {(pulse.warnings?.length ?? 0) > 0 ? (
        <p className="trend-pulse__warning">{pulse.warnings?.join(" · ")}</p>
      ) : null}
      <p className="trend-pulse__boundary">
        <CircleHelp size={14} />
        这里描述成员涨跌分布和靠前成员，不代表指数权重贡献，也不是新闻事件的因果归因。
      </p>
    </section>
  );
}

export function TrendDiscoveryPage() {
  const navigate = useNavigate();
  const [kind, setKind] = useState<BoardTrendParams["kind"]>("industry");
  const [mode, setMode] = useState<BoardTrendParams["mode"]>("close");
  const [direction, setDirection] =
    useState<BoardTrendParams["direction"]>("all");
  const [days, setDays] = useState(3);
  const [sort, setSort] = useState<BoardTrendParams["sort"]>("streak");
  const [level, setLevel] = useState(1);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);

  const params = useMemo<BoardTrendParams>(
    () => ({ kind, mode, direction, days, sort, level, limit: 50 }),
    [days, direction, kind, level, mode, sort],
  );
  const trendQuery = useQuery({
    queryKey: ["board-trends", params],
    queryFn: () => api.boardTrends(params),
  });
  const rows = trendQuery.data?.rows ?? [];

  useEffect(() => {
    if (!rows.some((row) => row.code === selectedCode)) {
      setSelectedCode(rows[0]?.code ?? null);
    }
  }, [rows, selectedCode]);

  const selected = rows.find((row) => row.code === selectedCode) ?? rows[0] ?? null;
  const pulseLevel = selected?.kind === "industry" ? level : 1;
  const pulseQuery = useQuery({
    queryKey: ["board-pulse", selected?.kind, selected?.code, pulseLevel],
    queryFn: () => api.boardPulse(
      selected!.kind,
      selected!.kind === "industry" ? selected!.code : selected!.name,
      pulseLevel,
    ),
    enabled: Boolean(selected),
  });
  const source = trendQuery.data?.source
    ? (SOURCE_LABELS[trendQuery.data.source] ?? trendQuery.data.source)
    : "等待数据";

  return (
    <div className="trend-page">
      <PageHeader
        eyebrow="Trend discovery"
        title="先找正在形成趋势的板块，再看板块里的股票"
        description="行业和题材指数按同一套连续涨跌口径排序。选中板块后只带入股票池，具体选股条件仍由你决定。"
        actions={
          <>
            <Badge tone="neutral">{source}</Badge>
            {trendQuery.data?.data_cutoff ? (
              <span className="trend-cutoff">
                <CalendarDays size={14} /> 数据截止 {trendQuery.data.data_cutoff}
              </span>
            ) : null}
          </>
        }
      />

      <div className="trend-layout">
        <Card className="trend-controls">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">01 · 定义趋势</span>
              <h2>我要找什么</h2>
            </div>
            <SlidersHorizontal size={18} />
          </div>

          <div className="trend-control-group">
            <label>板块类型</label>
            <Segmented
              label="板块类型"
              value={kind}
              options={KIND_OPTIONS}
              onChange={(value) => {
                setKind(value);
                if (value === "theme") setLevel(1);
              }}
            />
          </div>
          {kind === "industry" ? (
            <div className="trend-control-group">
              <label htmlFor="trend-level">申万层级</label>
              <select
                id="trend-level"
                value={level}
                disabled={sort === "moneyflow"}
                onChange={(event) => setLevel(Number(event.target.value))}
              >
                <option value={1}>一级行业 · 大方向</option>
                <option value={2}>二级行业 · 更细</option>
                <option value={3}>三级行业 · 最细</option>
              </select>
              {sort === "moneyflow" ? <small>资金排序当前固定一级行业</small> : null}
            </div>
          ) : null}
          <div className="trend-control-group">
            <label>趋势口径</label>
            <Segmented
              label="趋势口径"
              value={mode}
              options={MODE_OPTIONS}
              onChange={setMode}
            />
            <small>
              {mode === "close"
                ? "今日收盘高于昨日收盘，记为上涨一天"
                : "当日收盘高于开盘，记为一根阳线"}
            </small>
          </div>
          <div className="trend-control-group">
            <label>方向</label>
            <Segmented
              label="趋势方向"
              value={direction}
              options={DIRECTION_OPTIONS}
              onChange={setDirection}
            />
          </div>
          <div className="trend-control-row">
            <label>
              <span>至少连续</span>
              <span className="trend-days-input">
                <input
                  aria-label="连续天数"
                  type="number"
                  min={1}
                  max={30}
                  value={days}
                  disabled={direction === "all"}
                  onChange={(event) =>
                    setDays(Math.max(1, Math.min(30, Number(event.target.value) || 1)))
                  }
                />
                <small>天</small>
              </span>
            </label>
            <label>
              <span>结果排序</span>
              <select
                aria-label="结果排序"
                value={sort}
                onChange={(event) => {
                  const value = event.target.value as BoardTrendParams["sort"];
                  setSort(value);
                  if (value === "moneyflow" && kind === "industry") setLevel(1);
                }}
              >
                <option value="streak">连续天数</option>
                <option value="latest">最新涨幅</option>
                <option value="moneyflow">主力净额</option>
              </select>
            </label>
          </div>
          <Button
            variant="secondary"
            className="trend-refresh"
            disabled={trendQuery.isFetching}
            onClick={() => void trendQuery.refetch()}
          >
            <RefreshCw size={15} className={trendQuery.isFetching ? "spin" : ""} />
            重新读取
          </Button>
          <p className="trend-method-note">
            这里只做客观发现，不预测下一天，也不会自动替你生成买入条件。
          </p>
        </Card>

        <Card className="trend-radar">
          <div className="panel-heading trend-radar__heading">
            <div>
              <span className="panel-kicker">02 · 趋势雷达</span>
              <h2>{kind === "industry" ? "行业" : "题材"}趋势榜</h2>
              <p>
                {trendQuery.data
                  ? `已评估 ${trendQuery.data.coverage.evaluated}/${trendQuery.data.coverage.total} 个 · 命中 ${trendQuery.data.coverage.matched} 个`
                  : "读取板块指数并计算连续走势"}
              </p>
            </div>
            {trendQuery.data?.partial ? <Badge tone="warning">部分数据</Badge> : null}
          </div>

          {trendQuery.isLoading ? <Loading label="计算板块趋势" /> : null}
          {trendQuery.isError ? (
            <EmptyState
              title="板块趋势暂时不可用"
              detail={errorMessage(trendQuery.error)}
              action={
                <Button variant="secondary" onClick={() => void trendQuery.refetch()}>
                  再试一次
                </Button>
              }
            />
          ) : null}
          {!trendQuery.isLoading && !trendQuery.isError && rows.length === 0 ? (
            <EmptyState
              title="当前没有符合条件的板块"
              detail="可以降低连续天数，或切换到全部方向查看完整趋势。"
            />
          ) : null}
          {rows.length ? (
            <div className="trend-table-wrap">
              <table className="trend-table">
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>板块</th>
                    <th>连续状态</th>
                    <th>期间累计</th>
                    <th>最新一天</th>
                    {sort === "moneyflow" ? <th>主力净额</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.code}
                      className={row.code === selected?.code ? "is-selected" : ""}
                      onClick={() => setSelectedCode(row.code)}
                    >
                      <td><span className="trend-rank">{String(row.rank).padStart(2, "0")}</span></td>
                      <td>
                        <button
                          type="button"
                          className="trend-board-name"
                          aria-pressed={row.code === selected?.code}
                          onClick={() => setSelectedCode(row.code)}
                        >
                          <strong>{row.name}</strong>
                          <small>{row.code}</small>
                        </button>
                      </td>
                      <td><span className="trend-streak">{signedDays(row.streak)}</span></td>
                      <td>{percent(row.streak_pct)}</td>
                      <td>{percent(row.latest_change_pct)}</td>
                      {sort === "moneyflow" ? <td>{moneyflow(row.moneyflow_net)}</td> : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {(trendQuery.data?.warnings?.length ?? 0) > 0 ? (
            <p className="trend-warning">{trendQuery.data?.warnings?.join(" · ")}</p>
          ) : null}
        </Card>

        <Card className="trend-detail">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">03 · 复核与下钻</span>
              <h2>{selected?.name ?? "选择一个板块"}</h2>
            </div>
            <LineChart size={19} />
          </div>
          {selected ? (
            <>
              <div className="trend-detail__metrics">
                <div>
                  <span>连续状态</span>
                  <strong>{signedDays(selected.streak)}</strong>
                </div>
                <div>
                  <span>连续期累计</span>
                  <strong>{percent(selected.streak_pct)}</strong>
                </div>
                <div>
                  <span>最新一天</span>
                  <strong>{percent(selected.latest_change_pct)}</strong>
                </div>
              </div>
              <TrendChart row={selected} />
              <BoardPulsePanel
                pulse={pulseQuery.data}
                isLoading={pulseQuery.isLoading}
                error={pulseQuery.error}
                onRetry={() => void pulseQuery.refetch()}
                onOpenMarket={() => navigate("/market")}
              />
              <div className="trend-next-actions">
                <div className="trend-drilldown">
                  <span className="trend-drilldown__icon"><History size={19} /></span>
                  <div>
                    <strong>先看：同类趋势过去怎么走</strong>
                    <p>
                      复核“{signedDays(selected.streak)}”首次出现后，未来交易日的实际涨跌分布。
                    </p>
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() => navigate(boardHistoryPath(selected, mode, level))}
                  >
                    历史复核 <ArrowRight size={16} />
                  </Button>
                </div>
                <div className="trend-drilldown">
                  <span className="trend-drilldown__icon"><Layers3 size={19} /></span>
                  <div>
                    <strong>再看：这个板块里的股票</strong>
                    <p>
                      只把“{selected.name}”带入选股工作台。系统不会预设低位、估值或技术指标。
                    </p>
                  </div>
                  <Button onClick={() => navigate(boardPath(selected))}>
                    用本板块选股 <ArrowRight size={16} />
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <EmptyState
              title="先从趋势榜选一个板块"
              detail="选中后可以复核近日日涨跌，并把板块成分股带入选股工作台。"
            />
          )}
        </Card>
      </div>

      <div className="trend-principle">
        <TrendingUp size={18} />
        <p>
          <strong>这页回答“哪里正在形成趋势、板块内部最新交易日怎么动”。</strong>
          成员分布不是权重归因；历史复核只描述过去样本，个股条件、运行证据与候选比较继续由选股工作台负责。
        </p>
      </div>
    </div>
  );
}
