import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Check,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  api,
  type DiscoveryGroup,
  type DiscoveryQuery,
  type DiscoveryResult,
} from "../api/client";
import {
  BreadthBar,
  BreadthHistory,
  ReturnDistribution,
} from "../components/DiscoveryCharts";
import { DiscoveryEvidence } from "../components/DiscoveryEvidence";
import { SaveObservation } from "../components/SaveObservation";
import { Button, Empty, Loading, Notice } from "../components/ui";
import { errorMessage, number, percent } from "../lib/format";
import { parseCodes } from "../lib/study";
import "../styles/discovery.css";

const initialQuery: DiscoveryQuery = {
  universe: "all",
  codes: [],
  industries: [],
  as_of: null,
  window: 20,
};
const storageKey = "manmankan.discovery.v1";
function rememberedQuery(): DiscoveryQuery {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    if (
      saved &&
      ["all", "personal", "codes"].includes(saved.universe) &&
      Array.isArray(saved.codes) &&
      typeof saved.window === "number"
    )
      return saved;
  } catch {
    /* 失效的界面草稿从完整范围重新开始，不影响本地研究资产。 */
  }
  return initialQuery;
}
function change(value: number | null | undefined) {
  return value == null ? "—" : `${value > 0 ? "+" : ""}${number(value, 1)}`;
}
function Delta({ value }: { value: number | null | undefined }) {
  return (
    <span className="discovery-delta">
      {value == null ? null : value > 0 ? (
        <ArrowUp size={13} />
      ) : value < 0 ? (
        <ArrowDown size={13} />
      ) : null}
      {change(value)}
      <small>个百分点</small>
    </span>
  );
}
type MemberFilter = {
  kind: "transition" | "bin";
  key: string;
  label: string;
} | null;

const industryChangeLabels = {
  increased: "上涨占比增加",
  decreased: "上涨占比减少",
  unchanged: "上涨占比持平",
  unknown: "无法比较",
} as const;
type IndustryChange = keyof typeof industryChangeLabels;
function industryChange(group: DiscoveryGroup): IndustryChange {
  const delta = group.comparison.breadth_delta_pp;
  return delta == null
    ? "unknown"
    : delta > 0
      ? "increased"
      : delta < 0
        ? "decreased"
        : "unchanged";
}

type ObservationView = {
  industry: string | null;
  industrySearch: string;
  industryFilter: IndustryChange | null;
  filter: MemberFilter;
  memberSearch: string;
  selectedSymbol: string | null;
  page: number;
};
const emptyView: ObservationView = {
  industry: null,
  industrySearch: "",
  industryFilter: null,
  filter: null,
  memberSearch: "",
  selectedSymbol: null,
  page: 0,
};
function rememberedView(query: DiscoveryQuery): ObservationView {
  try {
    const saved = JSON.parse(
      sessionStorage.getItem(`${storageKey}.view`) ?? "null",
    );
    if (saved?.queryKey === JSON.stringify(query)) return saved.view;
  } catch {
    /* 页面会话状态损坏时，只重置浏览位置。 */
  }
  return emptyView;
}

function ScopeFacts({ result }: { result: DiscoveryResult }) {
  return (
    <div className="discovery-scope-facts">
      <span>
        <Check size={13} />
        {number(result.market.current.available, 0)} /{" "}
        {number(result.market.total, 0)} 只可判断
      </span>
      <span>{number(result.market.current.missing, 0)} 只资料不足</span>
      <span>
        本期 {result.current_start} → {result.as_of}
      </span>
      <span>
        前期 {result.previous_start} → {result.previous_as_of}
      </span>
    </div>
  );
}
function GroupSummary({
  group,
  window,
}: {
  group: DiscoveryGroup;
  window: number;
}) {
  return (
    <section className="market-overview" aria-label={`${group.name}整体观察`}>
      <div className="market-overview-copy">
        <h2>涨跌如何分布</h2>
        <p>
          近 {window} 个交易日 · {group.name}
        </p>
        <div className="market-breadth-value">
          <strong>{percent(group.current.positive_share)}</strong>
          <span>
            成员上涨
            <br />
            <b>
              {number(group.current.up, 0)} /{" "}
              {number(group.current.available, 0)}
            </b>{" "}
            只
          </span>
        </div>
        <BreadthBar stats={group.current} />
        <div className="market-comparison">
          <div>
            <span>本期涨跌中位数</span>
            <strong>{percent(group.current.median_return, 2)}</strong>
          </div>
          <div>
            <span>上涨占比较前期</span>
            <Delta value={group.comparison.breadth_delta_pp} />
          </div>
        </div>
        <p className="comparison-denominator">
          两期变化按同一批 {number(group.comparison.available, 0)} 只成员比较
        </p>
      </div>
      <BreadthHistory group={group} window={window} />
    </section>
  );
}

