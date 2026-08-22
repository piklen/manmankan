import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckSquare2,
  GitCompareArrows,
  ListPlus,
  MessageSquareText,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type Candidate,
  type CandidateList,
  type CandidateStatus,
} from "../api/client";
import { Badge, Button, Card, EmptyState, Loading, PageHeader } from "../components/ui";
import { errorMessage, shortDate } from "../lib/format";

const STATUS_META: Record<CandidateStatus, { label: string; tone: "neutral" | "info" | "positive" | "danger" }> = {
  research: { label: "待研究", tone: "info" },
  watch: { label: "持续观察", tone: "neutral" },
  selected: { label: "已入选", tone: "positive" },
  rejected: { label: "已排除", tone: "danger" },
};

function CandidateCard({
  candidate,
  selected,
  onSelect,
  onUpdate,
  onRemove,
  onResearch,
}: {
  candidate: Candidate;
  selected: boolean;
  onSelect: (active: boolean) => void;
  onUpdate: (updates: { status?: CandidateStatus; note?: string }) => void;
  onRemove: () => void;
  onResearch: () => void;
}) {
  const [note, setNote] = useState(candidate.note);
  const meta = STATUS_META[candidate.status];
  return (
    <article className={`candidate-card ${selected ? "is-selected" : ""}`}>
      <div className="candidate-card__select">
        <input
          type="checkbox"
          checked={selected}
          onChange={(event) => onSelect(event.target.checked)}
          aria-label={`选择 ${candidate.name}`}
        />
      </div>
      <button type="button" className="candidate-card__stock" onClick={onResearch}>
        <strong>{candidate.name}</strong>
        <span>{candidate.symbol}</span>
      </button>
      <div className="candidate-card__status">
        <Badge tone={meta.tone}>{meta.label}</Badge>
        <select
          aria-label={`${candidate.name} 状态`}
          value={candidate.status}
          onChange={(event) => onUpdate({ status: event.target.value as CandidateStatus })}
        >
          {Object.entries(STATUS_META).map(([value, item]) => (
            <option key={value} value={value}>{item.label}</option>
          ))}
        </select>
      </div>
      <label className="candidate-card__note">
        <MessageSquareText size={15} />
        <span className="sr-only">研究笔记</span>
        <input
          value={note}
          placeholder="记录下一步要验证的事实…"
          onChange={(event) => setNote(event.target.value)}
          onBlur={() => {
            if (note !== candidate.note) onUpdate({ note });
          }}
        />
      </label>
      <div className="candidate-card__source">
        <span>{candidate.source_run_id ? `来自 run ${candidate.source_run_id.slice(0, 8)}` : "手动加入"}</span>
        <small>{shortDate(candidate.updated_at)}</small>
      </div>
      <button type="button" className="icon-button" onClick={onRemove} aria-label="移出候选">
        <Trash2 size={15} />
      </button>
    </article>
  );
}

