import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  BarChart3,
  CalendarRange,
  Check,
  CircleHelp,
  Database,
  History,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  type BoardHistoryEvent,
  type BoardHistoryStudyQuery,
  type ReturnDistribution,
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
  sw_index_history: "申万行业指数历史",
  tushare_ths_index_history: "同花顺概念指数历史 · TuShare",
  em_concept_history: "东方财富概念指数历史",
};

const KIND_OPTIONS = [
  { value: "industry", label: "行业" },
  { value: "theme", label: "题材" },
] satisfies Array<{ value: BoardHistoryStudyQuery["kind"]; label: string }>;

const MODE_OPTIONS = [
  { value: "close", label: "收盘连续" },
  { value: "candle", label: "阳线连续" },
] satisfies Array<{ value: BoardHistoryStudyQuery["mode"]; label: string }>;

const DIRECTION_OPTIONS = [
  { value: "up", label: "连续上涨" },
  { value: "down", label: "连续下跌" },
] satisfies Array<{ value: BoardHistoryStudyQuery["direction"]; label: string }>;

const SAMPLE_OPTIONS = [
  { value: "first_hit", label: "首次达到" },
  { value: "non_overlapping", label: "窗口不重叠" },
] satisfies Array<{ value: BoardHistoryStudyQuery["sample_policy"]; label: string }>;

function boundedInteger(raw: string | null, fallback: number, min: number, max: number) {
  const value = Number(raw);
  return Number.isInteger(value) ? Math.max(min, Math.min(max, value)) : fallback;
}

function queryFromUrl(params: URLSearchParams): BoardHistoryStudyQuery {
  const kind = params.get("kind") === "theme" ? "theme" : "industry";
  return {
    kind,
    value: params.get("value")?.trim() || (kind === "theme" ? "885781" : "801080"),
    level: kind === "industry" ? boundedInteger(params.get("level"), 1, 1, 3) : 1,
    mode: params.get("mode") === "candle" ? "candle" : "close",
    direction: params.get("direction") === "down" ? "down" : "up",
    min_streak: boundedInteger(params.get("days"), 3, 2, 30),
    forward_days: boundedInteger(params.get("forward"), 5, 1, 60),
    lookback_years: boundedInteger(params.get("years"), 5, 1, 15),
    sample_policy:
      params.get("sample") === "non_overlapping" ? "non_overlapping" : "first_hit",
    benchmark_code: "000300.SH",
    force: false,
  };
}

function conditionSentence(query: BoardHistoryStudyQuery) {
  const mode = query.mode === "close" ? "收盘连续" : "连续阳线";
  const direction = query.direction === "up" ? "上涨" : "下跌";
  return `${mode}${direction}至少 ${query.min_streak} 天后，看未来 ${query.forward_days} 个交易日`;
}

function returnTone(value: number | null | undefined) {
  if (typeof value !== "number") return "is-empty";
  if (value > 0) return "is-positive";
  if (value < 0) return "is-negative";
  return "is-flat";
}

function DistributionCard({
  title,
  description,
  distribution,
}: {
  title: string;
  description: string;
  distribution: ReturnDistribution;
}) {
  return (
    <article className="history-distribution-card">
      <div>
        <span>{title}</span>
        <small>{description}</small>
      </div>
      <strong>{percent(distribution.median_pct, 2)}</strong>
      <p>中位涨跌</p>
      <dl>
        <div><dt>样本</dt><dd>{distribution.count}</dd></div>
        <div><dt>上涨占比</dt><dd>{percent(distribution.positive_ratio_pct)}</dd></div>
        <div><dt>中间 50%</dt><dd>{percent(distribution.p25_pct, 2)} ～ {percent(distribution.p75_pct, 2)}</dd></div>
        <div><dt>范围</dt><dd>{percent(distribution.min_pct, 2)} ～ {percent(distribution.max_pct, 2)}</dd></div>
      </dl>
    </article>
  );
}

