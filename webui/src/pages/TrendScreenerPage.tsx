import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Bookmark,
  ChevronLeft,
  ChevronRight,
  Filter,
  Grid2X2,
  List,
  MapPin,
  Search,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  api,
  type SavedTrendSearch,
  type TrendSearchQuery,
  type TrendSearchRow,
} from "../api/client";
import {
  ComparisonSummary,
  TrendChangesTable,
  type ChangeFilter,
} from "../components/TrendComparison";
import { SwingSettings } from "../components/SwingSettings";
import { TrendConditionBuilder } from "../components/TrendConditionBuilder";
import {
  PriceSparkline,
  segmentLabel,
  TrendStockDetail,
} from "../components/TrendStockDetail";
import {
  TrendScatter,
  type MapBounds,
  type TrendPoint,
} from "../components/TrendScatter";
import { Button, Empty, Loading, Notice } from "../components/ui";
import { conditionText, fieldValue, parseCodes, SWING_FIELDS, UNIVERSE_LABELS } from "../lib/study";
import {
  blankScreenDraft,
  conditionsToDraft,
  comparisonInputError,
  historicalQuery,
  screenDraftToQuery,
  screenInputError,
  screenQueryToDraft,
  taskConditions,
  TREND_TASKS,
  type ScreenerDraft,
  type TrendTask,
} from "../lib/screener";
import { errorMessage, number, percent } from "../lib/format";

const storageKey = "manmankan.trend-screen.v3";
function remembered(): {
  draft: ScreenerDraft;
  submitted: TrendSearchQuery | null;
  task: TrendTask | null;
} {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    if (
      saved?.draft &&
      Array.isArray(saved.draft.conditions) &&
      Array.isArray(saved.draft.industries)
    )
      return saved;
  } catch {
    /* 没有有效草稿时从空白问题开始。 */
  }
  return { draft: blankScreenDraft(), submitted: null, task: null };
}
function summary(query: TrendSearchQuery) {
  if (!query.conditions?.length) return "浏览当前股票池";
  return conditionsToDraft(query.conditions)
    .map((item) => {
      if (
        [
          "up_days",
          "down_days",
          "previous_up_days",
          "previous_down_days",
          "bull_days",
          "bear_days",
          "joint_up_days",
        ].includes(item.field)
      ) {
        const labels: Record<string, string> = {
          up_days: "连续上涨",
          down_days: "连续下跌",
          previous_up_days: "先连续上涨",
          previous_down_days: "先连续下跌",
          bull_days: "连续收阳",
          bear_days: "连续收阴",
          joint_up_days: "连续收阳且上涨",
        };
        return `${labels[item.field]}${item.operator === "gte" ? "至少 " : item.operator === "eq" ? "恰好 " : item.operator === "lte" ? "1–" : ""}${item.value} 天`;
      }
      return conditionText({
        field: item.field as NonNullable<
          TrendSearchQuery["conditions"]
        >[number]["field"],
        operator: item.operator,
        value: Number(item.value),
        window: item.window ? Number(item.window) : null,
      });
    })
    .join(" · ");
}