export function CandidatesPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [activeListId, setActiveListId] = useState("default");
  const [selected, setSelected] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [newListName, setNewListName] = useState("");
  const [editListName, setEditListName] = useState("");
  const [manualCode, setManualCode] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const listsQuery = useQuery({
    queryKey: ["candidate-lists"],
    queryFn: api.candidateLists,
  });
  const lists = listsQuery.data ?? [];
  const activeList = lists.find((item) => item.list_id === activeListId) ?? lists[0];
  useEffect(() => {
    setEditListName(activeList?.name ?? "");
  }, [activeList?.list_id, activeList?.name]);
  const candidates = useMemo(() => {
    const query = search.trim().toLowerCase();
    const items = activeList?.candidates ?? [];
    if (!query) return items;
    return items.filter(
      (item) => item.symbol.includes(query) || item.name.toLowerCase().includes(query),
    );
  }, [activeList, search]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["candidate-lists"] });
  const createList = useMutation({
    mutationFn: () => api.createCandidateList(newListName),
    onSuccess: (list) => {
      setActiveListId(list.list_id);
      setNewListName("");
      setNotice(`已创建「${list.name}」`);
      void invalidate();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const renameList = useMutation({
    mutationFn: () => api.renameCandidateList(activeList!.list_id, editListName),
    onSuccess: (list) => {
      setNotice(`已重命名为「${list.name}」`);
      void invalidate();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const deleteList = useMutation({
    mutationFn: () => api.deleteCandidateList(activeList!.list_id),
    onSuccess: () => {
      setActiveListId("default");
      setSelected([]);
      setNotice("候选池已删除");
      void invalidate();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const updateCandidate = useMutation({
    mutationFn: ({ candidate, updates }: { candidate: Candidate; updates: { status?: CandidateStatus; note?: string } }) =>
      api.upsertCandidate(candidate.list_id, candidate.symbol, {
        name: candidate.name,
        status: updates.status ?? candidate.status,
        note: updates.note ?? candidate.note,
        source_run_id: candidate.source_run_id,
      }),
    onSuccess: () => void invalidate(),
    onError: (error) => setNotice(errorMessage(error)),
  });
  const removeCandidate = useMutation({
    mutationFn: (candidate: Candidate) => api.deleteCandidate(candidate.list_id, candidate.symbol),
    onSuccess: () => void invalidate(),
    onError: (error) => setNotice(errorMessage(error)),
  });
  const addManual = useMutation({
    mutationFn: () => api.upsertCandidate(activeList?.list_id ?? "default", manualCode, {}),
    onSuccess: (candidate) => {
      setManualCode("");
      setNotice(`${candidate.symbol} 已加入候选`);
      void invalidate();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const createCompare = useMutation({
    mutationFn: () => api.saveCompareSet({
      name: `${activeList?.name ?? "候选"} · 横向对比`,
      symbols: selected,
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["compare-sets"] });
      navigate("/compare");
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const statusCounts = (activeList?.candidates ?? []).reduce<Record<CandidateStatus, number>>(
    (counts, item) => ({ ...counts, [item.status]: counts[item.status] + 1 }),
    { research: 0, watch: 0, selected: 0, rejected: 0 },
  );

  return (
    <div>
      <PageHeader
        eyebrow="Candidate research"
        title="候选不是结论，而是下一步研究队列"
        description="把筛选结果独立保存，记录状态、来源与待验证问题。Screen 变化不会冲掉你的研究进度。"
        actions={
          <>
            {notice ? <span className="notice-pill">{notice}</span> : null}
            <Button
              variant="secondary"
              disabled={selected.length < 3 || createCompare.isPending}
              onClick={() => createCompare.mutate()}
            >
              <GitCompareArrows size={16} /> 对比所选 {selected.length || ""}
            </Button>
          </>
        }
      />

      <div className="candidate-layout">
        <Card className="candidate-sidebar">
          <div className="panel-heading">
            <div><span className="panel-kicker">候选池</span><h2>研究列表</h2></div>
            <ListPlus size={18} />
          </div>
          <div className="candidate-list-tabs">
            {lists.map((list) => (
              <button
                type="button"
                key={list.list_id}
                className={activeList?.list_id === list.list_id ? "is-active" : ""}
                onClick={() => {
                  setActiveListId(list.list_id);
                  setSelected([]);
                }}
              >
                <span>{list.name}</span>
                <small>{list.candidates?.length ?? 0}</small>
              </button>
            ))}
          </div>
          <form
            className="inline-create"
            onSubmit={(event) => {
              event.preventDefault();
              if (newListName.trim()) createList.mutate();
            }}
          >
            <input
              value={newListName}
              onChange={(event) => setNewListName(event.target.value)}
              placeholder="新候选池名称"
            />
            <Button size="sm" variant="ghost" type="submit" aria-label="创建候选池">
              <Plus size={15} />
            </Button>
          </form>
          {activeList && activeList.list_id !== "default" ? (
            <form
              className="candidate-list-management"
              onSubmit={(event) => {
                event.preventDefault();
                if (editListName.trim()) renameList.mutate();
              }}
            >
              <label>
                <span className="sr-only">当前候选池名称</span>
                <input value={editListName} onChange={(event) => setEditListName(event.target.value)} />
              </label>
              <Button size="sm" variant="ghost" type="submit" aria-label="重命名候选池">
                <Pencil size={13} />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                type="button"
                aria-label="删除候选池"
                onClick={() => deleteList.mutate()}
              ><Trash2 size={13} /></Button>
            </form>
          ) : null}
          <div className="candidate-sidebar__tip">
            <CheckSquare2 size={17} />
            <p>建议每只候选都留一个“下次重看条件”，避免候选池变成收藏夹。</p>
          </div>
        </Card>

        <div className="candidate-main">
          <Card className="candidate-stats">
            {Object.entries(STATUS_META).map(([status, meta]) => (
              <div key={status}>
                <span>{meta.label}</span>
                <strong>{statusCounts[status as CandidateStatus]}</strong>
              </div>
            ))}
          </Card>

          <Card className="candidate-board">
            <div className="candidate-toolbar">
              <label className="search-field">
                <Search size={16} />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="搜索代码或名称"
                />
              </label>
              <form
                className="manual-add"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (manualCode.trim()) addManual.mutate();
                }}
              >
                <input
                  value={manualCode}
                  onChange={(event) => setManualCode(event.target.value)}
                  placeholder="6 位股票代码"
                  inputMode="numeric"
                />
                <Button size="sm" type="submit"><Plus size={15} /> 手动加入</Button>
              </form>
            </div>

            {listsQuery.isLoading ? <Loading label="读取候选池" /> : null}
            {!listsQuery.isLoading && candidates.length === 0 ? (
              <EmptyState
                title="这个候选池还是空的"
                detail="从选股结果加入，或输入一只你已经想研究的股票。"
                action={<Button size="sm" onClick={() => navigate("/screen")}>去运行 Screen</Button>}
              />
            ) : null}
            <div className="candidate-cards">
              {candidates.map((candidate) => (
                <CandidateCard
                  key={candidate.symbol}
                  candidate={candidate}
                  selected={selected.includes(candidate.symbol)}
                  onSelect={(active) =>
                    setSelected((current) =>
                      active
                        ? [...new Set([...current, candidate.symbol])].slice(0, 10)
                        : current.filter((item) => item !== candidate.symbol),
                    )
                  }
                  onUpdate={(updates) => updateCandidate.mutate({ candidate, updates })}
                  onRemove={() => removeCandidate.mutate(candidate)}
                  onResearch={() => navigate(`/research/${candidate.symbol}`)}
                />
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