function EventReturnChart({ events }: { events: BoardHistoryEvent[] }) {
  const series = useMemo(() => [...events].slice(0, 180).reverse(), [events]);
  if (!series.length) {
    return (
      <div className="history-event-chart history-event-chart--empty">
        当前条件在所选历史范围内没有完整样本
      </div>
    );
  }
  const width = 920;
  const height = 260;
  const insetX = 34;
  const insetY = 28;
  const values = series.map((event) => event.return_pct);
  const maxAbs = Math.max(2, ...values.map((value) => Math.abs(value)));
  const x = (index: number) => series.length === 1
    ? width / 2
    : insetX + index / (series.length - 1) * (width - insetX * 2);
  const y = (value: number) =>
    height / 2 - value / maxAbs * (height / 2 - insetY);

  return (
    <div className="history-event-chart">
      <div className="history-event-chart__heading">
        <div>
          <span>每个圆点是一段已经发生的未来区间</span>
          <strong>{series.length} 个完整样本</strong>
        </div>
        <div className="history-event-chart__legend">
          <span><i className="is-positive" /> 区间上涨</span>
          <span><i className="is-negative" /> 区间下跌</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="历史事件未来区间涨跌分布">
        <line className="history-event-chart__zero" x1={insetX} x2={width - insetX} y1={y(0)} y2={y(0)} />
        <text x={insetX} y={y(maxAbs) + 2}>{percent(maxAbs, 1)}</text>
        <text x={insetX} y={y(0) - 7}>0%</text>
        <text x={insetX} y={y(-maxAbs) - 5}>{percent(-maxAbs, 1)}</text>
        {series.map((event, index) => (
          <circle
            key={`${event.event_date}-${event.forward_date}`}
            className={returnTone(event.return_pct)}
            cx={x(index)}
            cy={y(event.return_pct)}
            r={series.length > 100 ? 3 : 4}
          >
            <title>{`${event.event_date} → ${event.forward_date} · ${percent(event.return_pct, 2)}`}</title>
          </circle>
        ))}
      </svg>
      <div className="history-event-chart__dates">
        <span>{series[0]?.event_date}</span>
        <span>{series.at(-1)?.event_date}</span>
      </div>
    </div>
  );
}

