import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, ChevronRight, LoaderCircle, NotebookPen, Plus, RefreshCw, Search, Star, X } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type FocusRow, type WorkspaceJob } from "../api/client";
import { Button, EmptyState, Loading, PageHeader } from "../components/ui";
import { errorMessage, number, percent, shortDate } from "../lib/format";

const DRAFT_KEY = "manmankan.focus-drafts.v1";
const SOURCE_LABELS: Record<string, string> = { watchlist: "自选", holding: "持仓", candidate: "研究列表" };
const JOB_LABELS: Record<string, string> = { queued: "等待更新", running: "正在更新", succeeded: "更新完成", partial: "部分完成", failed: "更新失败", interrupted: "更新中断" };
const terminalJob = (job?: WorkspaceJob | null) => Boolean(job && !["queued", "running"].includes(job.status));

function loadDrafts(): Record<string, string> {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? "{}");
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return Object.fromEntries(Object.entries(value).filter(([, note]) => typeof note === "string"));
    }
  } catch { /* 草稿损坏或浏览器禁止存储时，仍可编辑并显式保存。 */ }
  return {};
}

function PositionMeter({ value }: { value?: number | null }) {
  return <span className="focus-meter"><span className="focus-meter__track" aria-hidden="true">{value != null ? <i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /> : null}</span><span>{percent(value, 0)}</span></span>;
}

function ChangeValue({ value }: { value?: number | null }) {
  return <span className={value == null || value === 0 ? "" : value > 0 ? "fact-up" : "fact-down"}>{value == null ? "—" : `${value > 0 ? "+" : ""}${number(value, 2)}%`}</span>;
}

function ReviewStatus({ row }: { row: FocusRow }) {
  return <span className={`focus-status ${row.reviewed ? "is-reviewed" : !row.available ? "is-missing" : "is-pending"}`}>{!row.available ? "待补数据" : row.reviewed ? "已复看" : "待复看"}</span>;
}

