import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type Candidate, type StudyQuery } from "../api/client";
import { Button, Empty, Loading, Notice } from "../components/ui";
import { errorMessage, number, shortDate } from "../lib/format";
import { parseCodes } from "../lib/study";

const STATUS_LABELS: Record<Candidate["status"], string> = {
  research: "研究中",
  watch: "持续观察",
  selected: "用户已保留",
  rejected: "已排除",
};
const JOB_LABELS: Record<string, string> = {
  queued: "等待中",
  running: "运行中",
  succeeded: "完成",
  partial: "部分完成",
  failed: "失败",
  interrupted: "中断",
};

function NotesTool() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["candidate-lists"],
    queryFn: api.candidateLists,
  });
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [note, setNote] = useState("");
  const [search, setSearch] = useState("");
  const save = useMutation({
    mutationFn: () => api.updateCandidate(selected!, { note }),
    onSuccess: (candidate) => {
      setSelected(candidate);
      void client.invalidateQueries({ queryKey: ["candidate-lists"] });
    },
  });
  const remove = useMutation({
    mutationFn: (candidate: Candidate) => api.deleteCandidate(candidate),
    onSuccess: () => {
      setSelected(null);
      void client.invalidateQueries({ queryKey: ["candidate-lists"] });
      void client.invalidateQueries({ queryKey: ["focus"] });
    },
  });
  const items = (query.data ?? [])
    .flatMap((list) =>
      (list.candidates ?? []).map((candidate) => ({
        candidate,
        listName: list.name,
      })),
    )
    .filter(({ candidate }) =>
      `${candidate.name} ${candidate.symbol} ${candidate.note}`.includes(
        search.trim(),
      ),
    );
  return (
    <section>
      <h2>个人对象与原有笔记</h2>
      <p className="muted">
        已有笔记保留在原列表中。此处管理对象，不产生股票建议。
      </p>
      <label className="search-field">
        <Search size={16} />
        <input
          aria-label="搜索个人笔记"
          placeholder="搜索名称、代码或笔记"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      {query.isLoading ? (
        <Loading />
      ) : query.error ? (
        <Notice error>{errorMessage(query.error)}</Notice>
      ) : (
        <div className="notes-tool">
          <div className="notes-list">
            {items.map(({ candidate, listName }) => (
              <button
                className={
                  selected?.symbol === candidate.symbol &&
                  selected.list_id === candidate.list_id
                    ? "active"
                    : ""
                }
                type="button"
                key={`${candidate.list_id}-${candidate.symbol}`}
                onClick={() => {
                  if (
                    selected &&
                    note !== selected.note &&
                    !window.confirm("当前笔记尚未保存，放弃这次修改？")
                  )
                    return;
                  setSelected(candidate);
                  setNote(candidate.note);
                  save.reset();
                }}
              >
                <strong>
                  {candidate.name || candidate.symbol}
                  <small>{candidate.symbol}</small>
                </strong>
                <span>
                  {listName} · {STATUS_LABELS[candidate.status]}
                </span>
                <p>{candidate.note || "暂无笔记"}</p>
              </button>
            ))}
            {!items.length ? (
              <p className="muted">暂无匹配的个人笔记。</p>
            ) : null}
          </div>
          {selected ? (
            <form
              className="note-editor"
              onSubmit={(event) => {
                event.preventDefault();
                save.mutate();
              }}
            >
              <h3>
                {selected.name} · {selected.symbol}
              </h3>
              <label>
                观察笔记
                <textarea
                  value={note}
                  maxLength={2000}
                  rows={8}
                  onChange={(event) => setNote(event.target.value)}
                />
              </label>
              <div className="button-row">
                <Button
                  type="submit"
                  disabled={save.isPending || note === selected.note}
                >
                  保存笔记
                </Button>
                <Button
                  type="button"
                  variant="danger"
                  onClick={() => {
                    if (
                      window.confirm(
                        `从这个研究列表中移除 ${selected.symbol}？`,
                      )
                    )
                      remove.mutate(selected);
                  }}
                  disabled={remove.isPending}
                >
                  <Trash2 size={14} />
                  移出列表
                </Button>
              </div>
              {save.isSuccess ? <Notice>笔记已保存。</Notice> : null}
              {save.error || remove.error ? (
                <Notice error>
                  {errorMessage(save.error || remove.error)}
                </Notice>
              ) : null}
            </form>
          ) : (
            <div className="note-editor muted">
              选择对象查看或修改原有笔记。
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function PersonalTool() {
  const client = useQueryClient();
  const [code, setCode] = useState("");
  const query = useQuery({ queryKey: ["focus"], queryFn: api.focus });
  const add = useMutation({
    mutationFn: () => api.addFocus(code),
    onSuccess: () => {
      setCode("");
      void client.invalidateQueries({ queryKey: ["focus"] });
      void client.invalidateQueries({ queryKey: ["candidate-lists"] });
    },
  });
  return (
    <>
      <section className="data-section">
        <h2>个人股票池</h2>
        <p className="muted">
          汇集你的自选、持仓与未排除研究对象。只把你明确添加的股票纳入研究范围。
        </p>
        <form
          className="inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate();
          }}
        >
          <label>
            添加股票
            <input
              aria-label="添加个人池股票代码"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="6 位代码"
              required
            />
          </label>
          <Button type="submit" disabled={add.isPending}>
            <Plus size={16} />
            添加
          </Button>
        </form>
        {add.error ? (
          <Notice error>{errorMessage(add.error)}</Notice>
        ) : add.isSuccess ? (
          <Notice>已添加到个人池。</Notice>
        ) : null}
        {query.isLoading ? (
          <Loading />
        ) : query.error ? (
          <Notice error>{errorMessage(query.error)}</Notice>
        ) : (
          <p className="pool-summary">
            <strong>{query.data?.total ?? 0}</strong> 个个人对象 ·{" "}
            {query.data?.available ?? 0} 个有本地行情
          </p>
        )}
      </section>
      <section className="data-section">
        <NotesTool />
      </section>
    </>
  );
}

function HoldingsTool() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const [cash, setCash] = useState("");
  const [position, setPosition] = useState({ code: "", cost: "", shares: "" });
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["portfolio"] });
    void client.invalidateQueries({ queryKey: ["focus"] });
  };
  const saveCash = useMutation({
    mutationFn: () => api.updateCash(Number(cash)),
    onSuccess: () => {
      setCash("");
      refresh();
    },
  });
  const savePosition = useMutation({
    mutationFn: () =>
      api.addPosition({
        code: position.code,
        cost: Number(position.cost),
        shares: Number(position.shares),
      }),
    onSuccess: () => {
      setPosition({ code: "", cost: "", shares: "" });
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: api.deletePosition,
    onSuccess: refresh,
  });
  return (
    <section className="data-section">
      <h2>本地持仓账本</h2>
      <p className="muted">
        保留你录入的成本、数量和现金；只计算账户事实，不连接券商。
      </p>
      {query.isLoading ? (
        <Loading />
      ) : query.error ? (
        <Notice error>{errorMessage(query.error)}</Notice>
      ) : (
        <>
          <div className="account-facts">
            <span>
              现金 <strong>{number(query.data?.account.cash)}</strong>
            </span>
            <span>
              持仓市值{" "}
              <strong>{number(query.data?.account.total_market_value)}</strong>
            </span>
            <span>
              总资产 <strong>{number(query.data?.account.total_assets)}</strong>
            </span>
            <small>行情日 {query.data?.data_cutoff ?? "未知"}</small>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>数量</th>
                  <th>成本</th>
                  <th>缓存价格</th>
                  <th>市值</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {query.data?.rows?.map((row) => (
                  <tr key={row.code}>
                    <td>
                      <strong>{row.name}</strong>
                      <small>{row.code}</small>
                    </td>
                    <td>{number(row.shares, 0)}</td>
                    <td>{number(row.cost)}</td>
                    <td>{number(row.price)}</td>
                    <td>{number(row.market_value)}</td>
                    <td>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`删除 ${row.code} 持仓`}
                        onClick={() => {
                          if (
                            window.confirm(`删除 ${row.code} 的本地持仓记录？`)
                          )
                            remove.mutate(row.code);
                        }}
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {query.data?.error ? <Notice error>{query.data.error}</Notice> : null}
        </>
      )}
      <div className="data-form-columns">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            savePosition.mutate();
          }}
        >
          <h3>录入或更新持仓</h3>
          <label>
            股票代码
            <input
              pattern="[0-9]{6}"
              required
              maxLength={6}
              value={position.code}
              onChange={(event) =>
                setPosition({ ...position, code: event.target.value })
              }
            />
          </label>
          <div className="field-row">
            <label>
              持仓成本
              <input
                type="number"
                min="0.0001"
                step="0.0001"
                required
                value={position.cost}
                onChange={(event) =>
                  setPosition({ ...position, cost: event.target.value })
                }
              />
            </label>
            <label>
              持股数量
              <input
                type="number"
                min="1"
                step="1"
                required
                value={position.shares}
                onChange={(event) =>
                  setPosition({ ...position, shares: event.target.value })
                }
              />
            </label>
          </div>
          <Button disabled={savePosition.isPending} type="submit">
            保存持仓
          </Button>
          {savePosition.error ? (
            <Notice error>{errorMessage(savePosition.error)}</Notice>
          ) : savePosition.isSuccess ? (
            <Notice>持仓已保存。</Notice>
          ) : null}
        </form>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            saveCash.mutate();
          }}
        >
          <h3>账户现金</h3>
          <label>
            可用现金
            <input
              type="number"
              min="0"
              step="0.01"
              required
              value={cash}
              onChange={(event) => setCash(event.target.value)}
            />
          </label>
          <Button type="submit" disabled={saveCash.isPending}>
            保存现金
          </Button>
          {saveCash.error ? (
            <Notice error>{errorMessage(saveCash.error)}</Notice>
          ) : saveCash.isSuccess ? (
            <Notice>现金已保存。</Notice>
          ) : null}
        </form>
      </div>
      {remove.error ? (
        <Notice error>{errorMessage(remove.error)}</Notice>
      ) : null}
    </section>
  );
}

