import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Search,
  CalendarDays,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  api,
  type DiscoveryGroup,
  type DiscoveryQuery,
  type DiscoveryResult,
} from "../api/client";
import {
  BreadthHistory,
  ReturnDistribution,
  TransitionList,
} from "../components/DiscoveryCharts";
import { IndustryStrengthMap } from "../components/IndustryStrengthMap";
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
function change(value: number | null | undefined, digits = 1) {
  return value == null
    ? "—"
    : `${value > 0 ? "+" : ""}${number(value, digits)}`;
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
  industryOrder: StrengthOrder;
  memberOrder: StrengthOrder;
  industryFilter: IndustryChange | null;
  filter: MemberFilter;
  memberSearch: string;
  selectedSymbol: string | null;
  page: number;
};
const emptyView: ObservationView = {
  industry: null,
  industrySearch: "",
  industryOrder: "default",
  memberOrder: "default",
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

type StrengthOrder = "default" | "high" | "low";
function compareStrength(
  a: number | null | undefined,
  b: number | null | undefined,
  order: StrengthOrder,
) {
  if (a == null || b == null) return a == null ? Number(b != null) : -1;
  return order === "high" ? b - a : a - b;
}

function StrengthOrderSelect({
  value,
  onChange,
  kind,
}: {
  value: StrengthOrder;
  onChange: (order: StrengthOrder) => void;
  kind: "行业" | "成员";
}) {
  return (
    <select
      className="strength-order"
      aria-label={`${kind}排序`}
      value={value}
      onChange={(event) => onChange(event.target.value as StrengthOrder)}
    >
      <option value="default">
        {kind === "成员" ? "按股票代码" : "按行业名称"}
      </option>
      <option value="high">相对强度从高到低</option>
      <option value="low">相对强度从低到高</option>
    </select>
  );
}

function MarketSummary({ result }: { result: DiscoveryResult }) {
  const group = result.market;
  const { current, comparison } = group;
  return (
    <section className="market-summary" aria-label={`${group.name}整体观察`}>
      <div>
        <span>本期区间涨跌中位数</span>
        <strong>
          {current.median_return != null && current.median_return > 0
            ? "+"
            : ""}
          {percent(current.median_return, 2)}
        </strong>
        <small>
          {group.name} · {number(current.available, 0)} 只有效
        </small>
      </div>
      <div>
        <span>参与度 · 上涨成员占比</span>
        <strong>{percent(current.positive_share)}</strong>
        <small>
          同一批 {number(comparison.available, 0)} 只，较前期{" "}
          {change(comparison.breadth_delta_pp)} 个百分点
        </small>
      </div>
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
  const [industryOrder, setIndustryOrder] = useState(
    initialView.industryOrder ?? "default",
  );
  const [memberOrder, setMemberOrder] = useState(
    initialView.memberOrder ?? "default",
  );
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
  const scopeRef = useRef<HTMLDetailsElement>(null);
  const membersRef = useRef<HTMLElement>(null);
  const industriesRef = useRef<HTMLDivElement>(null);
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
          industryOrder,
          memberOrder,
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
    industryOrder,
    memberOrder,
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
  const listedMembers = useMemo(() => {
    const search = memberSearch.trim().toLowerCase();
    const rows = (result?.members ?? []).filter((member) => {
      if (industry && member.industry !== industry) return false;
      if (filter?.kind === "transition" && member.transition !== filter.key)
        return false;
      if (filter?.kind === "bin" && member.distribution_bin !== filter.key)
        return false;
      return `${member.symbol} ${member.name} ${member.industry}`
        .toLowerCase()
        .includes(search);
    });
    return rows.sort(
      (a, b) =>
        (memberOrder === "default"
          ? 0
          : compareStrength(
              a.relative_return_pp,
              b.relative_return_pp,
              memberOrder,
            )) || a.symbol.localeCompare(b.symbol),
    );
  }, [result, industry, filter, memberSearch, memberOrder]);
  const industryRows = (result?.industries ?? [])
    .filter(
      (item) =>
        item.name.includes(industrySearch.trim()) &&
        (!industryFilter || industryChange(item) === industryFilter),
    )
    .sort(
      (a, b) =>
        (industryOrder === "default"
          ? 0
          : compareStrength(
              a.relative_return_pp,
              b.relative_return_pp,
              industryOrder,
            )) || a.name.localeCompare(b.name, "zh-CN"),
    );
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
  const missingReasons = new Map<string, number>();
  for (const member of result?.members ?? []) {
    if (member.return_pct == null && member.reason)
      missingReasons.set(
        member.reason,
        (missingReasons.get(member.reason) ?? 0) + 1,
      );
  }
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
    if (scopeRef.current) scopeRef.current.open = false;
    setSubmitted(next);
    setDraft(next);
    setIndustry(null);
    setIndustryFilter(null);
    setIndustryOrder("default");
    setMemberOrder("default");
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
    if (name)
      requestAnimationFrame(() =>
        membersRef.current?.scrollIntoView({ block: "start" }),
      );
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
        <h1>市场观察</h1>
        <div className="observation-controls">
          <details
            className="scope-popover"
            ref={scopeRef}
            onBlur={(event) => {
              if (
                event.relatedTarget &&
                !event.currentTarget.contains(event.relatedTarget)
              )
                event.currentTarget.open = false;
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.currentTarget.open = false;
                event.currentTarget.querySelector("summary")?.focus();
              }
            }}
          >
            <summary>
              <CalendarDays size={15} />
              <span>
                {result?.market.name ?? "观察范围"} · 截至{" "}
                <strong>
                  {result?.as_of || submitted.as_of || "最近收盘"}
                </strong>
              </span>
              <ChevronRight size={13} />
            </summary>
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
                      universe: event.target
                        .value as DiscoveryQuery["universe"],
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
                variant="secondary"
                type="submit"
                disabled={Boolean(invalidCodes) || query.isFetching}
              >
                <RefreshCw
                  size={15}
                  className={query.isFetching ? "spin" : ""}
                />
                {query.isFetching ? "正在观察" : "应用范围"}
              </Button>
              {draft.universe === "codes" ? (
                <label className="discovery-code-input">
                  股票代码
                  <input
                    value={codes}
                    onChange={(event) => setCodes(event.target.value)}
                    placeholder="输入 6 位代码，用逗号或空格分隔"
                  />
                  {invalidCodes ? (
                    <small>请填写有效的 6 位股票代码。</small>
                  ) : null}
                </label>
              ) : null}
              {dirty && !query.isFetching ? (
                <p className="discovery-draft-note">
                  条件已修改，应用范围后更新结果。
                </p>
              ) : null}
            </form>
          </details>
          <fieldset className="window-picker">
            <legend>观察窗口</legend>
            <div role="group" aria-label="切换观察窗口">
              {[...new Set([5, 20, 60, submitted.window ?? 20])]
                .sort((a, b) => a - b)
                .map((days) => (
                  <button
                    key={days}
                    type="button"
                    aria-pressed={(submitted.window ?? 20) === days}
                    onClick={() => run({ ...submitted, window: days })}
                  >
                    {days} 日
                  </button>
                ))}
            </div>
          </fieldset>
          <button
            type="button"
            aria-label="重新观察"
            title="重新观察"
            className="refresh-observation"
            disabled={query.isFetching}
            onClick={() => run(submitted)}
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </header>
      {query.isFetching && !refreshingObservation ? (
        <div className="discovery-loading">
          <Loading>正在从日线汇集分布与变化</Loading>
          <p>同一批成员、相邻两个观察窗口。首次读取全市场需要一点时间。</p>
          <Link className="discovery-text-link" to="/example">
            先看历史样本 <ArrowRight size={14} />
          </Link>
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
          <Link className="discovery-text-link" to="/example">
            先看历史样本 <ArrowRight size={14} />
          </Link>
        </Notice>
      ) : result ? (
        <>
          {hasData && (
            <div className="market-front">
              <MarketSummary result={result} />
              <BreadthHistory
                key={result.market.name}
                group={result.market}
                window={window}
              />
            </div>
          )}
          <details className="coverage-details" open={!hasData}>
            <summary>
              数据覆盖 · {number(result.market.current.available, 0)} /{" "}
              {number(result.market.total, 0)} 只可判断 ·{" "}
              {number(result.market.current.missing, 0)} 只资料不足
            </summary>
            <p>
              本期 {result.current_start} 至 {result.as_of}，前期{" "}
              {result.previous_start} 至 {result.previous_as_of}。
            </p>
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
                <p>
                  只统计已有有效行情之后的窗口缺日，不把上市前历史不足计入。
                </p>
                <Link
                  to="/data"
                  state={{ returnTo: "/", discoveryQuery: submitted }}
                >
                  按本次范围核对数据 <ArrowRight size={14} />
                </Link>
              </details>
            ) : null}
            {missingReasons.size ? (
              <details
                className="discovery-data-gaps discovery-reasons"
                aria-label="资料不足原因"
                open={!hasData}
              >
                <summary>
                  无法判断的原因 · {number(result.market.current.missing, 0)} 只
                </summary>
                <ul>
                  {[...missingReasons].map(([reason, count]) => (
                    <li key={reason}>
                      <span>{reason}</span>
                      <span>{number(count, 0)} 只</span>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </details>
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
                    ? "本窗口没有可判断的成员。先核对上方原因，再决定补齐行情或选择其他日期。"
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
                <Link className="button button--secondary" to="/example">
                  先看历史样本
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
              <div className="industry-workbench" ref={industriesRef}>
                <IndustryStrengthMap
                  groups={result.industries}
                  selected={industry}
                  onSelect={chooseIndustry}
                />
                <section className="industry-section">
                  <header className="discovery-section-heading">
                    <div>
                      <h2>行业剖面</h2>
                      <p>
                        相对强度为行业涨跌中位数减原范围中位数（
                        {percent(result.market.current.median_return, 2)}
                        ），单位为百分点。
                      </p>
                    </div>
                    <div className="list-controls">
                      <select
                        className="strength-order"
                        aria-label="按行业上涨占比变化查看"
                        value={industryFilter ?? ""}
                        onChange={(event) =>
                          setIndustryFilter(
                            (event.target.value ||
                              null) as IndustryChange | null,
                          )
                        }
                      >
                        <option value="">
                          全部行业（{result.industries.length}）
                        </option>
                        {(
                          Object.keys(industryChangeLabels) as IndustryChange[]
                        ).map((key) => (
                          <option key={key} value={key}>
                            {industryChangeLabels[key]}（{industryCounts[key]}）
                          </option>
                        ))}
                      </select>
                      <StrengthOrderSelect
                        kind="行业"
                        value={industryOrder}
                        onChange={setIndustryOrder}
                      />
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
                    </div>
                  </header>
                  <div className="industry-table-scroll">
                    <table className="industry-table">
                      <thead>
                        <tr>
                          <th>行业名称</th>
                          <th>涨跌中位数</th>
                          <th title="行业减原范围中位数，单位百分点">
                            相对强度
                          </th>
                          <th>上涨占比</th>
                          <th title="共同成员的上涨占比变化，单位百分点">
                            占比变化
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {industryRows.map((item) => (
                          <tr
                            key={item.name}
                            className={
                              industry === item.name ? "is-selected" : ""
                            }
                          >
                            <td>
                              <button
                                type="button"
                                className="industry-select"
                                aria-pressed={industry === item.name}
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
                            <td>{percent(item.current.median_return, 2)}</td>
                            <td className="strength-number">
                              {change(item.relative_return_pp, 2)}
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
                            <td>{change(item.comparison.breadth_delta_pp)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!industryRows.length ? (
                      <p className="industry-no-results">
                        没有符合当前名称和条件的行业。
                      </p>
                    ) : null}
                  </div>
                </section>
              </div>
            </>
          )}
          <section className="discovery-members" ref={membersRef}>
            <header className="discovery-section-heading">
              <div>
                <h2>
                  {industry ? industry + " · " : ""}成员与证据{" "}
                  <span>{number(listedMembers.length, 0)}</span>
                </h2>
                <p>
                  {industry ?? "整个范围"}
                  {filter ? ` · ${filter.label}` : " · 全部成员"} ·
                  相对原观察范围中位数{" "}
                  {percent(result.market.current.median_return, 2)}
                </p>
              </div>
              <div className="member-heading-actions">
                {industry && (
                  <button
                    type="button"
                    className="discovery-text-link"
                    onClick={() => {
                      chooseIndustry(null);
                      industriesRef.current?.scrollIntoView({ block: "start" });
                    }}
                  >
                    返回行业比较 <ArrowRight size={14} />
                  </button>
                )}
                <StrengthOrderSelect
                  kind="成员"
                  value={memberOrder}
                  onChange={(order) => {
                    setMemberOrder(order);
                    setPage(0);
                  }}
                />
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
                        <th>相对强度（百分点）</th>
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
                          <td className="strength-number">
                            {change(member.relative_return_pp, 2)}
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
                    benchmark={result.market.current}
                    result={result}
                    revision={query.dataUpdatedAt}
                    onClose={() => setSelectedSymbol(null)}
                  />
                </div>
              ) : null}
            </div>
            {hasData && (
              <button
                type="button"
                className="discovery-explore-link"
                onClick={() =>
                  detailRef.current?.scrollIntoView({ block: "start" })
                }
              >
                查看涨跌分布与前后期变化 <ArrowRight size={16} />
              </button>
            )}
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
          {hasData ? (
            <>
              <div className="discovery-market-save">
                <SaveObservation
                  result={result}
                  industry={null}
                  onRefresh={refreshObservationFacts}
                />
              </div>
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
                      {industry && group && (
                        <button
                          type="button"
                          className="discovery-text-link"
                          onClick={() => drill(null)}
                        >
                          查看 {group.total} 只成员 <ArrowRight size={14} />
                        </button>
                      )}
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
                        <TransitionList
                          transitions={group.transitions}
                          total={group.total}
                          selected={
                            filter?.kind === "transition" ? filter.key : null
                          }
                          onSelect={(item) =>
                            drill({
                              kind: "transition",
                              key: item.key,
                              label: item.label,
                            })
                          }
                        />
                      </section>
                    </div>
                  ) : null}
                  {industry && group ? (
                    <BreadthHistory group={group} window={window} />
                  ) : null}
                </div>
              ) : null}
            </>
          ) : null}
          <details className="discovery-method">
            <summary>日期、数据来源与统计口径</summary>
            <Link className="discovery-text-link" to="/example">
              先看历史样本 <ArrowRight size={14} />
            </Link>
            <p>
              本期 {result.current_start} 至 {result.as_of}，前期{" "}
              {result.previous_start} 至 {result.previous_as_of}
              。相对强度比较同一窗口，单位为百分点。负收益的成员也可能高于范围中位数。
            </p>
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
