import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpenCheck,
  CalendarDays,
  Database,
  Search,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type ScreenEvidence } from "../api/client";
import { Badge, Button, Card, EmptyState, Loading, PageHeader } from "../components/ui";
import { number, percent, shortDate } from "../lib/format";

interface InfoPeriod {
  period: number;
  position_pct: number | null;
  n_low: number | null;
  n_high: number | null;
  gain_pct: number | null;
}

interface StockInfo {
  ok: boolean;
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  scan_date: string | null;
  data_cutoff: string | null;
  stale: boolean;
  low_resonance: number;
  high_resonance: number;
  valuation: Record<string, number | string | null>;
  moneyflow: Record<string, number | string | null>;
  periods: InfoPeriod[];
  trend: { streak: number; streak_pct: number | null; direction: string };
}

interface StockResearchResponse {
  available: boolean;
  data: StockInfo | null;
  message: string | null;
}

interface HistoryPayload {
  series: Array<{ date: string; position_pct: number | null }>;
}

const CANDIDATE_LABEL = {
  research: "待研究",
  watch: "持续观察",
  selected: "用户已保留",
  rejected: "已排除",
} as const;

function PositionBand({ period }: { period: InfoPeriod }) {
  const value = period.position_pct;
  const position = value === null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div className="position-band">
      <div className="position-band__label">
        <strong>{period.period} 日</strong>
        <span>{percent(value)}</span>
      </div>
      <div className="position-band__track">
        <span className="position-band__low" />
        <span className="position-band__high" />
        {value !== null ? <i style={{ left: `${position}%` }} /> : null}
      </div>
      <div className="position-band__range">
        <small>{number(period.n_low)}</small>
        <small>区间低 → 高</small>
        <small>{number(period.n_high)}</small>
      </div>
    </div>
  );
}