export function TrendScreenerPage() {
  const navigate = useNavigate(),
    client = useQueryClient();
  const [initial] = useState(remembered);
  const [draft, setDraft] = useState(initial.draft);
  const [submitted, setSubmitted] = useState<TrendSearchQuery | null>(
    initial.submitted,
  );
  const [task, setTask] = useState<TrendTask | null>(initial.task);
  const [search, setSearch] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const explicitSelection = useRef<string | null>(null);
  const [view, setView] = useState<"table" | "map">("table");
  const [listMode, setListMode] = useState<"matches" | "missing" | "changes">(
    "matches",
  );
  const [changeFilter, setChangeFilter] = useState<ChangeFilter>("all");
  const [page, setPage] = useState(0);
  const [editorOpen, setEditorOpen] = useState(!initial.submitted);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false),
    [saveTitle, setSaveTitle] = useState("");
  const [feedback, setFeedback] = useState("");
  const [positionWindow, setPositionWindow] = useState(180),
    [momentumWindow, setMomentumWindow] = useState(20);
  const [bounds, setBounds] = useState<MapBounds | null>(null);
  const [boundsOpen, setBoundsOpen] = useState(false);
  const [rangeDraft, setRangeDraft] = useState({
    xMin: "",
    xMax: "",
    yMin: "",
    yMax: "",
  });
  const query = useQuery({
    queryKey: ["trend-search", submitted],
    queryFn: () => api.searchTrends(submitted!),
    enabled: Boolean(submitted),
    staleTime: Infinity,
    placeholderData: (previous) => previous,
    retry: false,
  });
  const result = query.data;
  const saved = useQuery({
    queryKey: ["saved-trends"],
    queryFn: api.savedTrends,
    staleTime: Infinity,
    retry: false,
  });
  const save = useMutation({
    mutationFn: () =>
      api.saveTrend(saveTitle.trim(), screenDraftToQuery(draft)),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["saved-trends"] });
      setSaveOpen(false);
      setSaveTitle("");
      setFeedback(
        "已保存筛选。下次载入后可直接筛选。日期留空的筛选会使用最近完整交易日。",
      );
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteSavedTrend(id),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["saved-trends"] }),
  });
  const validation = screenInputError(draft);
  const dirty = Boolean(
    result &&
      (validation ||
        JSON.stringify(screenDraftToQuery(draft)) !==
          JSON.stringify(screenDraftToQuery(screenQueryToDraft(result.query)))),
  );
  const sortedRows = useMemo(
    () =>
      [...(result?.rows ?? [])].sort((a, b) =>
        a.symbol.localeCompare(b.symbol),
      ),
    [result],
  );
  const rows = useMemo(
    () =>
      sortedRows.filter((row) =>
        `${row.symbol} ${row.name} ${row.industry ?? ""}`
          .toLowerCase()
          .includes(search.trim().toLowerCase()),
      ),
    [sortedRows, search],
  );
  const missingRows = (result?.missing_rows ?? []).filter((row) =>
    `${row.symbol} ${row.name}`.includes(search.trim()),
  );
  const sortedChanges = useMemo(
    () =>
      [...(result?.comparison?.rows ?? [])].sort((a, b) =>
        a.symbol.localeCompare(b.symbol),
      ),
    [result],
  );
  const changeRows = useMemo(
    () =>
      sortedChanges.filter(
        (row) =>
          (changeFilter === "all" || row.status === changeFilter) &&
          `${row.symbol} ${row.name} ${row.industry ?? ""}`
            .toLowerCase()
            .includes(search.trim().toLowerCase()),
      ),
    [sortedChanges, changeFilter, search],
  );
  const swingWindows = [...new Set(result?.query.conditions?.filter((item) => SWING_FIELDS.has(item.field)).map((item) => item.window) ?? [])];
  const selectedRow = result?.rows.find((row) => row.symbol === selectedSymbol);
  const selectedChange = sortedChanges.find(
    (row) => row.symbol === selectedSymbol,
  );
  const selected = selectedRow ?? selectedChange;
  const listedItems =
    listMode === "changes"
      ? changeRows
      : listMode === "missing"
        ? missingRows
        : rows;
  const openChanges = (filter: ChangeFilter) => {
    setListMode("changes");
    setView("table");
    setChangeFilter(filter);
    setPage(0);
    setMobileDetail(false);
    const available = sortedChanges.filter(
      (row) =>
        (filter === "all" || row.status === filter) &&
        `${row.symbol} ${row.name} ${row.industry ?? ""}`
          .toLowerCase()
          .includes(search.trim().toLowerCase()),
    );
    if (!available.some((row) => row.symbol === selectedSymbol)) {
      setSelectedSymbol(available[0]?.symbol ?? null);
      explicitSelection.current = null;
    }
  };
  const mapRows: TrendPoint[] = useMemo(
    () =>
      rows.map((row) => {
        const x = row.positions[String(positionWindow)] ?? null,
          y = row.returns[String(momentumWindow)] ?? null;
        return {
          symbol: row.symbol,
          name: row.name,
          available: x != null && y != null,
          date: row.date,
          x,
          y,
        };
      }),
    [rows, positionWindow, momentumWindow],
  );
  useEffect(() => {
    try {
      sessionStorage.setItem(
        storageKey,
        JSON.stringify({ draft, submitted, task }),
      );
    } catch {
      /* 当前筛选仍可正常运行。 */
    }
  }, [draft, submitted, task]);
  useEffect(() => {
    if (result && !query.isFetching) {
      const retained =
        sortedRows.find((row) => row.symbol === explicitSelection.current) ??
        sortedChanges.find((row) => row.symbol === explicitSelection.current);
      const next = retained ?? sortedRows[0] ?? sortedChanges[0];
      if (!retained) explicitSelection.current = null;
      setSelectedSymbol(next?.symbol ?? null);
      const currentIndex = next
        ? sortedRows.findIndex((row) => row.symbol === next.symbol)
        : -1;
      if (next && currentIndex < 0) {
        setListMode("changes");
        setView("table");
        setChangeFilter("all");
      }
      setPage(
        next
          ? Math.floor(
              (currentIndex >= 0
                ? currentIndex
                : sortedChanges.findIndex(
                    (row) => row.symbol === next.symbol,
                  )) / 10,
            )
          : 0,
      );
      setBounds(null);
      if (window.innerWidth > 700) window.scrollTo(0, 0);
    }
  }, [result, query.isFetching, sortedRows, sortedChanges]);
  const update = <K extends keyof ScreenerDraft>(
    key: K,
    value: ScreenerDraft[K],
  ) => setDraft((previous) => ({ ...previous, [key]: value }));
  const selectTask = (value: TrendTask) => {
    setTask(value);
    update("conditions", taskConditions(value));
    setEditorOpen(true);
    setMobileDetail(false);
    setFeedback("");
  };
  const run = (next = screenDraftToQuery(draft)) => {
    // 明确执行始终读当前缓存；返回页面仍可复用未主动重跑的结果。
    void client.invalidateQueries({
      queryKey: ["trend-search", next],
      exact: true,
      refetchType: "none",
    });
    setSubmitted(next);
    setSearch("");
    setPage(0);
    setListMode("matches");
    setChangeFilter("all");
    setBounds(null);
    setEditorOpen(false);
    setMobileDetail(false);
    setFeedback("");
    window.scrollTo(0, 0);
    if (JSON.stringify(next) === JSON.stringify(submitted))
      void query.refetch();
  };
  const browse = () => {
    const next = {
      ...screenDraftToQuery({ ...draft, conditions: [] }),
      reference: null,
    };
    setDraft(screenQueryToDraft(next));
    setTask(null);
    run(next);
  };
  const pick = (symbol: string) => {
    explicitSelection.current = symbol;
    setSelectedSymbol(symbol);
    setMobileDetail(true);
    if (window.innerWidth <= 700) window.scrollTo(0, 0);
  };
  const openHistory = () => {
    if (result && result.query.conditions?.length)
      navigate("/studies/new", {
        state: {
          query: historicalQuery(result, summary(result.query).slice(0, 120)),
        },
      });
  };
  const loadSaved = (item: SavedTrendSearch) => {
    setDraft(screenQueryToDraft(item.query));
    setTask(null);
    setEditorOpen(true);
    setMobileDetail(false);
    setFeedback(`已载入「${item.title}」，点击开始筛选查看当前匹配。`);
  };
  const shape = (row: TrendSearchRow) => {
    if (!result) return;
    setTask(null);
    setDraft({
      ...screenQueryToDraft(result.query),
      conditions: [
        {
          id: 1,
          field: "shape_distance",
          operator: "lte",
          value: "",
          window: "20",
        },
      ],
      referenceSymbol: row.symbol,
      referenceDate: row.date,
    });
    setEditorOpen(true);
    setMobileDetail(false);
    if (window.innerWidth <= 700) window.scrollTo(0, 0);
    setFeedback(
      "已选定参照。填写最大均方根距离后筛选当前形态，不会自动运行历史研究。",
    );
  };
  const changeBounds = (value: MapBounds | null) => {
    setBounds(value);
    if (value)
      setRangeDraft(
        Object.fromEntries(
          Object.entries(value).map(([key, number]) => [key, String(number)]),
        ) as typeof rangeDraft,
      );
  };
  const boundsValid =
    Object.values(rangeDraft).every(
      (value) => value.trim() && Number.isFinite(Number(value)),
    ) &&
    Number(rangeDraft.xMin) >= 0 &&
    Number(rangeDraft.xMax) <= 100 &&
    Number(rangeDraft.xMin) < Number(rangeDraft.xMax) &&
    Number(rangeDraft.yMin) < Number(rangeDraft.yMax);
  const applyRegion = () => {
    if (!result || !bounds) return;
    const next: TrendSearchQuery = {
      ...result.query,
      as_of: result.as_of,
      conditions: [
        ...(result.query.conditions ?? []),
        {
          field: "position",
          window: positionWindow,
          operator: "gte",
          value: bounds.xMin,
        },
        {
          field: "position",
          window: positionWindow,
          operator: "lte",
          value: bounds.xMax,
        },
        {
          field: "return_pct",
          window: momentumWindow,
          operator: "gte",
          value: bounds.yMin,
        },
        {
          field: "return_pct",
          window: momentumWindow,
          operator: "lte",
          value: bounds.yMax,
        },
      ],
    };
    setDraft(screenQueryToDraft(next));
    setTask(null);
    setEditorOpen(true);
    setFeedback("框选已转成可见的位置与涨幅条件，确认后点击开始筛选。");
  };
  const scopeError =
    comparisonInputError(draft) ||
    (draft.universe === "codes" &&
      (!parseCodes(draft.codes).length ||
        parseCodes(draft.codes).some((code) => !/^\d{6}$/.test(code))));
  return (
    <div
      className={`screener-page${mobileDetail && selected ? " screener-page--detail" : ""}`}
    >
      <header className="screener-heading">
        <h1>筛出你要找的走势</h1>
        <p>看整体方向、波段结构和当前阶段，再核对每一段的价格证据。</p>
        <div className="trend-task-tabs" role="group" aria-label="趋势问题">
          {Object.entries(TREND_TASKS).map(([value, label]) => (
            <button
              type="button"
              key={value}
              disabled={query.isFetching}
              aria-pressed={task === value}
              onClick={() => selectTask(value as TrendTask)}
            >
              {label}
            </button>
          ))}
          <button
            type="button"
            disabled={query.isFetching}
            onClick={() => {
              setTask(null);
              setDraft({
                ...draft,
                conditions: [
                  {
                    id: 1,
                    field: "shape_distance",
                    operator: "lte",
                    value: "",
                    window: "",
                  },
                ],
              });
              setEditorOpen(true);
              setMobileDetail(false);
            }}
            aria-pressed={draft.conditions.some(
              (item) => item.field === "shape_distance",
            )}
          >
            形态检索
          </button>
        </div>
      </header>
      <button
        className="mobile-filter-toggle"
        type="button"
        aria-expanded={editorOpen}
        onClick={() => {
          setEditorOpen(!editorOpen);
          setMobileDetail(false);
        }}
      >
        <Filter size={16} />
        筛选条件（{draft.conditions.length}）
        <span>{editorOpen ? "收起" : "编辑条件"}</span>
      </button>
      <div className="screener-layout">
        <aside className={`screener-editor${editorOpen ? " is-open" : ""}`}>
          <div className="screen-editor-scroll">
            <form
              id="trend-filter-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (!validation && !query.isFetching) run();
              }}
            >
              <fieldset disabled={query.isFetching}>
                <label>
                  筛选范围
                  <select
                    value={draft.universe}
                    onChange={(e) => {
                      update(
                        "universe",
                        e.target.value as ScreenerDraft["universe"],
                      );
                      update("industries", []);
                    }}
                  >
                    {Object.entries(UNIVERSE_LABELS).map(([value, label]) => (
                      <option value={value} key={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {draft.universe === "codes" ? (
                  <label>
                    股票代码
                    <textarea
                      value={draft.codes}
                      onChange={(e) => update("codes", e.target.value)}
                      placeholder="填写6位代码，多个代码用逗号分隔"
                      rows={2}
                    />
                  </label>
                ) : draft.universe === "personal" ? (
                  <Link className="small-link" to="/data">
                    管理个人池 <ArrowRight size={13} />
                  </Link>
                ) : null}
                <label>
                  截止日期
                  <input
                    type="date"
                    aria-label="截止日期"
                    value={draft.asOf}
                    onChange={(e) => update("asOf", e.target.value)}
                  />
                  <small>留空使用最近完整交易日</small>
                </label>
                <label className="comparison-setting">
                  两日对比
                  <select
                    aria-label="两日对比"
                    value={draft.compareMode}
                    onChange={(e) =>
                      update(
                        "compareMode",
                        e.target.value as ScreenerDraft["compareMode"],
                      )
                    }
                  >
                    <option value="none">不对比</option>
                    <option value="previous_session">与上一交易日对比</option>
                    <option value="date">指定对照日期</option>
                  </select>
                  <small>看哪些新出现、持续匹配或已退出</small>
                </label>
                {draft.compareMode === "date" ? (
                  <label>
                    对照日期
                    <input
                      type="date"
                      value={draft.compareDate}
                      max={draft.asOf || undefined}
                      onChange={(e) => update("compareDate", e.target.value)}
                    />
                  </label>
                ) : null}
                <TrendConditionBuilder
                  conditions={draft.conditions}
                  onChange={(items) => update("conditions", items)}
                />
                {draft.conditions.some((item) => item.field && SWING_FIELDS.has(item.field)) ? (
                  <SwingSettings value={draft.swingReversal} onChange={(value) => update("swingReversal", value)} />
                ) : null}
                {draft.conditions.some(
                  (item) => item.field === "shape_distance",
                ) ? (
                  <div className="trend-reference">
                    <label>
                      参照股票
                      <input
                        value={draft.referenceSymbol}
                        maxLength={6}
                        placeholder="6位股票代码"
                        onChange={(e) =>
                          update("referenceSymbol", e.target.value)
                        }
                      />
                    </label>
                    <label>
                      参照截止日
                      <input
                        type="date"
                        value={draft.referenceDate}
                        onChange={(e) =>
                          update("referenceDate", e.target.value)
                        }
                      />
                    </label>
                    <p className="field-hint">
                      相似度采用归一收盘的均方根距离，不代表后续走势相同。
                    </p>
                  </div>
                ) : null}
                <label>
                  行业
                  <input
                    list="trend-industry-options"
                    aria-label="筛选行业"
                    value={draft.industries.join("、")}
                    placeholder="全部行业"
                    onChange={(e) =>
                      update(
                        "industries",
                        e.target.value
                          .split(/[、,，]/)
                          .map((name) => name.trim())
                          .filter(Boolean),
                      )
                    }
                  />
                  <datalist id="trend-industry-options">
                    {result?.industries.map((industry) => (
                      <option key={industry.name} value={industry.name}>
                        {industry.total}只
                      </option>
                    ))}
                  </datalist>
                  <small>行业归属按当前股票池；多个行业用顿号分隔</small>
                </label>
              </fieldset>
            </form>
            {saveOpen ? (
              <form
                className="save-screen-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (saveTitle.trim()) save.mutate();
                }}
              >
                <label>
                  筛选名称
                  <input
                    autoFocus
                    value={saveTitle}
                    maxLength={120}
                    onChange={(e) => setSaveTitle(e.target.value)}
                    placeholder="给自己的条件命名"
                  />
                </label>
                <div className="button-row">
                  <Button
                    type="submit"
                    disabled={!saveTitle.trim() || save.isPending}
                  >
                    确认保存
                  </Button>
                  <Button
                    variant="ghost"
                    type="button"
                    onClick={() => setSaveOpen(false)}
                  >
                    取消
                  </Button>
                </div>
              </form>
            ) : null}
            {save.error || remove.error || saved.error ? (
              <Notice error>
                {errorMessage(save.error || remove.error || saved.error)}
              </Notice>
            ) : null}
            <section className="saved-trends">
              <h3>已存筛选</h3>
              {saved.data?.length ? (
                saved.data.map((item) => (
                  <div key={item.id}>
                    <button
                      type="button"
                      className="saved-trend-name"
                      disabled={query.isFetching}
                      onClick={() => loadSaved(item)}
                    >
                      {item.title}
                      <small>{item.query.as_of ?? "最近完整交易日"}</small>
                    </button>
                    <button
                      className="icon-button"
                      type="button"
                      aria-label={`删除筛选 ${item.title}`}
                      disabled={remove.isPending}
                      onClick={() => {
                        if (window.confirm(`删除已存筛选「${item.title}」？`))
                          remove.mutate(item.id);
                      }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))
              ) : (
                <p>保存你常用的条件，下次直接载入。</p>
              )}
            </section>
            <Link to="/data" className="small-link">
              行情与数据更新 <ArrowRight size={13} />
            </Link>
          </div>
          <div className="screen-filter-actions">
            <Button
              type="submit"
              form="trend-filter-form"
              className="screen-submit"
              disabled={Boolean(validation) || query.isFetching}
            >
              {query.isFetching ? "正在筛选" : "开始筛选"}
              <ArrowRight size={15} />
            </Button>
            <Button
              variant="secondary"
              type="button"
              disabled={Boolean(validation) || query.isFetching}
              onClick={() => {
                setSaveOpen(!saveOpen);
                setSaveTitle("");
              }}
            >
              <Bookmark size={15} />
              保存筛选
            </Button>
            {validation ? (
              <p className="field-hint">{validation}</p>
            ) : (
              <p className="field-hint">只查当前匹配，不计算历史或保存研究。</p>
            )}
          </div>
        </aside>
        <section className="screener-results">
          {feedback ? <Notice>{feedback}</Notice> : null}
          {query.error ? (
            <Notice error>
              {errorMessage(query.error)}
              <Button variant="ghost" onClick={() => void query.refetch()}>
                重试
              </Button>
            </Notice>
          ) : null}
          {query.isFetching && result ? (
            <Loading>
              {result
                ? `正在筛选新的条件；下方仍是 ${result.as_of} 的上次结果。`
                : "正在读取同一截止日的日线并核对条件，不计算历史样本。"}
            </Loading>
          ) : null}
          {!result && query.isFetching && submitted ? (
            <div className="screener-pending">
              <h2>{summary(submitted)}</h2>
              <p>
                {UNIVERSE_LABELS[submitted.universe]}
                {submitted.universe === "codes"
                  ? ` · ${submitted.codes?.length ?? 0} 只股票`
                  : ""}
                {submitted.industries?.length
                  ? ` · ${submitted.industries.join("、")}`
                  : ""}{" "}
                · {submitted.as_of ?? "最近完整交易日"}
              </p>
              <Loading>正在读取日线并核对当前条件，不计算历史样本。</Loading>
            </div>
          ) : !result ? (
            <div className="screener-start">
              <div className="empty-trend-icon">
                <SlidersHorizontal size={42} strokeWidth={1.4} />
              </div>
              <h2>先说清楚，你在找什么走势</h2>
              <p>
                选择上方的趋势问题，填写天数与比较关系。
                <br />
                结果会告诉你哪些股票满足，以及每一项条件的依据。
              </p>
              <div className="screen-start-steps">
                <span>
                  <b>1</b>定义条件
                </span>
                <span>
                  <b>2</b>查看当前匹配
                </span>
                <span>
                  <b>3</b>按需核对历史
                </span>
              </div>
              <Button
                variant="secondary"
                onClick={browse}
                disabled={Boolean(scopeError) || query.isFetching}
              >
                先浏览全部股票池
              </Button>
              <small>无预置条件，按股票代码排列。</small>
            </div>
          ) : (
            <div
              className="screen-result-body"
              aria-busy={query.isFetching}
              inert={query.isFetching}
            >
              <header className="screen-result-heading">
                <h2>{summary(result.query)}</h2>
                <span className="result-data-date">数据日 {result.as_of}</span>
              </header>
              <div className="screen-coverage">
                <span>
                  范围 <b>{number(result.coverage.total, 0)}</b>
                </span>
                <span>
                  可判定 <b>{number(result.coverage.evaluated, 0)}</b>
                </span>
                <button
                  type="button"
                  className={listMode === "matches" ? "active" : ""}
                  onClick={() => {
                    setListMode("matches");
                    setPage(0);
                  }}
                >
                  匹配 <b>{number(result.coverage.matched, 0)}</b>
                </button>
                <button
                  type="button"
                  className={listMode === "missing" ? "active" : ""}
                  onClick={() => {
                    setListMode("missing");
                    setPage(0);
                  }}
                >
                  缺口 <b>{number(result.coverage.missing, 0)}</b>
                </button>
              </div>
              {result.comparison ? (
                <ComparisonSummary
                  comparison={result.comparison}
                  currentDate={result.as_of}
                  active={listMode === "changes" ? changeFilter : null}
                  onSelect={openChanges}
                />
              ) : null}
              {dirty && !query.isFetching ? (
                <p className="result-stale-note">
                  条件已修改，点击开始筛选后更新结果。
                </p>
              ) : null}
              {result.common_data_date &&
              result.common_data_date !== result.as_of ? (
                <div className="local-data-date">
                  <p>
                    本地主要数据截至 <strong>{result.common_data_date}</strong>
                    （{result.common_data_count} 只）。当前请求仍按{" "}
                    {result.as_of} 判断。
                  </p>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      const next = {
                        ...result.query,
                        as_of: result.common_data_date,
                      };
                      setDraft(screenQueryToDraft(next));
                      run(next);
                    }}
                  >
                    查看这一天
                  </Button>
                  <Link className="small-link" to="/data">
                    更新数据
                  </Link>
                </div>
              ) : null}
              <div className="screen-result-toolbar">
                <div
                  className="screen-view-switch"
                  role="group"
                  aria-label="结果视图"
                >
                  <button
                    type="button"
                    aria-pressed={view === "table" && listMode !== "changes"}
                    onClick={() => {
                      setView("table");
                      setListMode("matches");
                      setPage(0);
                    }}
                  >
                    <List size={16} />
                    表格
                  </button>
                  <button
                    type="button"
                    aria-pressed={view === "map" && listMode === "matches"}
                    onClick={() => {
                      setView("map");
                      setListMode("matches");
                    }}
                  >
                    <MapPin size={16} />
                    地图
                  </button>
                  {result.comparison ? (
                    <button
                      type="button"
                      aria-pressed={listMode === "changes"}
                      onClick={() => openChanges("all")}
                    >
                      变化明细
                    </button>
                  ) : null}
                </div>
                <label className="search-field">
                  <Search size={15} />
                  <input
                    aria-label="搜索筛选结果"
                    placeholder="搜索代码或名称"
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value);
                      setPage(0);
                    }}
                  />
                </label>
              </div>
              {selected &&
              (listMode === "missing" ||
                !(
                  view === "map" && listMode === "matches"
                    ? rows
                    : listedItems.slice(page * 10, (page + 1) * 10)
                ).some((row) => row.symbol === selected.symbol)) ? (
                <div className="screen-retained-selection">
                  <span>
                    详情保留：{selected.name} {selected.symbol}
                    （不在当前显示范围）
                  </span>
                  <button
                    type="button"
                    className="small-link"
                    onClick={() => {
                      setSearch("");
                      setView("table");
                      const inChanges = Boolean(
                        selectedChange &&
                          (listMode === "changes" || !selectedRow),
                      );
                      setListMode(inChanges ? "changes" : "matches");
                      setChangeFilter("all");
                      const ordered = inChanges ? sortedChanges : sortedRows;
                      setPage(
                        Math.floor(
                          ordered.findIndex(
                            (row) => row.symbol === selected.symbol,
                          ) / 10,
                        ),
                      );
                    }}
                  >
                    定位此行
                  </button>
                </div>
              ) : null}
              {listMode === "changes" && result.comparison ? (
                <TrendChangesTable
                  rows={changeRows.slice(page * 10, (page + 1) * 10)}
                  currentDate={result.as_of}
                  previousDate={result.comparison.as_of}
                  selected={selectedSymbol}
                  onSelect={pick}
                />
              ) : view === "map" && listMode === "matches" ? (
                <div className="screen-map">
                  <div className="screen-map-axes">
                    <label>
                      横轴位置
                      <select
                        value={positionWindow}
                        onChange={(e) => {
                          setPositionWindow(Number(e.target.value));
                          setBounds(null);
                        }}
                      >
                        {[30, 60, 180].map((period) => (
                          <option value={period} key={period}>
                            {period}日位置
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      纵轴涨跌
                      <select
                        value={momentumWindow}
                        onChange={(e) => {
                          setMomentumWindow(Number(e.target.value));
                          setBounds(null);
                        }}
                      >
                        {[5, 20, 60].map((period) => (
                          <option value={period} key={period}>
                            {period}日涨跌
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="small-link"
                      onClick={() => setBoundsOpen(!boundsOpen)}
                    >
                      输入框选范围
                    </button>
                  </div>
                  <TrendScatter
                    rows={mapRows}
                    selected={
                      mapRows.find((row) => row.symbol === selectedSymbol) ??
                      null
                    }
                    positionWindow={positionWindow}
                    momentumWindow={momentumWindow}
                    bounds={bounds}
                    onBounds={changeBounds}
                    onSelect={(row) => pick(row.symbol)}
                  />
                  <p className="field-hint">
                    同一批匹配：{rows.length}只，当前坐标可绘制
                    {mapRows.filter((row) => row.available).length}
                    只。坐标缺失不会改变筛选结果。
                  </p>
                  {boundsOpen ? (
                    <form
                      className="screen-map-bounds"
                      onSubmit={(e) => {
                        e.preventDefault();
                        if (boundsValid)
                          changeBounds({
                            xMin: Number(rangeDraft.xMin),
                            xMax: Number(rangeDraft.xMax),
                            yMin: Number(rangeDraft.yMin),
                            yMax: Number(rangeDraft.yMax),
                          });
                      }}
                    >
                      {(
                        [
                          ["xMin", "位置下限"],
                          ["xMax", "位置上限"],
                          ["yMin", "涨跌下限"],
                          ["yMax", "涨跌上限"],
                        ] as const
                      ).map(([field, label]) => (
                        <label key={field}>
                          {label}
                          <input
                            type="number"
                            step="any"
                            value={rangeDraft[field]}
                            onChange={(e) =>
                              setRangeDraft({
                                ...rangeDraft,
                                [field]: e.target.value,
                              })
                            }
                          />
                        </label>
                      ))}
                      <Button type="submit" disabled={!boundsValid}>
                        应用范围
                      </Button>
                    </form>
                  ) : null}
                  {bounds ? (
                    <div className="screen-region">
                      <p>
                        {positionWindow}日位置 {bounds.xMin}%–{bounds.xMax}% ·{" "}
                        {momentumWindow}日涨跌 {bounds.yMin}%–{bounds.yMax}%
                      </p>
                      <Button
                        variant="secondary"
                        disabled={(result.query.conditions?.length ?? 0) > 8}
                        onClick={applyRegion}
                      >
                        把框选加入筛选条件
                      </Button>
                    </div>
                  ) : null}
                </div>
              ) : listMode === "missing" ? (
                <div className="table-scroll">
                  <table className="trend-result-table">
                    <thead>
                      <tr>
                        <th>股票</th>
                        <th>无法判定的原因</th>
                      </tr>
                    </thead>
                    <tbody>
                      {missingRows
                        .slice(page * 10, (page + 1) * 10)
                        .map((row) => (
                          <tr key={row.symbol}>
                            <td>
                              <strong>{row.name}</strong>
                              <small>{row.symbol}</small>
                            </td>
                            <td>{row.reason}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  {!missingRows.length ? (
                    <Empty title="当前范围没有数据缺口" />
                  ) : null}
                </div>
              ) : rows.length ? (
                <div className="table-scroll">
                  <table className="trend-result-table">
                    <thead>
                      <tr>
                        <th>股票</th>
                        <th>{swingWindows.length ? "波段结构 / 阶段" : "当前连续段"}</th>
                        <th>{swingWindows.length ? "当日涨跌" : "本段变化"}</th>
                        <th>30日位置</th>
                        <th>60日位置</th>
                        <th>180日位置</th>
                        <th>近20日走势</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.slice(page * 10, (page + 1) * 10).map((row) => (
                        <tr
                          key={row.symbol}
                          className={
                            selectedSymbol === row.symbol ? "selected" : ""
                          }
                          onClick={() => pick(row.symbol)}
                        >
                          <td>
                            <button
                              type="button"
                              className="stock-button"
                              aria-label={`查看 ${row.name} ${row.symbol}`}
                              onClick={() => pick(row.symbol)}
                            >
                              <small>{row.symbol}</small>
                              <strong>{row.name}</strong>
                            </button>
                          </td>
                          <td>
                            <span className="segment-tag">
                              {swingWindows.length ? swingWindows.map((window) => <span className="swing-row-fact" key={window}>
                                <small>{window} 日 · 已确认点关系</small>
                                {fieldValue("swing_structure", row.values[`swing_structure.${window}`])}
                                <small>{fieldValue("swing_direction", row.values[`swing_direction.${window}`])} · {fieldValue("swing_count", row.values[`swing_count.${window}`])}</small>
                              </span>) : segmentLabel(row)}
                            </span>
                          </td>
                          <td
                            className={
                              (swingWindows.length ? row.change_pct ?? 0 : row.current_segment?.return_pct ?? 0) >= 0
                                ? "value-up"
                                : "value-down"
                            }
                          >
                            {percent(swingWindows.length ? row.change_pct : row.current_segment?.return_pct, 2)}
                          </td>
                          {[30, 60, 180].map((period) => (
                            <td key={period}>
                              {percent(row.positions[String(period)], 0)}
                            </td>
                          ))}
                          <td>
                            <PriceSparkline points={row.sparkline} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty
                  title={
                    !result.coverage.total
                      ? "当前范围没有股票"
                      : !result.coverage.evaluated
                        ? "这个截止日暂无可判断的行情"
                        : search
                          ? "没有符合名称搜索的结果"
                          : "可判断的股票中没有匹配"
                  }
                >
                  <p>可核对数据缺口、调整条件或明确选择另一个数据日。</p>
                </Empty>
              )}
              {(view === "table" || listMode !== "matches") &&
              listedItems.length > 10 ? (
                <div className="pagination">
                  <span>共 {listedItems.length} 条 · 每页 10 条</span>
                  <Button
                    variant="ghost"
                    disabled={!page}
                    onClick={() => setPage(page - 1)}
                  >
                    <ChevronLeft size={14} />
                    上一页
                  </Button>
                  <strong>{page + 1}</strong>
                  <Button
                    variant="ghost"
                    disabled={(page + 1) * 10 >= listedItems.length}
                    onClick={() => setPage(page + 1)}
                  >
                    下一页
                    <ChevronRight size={14} />
                  </Button>
                </div>
              ) : null}
              <div className="screen-history-action">
                <Button
                  variant="secondary"
                  disabled={
                    !result.query.conditions?.length ||
                    !result.scope_codes.length
                  }
                  onClick={openHistory}
                >
                  核对历史 / 保存研究 <ArrowRight size={14} />
                </Button>
                <p>先确认历史范围与观察窗口，再运行并保存研究。</p>
              </div>
              {result.warnings.length ? (
                <details className="screen-warnings">
                  <summary>数据说明（{result.warnings.length}）</summary>
                  {result.warnings.map((warning) => (
                    <p key={warning}>{warning}</p>
                  ))}
                </details>
              ) : null}
              <p className="screen-disclaimer">
                工具仅返回符合您设置规则的股票数据，不构成任何形式的推荐或建议。
              </p>
            </div>
          )}
        </section>
        {selected && result ? (
          <div className="trend-detail-holder" inert={query.isFetching}>
            <TrendStockDetail
              key={`${selected.symbol}-${result.as_of}-${result.comparison?.as_of ?? ""}`}
              selection={selected}
              row={selectedRow}
              comparison={selectedChange}
              comparisonDate={result.comparison?.as_of}
              currentDate={result.as_of}
              revision={query.dataUpdatedAt}
              query={{ ...result.query, as_of: result.as_of }}
              busy={query.isFetching}
              onBack={() => setMobileDetail(false)}
              onHistory={openHistory}
              onShape={shape}
            />
          </div>
        ) : (
          <aside className="trend-detail-empty">
            <Grid2X2 size={34} strokeWidth={1.3} />
            <h3>让每个结果都有依据</h3>
            <p>选择一只股票，核对真实日线、连续段与每项条件。</p>
          </aside>
        )}
      </div>
    </div>
  );
}