export function DiscoveryPage() {
  const client = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const returned = location.state as {
    discoveryQuery?: DiscoveryQuery;
    refreshDiscovery?: boolean;
  } | null;
  const [initial] = useState(
    () => returned?.discoveryQuery ?? rememberedQuery(),
  );
  const [initialView] = useState(() =>
    returned?.refreshDiscovery ? emptyView : rememberedView(initial),
  );
  const [submitted, setSubmitted] = useState(initial);
  const [draft, setDraft] = useState(initial);
  const [codes, setCodes] = useState((initial.codes ?? []).join(", "));
  const [industry, setIndustry] = useState(initialView.industry);
  const [industrySearch, setIndustrySearch] = useState(
    initialView.industrySearch,
  );
  const [industryFilter, setIndustryFilter] = useState<IndustryChange | null>(
    initialView.industryFilter,
  );
  const [filter, setFilter] = useState<MemberFilter>(initialView.filter);
  const [memberSearch, setMemberSearch] = useState(initialView.memberSearch);
  const [selectedSymbol, setSelectedSymbol] = useState(
    initialView.selectedSymbol,
  );
  const [page, setPage] = useState(initialView.page);
  const [refreshingObservation, setRefreshingObservation] = useState(false);
  const membersRef = useRef<HTMLElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const evidenceRef = useRef<HTMLDivElement>(null);
  const restored = useRef(false);
  const returnHandled = useRef(false);
  const query = useQuery({
    queryKey: ["discovery", submitted],
    queryFn: () => api.discover(submitted),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  });
  const result = query.data;
  useEffect(() => {
    if (!returned?.refreshDiscovery || returnHandled.current) return;
    returnHandled.current = true;
    restored.current = true;
    if (!query.isFetching) void query.refetch();
    navigate("/", { replace: true, state: null });
  }, [
    returned?.refreshDiscovery,
    initial,
    query.isFetching,
    query.refetch,
    navigate,
  ]);
  useEffect(() => {
    sessionStorage.setItem(storageKey, JSON.stringify(submitted));
    sessionStorage.setItem(
      `${storageKey}.view`,
      JSON.stringify({
        queryKey: JSON.stringify(submitted),
        view: {
          industry,
          industrySearch,
          industryFilter,
          filter,
          memberSearch,
          selectedSymbol,
          page,
        },
      }),
    );
  }, [
    submitted,
    industry,
    industrySearch,
    industryFilter,
    filter,
    memberSearch,
    selectedSymbol,
    page,
  ]);
  useEffect(() => {
    if (!result || restored.current) return;
    restored.current = true;
    const target = initialView.selectedSymbol
      ? evidenceRef.current
      : initialView.filter || initialView.memberSearch || initialView.page
        ? membersRef.current
        : initialView.industry
          ? detailRef.current
          : null;
    requestAnimationFrame(() => target?.scrollIntoView({ block: "start" }));
  }, [result, initialView]);
  const group = industry
    ? result?.industries.find((item) => item.name === industry)
    : result?.market;
  const selected = result?.members.find(
    (member) => member.symbol === selectedSymbol,
  );
  const listedMembers = useMemo(
    () =>
      result?.members.filter((member) => {
        if (industry && member.industry !== industry) return false;
        if (filter?.kind === "transition" && member.transition !== filter.key)
          return false;
        if (filter?.kind === "bin" && member.distribution_bin !== filter.key)
          return false;
        return `${member.symbol} ${member.name} ${member.industry}`
          .toLowerCase()
          .includes(memberSearch.trim().toLowerCase());
      }) ?? [],
    [result, industry, filter, memberSearch],
  );
  const industryRows =
    result?.industries.filter(
      (item) =>
        item.name.includes(industrySearch.trim()) &&
        (!industryFilter || industryChange(item) === industryFilter),
    ) ?? [];
  const industryCounts = {
    increased: 0,
    decreased: 0,
    unchanged: 0,
    unknown: 0,
  };
  for (const item of result?.industries ?? [])
    industryCounts[industryChange(item)] += 1;
  const window = result?.query.window ?? submitted.window ?? 20;
  const pageRows = listedMembers.slice(page * 12, (page + 1) * 12);
  const hasData = Boolean(result?.market.current.available);
  const inputCodes = parseCodes(codes);
  const invalidCodes =
    draft.universe === "codes" &&
    (!inputCodes.length || inputCodes.some((code) => !/^\d{6}$/.test(code)));
  const inputQuery: DiscoveryQuery = {
    ...draft,
    codes: draft.universe === "codes" ? inputCodes : [],
  };
  const dirty = JSON.stringify(inputQuery) !== JSON.stringify(submitted);

  const run = (next: DiscoveryQuery) => {
    restored.current = true;
    void client.invalidateQueries({
      queryKey: ["discovery", next],
      exact: true,
      refetchType: "none",
    });
    setSubmitted(next);
    setDraft(next);
    setIndustry(null);
    setIndustryFilter(null);
    setIndustrySearch("");
    setFilter(null);
    setPage(0);
    setMemberSearch("");
    setSelectedSymbol(null);
    if (JSON.stringify(next) === JSON.stringify(submitted))
      void query.refetch();
  };
  const chooseIndustry = (name: string | null) => {
    setIndustry(name);
    setFilter(null);
    setPage(0);
    setMemberSearch("");
    setSelectedSymbol(null);
  };
  const drill = (next: MemberFilter) => {
    setFilter(next);
    setMemberSearch("");
    setPage(0);
    setSelectedSymbol(null);
    requestAnimationFrame(() =>
      membersRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      }),
    );
  };
  const selectMember = (symbol: string) => {
    setSelectedSymbol(symbol);
    requestAnimationFrame(() =>
      evidenceRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      }),
    );
  };
  const refreshObservationFacts = async () => {
    setRefreshingObservation(true);
    try {
      const refreshed = await query.refetch();
      if (refreshed.error) throw refreshed.error;
    } finally {
      setRefreshingObservation(false);
    }
  };
  return (
    <div className="discovery-page">
      <header className="discovery-heading">
        <div>
          <h1>看见变化的脉络</h1>
          <p>从市场整体到行业内部，把每个观察还原为可核对的事实。</p>
        </div>
        <Link to="/explore" className="discovery-text-link">
          <SlidersHorizontal size={16} />
          有明确条件？去筛选
          <ArrowRight size={15} />
        </Link>
      </header>
      <form
        className="discovery-toolbar"
        onSubmit={(event) => {
          event.preventDefault();
          if (!invalidCodes) run(inputQuery);
        }}
      >
        <label>
          观察范围
          <select
            value={draft.universe}
            onChange={(event) =>
              setDraft({
                ...draft,
                universe: event.target.value as DiscoveryQuery["universe"],
                industries: [],
              })
            }
          >
            <option value="all">全部 A 股</option>
            <option value="personal">我的股票池</option>
            <option value="codes">指定股票</option>
          </select>
        </label>
        <label>
          观察窗口
          <select
            value={draft.window}
            onChange={(event) =>
              setDraft({ ...draft, window: Number(event.target.value) })
            }
          >
            <option value={5}>5 个交易日</option>
            <option value={20}>20 个交易日</option>
            <option value={60}>60 个交易日</option>
          </select>
        </label>
        <label>
          截至日期
          <input
            type="date"
            aria-label="观察截至日期"
            value={draft.as_of ?? ""}
            onChange={(event) =>
              setDraft({ ...draft, as_of: event.target.value || null })
            }
          />
          <small>留空使用最近完整交易日</small>
        </label>
        <Button
          type="submit"
          disabled={Boolean(invalidCodes) || query.isFetching}
        >
          <RefreshCw size={15} className={query.isFetching ? "spin" : ""} />
          {query.isFetching ? "正在观察" : "重新观察"}
        </Button>
        {draft.universe === "codes" ? (
          <label className="discovery-code-input">
            股票代码
            <input
              value={codes}
              onChange={(event) => setCodes(event.target.value)}
              placeholder="输入 6 位代码，用逗号或空格分隔"
            />
            {invalidCodes ? <small>请填写有效的 6 位股票代码。</small> : null}
          </label>
        ) : null}
        {dirty && !query.isFetching ? (
          <p className="discovery-draft-note">
            条件已修改，点击“重新观察”后更新结果。
          </p>
        ) : null}
      </form>
      {query.isFetching && !refreshingObservation ? (
        <div className="discovery-loading">
          <Loading>正在从日线汇集分布与变化</Loading>
          <p>同一批成员、相邻两个观察窗口。首次读取全市场需要一点时间。</p>
        </div>
      ) : query.error ? (
        <Notice error>
          {errorMessage(query.error)}{" "}
          <Button variant="ghost" onClick={() => void query.refetch()}>
            重试
          </Button>
          <Link
            className="button button--secondary"
            to="/data"
            state={{ returnTo: "/", discoveryQuery: submitted }}
          >
            检查数据配置
          </Link>
        </Notice>
      ) : result ? (
        <>
          <div className="discovery-result-heading">
            <span>
              观察截至 <strong>{result.as_of}</strong>
            </span>
            <span>日线事实 · 两期各 {window} 个交易日</span>
          </div>
          <ScopeFacts result={result} />
          {result.data_gaps.length ? (
            <details className="discovery-data-gaps">
              <summary>
                行情存在共同缺口：{result.data_gaps[0]!.date} ·{" "}
                {number(result.data_gaps[0]!.missing, 0)} 只
              </summary>
              <p>
                以下日期缺少有效日线。缺失成员保留为未知，不当作下跌、停牌或退出；请先核对资料，再解释变化。
              </p>
              <ul>
                {result.data_gaps.map((gap) => (
                  <li key={gap.date}>
                    {gap.date}
                    <span>{number(gap.missing, 0)} 只</span>
                  </li>
                ))}
              </ul>
              <p>只统计已有有效行情之后的窗口缺日，不把上市前历史不足计入。</p>
              <Link
                to="/data"
                state={{ returnTo: "/", discoveryQuery: submitted }}
              >
                按本次范围核对数据 <ArrowRight size={14} />
              </Link>
            </details>
          ) : null}
          {!hasData ? (
            <section className="discovery-empty">
              <Empty
                title={
                  result.market.total
                    ? "这个日期，暂时还看不清整体"
                    : "这个范围还没有股票"
                }
              >
                <p>
                  {result.market.total
                    ? "缺少完整窗口的行情。先更新数据，或明确切到本地已有资料的日期。"
                    : "可以选择全部 A 股，或在数据页添加自己的观察对象。"}
                </p>
              </Empty>
              <div className="button-row">
                {result.common_data_date &&
                result.common_data_date !== result.as_of ? (
                  <Button
                    variant="secondary"
                    onClick={() =>
                      run({ ...submitted, as_of: result.common_data_date })
                    }
                  >
                    查看本地数据日 {result.common_data_date}
                  </Button>
                ) : null}
                <Link
                  className="button button--primary"
                  to="/data"
                  state={{ returnTo: "/", discoveryQuery: submitted }}
                >
                  去更新数据 <ArrowRight size={15} />
                </Link>
              </div>
              {result.common_data_date ? (
                <p>
                  本地主要数据日 {result.common_data_date} ·{" "}
                  {number(result.common_data_count, 0)} 只，未自动替换观察日期。
                </p>
              ) : null}
            </section>
          ) : (
            <>
              <GroupSummary group={result.market} window={window} />
              {result.market.observations.length ? (
                <div className="discovery-observations">
                  {result.market.observations.map((observation, i) => (
                    <div key={`${observation.kind}-${i}`}>
                      <span>{String(i + 1).padStart(2, "0")}</span>
                      <div>
                        <h3>{observation.title}</h3>
                        <p>{observation.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="discovery-market-save">
                <SaveObservation
                  result={result}
                  industry={null}
                  onRefresh={refreshObservationFacts}
                />
              </div>
              <section className="industry-section">
                <header className="discovery-section-heading">
                  <div>
                    <h2>行业剖面</h2>
                    <p>看变化在哪里发生，以及行业内部是否一致。</p>
                  </div>
                  <label className="search-field">
                    <Search size={15} />
                    <input
                      aria-label="查找行业"
                      placeholder="查找行业"
                      value={industrySearch}
                      onChange={(event) =>
                        setIndustrySearch(event.target.value)
                      }
                    />
                  </label>
                </header>
                <div
                  className="industry-changes"
                  role="group"
                  aria-label="按行业上涨占比变化查看"
                >
                  <button
                    type="button"
                    aria-pressed={industryFilter === null}
                    onClick={() => setIndustryFilter(null)}
                  >
                    全部行业 <strong>{result.industries.length}</strong>
                  </button>
                  {(Object.keys(industryChangeLabels) as IndustryChange[]).map(
                    (key) => (
                      <button
                        type="button"
                        key={key}
                        aria-label={`${industryChangeLabels[key]}，${industryCounts[key]}个行业`}
                        aria-pressed={industryFilter === key}
                        onClick={() =>
                          setIndustryFilter(industryFilter === key ? null : key)
                        }
                      >
                        <span>{industryChangeLabels[key]}</span>
                        <strong>{industryCounts[key]}</strong>
                      </button>
                    ),
                  )}
                </div>
                <p className="industry-comparison-note">
                  各行业在同一批可比较成员中，对照相邻两个 {window}{" "}
                  日窗口；点击数量查看对应行业。
                </p>
                <div className="industry-table-scroll">
                  <table className="industry-table">
                    <thead>
                      <tr>
                        <th>行业 / 成员</th>
                        <th>上涨占比</th>
                        <th>涨跌中位数</th>
                        <th>占比较前期</th>
                        <th>可判断 / 范围</th>
                      </tr>
                    </thead>
                    <tbody>
                      {industryRows.map((item) => (
                        <Fragment key={item.name}>
                          <tr
                            className={
                              industry === item.name ? "is-selected" : ""
                            }
                          >
                            <td>
                              <button
                                type="button"
                                className="industry-select"
                                aria-expanded={industry === item.name}
                                onClick={() =>
                                  chooseIndustry(
                                    industry === item.name ? null : item.name,
                                  )
                                }
                              >
                                <ChevronRight size={15} />
                                <strong>{item.name}</strong>
                              </button>
                            </td>
                            <td>
                              <div className="industry-breadth">
                                <span>
                                  {percent(item.current.positive_share)}
                                </span>
                                <i>
                                  <b
                                    style={{
                                      width: `${item.current.positive_share ?? 0}%`,
                                    }}
                                  />
                                </i>
                              </div>
                            </td>
                            <td>{percent(item.current.median_return, 2)}</td>
                            <td>
                              <Delta value={item.comparison.breadth_delta_pp} />
                            </td>
                            <td>
                              {number(item.current.available, 0)}
                              <span className="muted">
                                {" "}
                                / {number(item.total, 0)}
                              </span>
                            </td>
                          </tr>
                          {industry === item.name ? (
                            <tr className="industry-expanded">
                              <td colSpan={5}>
                                <div>
                                  <p>
                                    {item.observations[0]?.detail ||
                                      `当前 ${item.current.available} 只资料完整，${item.current.missing} 只资料不足。`}
                                  </p>
                                  <button
                                    type="button"
                                    className="discovery-text-link"
                                    onClick={() =>
                                      detailRef.current?.scrollIntoView({
                                        behavior: "smooth",
                                        block: "start",
                                      })
                                    }
                                  >
                                    展开分布与成员 <ArrowRight size={15} />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                  {!industryRows.length ? (
                    <p className="industry-no-results">没有符合名称的行业。</p>
                  ) : null}
                </div>
              </section>
              {group || industry ? (
                <div
                  ref={detailRef}
                  className="discovery-group-detail"
                  role="region"
                  aria-label={`${industry ?? "整个范围"}分布与成员`}
                >
                  <div className="observation-context-heading">
                    <header className="discovery-section-heading">
                      <div>
                        <h2>{industry ?? "整个范围"} · 拆开看</h2>
                        <p>
                          {industry
                            ? group
                              ? `${group.total} 只成员，当前 ${group.current.available} 只可判断。`
                              : "这个行业已不在当前范围中，原观察草稿仍然保留。"
                            : "每个分布都能下钻，查看组成它的全部成员。"}
                        </p>
                      </div>
                      {industry ? (
                        <button
                          type="button"
                          className="discovery-text-link"
                          onClick={() => chooseIndustry(null)}
                        >
                          返回整个范围
                          <X size={15} />
                        </button>
                      ) : null}
                    </header>
                    {industry ? (
                      <SaveObservation
                        key={`${result.as_of}-${industry ?? "all"}`}
                        result={result}
                        industry={industry}
                        onRefresh={refreshObservationFacts}
                      />
                    ) : null}
                  </div>
                  {group ? (
                    <div className="group-analysis">
                      <section>
                        <h3>本期涨跌分布</h3>
                        <p className="analysis-description">
                          中间一半成员的变化在 {percent(group.current.q25, 2)}{" "}
                          至 {percent(group.current.q75, 2)} 之间
                        </p>
                        <ReturnDistribution
                          group={group}
                          active={filter?.kind === "bin" ? filter.key : null}
                          onSelect={(key, label) =>
                            drill({ kind: "bin", key, label })
                          }
                        />
                      </section>
                      <section>
                        <h3>从前期，到本期</h3>
                        <p className="analysis-description">
                          相邻两个 {window} 日窗口 · 两期完整{" "}
                          {number(group.comparison.available, 0)} 只
                        </p>
                        <div className="transition-list">
                          {group.transitions.map((item) => (
                            <button
                              type="button"
                              key={item.key}
                              aria-label={`${item.label}，${item.count}只，查看成员`}
                              aria-pressed={
                                filter?.kind === "transition" &&
                                filter.key === item.key
                              }
                              onClick={() =>
                                drill({
                                  kind: "transition",
                                  key: item.key,
                                  label: item.label,
                                })
                              }
                              disabled={!item.count}
                            >
                              <span>{item.label}</span>
                              <i>
                                <b
                                  style={{
                                    width: `${group.total ? (item.count / group.total) * 100 : 0}%`,
                                  }}
                                />
                              </i>
                              <strong>{number(item.count, 0)}</strong>
                              <ChevronRight size={14} />
                            </button>
                          ))}
                        </div>
                      </section>
                    </div>
                  ) : null}
                  {industry && group ? (
                    <BreadthHistory group={group} window={window} />
                  ) : null}
                </div>
              ) : null}
            </>
          )}
          <section className="discovery-members" ref={membersRef}>
            <header className="discovery-section-heading">
              <div>
                <h2>
                  成员与证据 <span>{number(listedMembers.length, 0)}</span>
                </h2>
                <p>
                  {industry ?? "整个范围"}
                  {filter ? ` · ${filter.label}` : " · 全部成员"} · 按代码排列
                </p>
              </div>
              <div className="member-heading-actions">
                {filter ? (
                  <button
                    type="button"
                    className="discovery-text-link"
                    onClick={() => drill(null)}
                  >
                    清除分组
                    <X size={14} />
                  </button>
                ) : null}
                <label className="search-field">
                  <Search size={15} />
                  <input
                    aria-label="查找成员"
                    placeholder="名称或代码"
                    value={memberSearch}
                    onChange={(event) => {
                      setMemberSearch(event.target.value);
                      setPage(0);
                    }}
                  />
                </label>
              </div>
            </header>
            <div
              className={`discovery-member-layout${selected ? " has-evidence" : ""}`}
            >
              <div className="member-list">
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>股票</th>
                        <th>本期涨跌</th>
                        <th>前期涨跌</th>
                        <th>变化 / 资料</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageRows.map((member) => (
                        <tr
                          key={member.symbol}
                          className={
                            selectedSymbol === member.symbol ? "selected" : ""
                          }
                        >
                          <td>
                            <button
                              type="button"
                              className="member-name"
                              aria-label={`查看 ${member.name} ${member.symbol} 价格证据`}
                              onClick={() => selectMember(member.symbol)}
                            >
                              <strong>{member.name}</strong>
                              <small>
                                {member.symbol} · {member.industry}
                              </small>
                            </button>
                          </td>
                          <td>{percent(member.return_pct, 2)}</td>
                          <td>{percent(member.previous_return_pct, 2)}</td>
                          <td className="member-status">
                            {member.reason ??
                              group?.transitions.find(
                                (item) => item.key === member.transition,
                              )?.label ??
                              "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!listedMembers.length ? (
                  <Empty title="这个分组里没有成员">
                    <p>清除分组或调整名称搜索，查看完整范围。</p>
                  </Empty>
                ) : null}
                {listedMembers.length > 12 ? (
                  <div className="pagination">
                    <span>
                      {page + 1} / {Math.ceil(listedMembers.length / 12)} 页
                    </span>
                    <Button
                      variant="ghost"
                      aria-label="上一页成员"
                      disabled={!page}
                      onClick={() => setPage(page - 1)}
                    >
                      <ChevronLeft size={15} />
                    </Button>
                    <Button
                      variant="ghost"
                      aria-label="下一页成员"
                      disabled={(page + 1) * 12 >= listedMembers.length}
                      onClick={() => setPage(page + 1)}
                    >
                      <ChevronRight size={15} />
                    </Button>
                  </div>
                ) : null}
              </div>
              {selected ? (
                <div ref={evidenceRef} className="discovery-evidence-holder">
                  <DiscoveryEvidence
                    key={`${selected.symbol}-${result.as_of}`}
                    member={selected}
                    result={result}
                    revision={query.dataUpdatedAt}
                    onClose={() => setSelectedSymbol(null)}
                  />
                </div>
              ) : null}
            </div>
            <Link
              className="discovery-explore-link"
              to="/explore"
              state={{
                discoveryQuery: {
                  universe: submitted.universe,
                  codes: submitted.codes,
                  industries: industry ? [industry] : submitted.industries,
                  as_of: result.as_of,
                  conditions: [],
                  swing_reversal_pct: 5,
                },
              }}
            >
              在这个完整范围继续筛选
              <ArrowRight size={16} />
            </Link>
          </section>
          <details className="discovery-method">
            <summary>数据口径与解释边界</summary>
            <p>
              上涨与下跌描述收盘价格在观察窗口内的变化，不是股票评级。中位数按成员等权统计，不是行业指数收益。前期为紧邻本期的同长度窗口。
            </p>
            <p>
              每日轨迹使用整个轨迹期间都有完整行情的固定成员；当前分布与两期对照分别保留自己的可判断分母。资料不足单独呈现。
            </p>
            {result.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </details>
        </>
      ) : null}
    </div>
  );
}
