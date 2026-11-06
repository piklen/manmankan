import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookmarkPlus, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type DiscoveryResult } from "../api/client";
import { errorMessage } from "../lib/format";
import { Button, Notice } from "./ui";

function readDraft(key: string): { title: string; note: string } | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) ?? "null");
    return typeof saved?.title === "string" && typeof saved?.note === "string"
      ? saved
      : null;
  } catch {
    return null;
  }
}

export function SaveObservation({
  result,
  industry,
}: {
  result: DiscoveryResult;
  industry: string | null;
}) {
  const draftKey = useMemo(
    () =>
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
    [result, industry],
  );
  return (
    <ObservationForm
      key={draftKey}
      result={result}
      industry={industry}
      draftKey={draftKey}
    />
  );
}

function ObservationForm({
  result,
  industry,
  draftKey,
}: {
  result: DiscoveryResult;
  industry: string | null;
  draftKey: string;
}) {
  const [initialDraft] = useState(() => readDraft(draftKey));
  const [open, setOpen] = useState(Boolean(initialDraft));
  const [restored, setRestored] = useState(Boolean(initialDraft));
  const scope = industry ?? result.market.name;
  const count =
    (industry
      ? result.industries.find((group) => group.name === industry)
      : result.market
    )?.total ?? 0;
  const [title, setTitle] = useState(
    initialDraft?.title ?? `${scope} · ${result.as_of}`,
  );
  const [note, setNote] = useState(initialDraft?.note ?? "");
  useEffect(() => {
    if (open) sessionStorage.setItem(draftKey, JSON.stringify({ title, note }));
  }, [draftKey, open, title, note]);
  const cancel = () => {
    sessionStorage.removeItem(draftKey);
    setOpen(false);
    setRestored(false);
    setTitle(`${scope} · ${result.as_of}`);
    setNote("");
  };
  const client = useQueryClient();
  const navigate = useNavigate();
  const save = useMutation({
    mutationFn: () =>
      api.saveObservation({
        title: title.trim(),
        note,
        query: {
          ...result.query,
          as_of: result.as_of,
          industries: industry ? [industry] : result.query.industries,
        },
      }),
    onSuccess: (record) => {
      sessionStorage.removeItem(draftKey);
      setOpen(false);
      client.setQueryData(["observation", record.id], record);
      void client.invalidateQueries({ queryKey: ["observations"] });
      navigate(`/observations/${record.id}`);
    },
  });
  if (!open)
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <BookmarkPlus size={16} />
        记下这个观察
      </Button>
    );
  return (
    <form
      className="save-observation-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (title.trim()) save.mutate();
      }}
    >
      <header>
        <div>
          <h3>留住当时的认识</h3>
          <p>
            保存「{scope}」的完整 {count} 只范围与 {result.as_of}{" "}
            的事实。当前分组和名称搜索不会缩小保存范围。
          </p>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="收起观察记录"
          disabled={save.isPending}
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
      {save.error ? <Notice error>{errorMessage(save.error)}</Notice> : null}
      <div className="save-observation-actions">
        <Button type="submit" disabled={save.isPending || !title.trim()}>
          {save.isPending ? "正在核对并保存…" : "保存观察与想法"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={save.isPending}
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
