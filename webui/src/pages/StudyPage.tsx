import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  FlaskConical,
  RefreshCw,
  Search,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, type StudyQuery, type StudyResult } from "../api/client";
import { StudyEditor } from "../components/StudyEditor";
import {
  StudyChart,
  DistributionChart,
  ShapeOverlay,
} from "../components/StudyChart";
import { EvidencePanel } from "../components/EvidencePanel";
import { Button, Empty, Loading, Notice } from "../components/ui";
import {
  blankDraft,
  conditionText,
  draftError,
  draftToQuery,
  queryToDraft,
  type StudyDraft,
} from "../lib/study";
import { errorMessage, number, percent, shortDate } from "../lib/format";

type Selection = { symbol: string; date: string };
function initialDraft(
  result: StudyResult | undefined,
  query: StudyQuery | undefined,
): StudyDraft {
  if (query) return queryToDraft(query);
  if (result) return queryToDraft(result.query);
  try {
    const saved = sessionStorage.getItem("manmankan.study-draft.v1");
    if (saved) {
      const draft = JSON.parse(saved) as StudyDraft;
      if (
        Array.isArray(draft.conditions) &&
        typeof draft.codes === "string" &&
        typeof draft.lookback === "string"
      ) {
        draftError(draft);
        return draft;
      }
    }
  } catch {
    /* 无有效草稿时从空白条件开始。 */
  }
  return blankDraft();
}

export function SavedStudyPage() {
  const { studyId = "" } = useParams();
  const query = useQuery({
    queryKey: ["study", studyId],
    queryFn: () => api.study(studyId),
    retry: false,
  });
  if (query.isLoading) return <Loading>读取保存的研究与证据</Loading>;
  if (query.error)
    return (
      <div className="archive-page">
        <Notice error>{errorMessage(query.error)}</Notice>
        <Link to="/studies">返回我的研究</Link>
      </div>
    );
  return <StudyPage key={studyId} initialResult={query.data} />;
}