function FocusDetail({ row, note, onDraft, onSaved, onBack }: {
  row: FocusRow; note: string; onDraft: (value: string) => void; onSaved: (symbol: string, savedNote: string) => void; onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);
  const dirty = note !== row.note;
  const save = useMutation({
    mutationFn: async ({ review, savedNote }: { review: boolean; savedNote: string }) => {
      if (savedNote !== row.note) await api.saveFocusNote(row.symbol, savedNote, row.candidate_list_id);
      if (review) await api.reviewFocus(row.symbol, row.data_hash, savedNote);
      return { review, savedNote };
    },
    onSuccess: ({ review, savedNote }) => {
      onSaved(row.symbol, savedNote);
      setNotice({ text: review ? "已保存这次复看，数据日与观察已留存。" : "观察笔记已保存。", error: false });
      void queryClient.invalidateQueries({ queryKey: ["focus"] });
      void queryClient.invalidateQueries({ queryKey: ["candidate-lists"] });
    },
    onError: (error) => setNotice({ text: errorMessage(error), error: true }),
  });
  const otherNotes = (row.candidates ?? []).filter((item) => item.list_id !== row.candidate_list_id && item.note);
  return (
    <aside className="focus-detail" aria-label={`${row.name || row.symbol} 观察详情`}>
      <button type="button" className="focus-back" onClick={onBack}><ArrowLeft size={17} />返回关注列表</button>
      <div className="focus-detail__heading">
        <div><h2>{row.name || row.symbol}</h2><span>{row.symbol}</span></div>
        <Link to={`/research/${row.symbol}`} className="text-link">完整研究<ArrowRight size={15} /></Link>
      </div>
      <section className="focus-detail__section">
        <h3>较上一条行情</h3>
        {row.available ? (
          <>
            <div className="focus-detail__price"><span>{number(row.price)}</span><ChangeValue value={row.change_pct} /><small>缓存收盘价</small></div>
            <div className="focus-periods">
              {(row.periods ?? []).map((period) => (
                <div className="focus-period" key={period.period}>
                  <span>{period.period}日位置</span><PositionMeter value={period.position_pct} />
                  <small>{period.change_pp == null ? "变化缺失" : `${period.change_pp > 0 ? "+" : ""}${number(period.change_pp, 1)} 个百分点`}</small>
                </div>
              ))}
            </div>
            <p className="focus-provenance">数据日 {row.data_cutoff ?? "未知"} · 对比日 {row.previous_cutoff ?? "缺失"}<br />来源 {row.source} · 本地缓存{row.stale ? " · 时效待核" : ""}</p>
          </>
        ) : <p className="focus-data-gap">{row.message || "暂无本地行情。点击「更新关注数据」后，再核对价格与位置。"}</p>}
        {row.available && row.message ? <p className="focus-data-gap">{row.message}</p> : null}
        <p className="focus-source-label">来自{row.sources.map((source) => SOURCE_LABELS[source] ?? source).join("、")}</p>
      </section>
      <section className="focus-detail__section focus-observation">
        <div className="focus-section-heading"><h3>我的观察</h3>{dirty ? <small>未保存的草稿</small> : null}</div>
        <label className="sr-only" htmlFor={`note-${row.symbol}`}>观察笔记</label>
        <textarea id={`note-${row.symbol}`} rows={4} maxLength={2000} value={note} onChange={(event) => { onDraft(event.target.value); setNotice(null); }} placeholder="记下依据、疑问，或下次要核对的事实。" />
        <div className="focus-note-actions">
          <Button disabled={!dirty || save.isPending} onClick={() => save.mutate({ review: false, savedNote: note })}>{save.isPending ? <LoaderCircle size={16} className="spin" /> : null}保存笔记</Button>
          <Button variant="secondary" disabled={!row.available || save.isPending || (row.reviewed && !dirty)} onClick={() => save.mutate({ review: true, savedNote: note })}>{row.reviewed && !dirty ? <Check size={16} /> : null}{row.reviewed && !dirty ? "已复看" : dirty ? "保存并复看" : "标记已复看"}</Button>
        </div>
        {notice ? <p role={notice.error ? "alert" : "status"} className={`focus-feedback${notice.error ? " is-error" : ""}`}>{notice.text}{notice.error ? <Button variant="ghost" size="sm" onClick={() => { void queryClient.invalidateQueries({ queryKey: ["focus"] }); setNotice(null); }}>重新读取数据</Button> : null}</p> : null}
        {otherNotes.length ? <details className="focus-other-notes"><summary>其他研究列表中的笔记（{otherNotes.length}）</summary>{otherNotes.map((item) => <p key={item.list_id}>{item.note}</p>)}<Link className="text-link" to="/candidates">管理研究笔记<ArrowRight size={14} /></Link></details> : null}
      </section>
      <section className="focus-detail__section focus-history">
        <h3>最近复看</h3>
        {(row.review_history ?? []).length ? <ol>{row.review_history!.map((entry, index) => (
          <li key={`${entry.reviewed_at}-${index}`}><time>{shortDate(entry.reviewed_at)}</time><small>数据日 {entry.data_cutoff}</small><p>{entry.note || "本次没有填写观察笔记。"}</p><details className="focus-history-evidence"><summary>查看当时数据</summary><dl><div><dt>缓存收盘价</dt><dd>{number(entry.price)}</dd></div>{Object.entries(entry.positions).map(([period, position]) => <div key={period}><dt>{period}日位置</dt><dd>{percent(position)}</dd></div>)}</dl><small>这是本次复看时保存的事实，之后的数据更新不会改写它。</small></details></li>
        ))}</ol> : <div className="focus-history-empty"><NotebookPen size={19} /><p>核对数据后标记一次复看，留下当时的观察和数据日期。</p></div>}
      </section>
    </aside>
  );
}

