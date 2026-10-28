import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Empty, Loading, Notice } from "../components/ui";
import { errorMessage, shortDate } from "../lib/format";
import { conditionText, UNIVERSE_LABELS } from "../lib/study";

export function StudiesPage() {
  const query = useQuery({ queryKey: ["studies"], queryFn: api.studies });
  const [search, setSearch] = useState("");
  const studies = (query.data ?? []).filter((study) =>
    `${study.title} ${(study.query.codes ?? []).join(" ")}`
      .toLowerCase()
      .includes(search.trim().toLowerCase()),
  );
  return (
    <div className="archive-page">
      <header className="page-heading">
        <div>
          <h1>我的研究</h1>
          <p>保存条件和当时的证据，用最新日线再核对一次。</p>
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
          placeholder="搜索研究名称或代码"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>
      {query.isLoading ? (
        <Loading>读取研究记录</Loading>
      ) : query.error ? (
        <Notice error>{errorMessage(query.error)}</Notice>
      ) : studies.length ? (
        <div className="study-archive">
          {studies.map((study) => (
            <Link
              key={study.study_id}
              to={`/studies/${study.study_id}`}
              className="study-archive-row"
            >
              <div>
                <h2>{study.title}</h2>
                <p>{study.query.conditions.map(conditionText).join(" · ")}</p>
                <small>
                  {UNIVERSE_LABELS[study.query.universe]} ·{" "}
                  {study.query.lookback_days} 个交易日 ·{" "}
                  {shortDate(study.last_run_at)}
                </small>
              </div>
              <div className="archive-count">
                <strong>{study.current_count}</strong>
                <span>当前匹配</span>
              </div>
              <div className="archive-count">
                <strong>{study.event_count}</strong>
                <span>历史样本</span>
              </div>
              <ArrowRight size={18} />
            </Link>
          ))}
        </div>
      ) : (
        <Empty title={search ? "没有匹配的研究" : "让一个问题留下可核对的答案"}>
          <p>
            从趋势地图圈定一片区域，或明确写下自己的日线条件。每次运行都会自动保留。
          </p>
          <Link className="button button--primary" to="/">
            发现趋势
            <ArrowRight size={16} />
          </Link>
        </Empty>
      )}
    </div>
  );
}
