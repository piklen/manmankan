import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  GitCompareArrows,
  Plus,
  Rows3,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type CompareSet, type ScreenRow } from "../api/client";
import { Badge, Button, Card, EmptyState, Loading, PageHeader } from "../components/ui";
import { errorMessage, number, percent, shortDate } from "../lib/format";

const METRICS = [
  { key: "price", label: "最新缓存价格", format: number },
  { key: "position.30d", label: "30 日位置", format: percent },
  { key: "position.60d", label: "60 日位置", format: percent },
  { key: "position.180d", label: "180 日位置", format: percent },
  { key: "pe", label: "PE TTM", format: number },
  { key: "pb", label: "PB", format: number },
  { key: "roe", label: "ROE", format: percent },
  { key: "turnover", label: "换手率", format: percent },
  { key: "moneyflow", label: "主力净额", format: number },
  { key: "rsi", label: "RSI (6)", format: number },
] as const;

function rowValue(row: ScreenRow | undefined, key: string): unknown {
  if (!row) return null;
  if (key === "price") return row.price;
  if (key.startsWith("position.")) {
    const period = key.slice("position.".length).replace("d", "");
    return row.values?.[key] ?? row.positions?.[period];
  }
  return row.values?.[key];
}

export function ComparePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [name, setName] = useState("新的横向对比");
  const [symbolsText, setSymbolsText] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const setsQuery = useQuery({ queryKey: ["compare-sets"], queryFn: api.compareSets });
  const runsQuery = useQuery({ queryKey: ["runs", "compare"], queryFn: () => api.runs(null, 100) });
  const sets = setsQuery.data ?? [];
  useEffect(() => {
    if (!activeId && sets[0]) setActiveId(sets[0].compare_id);
  }, [activeId, sets]);
  const active = sets.find((item) => item.compare_id === activeId) ?? null;

  const latestRows = useMemo(() => {
    const rows = new Map<string, { row: ScreenRow; createdAt: string }>();
    for (const run of runsQuery.data ?? []) {
      for (const row of run.rows ?? []) {
        if (!rows.has(row.symbol)) rows.set(row.symbol, { row, createdAt: run.created_at });
      }
    }
    return rows;
  }, [runsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const symbols = symbolsText
        .split(/[\s,，]+/)
        .map((item) => item.trim())
        .filter(Boolean);
      return api.saveCompareSet({ name, symbols });
    },
    onSuccess: (set) => {
      setActiveId(set.compare_id);
      setSymbolsText("");
      setNotice(`已保存「${set.name}」`);
      void queryClient.invalidateQueries({ queryKey: ["compare-sets"] });
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const deleteMutation = useMutation({
    mutationFn: (set: CompareSet) => api.deleteCompareSet(set.compare_id),
    onSuccess: () => {
      setActiveId(null);
      void queryClient.invalidateQueries({ queryKey: ["compare-sets"] });
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  return (
    <div>
      <PageHeader
        eyebrow="Compare set"
        title="横向摆在一起，差异才真正可见"
        description="对比组只保存研究对象；指标来自最近一次可追溯的 ScreenRun，不用填充出来的假数据补空白。"
        actions={notice ? <span className="notice-pill">{notice}</span> : undefined}
      />

      <div className="compare-layout">
        <Card className="compare-sidebar">
          <div className="panel-heading">
            <div><span className="panel-kicker">对比组</span><h2>已保存</h2></div>
            <GitCompareArrows size={18} />
          </div>
          {setsQuery.isLoading ? <Loading label="读取对比组" /> : null}
          <div className="compare-set-list">
            {sets.map((set) => (
              <button
                type="button"
                key={set.compare_id}
                className={active?.compare_id === set.compare_id ? "is-active" : ""}
                onClick={() => setActiveId(set.compare_id)}
              >
                <span><strong>{set.name}</strong><small>{set.symbols.length} 只 · {shortDate(set.updated_at)}</small></span>
                <ArrowRight size={15} />
              </button>
            ))}
          </div>
          <div className="compare-create">
            <h3><Plus size={15} /> 新建对比</h3>
            <label><span>名称</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label>
              <span>股票代码（3–10 只）</span>
              <textarea
                rows={3}
                value={symbolsText}
                placeholder="600519, 000858, 000568"
                onChange={(event) => setSymbolsText(event.target.value)}
              />
            </label>
            <Button size="sm" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
              保存对比组
            </Button>
          </div>
        </Card>

        <Card className="compare-board">
          {!active ? (
            <EmptyState
              title="还没有对比组"
              detail="在选股结果或候选池勾选 3–10 只股票，也可以在左侧直接输入代码。"
            />
          ) : (
            <>
              <div className="compare-board__heading">
                <div>
                  <span className="panel-kicker">Comparison matrix</span>
                  <h2>{active.name}</h2>
                  <p>{active.symbols.length} 只股票 · 缺失项保持为空</p>
                </div>
                <Button variant="danger" size="sm" onClick={() => deleteMutation.mutate(active)}>
                  <Trash2 size={14} /> 删除
                </Button>
              </div>
              {runsQuery.isLoading ? <Loading label="汇总最近运行数据" /> : null}
              <div className="comparison-table-wrap">
                <table className="comparison-table">
                  <thead>
                    <tr>
                      <th><Rows3 size={15} /> 指标</th>
                      {active.symbols.map((symbol) => {
                        const item = latestRows.get(symbol);
                        return (
                          <th key={symbol}>
                            <button type="button" onClick={() => navigate(`/research/${symbol}`)}>
                              <strong>{item?.row.name ?? symbol}</strong>
                              <span>{symbol}</span>
                            </button>
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {METRICS.map((metric) => (
                      <tr key={metric.key}>
                        <th>{metric.label}</th>
                        {active.symbols.map((symbol) => (
                          <td key={symbol}>
                            {metric.format(rowValue(latestRows.get(symbol)?.row, metric.key))}
                          </td>
                        ))}
                      </tr>
                    ))}
                    <tr className="comparison-table__source">
                      <th>最近证据时间</th>
                      {active.symbols.map((symbol) => (
                        <td key={symbol}>
                          {latestRows.has(symbol)
                            ? <Badge tone="neutral">{shortDate(latestRows.get(symbol)?.createdAt)}</Badge>
                            : <Badge tone="warning">尚无 ScreenRun</Badge>}
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
              <div className="compare-footnote">
                对比只呈现已记录事实，不做综合评分。点击股票名称进入研究页查看条件与来源。
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