export function StudyPage({ initialResult }: { initialResult?: StudyResult }) {
  const location = useLocation();
  const navigate = useNavigate();
  const client = useQueryClient();
  const suppliedQuery = (location.state as { query?: StudyQuery } | null)
    ?.query;
  const [draft, setDraft] = useState(() =>
    initialDraft(initialResult, suppliedQuery),
  );
  const [result, setResult] = useState<StudyResult | undefined>(initialResult);
  const [editorExpanded, setEditorExpanded] = useState(!initialResult);
  const [tab, setTab] = useState<"history" | "current" | "diff">("history");
  const firstEvent = initialResult?.events[0];
  const firstMatch = initialResult?.current_matches[0];
  const [selection, setSelection] = useState<Selection | null>(
    firstEvent
      ? { symbol: firstEvent.symbol, date: firstEvent.event_date }
      : firstMatch
        ? { symbol: firstMatch.symbol, date: firstMatch.date }
        : null,
  );
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(0);
  useEffect(() => {
    if (!initialResult) {
      try {
        sessionStorage.setItem(
          "manmankan.study-draft.v1",
          JSON.stringify(draft),
        );
      } catch {
        /* 运行结果仍由本机服务保存。 */
      }
    }
  }, [draft, initialResult]);
  const receive = (value: StudyResult) => {
    void client.invalidateQueries({ queryKey: ["studies"] });
    client.setQueryData(["study", value.study_id], value);
    if (location.pathname !== `/studies/${value.study_id}`) {
      navigate(`/studies/${value.study_id}`, { replace: true });
      return;
    }
    setEditorExpanded(false);
    setResult(value);
    setDraft(queryToDraft(value.query));
    setOffset(0);
    setCurrentPage(0);
    setSearch("");
    const event = value.events[0];
    const current = value.current_matches[0];
    setSelection(
      event
        ? { symbol: event.symbol, date: event.event_date }
        : current
          ? { symbol: current.symbol, date: current.date }
          : null,
    );
    setTab(event ? "history" : "current");
  };
  const run = useMutation({
    mutationFn: () => api.runStudy(draftToQuery(draft)),
    onSuccess: receive,
  });
  const rerun = useMutation({
    mutationFn: (latest: boolean) => api.rerunStudy(result!.study_id, latest),
    onSuccess: receive,
  });
  const busy = run.isPending || rerun.isPending;
  const automaticRunStarted = useRef(false);
  useEffect(() => {
    if (
      (location.state as { autoRun?: boolean } | null)?.autoRun &&
      suppliedQuery &&
      !automaticRunStarted.current
    ) {
      automaticRunStarted.current = true;
      if (!draftError(draft)) run.mutate();
    }
  }, [suppliedQuery]);
  const evidence = useQuery({
    queryKey: [
      "study-evidence",
      result?.run_id,
      selection?.symbol,
      selection?.date,
    ],
    queryFn: () =>
      api.studyEvidence(result!.run_id, selection!.symbol, selection!.date),
    enabled: Boolean(result && selection),
    retry: false,
  });
  const eventsPage = useQuery({
    queryKey: ["study-events", result?.run_id, offset],
    queryFn: () => api.studyEvents(result!.run_id, offset),
    enabled: Boolean(result && offset > 0 && tab === "history"),
    retry: false,
  });
  const events = offset
    ? (eventsPage.data?.items ?? [])
    : (result?.events ?? []);
  const matches = (result?.current_matches ?? []).filter((match) =>
    `${match.name} ${match.symbol}`.includes(search.trim()),
  );
  const dirty = Boolean(
    result &&
      !draftError(draft) &&
      JSON.stringify(draftToQuery(draft)) !==
        JSON.stringify(draftToQuery(queryToDraft(result.query))),
  );
  const changeTab = (value: typeof tab) => {
    setTab(value);
    if (value === "current" && matches[0])
      setSelection({ symbol: matches[0].symbol, date: matches[0].date });
    if (value === "history" && events[0])
      setSelection({ symbol: events[0].symbol, date: events[0].event_date });
  };
  return (
    <div className="study-layout">
      <StudyEditor
        draft={draft}
        onChange={setDraft}
        onRun={() => run.mutate()}
        busy={busy}
        expanded={editorExpanded}
        onToggle={() => setEditorExpanded(!editorExpanded)}
      />
      <section className="study-main">
        <header className="study-heading">
          <div>
            <Link to="/" className="small-link">
              <ArrowLeft size={14} />
              趋势地图
            </Link>
            <h1>{result?.query.title ?? "验证一组明确条件"}</h1>
            <p>当前匹配与历史验证使用同一组条件。</p>
          </div>
          {result ? (
            <div className="study-rerun-actions">
              <Button
                variant="secondary"
                disabled={busy || dirty}
                onClick={() => rerun.mutate(true)}
              >
                <RefreshCw size={14} />
                更新至最近收盘
              </Button>
              <button
                className="small-link"
                type="button"
                disabled={busy || dirty}
                onClick={() => rerun.mutate(false)}
              >
                按原日期复算
              </button>
            </div>
          ) : null}
        </header>
        {run.error || rerun.error ? (
          <Notice error>{errorMessage(run.error || rerun.error)}</Notice>
        ) : null}
        {dirty ? (
          <Notice>
            条件有修改，运行后更新结果。当前图表仍对应上一次已保存研究。
          </Notice>
        ) : null}
        {busy ? (
          <Loading>
            正在核对日线、计算样本并保存证据；较大的股票池需要更多时间。
          </Loading>
        ) : null}
        {!result ? (
          <Empty title="把一个趋势问题，变成可核对的事实">
            <FlaskConical size={36} strokeWidth={1.4} />
            <p>从地图圈选区域进入，或在左侧明确自己的条件。</p>
            <ol className="research-steps">
              <li>
                <strong>看当前</strong>
                <span>同一天，哪些股票满足条件</span>
              </li>
              <li>
                <strong>验历史</strong>
                <span>过去何时出现，之后实际怎样</span>
              </li>
              <li>
                <strong>查证据</strong>
                <span>点开任一样本，逐条核对日线</span>
              </li>
            </ol>
            <p className="muted">
              只使用可靠的日线事实；没有预填股票或隐藏策略。
            </p>
          </Empty>
        ) : (
          <>
            <div className="query-summary">
              {result.query.conditions.map((condition, index) => (
                <span key={index}>{conditionText(condition)}</span>
              ))}
            </div>
            <div className="study-meta">
              <span>数据截至 {result.as_of}</span>
              <span>已保存 {shortDate(result.created_at)}</span>
              {result.query.reference ? (
                <span>
                  事后形态检索 · 参照 {result.query.reference.symbol} /{" "}
                  {result.query.reference.as_of}
                </span>
              ) : null}
            </div>
            <nav className="page-tabs" aria-label="研究结果视角">
              <button
                className={tab === "current" ? "active" : ""}
                onClick={() => changeTab("current")}
              >
                当前匹配<span>{result.current_matches.length}</span>
              </button>
              <button
                className={tab === "history" ? "active" : ""}
                onClick={() => changeTab("history")}
              >
                历史验证<span>{result.events_total}</span>
              </button>
              <button
                className={tab === "diff" ? "active" : ""}
                onClick={() => changeTab("diff")}
              >
                运行变化
              </button>
            </nav>
            {tab !== "diff" ? (
              <>
                <div className="study-facts">
                  <div>
                    <strong>
                      {tab === "history"
                        ? result.events_total
                        : result.coverage.current_matches}
                    </strong>
                    <span>
                      {tab === "history" ? "满足条件的事件" : "当前满足条件"}
                    </span>
                  </div>
                  <div>
                    <strong>
                      {tab === "history"
                        ? result.coverage.complete_events
                        : result.coverage.current_evaluated}
                    </strong>
                    <span>{tab === "history" ? "完整观察" : "可评估股票"}</span>
                  </div>
                  <div>
                    <strong>
                      {tab === "history"
                        ? result.coverage.pending_events
                        : result.coverage.current_missing}
                    </strong>
                    <span>{tab === "history" ? "窗口未完成" : "当前缺失"}</span>
                  </div>
                  <div>
                    <strong>
                      {result.distribution.positive} /{" "}
                      {result.distribution.count}
                    </strong>
                    <span>完整观察后上涨</span>
                    <small>历史样本占比，不代表未来概率</small>
                  </div>
                </div>
                {evidence.isLoading ? (
                  <Loading>读取当次保存的日线图证</Loading>
                ) : evidence.error ? (
                  <Notice error>{errorMessage(evidence.error)}</Notice>
                ) : evidence.data ? (
                  <StudyChart
                    key={`${evidence.data.run_id}-${evidence.data.symbol}-${evidence.data.event_date}`}
                    evidence={evidence.data}
                  />
                ) : null}
                {evidence.data?.reference_bars?.length ? (
                  <ShapeOverlay evidence={evidence.data} />
                ) : null}
                {tab === "history" ? (
                  <>
                    <DistributionChart
                      data={result.distribution}
                      days={result.query.forward_days}
                    />
                    <div className="section-heading">
                      <h3>历史样本</h3>
                      <span>
                        {result.coverage.missing_events} 个缺数据，未计入分布
                        {result.coverage.self_matches_excluded
                          ? ` · 排除参照自身 ${result.coverage.self_matches_excluded} 次`
                          : ""}
                      </span>
                    </div>
                    {eventsPage.isFetching && offset ? (
                      <Loading>读取下一页样本</Loading>
                    ) : eventsPage.error ? (
                      <Notice error>{errorMessage(eventsPage.error)}</Notice>
                    ) : events.length ? (
                      <div className="table-scroll">
                        <table className="sample-table">
                          <thead>
                            <tr>
                              <th>事件日期</th>
                              <th>股票</th>
                              <th>当日收盘</th>
                              <th>{result.query.forward_days}日后变化</th>
                              <th>观察状态</th>
                              <th />
                            </tr>
                          </thead>
                          <tbody>
                            {events.map((event) => (
                              <tr
                                key={event.event_id}
                                className={
                                  selection?.symbol === event.symbol &&
                                  selection.date === event.event_date
                                    ? "selected"
                                    : ""
                                }
                                onClick={() =>
                                  setSelection({
                                    symbol: event.symbol,
                                    date: event.event_date,
                                  })
                                }
                              >
                                <td>{event.event_date}</td>
                                <td>
                                  <strong>{event.name}</strong>
                                  <small>{event.symbol}</small>
                                </td>
                                <td>{number(event.event_close)}</td>
                                <td
                                  className={
                                    event.return_pct == null
                                      ? ""
                                      : event.return_pct >= 0
                                        ? "value-up"
                                        : "value-down"
                                  }
                                >
                                  {percent(event.return_pct, 2)}
                                </td>
                                <td>
                                  {event.status === "complete"
                                    ? "完整"
                                    : event.status === "pending"
                                      ? "未完成"
                                      : "缺数据"}
                                </td>
                                <td>
                                  <button
                                    type="button"
                                    className="table-action"
                                    onClick={() =>
                                      setSelection({
                                        symbol: event.symbol,
                                        date: event.event_date,
                                      })
                                    }
                                    aria-label={`查看 ${event.symbol} ${event.event_date} 样本`}
                                  >
                                    查看
                                    <ArrowRight size={12} />
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <Empty title="这段历史中没有选取到事件">
                        <p>
                          可以查看当前匹配与缺失情况，或明确修改条件和范围后重新研究。
                        </p>
                      </Empty>
                    )}
                    <div className="pagination">
                      <span>
                        {result.events_total
                          ? `${offset + 1}–${Math.min(offset + 50, result.events_total)} / ${result.events_total}`
                          : "0 个样本"}
                      </span>
                      <Button
                        variant="ghost"
                        disabled={!offset}
                        onClick={() => setOffset(Math.max(0, offset - 50))}
                      >
                        <ChevronLeft size={15} />
                        上一页
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={offset + 50 >= result.events_total}
                        onClick={() => setOffset(offset + 50)}
                      >
                        下一页
                        <ChevronRight size={15} />
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="section-heading">
                      <h3>当前符合条件的股票</h3>
                      <label className="search-field">
                        <Search size={15} />
                        <input
                          aria-label="搜索当前匹配"
                          placeholder="名称或代码"
                          value={search}
                          onChange={(event) => {
                            setSearch(event.target.value);
                            setCurrentPage(0);
                          }}
                        />
                      </label>
                    </div>
                    {matches.length ? (
                      <div className="table-scroll">
                        <table className="sample-table">
                          <thead>
                            <tr>
                              <th>股票</th>
                              <th>收盘</th>
                              <th>当日涨跌</th>
                              <th>行情日</th>
                              <th />
                            </tr>
                          </thead>
                          <tbody>
                            {matches
                              .slice(currentPage * 100, (currentPage + 1) * 100)
                              .map((match) => (
                                <tr
                                  key={match.symbol}
                                  className={
                                    selection?.symbol === match.symbol &&
                                    selection.date === match.date
                                      ? "selected"
                                      : ""
                                  }
                                  onClick={() =>
                                    setSelection({
                                      symbol: match.symbol,
                                      date: match.date,
                                    })
                                  }
                                >
                                  <td>
                                    <strong>{match.name}</strong>
                                    <small>{match.symbol}</small>
                                  </td>
                                  <td>{number(match.close)}</td>
                                  <td
                                    className={
                                      (match.change_pct ?? 0) >= 0
                                        ? "value-up"
                                        : "value-down"
                                    }
                                  >
                                    {percent(match.change_pct, 2)}
                                  </td>
                                  <td>{match.date}</td>
                                  <td>
                                    <button
                                      className="table-action"
                                      type="button"
                                      onClick={() =>
                                        setSelection({
                                          symbol: match.symbol,
                                          date: match.date,
                                        })
                                      }
                                      aria-label={`查看 ${match.symbol} 当前证据`}
                                    >
                                      核对
                                      <ArrowRight size={12} />
                                    </button>
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <Empty
                        title={
                          search
                            ? "没有匹配的名称或代码"
                            : "当前没有股票满足这些条件"
                        }
                      >
                        <p>
                          当前无命中不等于历史无样本。可以切换历史验证，查看同一条件曾经发生的情况。
                        </p>
                      </Empty>
                    )}
                    {matches.length > 100 ? (
                      <div className="pagination">
                        <span>
                          {currentPage * 100 + 1}–
                          {Math.min((currentPage + 1) * 100, matches.length)} /{" "}
                          {matches.length}
                        </span>
                        <Button
                          variant="ghost"
                          disabled={!currentPage}
                          onClick={() => setCurrentPage(currentPage - 1)}
                        >
                          上一页
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={(currentPage + 1) * 100 >= matches.length}
                          onClick={() => setCurrentPage(currentPage + 1)}
                        >
                          下一页
                        </Button>
                      </div>
                    ) : null}
                  </>
                )}
              </>
            ) : result.diff?.previous_run_id ? (
              <div className="run-diff">
                <p>
                  对比前次数据日 {result.diff?.previous_as_of} 与本次{" "}
                  {result.as_of}。缺数据单独列出。
                </p>
                {(
                  [
                    ["新增满足", result.diff?.added],
                    ["已不满足", result.diff?.removed],
                    ["当前无法核对", result.diff?.unavailable ?? []],
                  ] as const
                ).map(([label, symbols]) => (
                  <section key={label}>
                    <h3>
                      {label}
                      <span>{symbols?.length ?? 0}</span>
                    </h3>
                    <div>
                      {symbols?.length ? (
                        symbols.map((symbol) => (
                          <span className="code-chip" key={symbol}>
                            {symbol}
                          </span>
                        ))
                      ) : (
                        <p className="muted">没有变化</p>
                      )}
                    </div>
                  </section>
                ))}
              </div>
            ) : (
              <Empty title="这次运行建立了比较基线">
                <p>
                  用相同条件重跑后，会显示新增满足、已不满足和无法核对的对象。
                </p>
              </Empty>
            )}
          </>
        )}
      </section>
      {result ? (
        evidence.isFetching && !evidence.data ? (
          <aside className="evidence-panel">
            <Loading>读取逐条证据</Loading>
          </aside>
        ) : (
          <EvidencePanel evidence={evidence.data} result={result} />
        )
      ) : (
        <aside className="evidence-panel">
          <h2>证据从这里展开</h2>
          <p className="evidence-hint">
            先运行条件。每个结果都保留实际值、行情日期和后续观察；样本不足与数据缺失会直接显示。
          </p>
        </aside>
      )}
    </div>
  );
}