export function DataPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "market";
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: api.jobs,
    refetchInterval: (query) =>
      query.state.data?.some((job) =>
        ["queued", "running"].includes(job.status),
      )
        ? 1500
        : false,
  });
  const [scope, setScope] = useState<StudyQuery["universe"]>("codes");
  const [codes, setCodes] = useState("");
  const [days, setDays] = useState("360");
  const refresh = useMutation({
    mutationFn: () =>
      api.refreshStudyData({
        universe: scope,
        codes: scope === "codes" ? parseCodes(codes) : [],
        days: Number(days),
      }),
    onSuccess: () => void jobs.refetch(),
  });
  const canRefresh =
    scope !== "codes" ||
    (parseCodes(codes).length > 0 &&
      parseCodes(codes).every((code) => /^\d{6}$/.test(code)));
  return (
    <div className="data-page">
      <header className="page-heading">
        <div>
          <h1>数据与个人资料</h1>
          <p>看清数据覆盖，再运行研究。个人资料只保存在本机。</p>
        </div>
      </header>
      <nav className="page-tabs" aria-label="数据工具">
        <button
          className={tab === "market" ? "active" : ""}
          onClick={() => setParams({})}
        >
          行情与任务
        </button>
        <button
          className={tab === "personal" ? "active" : ""}
          onClick={() => setParams({ tab: "personal" })}
        >
          个人池与笔记
        </button>
        <button
          className={tab === "holdings" ? "active" : ""}
          onClick={() => setParams({ tab: "holdings" })}
        >
          持仓账本
        </button>
      </nav>
      {tab === "personal" ? (
        <PersonalTool />
      ) : tab === "holdings" ? (
        <HoldingsTool />
      ) : (
        <>
          <section className="data-section">
            <div className="section-heading">
              <h2>
                <Database size={18} />
                日线数据
              </h2>
              <span>{settings.data?.kline_cache_files ?? "—"} 份本地缓存</span>
            </div>
            {settings.error ? (
              <Notice error>{errorMessage(settings.error)}</Notice>
            ) : (
              <p className="muted">
                TuShare{" "}
                {settings.data?.tushare_configured ? "已配置" : "未配置"} ·
                当前只提供已完成的日线，不提供分钟行情。
              </p>
            )}
            <form
              className="data-refresh-form"
              onSubmit={(event) => {
                event.preventDefault();
                refresh.mutate();
              }}
            >
              <label>
                更新范围
                <select
                  value={scope}
                  onChange={(event) =>
                    setScope(event.target.value as StudyQuery["universe"])
                  }
                >
                  <option value="codes">指定股票代码</option>
                  <option value="personal">我的个人池</option>
                  <option value="all">当前 A 股股票池</option>
                </select>
              </label>
              {scope === "codes" ? (
                <label>
                  股票代码
                  <input
                    value={codes}
                    onChange={(event) => setCodes(event.target.value)}
                    placeholder="填写代码，用逗号分隔"
                    required
                  />
                </label>
              ) : null}
              <label>
                获取日数
                <input
                  type="number"
                  min="180"
                  max="1500"
                  value={days}
                  onChange={(event) => setDays(event.target.value)}
                  required
                />
              </label>
              <Button type="submit" disabled={!canRefresh || refresh.isPending}>
                <RefreshCw size={15} />
                {refresh.isPending ? "正在创建任务" : "更新日线"}
              </Button>
            </form>
            {refresh.error ? (
              <Notice error>{errorMessage(refresh.error)}</Notice>
            ) : refresh.isSuccess ? (
              <Notice>更新任务已创建。完成后回到研究页重新运行。</Notice>
            ) : null}
          </section>
          <section className="data-section">
            <h2>更新任务</h2>
            {jobs.isLoading ? (
              <Loading />
            ) : jobs.error ? (
              <Notice error>{errorMessage(jobs.error)}</Notice>
            ) : jobs.data?.length ? (
              <div className="job-list">
                {jobs.data.map((job) => (
                  <article key={job.job_id}>
                    <span className={`job-state job-state--${job.status}`}>
                      {JOB_LABELS[job.status] ?? job.status}
                    </span>
                    <div>
                      <strong>{job.message || "行情更新"}</strong>
                      <p>
                        {job.progress} / {job.total || "—"} ·{" "}
                        {shortDate(job.updated_at)}
                      </p>
                      {job.error ? (
                        <p className="text-error">{job.error}</p>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <Empty title="还没有更新任务">
                <p>选择明确的股票范围后再更新，不会自动抓取全市场。</p>
              </Empty>
            )}
          </section>
        </>
      )}
    </div>
  );
}
