import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Pencil,
  RefreshCw,
  Search,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  type ObservationRecord,
  type ObservationReviewResult,
} from "../api/client";
import { BreadthBar, BreadthHistory } from "../components/DiscoveryCharts";
import { Button, Loading, Notice } from "../components/ui";
import { errorMessage, number, percent, shortDate } from "../lib/format";
import "../styles/observations.css";

function readEditDraft(key: string): { title: string; note: string } | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) ?? "null");
    return typeof saved?.title === "string" && typeof saved?.note === "string"
      ? saved
      : null;
  } catch {
    return null;
  }
}

function ObservationBody({ record }: { record: ObservationRecord }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const draftKey = `manmankan.observation-edit:${record.id}`;
  const [initialDraft] = useState(() => readEditDraft(draftKey));
  const [editing, setEditing] = useState(Boolean(initialDraft));
  const [restoredDraft, setRestoredDraft] = useState(Boolean(initialDraft));
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [title, setTitle] = useState(initialDraft?.title ?? record.title);
  const [note, setNote] = useState(initialDraft?.note ?? record.note);
  useEffect(() => {
    if (editing)
      sessionStorage.setItem(draftKey, JSON.stringify({ title, note }));
  }, [draftKey, editing, title, note]);
  const [date, setDate] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const snapshot = record.snapshot;
  const stats = snapshot.group.current;
  const window = record.query.window ?? 20;
  const update = useMutation({
    mutationFn: () =>
      api.updateObservation(record.id, { title: title.trim(), note }),
    onSuccess: (updated) => {
      sessionStorage.removeItem(draftKey);
      client.setQueryData(["observation", record.id], updated);
      void client.invalidateQueries({ queryKey: ["observations"] });
      setEditing(false);
    },
  });
  const review = useMutation({
    mutationFn: () => api.reviewObservation(record.id, date || null),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteObservation(record.id),
    onSuccess: () => {
      client.removeQueries({
        queryKey: ["observation", record.id],
        exact: true,
      });
      void client.invalidateQueries({ queryKey: ["observations"] });
      navigate("/studies", { replace: true });
    },
  });
  const checked = review.data;
  const currentMembers = useMemo(
    () =>
      new Map(
        checked?.current.members.map((member) => [member.symbol, member]) ?? [],
      ),
    [checked],
  );
  const members = snapshot.members.filter((member) =>
    `${member.symbol} ${member.name} ${member.industry}`
      .toLowerCase()
      .includes(search.trim().toLowerCase()),
  );
  const comparison = checked?.comparison;
  const readonlyQuery = {
    ...record.query,
    universe: "codes",
    codes: snapshot.members.map((member) => member.symbol),
    industries: [],
    as_of: snapshot.as_of,
  };
  return (
    <div className="observation-page">
      <Link className="observation-back" to="/studies">
        <ArrowLeft size={15} />
        我的研究
      </Link>
      <header className="observation-heading">
        <div>
          <p>观察记录 · {record.scope_label}</p>
          <h1>{record.title}</h1>
          <span>
            记录于 {shortDate(record.created_at)} · 原观察截至 {snapshot.as_of}
          </span>
        </div>
        <Link
          to="/"
          state={{ discoveryQuery: readonlyQuery }}
          className="discovery-text-link"
        >
          回到这个范围
          <ArrowRight size={15} />
        </Link>
      </header>
      <section className="observation-note">
        <header>
          <h2>当时的想法</h2>
          {!editing ? (
            <button
              type="button"
              className="discovery-text-link"
              disabled={remove.isPending}
              onClick={() => {
                setDeleteOpen(false);
                setRestoredDraft(false);
                setTitle(record.title);
                setNote(record.note);
                setEditing(true);
              }}
            >
              <Pencil size={14} />
              编辑标题与想法
            </button>
          ) : null}
        </header>
        {editing ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (title.trim()) update.mutate();
            }}
          >
            {restoredDraft ? (
              <p className="observation-draft-notice" role="status">
                已恢复尚未保存的编辑草稿，原记录还没有改变。
              </p>
            ) : null}
            <label>
              观察标题
              <input
                value={title}
                required
                maxLength={120}
                disabled={update.isPending}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label>
              自己的想法
              <textarea
                rows={4}
                maxLength={4000}
                value={note}
                disabled={update.isPending}
                onChange={(event) => setNote(event.target.value)}
              />
            </label>
            {update.error ? (
              <Notice error>{errorMessage(update.error)}</Notice>
            ) : null}
            <div className="button-row">
              <Button
                type="submit"
                disabled={!title.trim() || update.isPending}
              >
                {update.isPending ? "正在保存…" : "保存修改"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={update.isPending}
                onClick={() => {
                  sessionStorage.removeItem(draftKey);
                  setEditing(false);
                  setRestoredDraft(false);
                }}
              >
                取消
              </Button>
            </div>
          </form>
        ) : (
          <p
            className={
              record.note ? "saved-observation-note" : "observation-note-empty"
            }
          >
            {record.note ||
              "还没有写下自己的想法。可以先留住事实，再补上想核对的问题。"}
          </p>
        )}
      </section>
      <section className="observation-original">
        <header className="observation-section-heading">
          <div>
            <h2>留下的事实</h2>
            <p>
              {snapshot.current_start} → {snapshot.as_of} · {window} 个交易日 ·
              固定 {snapshot.members.length} 只成员
            </p>
          </div>
          <span>
            <Check size={13} />
            已保存当时的统计与成员
          </span>
        </header>
        <div className="observation-original-layout">
          <div>
            <div className="observation-facts">
              <div>
                <span>上涨占比</span>
                <strong>{percent(stats.positive_share)}</strong>
                <small>
                  {stats.up} / {stats.available} 只
                </small>
              </div>
              <div>
                <span>涨跌中位数</span>
                <strong>{percent(stats.median_return, 2)}</strong>
                <small>按成员等权统计</small>
              </div>
              <div>
                <span>资料不足</span>
                <strong>{number(stats.missing, 0)}</strong>
                <small>完整范围 {number(snapshot.group.total, 0)} 只</small>
              </div>
            </div>
            <BreadthBar stats={stats} />
            {snapshot.group.observations
              .slice(0, 2)
              .map((observation, index) => (
                <p
                  className="observation-original-statement"
                  key={`${observation.kind}-${index}`}
                >
                  {observation.detail}
                </p>
              ))}
          </div>
          <BreadthHistory group={snapshot.group} window={window} />
        </div>
      </section>
      <section className="observation-review">
        <header className="observation-section-heading">
          <div>
            <h2>用同一批成员，再看一次</h2>
            <p>
              保持保存时的 {snapshot.members.length} 只成员与 {window}{" "}
              日窗口。复看保留原记录和自己的想法。
            </p>
          </div>
        </header>
        <p className="observation-window-definition">
          两次观察的滚动窗口可能重叠。这里比较各自窗口的涨跌，不是从原观察日期持有到本次日期的收益。
        </p>
        <form
          className="observation-review-form"
          onSubmit={(event) => {
            event.preventDefault();
            review.mutate();
          }}
        >
          <label>
            复看截至日期
            <input
              type="date"
              min={snapshot.as_of}
              value={date}
              disabled={review.isPending}
              onChange={(event) => setDate(event.target.value)}
            />
            <small>留空，明确查看最近完整交易日</small>
          </label>
          <Button type="submit" disabled={review.isPending}>
            <RefreshCw size={15} className={review.isPending ? "spin" : ""} />
            {review.isPending ? "正在复看…" : "开始复看"}
          </Button>
        </form>
        {review.isPending ? (
          <Loading>正在按保存的完整成员读取日线并核对变化</Loading>
        ) : review.error ? (
          <Notice error>{errorMessage(review.error)}</Notice>
        ) : checked && comparison ? (
          <ReviewComparison record={record} checked={checked} />
        ) : (
          <p className="observation-review-empty">
            复看由你明确开始。原观察的事实已经保存在这里。
          </p>
        )}
      </section>
      <section className="observation-members">
        <header className="observation-section-heading">
          <div>
            <h2>{checked ? "逐个成员核对" : "原观察的成员"}</h2>
            <p>始终保留原范围，按代码排列；缺少资料的对象单独标明。</p>
          </div>
          <label className="search-field">
            <Search size={15} />
            <input
              aria-label="查找观察成员"
              placeholder="名称或代码"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
            />
          </label>
        </header>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>原观察 · {snapshot.as_of}</th>
                {checked ? (
                  <th>本次 · {checked.current.as_of}</th>
                ) : (
                  <th>行业</th>
                )}
                <th>资料情况</th>
              </tr>
            </thead>
            <tbody>
              {members.slice(page * 12, (page + 1) * 12).map((member) => {
                const current = currentMembers.get(member.symbol);
                return (
                  <tr key={member.symbol}>
                    <td>
                      <strong>{member.name}</strong>
                      <small>{member.symbol}</small>
                    </td>
                    <td>{percent(member.return_pct, 2)}</td>
                    <td>
                      {checked
                        ? percent(current?.return_pct, 2)
                        : member.industry}
                    </td>
                    <td className="observation-member-reason">
                      {member.return_pct == null
                        ? `原观察：${member.reason || "窗口资料不足"}`
                        : checked && current?.return_pct == null
                          ? `本次：${current?.reason || "窗口资料不足"}`
                          : checked
                            ? "两次窗口完整"
                            : "原窗口完整"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!members.length ? (
          <p className="observation-review-empty">没有符合名称或代码的成员。</p>
        ) : null}
        {members.length > 12 ? (
          <div className="pagination">
            <span>
              {page + 1} / {Math.ceil(members.length / 12)} 页 ·{" "}
              {members.length} 只
            </span>
            <Button
              variant="ghost"
              aria-label="上一页观察成员"
              disabled={!page}
              onClick={() => setPage(page - 1)}
            >
              <ChevronLeft size={15} />
            </Button>
            <Button
              variant="ghost"
              aria-label="下一页观察成员"
              disabled={(page + 1) * 12 >= members.length}
              onClick={() => setPage(page + 1)}
            >
              <ChevronRight size={15} />
            </Button>
          </div>
        ) : null}
      </section>
      <p className="observation-boundary">
        原观察使用保存时的成员范围与行业归属回看指定日期，不代表那个历史日期的完整市场。记录保留当时的统计、成员事实与自己的文字；复看不证明变化原因，也不预测后续走势。
      </p>
      <div className="observation-delete">
        {deleteOpen ? (
          <div className="observation-delete-confirm" role="alert">
            <p>
              删除「{record.title}
              」后，保存的原始事实和自己的想法都会被删除，无法恢复。
            </p>
            <div className="button-row">
              <Button
                variant="danger"
                disabled={remove.isPending || editing}
                onClick={() => remove.mutate()}
              >
                {remove.isPending ? "正在删除…" : "确认删除这条观察"}
              </Button>
              <Button
                variant="ghost"
                disabled={remove.isPending}
                onClick={() => setDeleteOpen(false)}
              >
                保留观察
              </Button>
            </div>
            {remove.error ? (
              <Notice error>{errorMessage(remove.error)}</Notice>
            ) : null}
          </div>
        ) : (
          <button
            type="button"
            className="observation-delete-trigger"
            disabled={editing}
            onClick={() => setDeleteOpen(true)}
          >
            删除这条观察
          </button>
        )}
        {editing ? <p>先保存或取消正在编辑的文字，再删除记录。</p> : null}
      </div>
    </div>
  );
}

function ReviewComparison({
  record,
  checked,
}: {
  record: ObservationRecord;
  checked: ObservationReviewResult;
}) {
  const comparison = checked.comparison;
  const delta = comparison.breadth_delta_pp;
  return (
    <section
      className="observation-review-result"
      aria-label="原观察与本次复看比较"
    >
      <div className="review-comparison-head">
        <h3>
          {record.snapshot.as_of} → {checked.current.as_of}
        </h3>
        <p>
          两次窗口均完整 <strong>{comparison.available}</strong> 只 · 无法比较{" "}
          <strong>{comparison.missing}</strong> 只
        </p>
      </div>
      <div className="review-comparison-layout">
        <table>
          <thead>
            <tr>
              <th>同一批成员</th>
              <th>原观察</th>
              <th>本次复看</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>上涨占比</th>
              <td>{percent(comparison.previous_positive_share)}</td>
              <td>{percent(comparison.current_positive_share)}</td>
            </tr>
            <tr>
              <th>涨跌中位数</th>
              <td>{percent(comparison.previous_median, 2)}</td>
              <td>{percent(comparison.current_median, 2)}</td>
            </tr>
          </tbody>
        </table>
        <div className="review-delta">
          <span>上涨占比变化</span>
          <strong>
            {delta == null
              ? "暂不可比"
              : `${delta > 0 ? "+" : ""}${number(delta, 1)}`}
          </strong>
          {delta != null ? (
            <small>个百分点 · 两次都完整的同一批成员</small>
          ) : null}
        </div>
      </div>
      <div className="review-transitions">
        {checked.transitions.map((item) => (
          <div key={item.key}>
            <span>{item.label}</span>
            <strong>{number(item.count, 0)}</strong>
          </div>
        ))}
      </div>
      <p className="review-coverage-note">
        本次完整窗口 {checked.current.group.current.available} /{" "}
        {checked.current.group.total}{" "}
        只。上表只比较两次都有资料的成员，因此分母可能小于任一单次统计。
      </p>
    </section>
  );
}

export function ObservationPage() {
  const { observationId } = useParams();
  const query = useQuery({
    queryKey: ["observation", observationId],
    queryFn: () => api.observation(observationId!),
    staleTime: Infinity,
  });
  if (query.isPending)
    return (
      <div className="observation-page">
        <Loading>读取已保存的观察与想法</Loading>
      </div>
    );
  if (query.error)
    return (
      <div className="observation-page">
        <Notice error>{errorMessage(query.error)}</Notice>
        <Link to="/studies" className="discovery-text-link">
          返回我的研究
        </Link>
      </div>
    );
  return <ObservationBody key={query.data.id} record={query.data} />;
}
