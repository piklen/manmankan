import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarCheck2,
  CheckCircle2,
  Clock3,
  FileClock,
  Layers3,
  ListChecks,
  Play,
  RefreshCw,
  StickyNote,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type BoardDailyReview,
  type BoardDailyReviewRequest,
  type BoardReviewChange,
  type Candidate,
  type SavedScreen,
  type ScreenRun,
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
import { errorMessage, shortDate } from "../lib/format";

type ReviewMode = BoardDailyReviewRequest["mode"];
type ChangeType = BoardReviewChange["change_type"];

const MODE_OPTIONS = [
  { value: "close", label: "收盘连续" },
  { value: "candle", label: "阳线连续" },
] satisfies Array<{ value: ReviewMode; label: string }>;

const CHANGE_META: Record<
  ChangeType,
  { label: string; detail: string; tone: "neutral" | "info" | "warning" }
> = {
  direction_changed: {
    label: "方向切换",
    detail: "连续涨跌的正负方向与上一份不同",
    tone: "warning",
  },
  streak_extended: {
    label: "连续天数延长",
    detail: "方向相同，连续天数绝对值增加",
    tone: "info",
  },
  streak_shortened: {
    label: "连续天数缩短",
    detail: "方向相同，连续天数绝对值减少",
    tone: "neutral",
  },
  data_appeared: {
    label: "本次有数据",
    detail: "上一份没有该行，本次可以评估",
    tone: "neutral",
  },
  data_unavailable: {
    label: "本次缺数据",
    detail: "上一份存在，本次快照没有可用行",
    tone: "warning",
  },
};

const SOURCE_LABELS: Record<string, string> = {
  sw: "申万行业指数",
  tushare: "TuShare 概念指数",
  em: "东方财富概念指数",
};

const CANDIDATE_STATUS_LABELS: Record<Candidate["status"], string> = {
  research: "待研究",
  watch: "持续观察",
  selected: "用户已保留",
  rejected: "已排除",
};

function signedStreak(value?: number | null): string {
  if (value === null || value === undefined) return "—";
  if (value > 0) return `连涨 ${value} 天`;
  if (value < 0) return `连跌 ${Math.abs(value)} 天`;
  return "平盘";
}

function ReviewFacts({ review }: { review: BoardDailyReview }) {
  const counts = review.change_counts;
  const metrics = [
    { label: "方向切换", value: counts?.direction_changed ?? 0 },
    { label: "连续延长", value: counts?.streak_extended ?? 0 },
    { label: "连续缩短", value: counts?.streak_shortened ?? 0 },
    {
      label: "数据变化",
      value: (counts?.data_appeared ?? 0) + (counts?.data_unavailable ?? 0),
    },
  ];
  return (
    <>
      <div className="daily-review-sections">
        {review.sections.map((section) => {
          const snapshot = section.snapshot;
          const label = section.kind === "industry" ? "行业" : "题材";
          return (
            <article key={section.kind} className={snapshot ? "" : "is-partial"}>
              <div>
                <span>{label}趋势事实</span>
                <strong>
                  {snapshot
                    ? `${snapshot.coverage.evaluated}/${snapshot.coverage.total} 个已评估`
                    : "本次不可用"}
                </strong>
              </div>
              <p>
                {snapshot
                  ? `${SOURCE_LABELS[snapshot.source] ?? snapshot.source} · 截止 ${snapshot.data_cutoff ?? "未知"}`
                  : section.error_message}
              </p>
              {snapshot?.partial || !snapshot ? (
                <Badge tone="warning">部分记录</Badge>
              ) : (
                <Badge tone="neutral">完整记录</Badge>
              )}
            </article>
          );
        })}
      </div>
      <div className="daily-review-metrics">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
            <small>个板块</small>
          </div>
        ))}
      </div>
    </>
  );
}

