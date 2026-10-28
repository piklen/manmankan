import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  ListFilter,
  Search,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  type StudyCondition,
  type StudyEvidence,
  type StudyQuery,
  type TrendMapQuery,
  type TrendMapRow,
  type WorkspaceJob,
} from "../api/client";
import {
  TrendScatter,
  inBounds,
  type MapBounds,
} from "../components/TrendScatter";
import { StudyChart } from "../components/StudyChart";
import { Button, Empty, Loading, Notice } from "../components/ui";
import { errorMessage, number, percent } from "../lib/format";
import { parseCodes, UNIVERSE_LABELS } from "../lib/study";

const defaultMapQuery = (): TrendMapQuery => ({
  universe: "all",
  codes: [],
  as_of: null,
  position_window: 180,
  momentum_window: 20,
  trail_days: 5,
});
function rememberedQuery(): TrendMapQuery {
  try {
    const query = JSON.parse(
      sessionStorage.getItem("manmankan.map-query.v2") ?? "null",
    );
    if (
      query &&
      ["all", "personal", "codes"].includes(query.universe) &&
      Array.isArray(query.codes) &&
      Number.isFinite(query.position_window) &&
      Number.isFinite(query.momentum_window)
    )
      return query;
  } catch {
    /* 工作区可从默认坐标重新打开。 */
  }
  return defaultMapQuery();
}
const sourceLabels: Record<string, string> = {
  tushare_market_batch: "TuShare 日线",
  tushare: "TuShare",
  baostock: "Baostock",
  akshare: "AkShare",
  local_cache: "本地行情缓存",
};
const terminal = (job: WorkspaceJob | undefined) =>
  job && !["queued", "running"].includes(job.status);