export function BoardHistoryPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQuery = useMemo(() => queryFromUrl(searchParams), []);
  const initialName = searchParams.get("name")?.trim() || "";
  const [draft, setDraft] = useState<BoardHistoryStudyQuery>(initialQuery);
  const [submitted, setSubmitted] = useState<BoardHistoryStudyQuery>(initialQuery);

  const studyQuery = useQuery({
    queryKey: ["board-history-study", submitted],
    queryFn: () => api.studyBoardHistory(submitted),
  });
  const study = studyQuery.data;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = { ...draft, level: draft.kind === "theme" ? 1 : draft.level };
    setSubmitted(next);
    const params = new URLSearchParams({
      kind: next.kind,
      value: next.value,
      level: String(next.level),
      mode: next.mode,
      direction: next.direction,
      days: String(next.min_streak),
      forward: String(next.forward_days),
      years: String(next.lookback_years),
      sample: next.sample_policy,
    });
    if (initialName && next.value === initialQuery.value) params.set("name", initialName);
    setSearchParams(params, { replace: true });
  }

  const events = study?.events ?? [];
  const completed = study?.coverage.completed ?? 0;
  const displayName = study?.board_name || initialName || draft.value;
  const source = study ? SOURCE_LABELS[study.source] ?? study.source : "板块原生指数历史";

  return (
    <div className="board-history-page">
      <PageHeader
        eyebrow="Historical review"
        title="把一次趋势，放回历史里看"
        description="按你明确选择的连续条件，统计板块指数在历史上首次达到条件后，未来若干交易日的实际涨跌分布。这里不预测，也不自动寻找最优参数。"
        actions={
          <Button variant="ghost" onClick={() => navigate("/trends")}>
            <ArrowLeft size={15} /> 返回趋势发现
          </Button>
        }
      />

      <div className="history-board-strip">
        <div className="history-board-strip__icon"><History size={20} /></div>
        <div>
          <span>当前复核对象</span>
          <strong>{displayName}</strong>
          <small>{draft.value} · {source}</small>
        </div>
        <Badge tone="neutral">{draft.kind === "industry" ? "行业指数" : "题材指数"}</Badge>
      </div>

      <div className="history-study-layout">
        <Card className="history-study-controls">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">事件定义</span>
              <h2>你要复核什么</h2>
            </div>
            <CalendarRange size={18} />
          </div>
          <form onSubmit={submit}>
            <div className="history-control-group">
              <label>板块类型</label>
              <Segmented
                label="历史复核板块类型"
                value={draft.kind}
                options={KIND_OPTIONS}
                onChange={(kind) => setDraft((value) => ({ ...value, kind, level: 1 }))}
              />
            </div>
            <div className="history-control-group">
              <label htmlFor="history-board-value">板块名称或代码</label>
              <input
                id="history-board-value"
                value={draft.value}
                maxLength={80}
                onChange={(event) => setDraft((value) => ({ ...value, value: event.target.value }))}
              />
              {initialName && draft.value === initialQuery.value ? <small>已选：{initialName}</small> : null}
            </div>
            {draft.kind === "industry" ? (
              <div className="history-control-group">
                <label htmlFor="history-board-level">申万层级</label>
                <select
                  id="history-board-level"
                  value={draft.level}
                  onChange={(event) => setDraft((value) => ({ ...value, level: Number(event.target.value) }))}
                >
                  <option value={1}>一级行业</option>
                  <option value={2}>二级行业</option>
                  <option value={3}>三级行业</option>
                </select>
              </div>
            ) : null}
            <div className="history-control-group">
              <label>连续口径</label>
              <Segmented
                label="历史复核连续口径"
                value={draft.mode}
                options={MODE_OPTIONS}
                onChange={(mode) => setDraft((value) => ({ ...value, mode }))}
              />
              <small>平盘日沿用最近方向并计入连续天数，与趋势榜口径一致。</small>
            </div>
            <div className="history-control-group">
              <label>方向</label>
              <Segmented
                label="历史复核方向"
                value={draft.direction}
                options={DIRECTION_OPTIONS}
                onChange={(direction) => setDraft((value) => ({ ...value, direction }))}
              />
            </div>
            <div className="history-control-grid">
              <label>
                <span>至少连续天数</span>
                <input
                  aria-label="至少连续天数"
                  type="number"
                  min={2}
                  max={30}
                  value={draft.min_streak}
                  onChange={(event) => setDraft((value) => ({
                    ...value,
                    min_streak: Math.max(2, Math.min(30, Number(event.target.value) || 2)),
                  }))}
                />
              </label>
              <label>
                <span>未来交易日</span>
                <input
                  aria-label="未来交易日"
                  type="number"
                  min={1}
                  max={60}
                  value={draft.forward_days}
                  onChange={(event) => setDraft((value) => ({
                    ...value,
                    forward_days: Math.max(1, Math.min(60, Number(event.target.value) || 1)),
                  }))}
                />
              </label>
            </div>
            <div className="history-control-group">
              <label htmlFor="history-lookback">历史范围</label>
              <select
                id="history-lookback"
                value={draft.lookback_years}
                onChange={(event) => setDraft((value) => ({ ...value, lookback_years: Number(event.target.value) }))}
              >
                <option value={1}>近 1 年</option>
                <option value={3}>近 3 年</option>
                <option value={5}>近 5 年</option>
                <option value={10}>近 10 年</option>
                <option value={15}>近 15 年</option>
              </select>
            </div>
            <div className="history-control-group">
              <label>样本规则</label>
              <Segmented
                label="历史复核样本规则"
                value={draft.sample_policy}
                options={SAMPLE_OPTIONS}
                onChange={(sample_policy) => setDraft((value) => ({ ...value, sample_policy }))}
              />
              <small>
                {draft.sample_policy === "first_hit"
                  ? "一段连续走势只在首次达到门槛时计一次"
                  : "首次达到后，未来观察窗口互不重叠"}
              </small>
            </div>
            <div className="history-control-group">
              <label htmlFor="history-benchmark">比较基准</label>
              <select id="history-benchmark" value="000300.SH" disabled>
                <option value="000300.SH">沪深 300 · 精确同日</option>
              </select>
            </div>
            <Button type="submit" className="history-submit" disabled={!draft.value.trim() || studyQuery.isFetching}>
              <RefreshCw size={15} className={studyQuery.isFetching ? "spin" : ""} />
              {studyQuery.isFetching ? "正在复核" : "按这些条件复核"}
            </Button>
          </form>
          <p className="history-control-note">
            参数完全由你设置。页面不遍历参数找“最好结果”，避免把偶然样本包装成规律。
          </p>
        </Card>

        <div className="history-study-results">
          {studyQuery.isLoading ? <Card><Loading label="读取板块历史并复核事件" /></Card> : null}
          {studyQuery.isError ? (
            <Card>
              <EmptyState
                title="这次历史复核没有完成"
                detail={errorMessage(studyQuery.error)}
                action={<Button variant="secondary" onClick={() => void studyQuery.refetch()}>再试一次</Button>}
              />
            </Card>
          ) : null}
          {study ? (
            <>
              <Card className="history-summary-card">
                <div className="history-summary-card__heading">
                  <div>
                    <span className="panel-kicker">历史结果</span>
                    <h2>{study.board_name}</h2>
                    <p>{conditionSentence(study.query)}</p>
                  </div>
                  <div className="history-summary-card__meta">
                    <Badge tone="neutral">{study.data_start} → {study.data_cutoff}</Badge>
                    <span>{SOURCE_LABELS[study.source] ?? study.source}</span>
                  </div>
                </div>
                <div className="history-summary-metrics">
                  <div><span>完整样本</span><strong>{completed}</strong><small>首次命中 {study.coverage.first_hits} 次</small></div>
                  <div><span>上涨样本占比</span><strong>{percent(study.raw_distribution.positive_ratio_pct)}</strong><small>{study.raw_distribution.positive} 涨 / {study.raw_distribution.negative} 跌</small></div>
                  <div><span>板块中位涨跌</span><strong>{percent(study.raw_distribution.median_pct, 2)}</strong><small>未来 {study.query.forward_days} 个交易日</small></div>
                  <div><span>相对基准中位值</span><strong>{percent(study.relative_distribution.median_pct, 2)}</strong><small>精确对齐 {study.coverage.benchmark_aligned} 个</small></div>
                </div>
                <EventReturnChart events={events} />
                <div className="history-share-bar" aria-label="完整样本涨跌数量">
                  <span className="is-positive" style={{ width: `${study.raw_distribution.count ? study.raw_distribution.positive / study.raw_distribution.count * 100 : 0}%` }} />
                  <span className="is-flat" style={{ width: `${study.raw_distribution.count ? study.raw_distribution.flat / study.raw_distribution.count * 100 : 0}%` }} />
                  <span className="is-negative" style={{ width: `${study.raw_distribution.count ? study.raw_distribution.negative / study.raw_distribution.count * 100 : 0}%` }} />
                </div>
                <p className="history-coverage-copy">
                  读取 {study.coverage.observations} 个交易日 · 选中 {study.coverage.selected} 个事件 ·
                  {study.coverage.censored ? ` ${study.coverage.censored} 个因未来数据不足未计入统计` : " 所有选中事件均有完整未来区间"}
                </p>
                {(study.warnings?.length ?? 0) > 0 ? <p className="history-warning">{study.warnings?.join(" · ")}</p> : null}
              </Card>

              <div className="history-distributions">
                <DistributionCard title="板块自身" description="事件日收盘到未来收盘" distribution={study.raw_distribution} />
                <DistributionCard title={study.benchmark_name ?? "比较基准"} description="完全相同日期区间" distribution={study.benchmark_distribution} />
                <DistributionCard title="相对基准" description="板块涨跌减去基准涨跌" distribution={study.relative_distribution} />
              </div>

              <Card className="history-events-card">
                <div className="panel-heading">
                  <div><span className="panel-kicker">逐笔证据</span><h2>每个历史事件都能回看</h2></div>
                  <BarChart3 size={18} />
                </div>
                {events.length ? (
                  <div className="history-events-table-wrap">
                    <table className="history-events-table">
                      <thead><tr><th>事件日</th><th>当时状态</th><th>未来日期</th><th>板块涨跌</th><th>基准涨跌</th><th>相对基准</th></tr></thead>
                      <tbody>
                        {events.map((event) => (
                          <tr key={`${event.event_date}-${event.forward_date}`}>
                            <td>{event.event_date}</td>
                            <td>{event.streak > 0 ? `连涨 ${event.streak} 天` : `连跌 ${Math.abs(event.streak)} 天`}</td>
                            <td>{event.forward_date}</td>
                            <td className={returnTone(event.return_pct)}>{percent(event.return_pct, 2)}</td>
                            <td className={returnTone(event.benchmark_return_pct)}>{percent(event.benchmark_return_pct, 2)}</td>
                            <td className={returnTone(event.relative_return_pct)}>{percent(event.relative_return_pct, 2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <EmptyState title="所选范围内没有完整样本" detail="可以扩大历史范围或调整你主动设置的连续天数。" />}
              </Card>

              <Card className="history-audit-card">
                <div className="history-audit-card__heading">
                  <span><ShieldCheck size={19} /></span>
                  <div><h2>这份结果用了什么，也明确没用什么</h2><p>防止把事后数据误当成当时可知信息。</p></div>
                </div>
                <div className="history-audit-grid">
                  <div><Check size={15} /><span>板块原生指数历史</span><strong>已使用</strong></div>
                  <div><Check size={15} /><span>沪深 300 日期对齐</span><strong>精确同日</strong></div>
                  <div><Database size={15} /><span>当前成分股回填过去</span><strong>未使用</strong></div>
                  <div><Database size={15} /><span>历史股票池重建</span><strong>未执行</strong></div>
                  <div><Database size={15} /><span>数据源逐日历史版本</span><strong>未归档</strong></div>
                </div>
                <ul>
                  {(study.audit?.notes ?? []).map((note) => <li key={note}>{note}</li>)}
                </ul>
                <p className="history-audit-boundary"><CircleHelp size={14} /> 你从今天的趋势榜选择这个板块，本身带有事后选择；这里仅复核该板块指数的历史分布，不声称样本外有效。</p>
              </Card>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