function ChangeTable({ review }: { review: BoardDailyReview }) {
  const [filter, setFilter] = useState<"all" | ChangeType>("all");
  const changes = review.changes ?? [];
  const shown = filter === "all"
    ? changes
    : changes.filter((item) => item.change_type === filter);
  if (!review.previous_review_id) {
    return (
      <EmptyState
        title="这是一份跨日比较基线"
        detail="下一个完整交易日再次保存后，这里才会列出连续天数和数据可用性的变化。"
      />
    );
  }
  if (changes.length === 0) {
    return (
      <EmptyState
        title="与上一份同口径记录没有可列出的变化"
        detail="这只表示当前保存的板块行与连续天数相同，不代表未来走势。"
      />
    );
  }
  return (
    <>
      <div className="daily-change-filter">
        <button
          type="button"
          className={filter === "all" ? "is-active" : ""}
          onClick={() => setFilter("all")}
        >
          全部 <span>{changes.length}</span>
        </button>
        {Object.entries(CHANGE_META).map(([value, meta]) => {
          const count = changes.filter((item) => item.change_type === value).length;
          if (!count) return null;
          return (
            <button
              type="button"
              key={value}
              className={filter === value ? "is-active" : ""}
              onClick={() => setFilter(value as ChangeType)}
            >
              {meta.label} <span>{count}</span>
            </button>
          );
        })}
      </div>
      <div className="daily-change-list">
        {shown.map((change) => {
          const meta = CHANGE_META[change.change_type];
          return (
            <article key={`${change.kind}-${change.code}-${change.change_type}`}>
              <div className="daily-change-list__board">
                <Badge tone={meta.tone}>{meta.label}</Badge>
                <strong>{change.name}</strong>
                <small>{change.kind === "industry" ? "行业" : "题材"} · {change.code}</small>
              </div>
              <div className="daily-change-list__streak">
                <span>{signedStreak(change.previous_streak)}</span>
                <ArrowRight size={14} />
                <strong>{signedStreak(change.current_streak)}</strong>
              </div>
              <p>{meta.detail}</p>
            </article>
          );
        })}
      </div>
    </>
  );
}

function ScreenReviewRow({
  screen,
  run,
  pending,
  active,
  onRun,
  onOpen,
}: {
  screen: SavedScreen;
  run?: ScreenRun;
  pending: boolean;
  active: boolean;
  onRun: () => void;
  onOpen: () => void;
}) {
  return (
    <article className="daily-screen-row">
      <button type="button" onClick={onOpen}>
        <strong>{screen.name}</strong>
        <span>v{screen.current_version} · {run ? `最近 ${shortDate(run.created_at)}` : "尚未运行"}</span>
      </button>
      <div className="daily-screen-row__facts">
        <span>命中 <strong>{run?.coverage.matched ?? "—"}</strong></span>
        {run?.diff?.previous_run_id ? (
          <span>
            +{run.diff.added?.length ?? 0} / −{run.diff.removed?.length ?? 0}
          </span>
        ) : <span>暂无跨次 diff</span>}
      </div>
      <Button size="sm" variant="secondary" disabled={pending} onClick={onRun}>
        <Play size={13} /> {active ? "运行中" : "重跑"}
      </Button>
    </article>
  );
}

function CandidateReview({ candidates }: { candidates: Candidate[] }) {
  const active = candidates.filter((item) => item.status !== "rejected");
  const withoutNote = active.filter((item) => !item.note.trim()).length;
  return (
    <>
      <div className="daily-candidate-summary">
        <div><span>待复看候选</span><strong>{active.length}</strong></div>
        <div><span>未写重看条件</span><strong>{withoutNote}</strong></div>
      </div>
      <div className="daily-candidate-list">
        {active.slice(0, 6).map((candidate) => (
          <article key={`${candidate.list_id}-${candidate.symbol}`}>
            <div>
              <strong>{candidate.name}</strong>
              <small>{candidate.symbol} · {CANDIDATE_STATUS_LABELS[candidate.status]}</small>
            </div>
            <p>{candidate.note.trim() || "尚未记录下一次要核对的事实"}</p>
          </article>
        ))}
      </div>
    </>
  );
}

