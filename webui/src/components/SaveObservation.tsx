import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookmarkPlus, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  ApiError,
  type DiscoveryGroup,
  type DiscoveryResult,
} from "../api/client";
import { errorMessage, number, percent } from "../lib/format";
import { Button, Notice } from "./ui";

type DraftFacts = Pick<
  DiscoveryGroup["current"],
  "total" | "available" | "up" | "median_return"
>;
type ObservationDraft = {
  title: string;
  note: string;
  fingerprint?: string | null;
  facts?: DraftFacts | null;
  conflict?: boolean;
  needsReview?: boolean;
};
function readDraft(key: string): ObservationDraft | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) ?? "null");
    return typeof saved?.title === "string" && typeof saved?.note === "string"
      ? saved
      : null;
  } catch {
    return null;
  }
}
function summary(group?: DiscoveryGroup): DraftFacts | null {
  if (!group) return null;
  const { total, available, up, median_return } = group.current;
  return { total, available, up, median_return };
}

export function SaveObservation({
  result,
  industry,
  onRefresh,
}: {
  result: DiscoveryResult;
  industry: string | null;
  onRefresh: () => Promise<void>;
}) {
  const keys = useMemo(
    () => ({
      draft:
        "manmankan.observation-draft:query:" +
        JSON.stringify({
          universe: result.query.universe,
          codes: [...(result.query.codes ?? [])].sort(),
          industries: [...(result.query.industries ?? [])].sort(),
          as_of: result.as_of,
          window: result.query.window ?? 20,
          industry,
        }),
      // 已有会话中的文字可继续恢复；没有事实版本的旧草稿需要重新核对。
      previous:
        "manmankan.observation-draft:" +
        JSON.stringify({
          as_of: result.as_of,
          window: result.query.window ?? 20,
          industry,
          codes: result.members
            .filter((member) => !industry || member.industry === industry)
            .map((member) => member.symbol)
            .sort(),
        }),
    }),
    [result, industry],
  );
  return (
    <ObservationForm
      key={keys.draft}
      result={result}
      industry={industry}
      draftKey={keys.draft}
      previousKey={keys.previous}
      onRefresh={onRefresh}
    />
  );
}