function HistoryLine({ series }: { series: HistoryPayload["series"] }) {
  const points = series
    .filter((item): item is { date: string; position_pct: number } => item.position_pct !== null)
    .slice()
    .reverse();
  if (points.length < 2) return <div className="chart-empty">历史快照不足，暂不绘线</div>;
  const width = 640;
  const height = 180;
  const path = points
    .map((item, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - (item.position_pct / 100) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <div className="history-chart" aria-label="位置历史曲线">
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        <line x1="0" x2={width} y1={height * 0.2} y2={height * 0.2} className="chart-guide" />
        <line x1="0" x2={width} y1={height * 0.8} y2={height * 0.8} className="chart-guide" />
        <path d={path} className="chart-line" />
        <circle
          cx={width}
          cy={height - (points.at(-1)!.position_pct / 100) * height}
          r="5"
          className="chart-dot"
        />
      </svg>
      <div><span>{points[0]!.date}</span><span>{points.at(-1)!.date}</span></div>
    </div>
  );
}

export function ResearchPage() {
  const { symbol } = useParams();
  const navigate = useNavigate();
  const [query, setQuery] = useState(symbol ?? "");
  const validSymbol = Boolean(symbol && /^\d{6}$/.test(symbol));
  const infoQuery = useQuery({
    queryKey: ["stock-info", symbol],
    queryFn: async (): Promise<StockResearchResponse> => {
      const response = await api.stockResearch(symbol!);
      return {
        ...response,
        data: response.data as StockInfo | null,
        message: response.message ?? null,
      };
    },
    enabled: validSymbol,
    retry: false,
  });
  const historyQuery = useQuery({
    queryKey: ["stock-history", symbol],
    queryFn: () => api.stockHistory<HistoryPayload>(symbol!, 60),
    enabled: validSymbol,
    retry: false,
  });
  const runsQuery = useQuery({ queryKey: ["runs", "research"], queryFn: () => api.runs(null, 100) });
  const candidateQuery = useQuery({ queryKey: ["candidate-lists"], queryFn: api.candidateLists });

  const occurrences = useMemo(() => {
    if (!symbol) return [];
    return (runsQuery.data ?? []).flatMap((run) => {
      const row = run.rows?.find((item) => item.symbol === symbol);
      return row ? [{ run, row }] : [];
    });
  }, [runsQuery.data, symbol]);
  const candidate = (candidateQuery.data ?? [])
    .flatMap((list) => list.candidates ?? [])
    .find((item) => item.symbol === symbol);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const normalized = query.trim().replace(/^(sh|sz)/i, "");
    if (/^\d{6}$/.test(normalized)) navigate(`/research/${normalized}`);
  };

  if (!validSymbol) {
    const recent = (candidateQuery.data ?? []).flatMap((list) => list.candidates ?? []).slice(0, 8);
    return (
      <div>
        <PageHeader
          eyebrow="Stock research"
          title="从一只股票开始，串起它的全部研究证据"
          description="查看本地行情位置、最近 Screen 命中原因、候选状态与历史变化。"
        />
        <Card className="research-landing">
          <form onSubmit={submit} className="research-search">
            <Search size={20} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入 6 位股票代码" autoFocus />
            <Button type="submit">打开研究页</Button>
          </form>
          <div className="research-recents">
            <span>最近候选</span>
            {recent.map((item) => (
              <button type="button" key={`${item.list_id}-${item.symbol}`} onClick={() => navigate(`/research/${item.symbol}`)}>
                <strong>{item.name}</strong><small>{item.symbol}</small><ArrowRight size={14} />
              </button>
            ))}
          </div>
          {!candidateQuery.isLoading && recent.length === 0 ? (
            <EmptyState title="还没有研究对象" detail="先运行一个 Screen，把结果加入候选池。" />
          ) : null}
        </Card>
      </div>
    );
  }

  const info = infoQuery.data?.data ?? undefined;
  return (
    <div>
      <PageHeader
        eyebrow={`Stock research · ${symbol}`}
        title={info ? `${info.name} · ${info.code}` : `研究档案 · ${symbol}`}
        description="一页收拢行情位置、筛选证据与研究状态；缺失数据保持可见。"
        actions={
          <form onSubmit={submit} className="compact-search">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label="切换股票代码" />
          </form>
        }
      />

      {infoQuery.isLoading ? <Loading label="读取本地股票档案" /> : null}
      {infoQuery.data && !infoQuery.data.available ? (
        <div className="inline-warning research-data-note">{infoQuery.data.message}</div>
      ) : null}
      <div className="research-grid">
        <div className="research-main">
          <Card className="stock-hero-card">
            <div className="stock-hero-card__price">
              <span>本地缓存价格</span>
              <strong>{number(info?.price)}</strong>
              <Badge tone={info?.stale ? "warning" : "positive"}>{info?.data_cutoff ?? "无截止日"}</Badge>
            </div>
            <div className="stock-hero-card__facts">
              <div><span>PE TTM</span><strong>{number(info?.valuation.pe_ttm)}</strong></div>
              <div><span>PB</span><strong>{number(info?.valuation.pb)}</strong></div>
              <div><span>换手率</span><strong>{percent(info?.valuation.turnover_rate)}</strong></div>
              <div><span>近 5 日主力净额</span><strong>{number(info?.moneyflow.net_amount_5d)}</strong></div>
            </div>
          </Card>

          <Card className="research-section">
            <div className="research-section__heading">
              <div><span className="panel-kicker">Position map</span><h2>多周期位置</h2></div>
              <Badge tone="neutral">低位 0–20 · 高位 80–100</Badge>
            </div>
            <div className="position-bands">
              {(info?.periods ?? []).filter((item) => [30, 60, 180].includes(item.period)).map((period) => (
                <PositionBand key={period.period} period={period} />
              ))}
              {!info?.periods?.length ? <p className="muted-copy">本地暂无可用 K 线位置数据。</p> : null}
            </div>
          </Card>

          <Card className="research-section">
            <div className="research-section__heading">
              <div><span className="panel-kicker">History</span><h2>60 日位置快照轨迹</h2></div>
              <Badge tone="neutral">{historyQuery.data?.series.length ?? 0} 个快照日</Badge>
            </div>
            <HistoryLine series={historyQuery.data?.series ?? []} />
          </Card>

          <Card className="research-section">
            <div className="research-section__heading">
              <div><span className="panel-kicker">Evidence timeline</span><h2>出现在 ScreenRun 的记录</h2></div>
              <Badge tone="info">{occurrences.length} 次</Badge>
            </div>
            {runsQuery.isLoading ? <Loading label="汇总运行证据" /> : null}
            <div className="evidence-timeline">
              {occurrences.map(({ run, row }) => (
                <article key={run.run_id}>
                  <span className="timeline-dot" />
                  <div className="timeline-head">
                    <strong>{run.spec.name}</strong>
                    <span>{shortDate(run.created_at)} · 排名 #{row.rank}</span>
                  </div>
                  <div className="timeline-evidence">
                    {(row.evidence ?? []).map((evidence: ScreenEvidence) => (
                      <span key={evidence.evidence_ref}>
                        {evidence.filter_type} {evidence.operator} {number(evidence.threshold)} · 实际 {number(evidence.actual)}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
              {!runsQuery.isLoading && occurrences.length === 0 ? (
                <p className="muted-copy">最近运行中没有出现这只股票。</p>
              ) : null}
            </div>
          </Card>
        </div>

        <aside className="research-aside">
          <Card className="research-status-card">
            <BookOpenCheck size={20} />
            <span>候选状态</span>
            <strong>{candidate ? CANDIDATE_LABEL[candidate.status] : "尚未加入候选"}</strong>
            <p>{candidate?.note || "加入候选后，在这里保留下一步要验证的问题。"}</p>
            {!candidate ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => api.upsertCandidate("default", symbol!, { name: info?.name })}
              >加入研究候选</Button>
            ) : null}
          </Card>
          <Card className="provenance-card">
            <h3><ShieldCheck size={17} /> 证据边界</h3>
            <dl>
              <div><dt><CalendarDays size={14} /> 行情截止</dt><dd>{info?.data_cutoff ?? "未知"}</dd></div>
              <div><dt><Database size={14} /> 行情状态</dt><dd>{info?.stale ? "可能陈旧" : "未标记陈旧"}</dd></div>
              <div><dt>Screen 覆盖</dt><dd>{occurrences.length} 次运行</dd></div>
            </dl>
            <p>页面只展示本机已经取得或计算的数据。空值不代表 0，也不自动补成判断。</p>
          </Card>
        </aside>
      </div>
    </div>
  );
}