export function FocusPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedSymbol = searchParams.get("symbol");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "pending" | "notes">("all");
  const [adding, setAdding] = useState(false);
  const [symbol, setSymbol] = useState("");
  const [drafts, setDrafts] = useState(loadDrafts);
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null);
  const [startedJob, setStartedJob] = useState<WorkspaceJob | null>(null);
  const focus = useQuery({ queryKey: ["focus"], queryFn: api.focus, retry: false });
  const jobs = useQuery({ queryKey: ["jobs", "focus"], queryFn: () => api.jobs(30), retry: false });
  const latestJob = startedJob ?? jobs.data?.find((job) => job.kind === "market_refresh:focus") ?? null;
  const jobQuery = useQuery({
    queryKey: ["job", latestJob?.job_id], queryFn: () => api.job(latestJob!.job_id),
    enabled: Boolean(latestJob), initialData: latestJob ?? undefined,
    refetchInterval: (query) => terminalJob(query.state.data) ? false : 1200,
  });
  const visibleJob = jobQuery.data ?? latestJob;
  const refreshing = Boolean(visibleJob && !terminalJob(visibleJob));
  useEffect(() => {
    if (terminalJob(visibleJob)) void queryClient.invalidateQueries({ queryKey: ["focus"] });
  }, [visibleJob?.job_id, visibleJob?.status, queryClient]);
  useEffect(() => {
    try { if (Object.keys(drafts).length) sessionStorage.setItem(DRAFT_KEY, JSON.stringify(drafts)); else sessionStorage.removeItem(DRAFT_KEY); } catch { /* 笔记仍可显式保存到本机工作区。 */ }
  }, [drafts]);
  const rows = focus.data?.rows ?? [];
  const pendingCount = rows.filter((row) => row.available && !row.reviewed).length;
  const notesCount = rows.filter((row) => row.note || row.candidates?.some((item) => item.note)).length;
  const query = search.trim().toLowerCase();
  const visibleRows = rows.filter((row) => (!query || row.symbol.includes(query) || row.name.toLowerCase().includes(query)) && (filter !== "pending" || (row.available && !row.reviewed)) && (filter !== "notes" || row.note || row.candidates?.some((item) => item.note)));
  const selectedRow = selectedSymbol ? rows.find((row) => row.symbol === selectedSymbol) : visibleRows[0];
  const cutoffs = [...new Set(rows.map((row) => row.data_cutoff).filter(Boolean))].sort();
  const cutoffLabel = cutoffs.length > 1 ? `${cutoffs[0]} 至 ${cutoffs.at(-1)}` : cutoffs[0] ?? "暂无本地行情";
  const add = useMutation({
    mutationFn: (value: string) => api.addFocus(value),
    onSuccess: (_, value) => {
      setSymbol(""); setAdding(false); setSearch(""); setFilter("all"); setSearchParams({ symbol: value });
      setNotice({ text: `${value} 已加入关注。尚无行情时，可更新关注数据。`, error: false });
      void queryClient.invalidateQueries({ queryKey: ["focus"] });
    },
    onError: (error) => setNotice({ text: errorMessage(error), error: true }),
  });
  const refresh = useMutation({
    mutationFn: () => api.startMarketRefresh("focus"),
    onSuccess: (job) => { setStartedJob(job); setNotice(null); },
    onError: (error) => setNotice({ text: errorMessage(error), error: true }),
  });
  const submitAdd = (event: FormEvent) => { event.preventDefault(); if (/^\d{6}$/.test(symbol.trim())) add.mutate(symbol.trim()); };
  const clearSavedDraft = (code: string, savedNote: string) => {
    setDrafts((current) => { if (current[code] !== savedNote) return current; const next = { ...current }; delete next[code]; return next; });
    queryClient.setQueryData(["focus"], (current: typeof focus.data) => current ? { ...current, rows: current.rows.map((row) => row.symbol === code ? { ...row, note: savedNote } : row) } : current);
  };
  return (
    <div className={`focus-page${selectedSymbol && selectedRow ? " has-selection" : ""}`}>
      <PageHeader title="我的关注" description="从变化开始，把观察留下来。" actions={<>
        <Button variant="secondary" disabled={!rows.length || refresh.isPending || refreshing} onClick={() => refresh.mutate()}><RefreshCw size={17} className={refreshing ? "spin" : ""} />{refreshing ? "正在更新" : "更新关注数据"}</Button>
        <Button onClick={() => { setAdding(!adding); setNotice(null); }} aria-expanded={adding}><Plus size={18} />添加关注</Button>
      </>} />
      <p className="focus-summary">{focus.isLoading ? "正在读取本机工作区" : <><span>{rows.length} 个关注对象</span><span>{pendingCount} 个待复看</span><span>{cutoffs.length ? `数据截至 ${cutoffLabel}` : "暂无本地行情"}</span>{focus.data?.stale ? <span>{focus.data.stale} 个时效待核</span> : null}</>}</p>
      {adding ? <form className="focus-add" onSubmit={submitAdd}><label htmlFor="focus-add-code">添加明确的研究对象</label><div><input id="focus-add-code" value={symbol} onChange={(event) => setSymbol(event.target.value)} inputMode="numeric" pattern="[0-9]{6}" maxLength={6} placeholder="输入 6 位股票代码" autoFocus required /><Button type="submit" disabled={!/^\d{6}$/.test(symbol.trim()) || add.isPending}>{add.isPending ? "正在添加" : "添加"}</Button><Button variant="ghost" type="button" aria-label="取消添加" onClick={() => setAdding(false)}><X size={18} /></Button></div><p>仅加入你输入的股票；行情在明确更新后获取。</p></form> : null}
      {selectedSymbol && !focus.isLoading && !focus.error && !selectedRow ? <div className="focus-notice" role="status">{selectedSymbol} 不在当前关注列表中。<Button variant="ghost" size="sm" onClick={() => setSearchParams({})}>返回全部关注</Button></div> : null}
      {notice ? <div className={`focus-notice${notice.error ? " is-error" : ""}`} role={notice.error ? "alert" : "status"}>{notice.text}</div> : null}
      {focus.error ? <div role="alert" className="focus-notice is-error">{errorMessage(focus.error)}<Button variant="ghost" size="sm" onClick={() => void focus.refetch()}>重新读取</Button></div> : null}
      {visibleJob ? <div className={`focus-job${["failed", "interrupted", "partial"].includes(visibleJob.status) ? " has-issue" : ""}`} role="status"><RefreshCw size={16} className={refreshing ? "spin" : ""} /><div><strong>{JOB_LABELS[visibleJob.status] ?? visibleJob.status}</strong><span>{visibleJob.message}{visibleJob.total ? ` · ${visibleJob.progress}/${visibleJob.total}` : ""}</span>{visibleJob.error ? <p>{visibleJob.error}</p> : null}</div><Link to="/market" className="text-link">查看任务<ArrowRight size={14} /></Link></div> : null}
      {jobQuery.error ? <p role="alert" className="focus-notice is-error">更新进度暂时无法读取：{errorMessage(jobQuery.error)}<Link to="/market">前往数据管理</Link></p> : null}
      {rows.length && focus.data?.warnings?.length ? <div className="focus-warnings">{focus.data.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}
      {focus.isLoading ? <Loading label="读取关注对象与本地行情" /> : !focus.error && rows.length === 0 ? (
        <section className="focus-onboarding"><div className="focus-onboarding__icon"><Star size={30} strokeWidth={1.5} /></div><h2>从你正在研究的一只股票开始</h2><p>把散落的行情、问题和观察留在同一个地方。下次打开时，接着上次的研究继续。</p><Button onClick={() => setAdding(true)}><Plus size={17} />添加第一个关注</Button><Link className="text-link" to="/trends">先浏览行业与题材<ArrowRight size={16} /></Link><div className="focus-onboarding__steps"><span><strong>01</strong>添加研究对象</span><span><strong>02</strong>核对数据变化</span><span><strong>03</strong>留下观察记录</span></div></section>
      ) : rows.length ? (
        <div className="focus-layout">
          <section className="focus-list" aria-label="关注列表">
            <label className="focus-search"><Search size={18} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称或代码" aria-label="搜索关注名称或代码" />{search ? <button type="button" aria-label="清空搜索" onClick={() => setSearch("")}><X size={15} /></button> : null}</label>
            <div className="focus-filters" role="group" aria-label="关注对象筛选">{([
              ["all", "全部", rows.length], ["pending", "待复看", pendingCount], ["notes", "有笔记", notesCount],
            ] as const).map(([value, label, count]) => <button type="button" key={value} aria-pressed={filter === value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{label}<span>（{count}）</span></button>)}</div>
            <div className="focus-table-wrap"><table className="focus-table"><thead><tr><th>名称</th><th>最新价</th><th title="最新两条缓存行情之间的涨跌，日期见详情">区间涨跌</th><th>30日位置</th><th>复看</th></tr></thead><tbody>{visibleRows.map((row) => (
              <tr key={row.symbol} className={selectedRow?.symbol === row.symbol ? "is-selected" : ""} onClick={() => setSearchParams({ symbol: row.symbol })}>
                <td><button type="button" className="focus-stock" aria-label={`查看 ${row.name || row.symbol} ${row.symbol}`} onClick={() => setSearchParams({ symbol: row.symbol })}><strong>{row.name || row.symbol}</strong><small>{row.symbol}{row.stale && row.available ? " · 时效待核" : ""}</small></button></td><td>{number(row.price)}</td><td><ChangeValue value={row.change_pct} /></td><td><PositionMeter value={row.periods?.find((item) => item.period === 30)?.position_pct} /></td><td><ReviewStatus row={row} /></td>
              </tr>
            ))}</tbody></table></div>
            {!visibleRows.length ? <EmptyState title={search ? "没有匹配的关注对象" : filter === "pending" ? "可用数据已经复看过了" : "还没有观察笔记"} detail={search ? "换一个名称或代码试试，或添加新的研究对象。" : filter === "pending" ? "新的数据日期到来后，会再次进入待复看。缺数据的对象可在「全部」中查看。" : "选中一只股票，写下下次想核对的事实。"} action={<Button variant="secondary" size="sm" onClick={() => { setFilter("all"); setSearch(""); }}>查看全部</Button>} /> : null}
            <Link to="/trends" className="focus-discover"><span><Search size={21} /></span><div><strong>前往发现与筛选</strong><p>从行业、题材或明确条件扩展研究。</p></div><ChevronRight size={17} /></Link>
          </section>
          {selectedRow ? <FocusDetail key={selectedRow.symbol} row={selectedRow} note={drafts[selectedRow.symbol] ?? selectedRow.note} onDraft={(note) => setDrafts((current) => ({ ...current, [selectedRow.symbol]: note }))} onSaved={clearSavedDraft} onBack={() => setSearchParams({})} /> : <div className="focus-detail focus-no-selection"><NotebookPen size={26} /><p>从左侧选择一个对象，核对变化并记录观察。</p></div>}
        </div>
      ) : null}
    </div>
  );
}