export function DailyReviewPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<ReviewMode>("close");
  const [industryLevel, setIndustryLevel] = useState(1);
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);
  const [runningScreenId, setRunningScreenId] = useState<string | null>(null);
  const [batchProgress, setBatchProgress] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reviewsQuery = useQuery({
    queryKey: ["board-reviews"],
    queryFn: () => api.boardReviews(30),
  });
  useEffect(() => {
    if (!selectedReviewId && reviewsQuery.data?.[0]) {
      const latest = reviewsQuery.data[0];
      setSelectedReviewId(latest.review_id);
      setMode(latest.mode);
      setIndustryLevel(latest.industry_level);
    }
  }, [reviewsQuery.data, selectedReviewId]);
  const reviewQuery = useQuery({
    queryKey: ["board-review", selectedReviewId],
    queryFn: () => api.boardReview(selectedReviewId!),
    enabled: Boolean(selectedReviewId),
  });
  const screensQuery = useQuery({ queryKey: ["screens"], queryFn: api.screens });
  const runsQuery = useQuery({ queryKey: ["runs", "daily-review"], queryFn: () => api.runs(null, 200) });
  const candidatesQuery = useQuery({ queryKey: ["candidate-lists"], queryFn: api.candidateLists });

  const latestRuns = useMemo(() => {
    const map = new Map<string, ScreenRun>();
    for (const run of runsQuery.data ?? []) {
      if (run.screen_id && !map.has(run.screen_id)) map.set(run.screen_id, run);
    }
    return map;
  }, [runsQuery.data]);
  const candidates = useMemo(
    () => (candidatesQuery.data ?? []).flatMap((list) => list.candidates ?? []),
    [candidatesQuery.data],
  );

  const createReview = useMutation({
    mutationFn: () => api.createBoardReview({
      mode,
      industry_level: industryLevel,
      force: false,
    }),
    onSuccess: (review) => {
      setSelectedReviewId(review.review_id);
      setNotice(review.previous_review_id ? "已保存并完成跨日比较" : "已保存第一份比较基线");
      void queryClient.invalidateQueries({ queryKey: ["board-reviews"] });
      queryClient.setQueryData(["board-review", review.review_id], review);
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const runScreen = useMutation({
    mutationFn: async (screenId: string) => {
      setRunningScreenId(screenId);
      return api.runSavedScreen(screenId);
    },
    onSuccess: (run) => {
      setNotice(`「${run.spec.name}」已生成新一份不可变运行`);
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (error) => setNotice(errorMessage(error)),
    onSettled: () => setRunningScreenId(null),
  });

  const runAllScreens = useMutation({
    mutationFn: async () => {
      let succeeded = 0;
      const failures: string[] = [];
      const screens = screensQuery.data ?? [];
      for (const [index, screen] of screens.entries()) {
        setBatchProgress(`${index + 1}/${screens.length} · ${screen.name}`);
        try {
          await api.runSavedScreen(screen.screen_id);
          succeeded += 1;
        } catch (error) {
          failures.push(`${screen.name}: ${errorMessage(error)}`);
        }
      }
      return { succeeded, failures };
    },
    onSuccess: ({ succeeded, failures }) => {
      setNotice(
        failures.length
          ? `完成 ${succeeded} 个，${failures.length} 个失败；可单独重试`
          : `已顺序重跑 ${succeeded} 个 Screen`,
      );
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (error) => setNotice(errorMessage(error)),
    onSettled: () => setBatchProgress(null),
  });

  const review = reviewQuery.data;
  const screens = screensQuery.data ?? [];
  return (
    <div className="daily-review-page">
      <PageHeader
        eyebrow="Daily review"
        title="把今天看到的变化，留给明天复核"
        description="保存行业与题材趋势事实，比较连续天数和数据可用性；再顺序重跑你已经写好的 Screen，复看候选备注。"
        actions={
          <>
            {notice ? <span className="notice-pill">{notice}</span> : null}
            <Button
              disabled={createReview.isPending || runScreen.isPending || runAllScreens.isPending}
              onClick={() => createReview.mutate()}
            >
              <CalendarCheck2 size={16} />
              {createReview.isPending ? "正在生成" : "保存最新复看"}
            </Button>
          </>
        }
      />

      <Card className="daily-review-config">
        <div>
          <span className="panel-kicker">复看口径</span>
          <strong>只决定怎样读取趋势，不设置股票买卖条件</strong>
        </div>
        <Segmented
          label="复看趋势口径"
          value={mode}
          options={MODE_OPTIONS}
          onChange={setMode}
        />
        <label>
          <span>申万行业层级</span>
          <select value={industryLevel} onChange={(event) => setIndustryLevel(Number(event.target.value))}>
            <option value={1}>一级行业</option>
            <option value={2}>二级行业</option>
            <option value={3}>三级行业</option>
          </select>
        </label>
      </Card>

      <div className="daily-review-layout">
        <Card className="daily-review-main">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">01 · 板块跨日变化</span>
              <h2>{review ? `复看 ${shortDate(review.created_at)}` : "尚未保存复看记录"}</h2>
              <p>
                {review?.previous_review_id
                  ? `对比上一份 ${review.previous_review_id.slice(0, 8)}`
                  : "第一份只建立基线，不生成伪变化"}
              </p>
            </div>
            {review?.partial ? <Badge tone="warning">部分数据</Badge> : null}
          </div>
          {reviewsQuery.isLoading || reviewQuery.isLoading ? <Loading label="读取每日复看" /> : null}
          {reviewQuery.isError ? (
            <EmptyState
              title="这份复看暂时无法读取"
              detail={errorMessage(reviewQuery.error)}
              action={<Button variant="secondary" onClick={() => void reviewQuery.refetch()}>再试一次</Button>}
            />
          ) : null}
          {!reviewsQuery.isLoading && !selectedReviewId ? (
            <EmptyState
              title="还没有跨日趋势记录"
              detail="点击“保存最新复看”建立第一份基线；系统不会把第一天的所有板块写成新趋势。"
              action={<Button onClick={() => createReview.mutate()}>建立基线</Button>}
            />
          ) : null}
          {review ? (
            <>
              <ReviewFacts review={review} />
              <div className="daily-change-heading">
                <div><span className="panel-kicker">变化明细</span><h3>只列事实发生变化的板块</h3></div>
                <FileClock size={18} />
              </div>
              <ChangeTable review={review} />
              {(review.warnings?.length ?? 0) > 0 ? (
                <p className="daily-review-warning">{review.warnings?.join(" · ")}</p>
              ) : null}
            </>
          ) : null}
        </Card>

        <Card className="daily-review-history">
          <div className="panel-heading">
            <div><span className="panel-kicker">历史</span><h2>已保存复看</h2></div>
            <Clock3 size={18} />
          </div>
          <div className="daily-history-list">
            {(reviewsQuery.data ?? []).map((item) => (
              <button
                type="button"
                key={item.review_id}
                className={item.review_id === selectedReviewId ? "is-active" : ""}
                onClick={() => {
                  setSelectedReviewId(item.review_id);
                  setMode(item.mode);
                  setIndustryLevel(item.industry_level);
                }}
              >
                <span><strong>{shortDate(item.created_at)}</strong><small>{item.mode === "close" ? "收盘连续" : "阳线连续"} · L{item.industry_level}</small></span>
                {item.partial ? <Badge tone="warning">部分</Badge> : <CheckCircle2 size={15} />}
              </button>
            ))}
          </div>
          <p className="daily-history-note">相同数据与口径重复点击不会新增记录。</p>
        </Card>
      </div>

      <div className="daily-workflow-grid">
        <Card className="daily-screens">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">02 · 重跑已有规则</span>
              <h2>Screen 日常复看</h2>
              <p>沿用你已经保存的条件，新的运行仍会保留 added / removed / rank diff。</p>
            </div>
            <ListChecks size={19} />
          </div>
          <div className="daily-screens__actions">
            <span>{batchProgress ?? `${screens.length} 个已保存 Screen`}</span>
            <Button
              size="sm"
              variant="secondary"
              disabled={!screens.length || runAllScreens.isPending || runScreen.isPending || createReview.isPending}
              onClick={() => runAllScreens.mutate()}
            >
              <RefreshCw size={14} className={runAllScreens.isPending ? "spin" : ""} />
              顺序重跑全部
            </Button>
          </div>
          {screensQuery.isLoading || runsQuery.isLoading ? <Loading label="读取 Screen 运行" /> : null}
          {!screensQuery.isLoading && screens.length === 0 ? (
            <EmptyState
              title="还没有已保存的 Screen"
              detail="先在选股工作台写下自己的股票池和条件，再回到这里做每日复看。"
              action={<Button size="sm" onClick={() => navigate("/screen")}>去选股工作台</Button>}
            />
          ) : null}
          <div className="daily-screen-list">
            {screens.map((screen) => (
              <ScreenReviewRow
                key={screen.screen_id}
                screen={screen}
                run={latestRuns.get(screen.screen_id)}
                pending={runScreen.isPending || runAllScreens.isPending || createReview.isPending}
                active={runningScreenId === screen.screen_id}
                onRun={() => runScreen.mutate(screen.screen_id)}
                onOpen={() => navigate(`/screen?screen=${screen.screen_id}`)}
              />
            ))}
          </div>
        </Card>

        <Card className="daily-candidates">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">03 · 人工研究队列</span>
              <h2>候选重看条件</h2>
              <p>这里只展示你自己保存的状态和备注，不替你猜下一步动作。</p>
            </div>
            <StickyNote size={19} />
          </div>
          {candidatesQuery.isLoading ? <Loading label="读取候选备注" /> : null}
          {!candidatesQuery.isLoading && candidates.length === 0 ? (
            <EmptyState
              title="候选研究队列还是空的"
              detail="从 Screen 结果中手动保留对象，并写下下一次要核对的事实。"
            />
          ) : <CandidateReview candidates={candidates} />}
          <Button variant="ghost" className="daily-candidates__open" onClick={() => navigate("/candidates")}>
            打开候选研究 <ArrowRight size={15} />
          </Button>
        </Card>
      </div>

      <div className="trend-principle daily-review-principle">
        <Layers3 size={18} />
        <p>
          <strong>连续天数延长只是已发生的价格序列事实。</strong>
          它不等于趋势“更强”，也不会自动变成股票条件、候选状态或买卖动作。
        </p>
      </div>
    </div>
  );
}