export function TrendMapPage() {
  const navigate = useNavigate(),
    client = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState<TrendMapQuery>(() => {
    const initial = rememberedQuery();
    const position = Number(searchParams.get("position")),
      momentum = Number(searchParams.get("momentum"));
    return {
      ...initial,
      position_window: [30, 60, 180].includes(position)
        ? position
        : initial.position_window,
      momentum_window: [5, 20, 60].includes(momentum)
        ? momentum
        : initial.momentum_window,
    };
  });
  const [codesInput, setCodesInput] = useState(() =>
    (query.codes ?? []).join(", "),
  );
  const [industry, setIndustry] = useState("");
  const [industrySearch, setIndustrySearch] = useState("");
  const [search, setSearch] = useState("");
  const [symbol, setSymbol] = useState<string | null>(null);
  const [bounds, setBounds] = useState<MapBounds | null>(null);
  const [showBounds, setShowBounds] = useState(false);
  const [rangeDraft, setRangeDraft] = useState({
    xMin: "",
    xMax: "",
    yMin: "",
    yMax: "",
  });
  const [page, setPage] = useState(0);
  const [tableMode, setTableMode] = useState<"available" | "all" | "missing">(
    "available",
  );
  const [shapeOpen, setShapeOpen] = useState(false);
  const [shapeWindow, setShapeWindow] = useState("20");
  const [shapeDistance, setShapeDistance] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const validQuery =
    query.universe !== "codes" ||
    ((query.codes ?? []).length > 0 &&
      (query.codes ?? []).every((code) => /^\d{6}$/.test(code)));
  const requestQuery = { ...query, position_window: 180, momentum_window: 20 };
  const map = useQuery({
    queryKey: ["trend-map", requestQuery],
    queryFn: () => api.trendMap(requestQuery),
    enabled: validQuery,
    staleTime: Infinity,
    placeholderData: (previous) => previous,
    retry: false,
  });
  const activeQuery = {
    ...(map.data?.query ?? query),
    position_window: query.position_window,
    momentum_window: query.momentum_window,
  };
  const activeView =
    map.data?.views.find(
      (view) =>
        view.position_window === query.position_window &&
        view.momentum_window === query.momentum_window,
    ) ?? map.data;
  const rows = useMemo(
    () =>
      (map.data?.rows ?? []).map((row) => {
        const x = row.positions?.[String(query.position_window)] ?? null;
        const y = row.returns?.[String(query.momentum_window)] ?? null;
        const available =
          x != null && y != null && row.data_cutoff === map.data?.as_of;
        return {
          ...row,
          x,
          y,
          available,
          reason: available
            ? null
            : row.data_cutoff !== map.data?.as_of
              ? "截止日缺行情"
              : "所选窗口行情不完整",
          trail: (row.trail ?? []).map((point) => ({
            ...point,
            x: point.positions[String(query.position_window)] ?? null,
            y: point.returns[String(query.momentum_window)] ?? null,
          })),
        };
      }),
    [map.data, query.position_window, query.momentum_window],
  );
  const selected = rows.find((row) => row.symbol === symbol) ?? null;
  const industryRows = industry
    ? rows.filter((row) => (row.industry || "未分类") === industry)
    : rows;
  const scopedRows = industryRows.filter(
    (row) =>
      (!bounds || inBounds(row, bounds)) &&
      (!search.trim() ||
        `${row.name} ${row.symbol}`
          .toLowerCase()
          .includes(search.trim().toLowerCase())),
  );
  const tableRows = scopedRows.filter(
    (row) =>
      tableMode === "all" ||
      (tableMode === "available" ? row.available : !row.available),
  );
  const chartRows = industryRows.filter(
    (row) =>
      !search.trim() ||
      `${row.name} ${row.symbol}`
        .toLowerCase()
        .includes(search.trim().toLowerCase()),
  );
  const stock = useQuery({
    queryKey: ["trend-stock", selected?.symbol, map.data?.as_of],
    queryFn: () => api.trendStock(selected!.symbol, map.data!.as_of, 120),
    enabled: Boolean(selected && map.data),
    retry: false,
  });
  const refresh = useMutation({
    mutationFn: () =>
      api.refreshStudyData({
        universe: query.universe,
        codes: query.codes ?? [],
        days: Math.max(360, query.position_window + query.trail_days + 1),
      }),
    onSuccess: (job) => setJobId(job.job_id),
  });
  const job = useQuery({
    queryKey: ["map-refresh-job", jobId],
    queryFn: () => api.job(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (state) => (terminal(state.state.data) ? false : 1200),
    retry: false,
  });
  const refreshing =
    refresh.isPending || Boolean(jobId && !terminal(job.data) && !job.error);
  useEffect(() => {
    if (terminal(job.data))
      void client.invalidateQueries({ queryKey: ["trend-map"] });
  }, [job.data?.status, job.data?.job_id, client]);
  useEffect(() => {
    if (
      searchParams.get("position") !== String(query.position_window) ||
      searchParams.get("momentum") !== String(query.momentum_window)
    ) {
      setSearchParams(
        {
          position: String(query.position_window),
          momentum: String(query.momentum_window),
        },
        { replace: true },
      );
    }
  }, [query.position_window, query.momentum_window]);
  useEffect(() => {
    try {
      sessionStorage.setItem("manmankan.map-query.v2", JSON.stringify(query));
    } catch {
      /* 不影响当前地图。 */
    }
  }, [query]);
  const changeQuery = (changes: Partial<TrendMapQuery>) => {
    setQuery({ ...query, ...changes });
    setBounds(null);
    setPage(0);
    setIndustry("");
  };
  const changeBounds = (value: MapBounds | null) => {
    setBounds(value);
    setPage(0);
    setTableMode("available");
    if (value)
      setRangeDraft({
        xMin: String(value.xMin),
        xMax: String(value.xMax),
        yMin: String(value.yMin),
        yMax: String(value.yMax),
      });
  };
  const pick = (row: TrendMapRow) => {
    setSymbol(row.symbol);
    setShapeOpen(false);
  };
  const boundsValid =
    Object.values(rangeDraft).every(
      (value) => value.trim() && Number.isFinite(Number(value)),
    ) &&
    Number(rangeDraft.xMin) >= 0 &&
    Number(rangeDraft.xMax) <= 100 &&
    Number(rangeDraft.xMin) < Number(rangeDraft.xMax) &&
    Number(rangeDraft.yMin) < Number(rangeDraft.yMax);
  const studyScope = (): Pick<StudyQuery, "universe" | "codes"> =>
    industry || search.trim()
      ? { universe: "codes", codes: chartRows.map((row) => row.symbol) }
      : {
          universe: activeQuery.universe,
          codes:
            activeQuery.universe === "codes" ? (activeQuery.codes ?? []) : [],
        };
  const openStudy = (
    conditions: StudyCondition[],
    title: string,
    reference: StudyQuery["reference"] = null,
    scope = studyScope(),
    autoRun = true,
  ) => {
    const studyQuery: StudyQuery = {
      title,
      ...scope,
      lookback_days: 120,
      as_of: map.data?.as_of ?? query.as_of ?? null,
      forward_days: 5,
      sample_policy: "first",
      conditions,
      reference,
    };
    navigate("/studies/new", { state: { query: studyQuery, autoRun } });
  };
  const validateBounds = () => {
    if (!bounds) return;
    openStudy(
      [
        {
          field: "position",
          window: activeQuery.position_window,
          operator: "gte",
          value: bounds.xMin,
        },
        {
          field: "position",
          window: activeQuery.position_window,
          operator: "lte",
          value: bounds.xMax,
        },
        {
          field: "return_pct",
          window: activeQuery.momentum_window,
          operator: "gte",
          value: bounds.yMin,
        },
        {
          field: "return_pct",
          window: activeQuery.momentum_window,
          operator: "lte",
          value: bounds.yMax,
        },
      ],
      `${industry ? `${industry} · ` : ""}${activeQuery.position_window}日位置与${activeQuery.momentum_window}日变化`,
    );
  };
  const shapeValid = Boolean(
    shapeDistance.trim() &&
      Number.isFinite(Number(shapeDistance)) &&
      Number(shapeDistance) >= 0 &&
      Number.isInteger(Number(shapeWindow)) &&
      Number(shapeWindow) >= 2 &&
      Number(shapeWindow) <= 360,
  );
  const industryItems = (activeView?.industries ?? []).filter((item) =>
    item.name.includes(industrySearch.trim()),
  );
  const stockEvidence: StudyEvidence | undefined = stock.data
    ? {
        run_id: "map",
        symbol: stock.data.symbol,
        name: stock.data.name,
        event_date: stock.data.as_of,
        source: stock.data.source,
        bars: stock.data.bars,
        conditions: [],
        outcome: null,
        warnings: [],
      }
    : undefined;
  return (
    <div className="map-page">
      <header className="map-page-heading">
        <h1>发现正在发生的变化</h1>
        <p>用同一张坐标图，看清位置、方向与行业分布。</p>
      </header>
      <div className="map-settings">
        <label>
          股票池
          <select
            value={query.universe}
            onChange={(event) =>
              changeQuery({
                universe: event.target.value as TrendMapQuery["universe"],
                codes: [],
              })
            }
          >
            {Object.entries(UNIVERSE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          区间位置
          <select
            value={query.position_window}
            onChange={(event) =>
              changeQuery({ position_window: Number(event.target.value) })
            }
          >
            {[30, 60, 180].map((days) => (
              <option value={days} key={days}>
                {days}日
              </option>
            ))}
          </select>
        </label>
        <label>
          区间涨跌
          <select
            value={query.momentum_window}
            onChange={(event) =>
              changeQuery({ momentum_window: Number(event.target.value) })
            }
          >
            {[5, 20, 60].map((days) => (
              <option value={days} key={days}>
                {days}日
              </option>
            ))}
          </select>
        </label>
        <label>
          数据截至
          <input
            type="date"
            aria-label="地图截止日期"
            value={query.as_of ?? ""}
            onChange={(event) =>
              changeQuery({ as_of: event.target.value || null })
            }
            title="留空使用最近完整交易日"
          />
        </label>
        <Button
          disabled={!validQuery || refreshing}
          onClick={() => refresh.mutate()}
        >
          {refreshing ? "正在更新" : "更新数据"}
        </Button>
        <div className="map-coverage">
          {map.data ? (
            <>
              已定位{" "}
              <strong>
                {activeView?.plotted.toLocaleString()} /{" "}
                {map.data.total.toLocaleString()}
              </strong>
              <span>
                {activeView?.missing} 只数据不完整 · {map.data.as_of}
              </span>
            </>
          ) : (
            <span>只使用已完成的日线</span>
          )}
        </div>
      </div>
      {query.universe === "codes" ? (
        <form
          className="map-codes-form"
          onSubmit={(event) => {
            event.preventDefault();
            changeQuery({ codes: parseCodes(codesInput) });
          }}
        >
          <label>
            明确的股票代码
            <input
              value={codesInput}
              onChange={(event) => setCodesInput(event.target.value)}
              placeholder="输入代码，用逗号分隔"
            />
          </label>
          <Button
            type="submit"
            variant="secondary"
            disabled={
              !parseCodes(codesInput).length ||
              parseCodes(codesInput).some((code) => !/^\d{6}$/.test(code))
            }
          >
            读取这组股票
          </Button>
        </form>
      ) : null}
      {query.universe === "personal" ? (
        <Link to="/data?tab=personal" className="map-personal-link">
          管理个人股票池
          <ArrowRight size={13} />
        </Link>
      ) : null}
      {refresh.error ? (
        <Notice error>{errorMessage(refresh.error)}</Notice>
      ) : null}
      {job.data ? (
        <Notice error={["failed", "interrupted"].includes(job.data.status)}>
          {job.data.message || job.data.status}
          {job.data.total ? ` · ${job.data.progress}/${job.data.total}` : ""}
          {job.data.error ? ` · ${job.data.error}` : ""}
          <Link to="/data">查看更新任务</Link>
        </Notice>
      ) : job.error ? (
        <Notice error>
          {errorMessage(job.error)}
          <Link to="/data">查看更新任务</Link>
        </Notice>
      ) : null}
      {map.isFetching && map.data ? (
        <div className="map-loading-note" role="status">
          <strong>正在加载 {query.as_of || "最近完整交易日"} 的地图</strong>
          当前保留 {map.data.as_of} 的旧图（{activeQuery.position_window}日位置
          × {activeQuery.momentum_window}日涨跌），暂不能操作；完成后自动替换。
        </div>
      ) : null}
      {map.isLoading ? (
        <Loading>正在定位股票的多周期坐标</Loading>
      ) : map.error ? (
        <div className="map-failure">
          <Notice error>{errorMessage(map.error)}</Notice>
          <p>检查数据范围与连接后重试。没有使用其他日期或演示行情代替。</p>
          <div className="button-row">
            <Button onClick={() => void map.refetch()}>重新读取</Button>
            <Link to="/data" className="button button--secondary">
              查看数据
            </Link>
          </div>
        </div>
      ) : !validQuery ? (
        <Empty title="选择你要观察的股票">
          <p>填写明确代码后读取坐标，或切换当前 A 股股票池。</p>
        </Empty>
      ) : map.data ? (
        <div
          className="map-layout"
          aria-busy={map.isFetching}
          inert={map.isFetching ? true : undefined}
        >
          <aside className="industry-panel">
            <div className="section-heading">
              <h2>行业分布</h2>
              <ListFilter size={16} />
            </div>
            <label className="search-field">
              <Search size={15} />
              <input
                value={industrySearch}
                onChange={(event) => setIndustrySearch(event.target.value)}
                placeholder="搜索行业"
                aria-label="搜索行业"
              />
            </label>
            <button
              type="button"
              className={`industry-all${!industry ? " active" : ""}`}
              onClick={() => {
                setIndustry("");
                setPage(0);
              }}
            >
              全部行业<span>{map.data.total}</span>
            </button>
            <p className="industry-key">
              近{activeQuery.momentum_window}日：
              <span className="value-up">上涨</span> /{" "}
              <span className="value-down">下跌</span> / 已定位
            </p>
            <div className="industry-list">
              {industryItems.map((item) => (
                <button
                  type="button"
                  className={`industry-row${industry === item.name ? " active" : ""}`}
                  key={item.name}
                  onClick={() => {
                    setIndustry(industry === item.name ? "" : item.name);
                    setPage(0);
                    setSearch("");
                    setSymbol(null);
                  }}
                >
                  <strong>{item.name}</strong>
                  <span>
                    {item.up} / {item.down} / {item.available}
                  </span>
                  <i>
                    <b
                      className="industry-up"
                      style={{
                        width: `${item.available ? (item.up / item.available) * 100 : 0}%`,
                      }}
                    />
                    <b
                      className="industry-down"
                      style={{
                        width: `${item.available ? (item.down / item.available) * 100 : 0}%`,
                      }}
                    />
                  </i>
                  <small>
                    {item.total - item.available
                      ? `缺失 ${item.total - item.available} / ${item.total}`
                      : `${item.available} / ${item.total} 已定位`}
                  </small>
                </button>
              ))}
            </div>
            {!industryItems.length ? (
              <p className="muted">没有匹配的行业。</p>
            ) : null}
          </aside>
          <section className="map-main">
            <TrendScatter
              rows={chartRows}
              selected={selected}
              positionWindow={activeQuery.position_window}
              momentumWindow={activeQuery.momentum_window}
              bounds={bounds}
              onBounds={changeBounds}
              onSelect={pick}
            />
            <div className="map-selection">
              <div>
                {bounds ? (
                  <>
                    <strong>
                      已圈选 {tableRows.filter((row) => row.available).length}{" "}
                      只
                    </strong>
                    <span>
                      {activeQuery.position_window}日位置 {bounds.xMin}%–
                      {bounds.xMax}% · {activeQuery.momentum_window}日涨跌{" "}
                      {bounds.yMin}%–{bounds.yMax}%
                    </span>
                  </>
                ) : (
                  <>
                    <strong>{industry || "全部行业"}</strong>
                    <span>点击个股看轨迹，框选区域再验证历史。</span>
                  </>
                )}
              </div>
              {bounds ? (
                <Button
                  onClick={validateBounds}
                  disabled={!chartRows.length || map.isFetching}
                >
                  验证这片区域
                  <ArrowRight size={14} />
                </Button>
              ) : null}
              <button
                type="button"
                className="range-toggle"
                onClick={() => setShowBounds(!showBounds)}
                aria-expanded={showBounds}
              >
                <SlidersHorizontal size={16} />
                输入范围
              </button>
            </div>
            {showBounds ? (
              <form
                className="numeric-bounds"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (boundsValid)
                    changeBounds({
                      xMin: Number(rangeDraft.xMin),
                      xMax: Number(rangeDraft.xMax),
                      yMin: Number(rangeDraft.yMin),
                      yMax: Number(rangeDraft.yMax),
                    });
                }}
              >
                <div>
                  <strong>{activeQuery.position_window}日位置 %</strong>
                  <label>
                    <span className="sr-only">位置下限</span>
                    <input
                      aria-label="位置下限"
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="下限"
                      value={rangeDraft.xMin}
                      onChange={(event) =>
                        setRangeDraft({
                          ...rangeDraft,
                          xMin: event.target.value,
                        })
                      }
                    />
                  </label>
                  <span>至</span>
                  <label>
                    <span className="sr-only">位置上限</span>
                    <input
                      aria-label="位置上限"
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="上限"
                      value={rangeDraft.xMax}
                      onChange={(event) =>
                        setRangeDraft({
                          ...rangeDraft,
                          xMax: event.target.value,
                        })
                      }
                    />
                  </label>
                </div>
                <div>
                  <strong>{activeQuery.momentum_window}日涨跌 %</strong>
                  <label>
                    <input
                      aria-label="涨跌下限"
                      type="number"
                      step="any"
                      placeholder="下限"
                      value={rangeDraft.yMin}
                      onChange={(event) =>
                        setRangeDraft({
                          ...rangeDraft,
                          yMin: event.target.value,
                        })
                      }
                    />
                  </label>
                  <span>至</span>
                  <label>
                    <input
                      aria-label="涨跌上限"
                      type="number"
                      step="any"
                      placeholder="上限"
                      value={rangeDraft.yMax}
                      onChange={(event) =>
                        setRangeDraft({
                          ...rangeDraft,
                          yMax: event.target.value,
                        })
                      }
                    />
                  </label>
                </div>
                <Button type="submit" disabled={!boundsValid}>
                  应用范围
                </Button>
              </form>
            ) : null}
            <div className="map-table-section">
              <div className="section-heading">
                <h2>
                  {bounds ? "所选区域" : industry || "股票列表"}
                  <span>{tableRows.length} 只</span>
                </h2>
                <label className="search-field">
                  <Search size={15} />
                  <input
                    aria-label="搜索股票名称或代码"
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value);
                      setPage(0);
                    }}
                    placeholder="搜索名称或代码"
                  />
                </label>
              </div>
              <div
                className="table-view-switch"
                role="group"
                aria-label="股票列表显示范围"
              >
                {(
                  [
                    [
                      "available",
                      "可定位",
                      scopedRows.filter((row) => row.available).length,
                    ],
                    ["all", "全部", scopedRows.length],
                    [
                      "missing",
                      "缺口",
                      scopedRows.filter((row) => !row.available).length,
                    ],
                  ] as const
                ).map(([value, label, count]) => (
                  <button
                    type="button"
                    key={value}
                    aria-pressed={tableMode === value}
                    onClick={() => {
                      setTableMode(value);
                      setPage(0);
                    }}
                  >
                    {label}
                    <span>{count}</span>
                  </button>
                ))}
                <small>仅切换列表展示，不改变研究股票池。</small>
              </div>
              {tableRows.length ? (
                <div className="table-scroll">
                  <table className="map-table">
                    <thead>
                      <tr>
                        <th>股票</th>
                        <th>30日位置</th>
                        <th>60日位置</th>
                        <th>180日位置</th>
                        <th>{activeQuery.momentum_window}日涨跌</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tableRows
                        .slice(page * 50, (page + 1) * 50)
                        .map((row) => (
                          <tr
                            key={row.symbol}
                            className={
                              row.symbol === selected?.symbol ? "selected" : ""
                            }
                            onClick={() => pick(row)}
                          >
                            <td>
                              <button
                                className="stock-button"
                                type="button"
                                onClick={() => pick(row)}
                                aria-label={`查看 ${row.name} ${row.symbol}`}
                              >
                                <strong>{row.name || row.symbol}</strong>
                                <small>{row.symbol}</small>
                              </button>
                              {!row.available ? (
                                <small className="missing-label">
                                  {row.reason || "当前数据不完整"}
                                </small>
                              ) : null}
                            </td>
                            <td>{percent(row.positions?.["30"], 0)}</td>
                            <td>{percent(row.positions?.["60"], 0)}</td>
                            <td>{percent(row.positions?.["180"], 0)}</td>
                            <td
                              className={
                                (row.y ?? 0) >= 0 ? "value-up" : "value-down"
                              }
                            >
                              {percent(row.y, 2)}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty
                  title={
                    tableMode === "missing"
                      ? "当前显示范围没有数据缺口"
                      : bounds
                        ? "当前区域没有股票"
                        : "没有可定位的股票"
                  }
                >
                  <p>
                    范围仍然可以用于历史研究；调整数值或清空搜索可查看更多对象。
                  </p>
                </Empty>
              )}
              {tableRows.length > 50 ? (
                <div className="pagination">
                  <span>
                    {page * 50 + 1}–
                    {Math.min((page + 1) * 50, tableRows.length)} /{" "}
                    {tableRows.length}
                  </span>
                  <Button
                    variant="ghost"
                    disabled={!page}
                    onClick={() => setPage(page - 1)}
                  >
                    <ChevronLeft size={14} />
                    上一页
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={(page + 1) * 50 >= tableRows.length}
                    onClick={() => setPage(page + 1)}
                  >
                    下一页
                    <ChevronRight size={14} />
                  </Button>
                </div>
              ) : null}
            </div>
          </section>
          <aside className="stock-panel">
            {selected ? (
              <>
                <header className="stock-panel-heading">
                  <h2>
                    {selected.name}
                    <small>{selected.symbol}</small>
                  </h2>
                  <span>{selected.data_cutoff ?? "缺少日期"}</span>
                </header>
                <h3>多周期位置</h3>
                <div className="stock-periods">
                  {[30, 60, 180].map((period) => (
                    <div key={period}>
                      <span>{period}日</span>
                      <i>
                        <b
                          style={{
                            width: `${Math.max(0, Math.min(100, selected.positions?.[String(period)] ?? 0))}%`,
                          }}
                        />
                      </i>
                      <strong>
                        {percent(selected.positions?.[String(period)], 0)}
                      </strong>
                    </div>
                  ))}
                </div>
                <h3>区间变化</h3>
                <div className="stock-returns">
                  {[5, 20, 60].map((period) => (
                    <div key={period}>
                      <span>{period}日</span>
                      <strong
                        className={
                          (selected.returns?.[String(period)] ?? 0) >= 0
                            ? "value-up"
                            : "value-down"
                        }
                      >
                        {percent(selected.returns?.[String(period)], 1)}
                      </strong>
                    </div>
                  ))}
                </div>
                <h3>日线图</h3>
                {stock.isLoading ? (
                  <Loading>读取真实日线</Loading>
                ) : stock.error ? (
                  <Notice error>{errorMessage(stock.error)}</Notice>
                ) : stockEvidence ? (
                  <div className="stock-mini-chart">
                    <StudyChart
                      key={`${stockEvidence.symbol}-${stockEvidence.event_date}`}
                      evidence={stockEvidence}
                      context="market"
                    />
                  </div>
                ) : null}
                <div className="stock-actions">
                  <Button
                    onClick={() => setShapeOpen(!shapeOpen)}
                    disabled={!selected.available || map.isFetching}
                  >
                    <Sparkles size={15} />
                    按这段形态查找
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={map.isFetching}
                    onClick={() =>
                      openStudy(
                        [],
                        `${selected.name} · 条件研究`,
                        null,
                        { universe: "codes", codes: [selected.symbol] },
                        false,
                      )
                    }
                  >
                    定义历史研究
                  </Button>
                </div>
                {shapeOpen ? (
                  <form
                    className="shape-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (shapeValid)
                        openStudy(
                          [
                            {
                              field: "shape_distance",
                              operator: "lte",
                              value: Number(shapeDistance),
                              window: Number(shapeWindow),
                            },
                          ],
                          `${selected.name} · ${shapeWindow}日形态检索`,
                          { symbol: selected.symbol, as_of: map.data!.as_of },
                        );
                    }}
                  >
                    <h3>明确形态参照</h3>
                    <p>
                      {selected.name} · 截止 {map.data.as_of}
                      <br />
                      查找范围：
                      {industry ||
                        (search
                          ? "当前名称检索范围"
                          : UNIVERSE_LABELS[query.universe])}
                    </p>
                    <label>
                      收盘形态窗口
                      <span className="input-unit">
                        <input
                          type="number"
                          min={2}
                          max={360}
                          required
                          value={shapeWindow}
                          onChange={(event) =>
                            setShapeWindow(event.target.value)
                          }
                        />
                        <span>日</span>
                      </span>
                    </label>
                    <label>
                      最大均方根距离
                      <span className="input-unit">
                        <input
                          type="number"
                          min={0}
                          step="any"
                          required
                          placeholder="请明确距离"
                          value={shapeDistance}
                          onChange={(event) =>
                            setShapeDistance(event.target.value)
                          }
                        />
                        <span>百分点</span>
                      </span>
                    </label>
                    <p className="field-hint">
                      按各自首日归一为100，比较逐日差异。这是事后形态检索，不是评分或未来走势预测。
                    </p>
                    <Button
                      type="submit"
                      disabled={!shapeValid || map.isFetching}
                    >
                      查找并验证
                      <ArrowRight size={14} />
                    </Button>
                  </form>
                ) : null}
                <p className="stock-explainer">
                  轨迹向右：区间位置上移；向上：近{activeQuery.momentum_window}
                  日涨幅增加。两个方向分别描述事实。
                </p>
                <h3>来源与缺口</h3>
                <p className="stock-source">
                  来源：{sourceLabels[selected.source] ?? selected.source}
                  <br />
                  数据日期：{selected.data_cutoff ?? "缺失"}
                  <br />
                  {selected.industry || "行业未分类"}
                  {selected.reason ? ` · ${selected.reason}` : ""}
                </p>
              </>
            ) : (
              <div className="stock-panel-empty">
                <CircleHelp size={27} />
                <h2>选一只股票，看它走到哪里</h2>
                <p>
                  点击图上的点或下方股票，联动查看多周期位置、变化轨迹与真实日线。
                </p>
                <p>也可以框选一片区域，验证这种组合在历史上发生过什么。</p>
              </div>
            )}
            {map.data.warnings?.map((warning) => (
              <p className="evidence-hint" key={warning}>
                {warning}
              </p>
            ))}
          </aside>
        </div>
      ) : null}
    </div>
  );
}