function ObservationForm({
  result,
  industry,
  draftKey,
  previousKey,
  onRefresh,
}: {
  result: DiscoveryResult;
  industry: string | null;
  draftKey: string;
  previousKey: string;
  onRefresh: () => Promise<void>;
}) {
  const group = industry
    ? result.industries.find((item) => item.name === industry)
    : result.market;
  const scope =
    industry ??
    { all: "全市场", personal: "个人池", codes: "指定股票" }[
      result.query.universe ?? "all"
    ];
  const currentFingerprint = group?.fingerprint || null;
  const [initialDraft] = useState(
    () => readDraft(draftKey) ?? readDraft(previousKey),
  );
  const [open, setOpen] = useState(Boolean(initialDraft));
  const [restored, setRestored] = useState(Boolean(initialDraft));
  const [title, setTitle] = useState(
    initialDraft?.title ?? `${scope} · ${result.as_of}`,
  );
  const [note, setNote] = useState(initialDraft?.note ?? "");
  const [fingerprint, setFingerprint] = useState(
    initialDraft ? (initialDraft.fingerprint ?? null) : currentFingerprint,
  );
  const [facts, setFacts] = useState(
    initialDraft ? (initialDraft.facts ?? null) : summary(group),
  );
  const [conflict, setConflict] = useState(
    Boolean(
      initialDraft?.conflict && initialDraft.fingerprint === currentFingerprint,
    ),
  );
  const [needsReview, setNeedsReview] = useState(
    Boolean(initialDraft?.needsReview),
  );
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const changed = fingerprint !== currentFingerprint || needsReview;
  const canSave = Boolean(
    currentFingerprint && !changed && !conflict && !refreshing,
  );
  const client = useQueryClient();
  const navigate = useNavigate();
  useEffect(() => {
    if (open)
      sessionStorage.setItem(
        draftKey,
        JSON.stringify({
          title,
          note,
          fingerprint,
          facts,
          conflict,
          needsReview,
        }),
      );
  }, [draftKey, open, title, note, fingerprint, facts, conflict, needsReview]);
  const clearDraft = () => {
    sessionStorage.removeItem(draftKey);
    sessionStorage.removeItem(previousKey);
  };
  const cancel = () => {
    clearDraft();
    setOpen(false);
    setRestored(false);
    setTitle(`${scope} · ${result.as_of}`);
    setNote("");
    setFingerprint(currentFingerprint);
    setFacts(summary(group));
    setConflict(false);
    setNeedsReview(false);
  };
  const save = useMutation({
    mutationFn: () =>
      api.saveObservation({
        title: title.trim(),
        note,
        expected_fingerprint: fingerprint!,
        query: {
          ...result.query,
          as_of: result.as_of,
          industries: industry ? [industry] : result.query.industries,
        },
      }),
    onError: (error) => {
      if (error instanceof ApiError && error.code === "observation_changed")
        setConflict(true);
    },
    onSuccess: (record) => {
      clearDraft();
      setOpen(false);
      client.setQueryData(["observation", record.id], record);
      void client.invalidateQueries({ queryKey: ["observations"] });
      navigate(`/observations/${record.id}`);
    },
  });
  const refreshFacts = async () => {
    setRefreshing(true);
    setRefreshError("");
    try {
      await onRefresh();
      setConflict(false);
      setNeedsReview(true);
      save.reset();
    } catch (error) {
      setRefreshError(errorMessage(error));
    } finally {
      setRefreshing(false);
    }
  };
  const confirmFacts = () => {
    setFingerprint(currentFingerprint);
    setFacts(summary(group));
    setNeedsReview(false);
    setConflict(false);
    save.reset();
  };
  if (!open)
    return (
      <Button type="button" variant="secondary" onClick={() => setOpen(true)}>
        <BookmarkPlus size={16} />
        {`记下${scope}观察`}
      </Button>
    );
  return (
    <form
      className="save-observation-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (title.trim() && canSave) save.mutate();
      }}
    >
      <header>
        <div>
          <h3>留住当时的认识</h3>
          <p>
            保存「{scope}」的完整 {group?.total ?? 0} 只范围与 {result.as_of}{" "}
            的事实。当前分组和名称搜索不会缩小保存范围。
          </p>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="收起观察记录"
          disabled={save.isPending || refreshing}
          onClick={() => setOpen(false)}
        >
          <X size={18} />
        </button>
      </header>
      {restored ? (
        <p className="observation-draft-notice" role="status">
          已恢复这个范围、日期与窗口的草稿，仅保留在本次会话，尚未保存为观察记录。
        </p>
      ) : null}
      {conflict || changed ? (
        <section
          className="observation-facts-changed"
          aria-label="保存前核对资料变化"
        >
          <h4>
            {conflict
              ? "保存前发现资料变化，尚未保存"
              : "资料已经更新，请先核对"}
          </h4>
          <p>
            你的标题和想法保持原文。核对当前事实后，可以继续修改，再明确保存。
          </p>
          {conflict ? (
            <Button
              type="button"
              variant="secondary"
              disabled={refreshing}
              onClick={() => void refreshFacts()}
            >
              <RefreshCw size={15} className={refreshing ? "spin" : ""} />
              {refreshing ? "正在读取新事实…" : "查看更新后的事实"}
            </Button>
          ) : (
            <>
              {group ? (
                <>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>同一观察范围</th>
                          <th>写下想法时</th>
                          <th>当前资料</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <th>完整成员</th>
                          <td>{number(facts?.total, 0)}</td>
                          <td>{group.current.total}</td>
                        </tr>
                        <tr>
                          <th>可判断成员</th>
                          <td>{number(facts?.available, 0)}</td>
                          <td>{group.current.available}</td>
                        </tr>
                        <tr>
                          <th>上涨成员</th>
                          <td>{number(facts?.up, 0)}</td>
                          <td>{group.current.up}</td>
                        </tr>
                        <tr>
                          <th>涨跌中位数</th>
                          <td>{percent(facts?.median_return, 2)}</td>
                          <td>{percent(group.current.median_return, 2)}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <p>
                    同时核对逐个成员与历史轨迹；摘要相同，具体事实仍可能变化。
                  </p>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={refreshing}
                    onClick={confirmFacts}
                  >
                    已核对当前事实，继续填写
                  </Button>
                </>
              ) : (
                <p>这个行业已不在当前范围中。草稿仍保留，请先核对观察范围。</p>
              )}
            </>
          )}
          {refreshError ? <Notice error>{refreshError}</Notice> : null}
        </section>
      ) : null}
      <label>
        观察标题
        <input
          value={title}
          maxLength={120}
          required
          disabled={save.isPending}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      <label>
        当时的想法 <span>可留空</span>
        <textarea
          aria-label="当时的想法"
          value={note}
          rows={3}
          maxLength={4000}
          disabled={save.isPending}
          onChange={(event) => setNote(event.target.value)}
          placeholder="你看到了什么？下一次想核对什么变化？"
        />
      </label>
      {save.error && !conflict ? (
        <Notice error>{errorMessage(save.error)}</Notice>
      ) : null}
      <div className="save-observation-actions">
        <Button
          type="submit"
          disabled={save.isPending || !title.trim() || !canSave}
        >
          {save.isPending ? "正在核对并保存…" : "保存观察与想法"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={save.isPending || refreshing}
          onClick={cancel}
        >
          取消记录并清除草稿
        </Button>
        <span>
          {save.isPending
            ? "正在核对这一天的完整范围，通常需要几秒。"
            : "保存后，在“我的研究”里继续复看。"}
        </span>
      </div>
    </form>
  );
}
