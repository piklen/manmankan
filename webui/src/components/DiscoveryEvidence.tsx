import { useQuery } from "@tanstack/react-query";
import { ArrowRight, X } from "lucide-react";
import { Link } from "react-router-dom";
import {
  api,
  type DiscoveryMember,
  type DiscoveryResult,
  type StudyEvidence,
  type TrendSearchQuery,
} from "../api/client";
import { errorMessage, number, percent } from "../lib/format";
import { StudyChart } from "./StudyChart";
import { Loading, Notice } from "./ui";

export function DiscoveryEvidence({
  member,
  result,
  revision,
  onClose,
  recorded = false,
}: {
  member: DiscoveryMember;
  result: Pick<
    DiscoveryResult,
    "as_of" | "current_start" | "previous_start" | "previous_as_of" | "query"
  >;
  revision: number;
  onClose: () => void;
  recorded?: boolean;
}) {
  const query: TrendSearchQuery = {
    universe: "codes",
    codes: [member.symbol],
    as_of: result.as_of,
    conditions: [],
    swing_reversal_pct: 5,
  };
  const evidence = useQuery({
    queryKey: ["discovery-evidence", member.symbol, result.as_of, revision],
    queryFn: () => api.trendEvidence(query, member.symbol),
    enabled: recorded || member.latest_available,
    staleTime: Infinity,
    retry: false,
  });
  const data = evidence.data;
  const chart: StudyEvidence | null = data
    ? {
        run_id: "discovery",
        symbol: member.symbol,
        name: member.name,
        event_date: result.as_of,
        source: data.row.source,
        bars: data.bars,
        conditions: [],
        outcome: null,
        warnings: data.warnings,
        swings: data.swings,
      }
    : null;
  return (
    <section
      className="discovery-evidence"
      aria-label={`${member.name}价格证据`}
    >
      <header>
        <div>
          <span>
            {member.symbol} · {member.industry}
          </span>
          <h3>{member.name}</h3>
        </div>
        <button
          type="button"
          className="icon-button"
          onClick={onClose}
          aria-label="关闭价格证据"
        >
          <X size={20} />
        </button>
      </header>
      <div className="evidence-periods">
        <div>
          <span>
            本期 · {result.current_start} → {result.as_of}
          </span>
          <strong
            className={
              member.return_pct == null
                ? ""
                : member.return_pct >= 0
                  ? "value-up"
                  : "value-down"
            }
          >
            {percent(member.return_pct, 2)}
          </strong>
        </div>
        <div>
          <span>
            前期 · {result.previous_start} → {result.previous_as_of}
          </span>
          <strong>{percent(member.previous_return_pct, 2)}</strong>
        </div>
      </div>
      {recorded ? (
        <p className="evidence-period-note">
          上方数字保留所选观察的统计。下方日线按当前本地资料回看该日期；原记录没有冻结逐日日线，资料修订可能使图中变化与存档不同。
        </p>
      ) : null}
      {!recorded && !member.latest_available ? (
        <Notice>
          {member.reason || "截止日缺少有效行情，无法绘制价格证据。"}
        </Notice>
      ) : evidence.isPending ? (
        <Loading>读取同一日期的价格证据</Loading>
      ) : evidence.error ? (
        <Notice error>{errorMessage(evidence.error)}</Notice>
      ) : chart ? (
        <>
          <StudyChart
            evidence={chart}
            context="market"
            tone="light"
            observation={{
              start: result.previous_start,
              boundary: result.current_start,
              window: result.query.window ?? 20,
            }}
          />
          <p className="evidence-period-note">
            分界日 {result.current_start ?? "尚无资料"}{" "}
            的收盘，是前期终点和本期起点；两期各比较 {result.query.window ?? 20}{" "}
            次收盘变化。
          </p>
        </>
      ) : null}
      {data ? (
        <details className="chart-data">
          <summary>逐日收盘与变化</summary>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>日期</th>
                  <th>收盘</th>
                  <th>较前日</th>
                </tr>
              </thead>
              <tbody>
                {data.bars
                  .slice(-2 * (result.query.window ?? 20) - 1)
                  .reverse()
                  .map((bar) => (
                    <tr key={bar.date}>
                      <td>{bar.date}</td>
                      <td>{number(bar.close)}</td>
                      <td>{percent(bar.change_pct, 2)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
      <footer>
        <span>
          来源 {data?.row.source || member.source || "本地日线"} · 截至{" "}
          {result.as_of}
        </span>
        <Link to="/explore" state={{ discoveryQuery: query }}>
          继续筛选与研究 <ArrowRight size={14} />
        </Link>
      </footer>
    </section>
  );
}
