import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Empty, Loading, Notice } from "../components/ui";
import { errorMessage, shortDate } from "../lib/format";
import { conditionText, UNIVERSE_LABELS } from "../lib/study";

export function StudiesPage() {
  const studies = useQuery({ queryKey: ["studies"], queryFn: api.studies });
  const observations = useQuery({
    queryKey: ["observations"],
    queryFn: api.observations,
  });
  const [search, setSearch] = useState("");
  const records = [
    ...(studies.data ?? []).map((study) => ({
      kind: "study" as const,
      value: study,
      at: study.last_run_at,
      text: `${study.title} ${(study.query.codes ?? []).join(" ")}`,
    })),
    ...(observations.data ?? []).map((observation) => ({
      kind: "observation" as const,
      value: observation,
      at: observation.created_at,
      text: `${observation.title} ${observation.note} ${observation.scope_label}`,
    })),
  ]
    .filter((record) =>
      record.text.toLowerCase().includes(search.trim().toLowerCase()),
    )
    .sort((a, b) => b.at.localeCompare(a.at));
  return (
    <div className="archive-page">
      <header className="page-heading">
        <div>
          <h1>我的研究</h1>
          <p>留住当时的观察和想法，再用同一批成员核对变化。</p>
        </div>
        <Link className="button button--secondary" to="/studies/new">
          <Plus size={16} />
          自定义条件研究
        </Link>
      </header>
      <label className="search-field">
        <Search size={17} />
        <input
          aria-label="搜索研究记录"
          placeholder="搜索名称、想法或代码"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      {observations.error ? (
        <Notice error>观察记录：{errorMessage(observations.error)}</Notice>
      ) : null}
      {studies.error ? (
        <Notice error>条件研究：{errorMessage(studies.error)}</Notice>
      ) : null}
      {records.length ? (
        <div className="study-archive">
          {records.map((record) =>
            record.kind === "observation" ? (
              <Link
                key={`observation-${record.value.id}`}
                to={`/observations/${record.value.id}`}
                className="study-archive-row"
              >
                <div>
                  <span className="research-record-kind">观察记录</span>
                  <h2>{record.value.title}</h2>
                  <p>
                    {record.value.note ||
                      "已保留当时的群体事实，自己的想法可随时补充。"}
                  </p>
                  <small>
                    {record.value.scope_label} · {record.value.window} 日窗口 ·
                    观察截至 {record.value.as_of}
                  </small>
                </div>
                <div className="archive-count">
                  <strong>{record.value.total}</strong>
                  <span>固定成员</span>
                </div>
                <ArrowRight size={18} />
              </Link>
            ) : (
              <Link
                key={`study-${record.value.study_id}`}
                to={`/studies/${record.value.study_id}`}
                className="study-archive-row"
              >
                <div>
                  <span className="research-record-kind">条件研究</span>
                  <h2>{record.value.title}</h2>
                  <p>
                    {record.value.query.conditions
                      .map(conditionText)
                      .join(" · ")}
                  </p>
                  <small>
                    {UNIVERSE_LABELS[record.value.query.universe]} ·{" "}
                    {record.value.query.lookback_days} 个交易日 ·{" "}
                    {shortDate(record.value.last_run_at)}
                  </small>
                </div>
                <div className="archive-count">
                  <strong>{record.value.current_count}</strong>
                  <span>当前匹配</span>
                </div>
                <div className="archive-count">
                  <strong>{record.value.event_count}</strong>
                  <span>历史样本</span>
                </div>
                <ArrowRight size={18} />
              </Link>
            ),
          )}
        </div>
      ) : studies.isPending || observations.isPending ? (
        <Loading>读取观察与研究记录</Loading>
      ) : !studies.error && !observations.error ? (
        <Empty title={search ? "没有匹配的研究" : "把一个观察，留给下一次核对"}>
          <p>
            在市场观察中记下一个现象和自己的想法；已有明确条件时，也可以直接做历史研究。
          </p>
          <Link className="button button--primary" to="/">
            去市场观察
            <ArrowRight size={16} />
          </Link>
        </Empty>
      ) : null}
    </div>
  );
}
