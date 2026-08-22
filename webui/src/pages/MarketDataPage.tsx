import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  CalendarClock,
  Database,
  Gauge,
  HardDrive,
  RefreshCw,
} from "lucide-react";
import { useState } from "react";
import { api, type WorkspaceJob, waitForJob } from "../api/client";
import { Badge, Button, Card, Loading, PageHeader } from "../components/ui";
import { errorMessage, number, percent, shortDate } from "../lib/format";

interface ScanPayload {
  ok: boolean;
  source_name: string;
  stats: {
    targets: number;
    shown: number;
    data_cutoff: string | null;
    stale: boolean;
  };
  freshness: {
    status: "current" | "stale" | "missing";
    title: string;
    detail: string;
  };
  overview?: {
    scanned_count: number;
    low_180_count: number;
    high_180_count: number;
    change_count: number;
  };
}

export function MarketDataPage() {
  const queryClient = useQueryClient();
  const [refreshJob, setRefreshJob] = useState<WorkspaceJob | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const marketQuery = useQuery({
    queryKey: ["market"],
    queryFn: api.market,
    retry: false,
  });
  const jobsQuery = useQuery({
    queryKey: ["jobs", "market-refresh"],
    queryFn: () => api.jobs(20),
    refetchInterval: 1500,
  });
  const latestPersistedJob = jobsQuery.data?.find((job) => job.kind.startsWith("market_refresh:"));
  const visibleJob = refreshJob ?? latestPersistedJob ?? null;
  const refreshMutation = useMutation({
    mutationFn: async (scope: "default" | "all") => {
      const started = await api.startMarketRefresh(scope);
      setRefreshJob(started);
      const completed = await waitForJob(started.job_id, setRefreshJob);
      if (!["succeeded", "partial"].includes(completed.status)) {
        throw new Error(completed.error || completed.message || "行情刷新未完成");
      }
      return completed;
    },
    onSuccess: (job) => {
      setNotice(job.message);
      void queryClient.invalidateQueries({ queryKey: ["market"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs", "market-refresh"] });
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const scan = marketQuery.data?.scan as ScanPayload | null | undefined;
  const market = marketQuery.data?.sentiment;
  const total = (market?.up_count ?? 0) + (market?.down_count ?? 0) + (market?.flat_count ?? 0);
  const upRatio = total ? ((market?.up_count ?? 0) / total) * 100 : 0;

  return (
    <div>
      <PageHeader
        eyebrow="Market & data"
        title="先确认数据边界，再看任何筛选结果"
        description="集中查看本地行情截止日、覆盖范围与全市场截面事实；不会在缺数时给出伪精确结论。"
        actions={
          <>
            {notice ? <span className="notice-pill">{notice}</span> : null}
            <Button
              variant="secondary"
              disabled={refreshMutation.isPending}
              onClick={() => refreshMutation.mutate("default")}
            >
              <RefreshCw size={15} /> 更新默认池
            </Button>
            <Button
              disabled={refreshMutation.isPending}
              onClick={() => refreshMutation.mutate("all")}
            >
              <Database size={15} /> 更新全市场
            </Button>
          </>
        }
      />
      {marketQuery.isLoading ? <Loading label="读取本地市场快照" /> : null}

      {visibleJob ? (
        <Card className="refresh-job-card">
          <div>
            <span className="panel-kicker">Persistent job</span>
            <h2>{visibleJob.message || "行情刷新任务"}</h2>
            <p>
              {visibleJob.progress}/{visibleJob.total || "?"}
              {visibleJob.watermark ? ` · 水位 ${visibleJob.watermark}` : ""}
              {` · ${shortDate(visibleJob.updated_at)}`}
            </p>
          </div>
          <div className="refresh-job-card__progress">
            <span style={{
              width: `${visibleJob.total ? Math.min(100, (visibleJob.progress / visibleJob.total) * 100) : 0}%`,
            }} />
          </div>
          <Badge tone={
            visibleJob.status === "succeeded" ? "positive"
              : visibleJob.status === "partial" ? "warning"
                : visibleJob.status === "failed" || visibleJob.status === "interrupted" ? "danger"
                  : "info"
          }>{visibleJob.status}</Badge>
          {visibleJob.error ? <p className="inline-warning">{visibleJob.error}</p> : null}
        </Card>
      ) : null}

      <div className="market-grid">
        <Card className="data-health-card">
          <div className="data-health-card__icon"><HardDrive size={22} /></div>
          <div>
            <span className="panel-kicker">Data health</span>
            <h2>{scan?.freshness.title ?? "本地行情状态未知"}</h2>
            <p>{scan?.freshness.detail ?? "尚未读取到默认股票池状态。"}</p>
          </div>
          <Badge tone={scan?.stats.stale ? "warning" : scan?.stats.data_cutoff ? "positive" : "neutral"}>
            {scan?.freshness.status ?? "unknown"}
          </Badge>
        </Card>

        <Card className="market-overview-card">
          <div className="research-section__heading">
            <div><span className="panel-kicker">Breadth</span><h2>全市场涨跌分布</h2></div>
            <Badge tone="neutral">{market?.trade_date ?? "无交易日"}</Badge>
          </div>
          <div className="breadth-bar" aria-label="涨跌家数分布">
            <span className="breadth-bar__up" style={{ width: `${upRatio}%` }} />
          </div>
          <div className="breadth-stats">
            <div className="is-up"><ArrowUp size={17} /><span>上涨</span><strong>{number(market?.up_count, 0)}</strong></div>
            <div><Activity size={17} /><span>平盘</span><strong>{number(market?.flat_count, 0)}</strong></div>
            <div className="is-down"><ArrowDown size={17} /><span>下跌</span><strong>{number(market?.down_count, 0)}</strong></div>
          </div>
          {!market?.ok ? <p className="inline-warning">{market?.error ?? "本地没有全市场快照"}</p> : null}
        </Card>

        <Card className="market-metrics-card">
          <div><span><Gauge size={16} /> 180 日位置中位</span><strong>{percent(market?.median_position_180)}</strong></div>
          <div><span><ArrowUp size={16} /> 涨停家数</span><strong>{number(market?.limit_up, 0)}</strong></div>
          <div><span><ArrowDown size={16} /> 跌停家数</span><strong>{number(market?.limit_down, 0)}</strong></div>
          <div><span><Database size={16} /> 默认池覆盖</span><strong>{scan?.stats.targets ?? 0} 只</strong></div>
        </Card>

        <Card className="data-lineage-card">
          <div className="research-section__heading">
            <div><span className="panel-kicker">Lineage</span><h2>当前读取链路</h2></div>
            <CalendarClock size={19} />
          </div>
          <ol>
            <li><span>01</span><div><strong>本地行情缓存</strong><p>默认池：{scan?.source_name ?? "未解析"}</p></div></li>
            <li><span>02</span><div><strong>完整交易日判断</strong><p>截止：{scan?.stats.data_cutoff ?? "未知"}</p></div></li>
            <li><span>03</span><div><strong>选股应用服务</strong><p>ScreenRun 固化 snapshot_id、覆盖率与逐行证据。</p></div></li>
          </ol>
          <p className="data-lineage-card__note">
            全市场更新需要已配置的 TuShare 数据能力，可能持续数分钟；任务进度写入 SQLite，
            中断后重新发起会复用已完成缓存。
          </p>
        </Card>
      </div>
    </div>
  );
}
