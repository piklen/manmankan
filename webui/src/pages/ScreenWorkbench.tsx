import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownUp,
  Bookmark,
  Check,
  ChevronDown,
  CirclePlus,
  Clock3,
  Copy,
  GitCompareArrows,
  History,
  ListFilter,
  Play,
  Plus,
  Save,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  defaultScreenSpec,
  waitForJob,
  type FilterOption,
  type SavedScreen,
  type ScreenCondition,
  type ScreenFilterType,
  type ScreenRow,
  type ScreenRun,
  type ScreenSpec,
} from "../api/client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Loading,
  PageHeader,
  Segmented,
} from "../components/ui";
import { compactId, errorMessage, number, percent, shortDate } from "../lib/format";

const FALLBACK_FILTERS: FilterOption[] = [
  {
    type: "pos",
    label: "价格区间位置",
    unit: "%",
    input: "period",
    flag: "--pos",
    supports_all: true,
    source: "kline",
    frequency: "daily",
    missing_semantics: "exclude",
  },
  {
    type: "pe",
    label: "市盈率 PE TTM",
    unit: "倍",
    input: "scalar",
    flag: "--pe",
    supports_all: true,
    source: "daily_basic",
    frequency: "daily",
    missing_semantics: "exclude",
  },
  {
    type: "turnover",
    label: "换手率",
    unit: "%",
    input: "scalar",
    flag: "--turnover",
    supports_all: true,
    source: "daily_basic",
    frequency: "daily",
    missing_semantics: "exclude",
  },
];

const OPERATORS = [
  { value: "lt", label: "低于" },
  { value: "lte", label: "不高于" },
  { value: "gt", label: "高于" },
  { value: "gte", label: "不低于" },
  { value: "eq", label: "等于" },
  { value: "ne", label: "不等于" },
] as const;

const UNIVERSES = [
  { value: "watchlist", label: "自选" },
  { value: "holdings", label: "持仓" },
  { value: "all", label: "全市场" },
  { value: "codes", label: "代码池" },
  { value: "industry", label: "行业" },
  { value: "theme", label: "题材" },
] as const;

const SORT_FIELDS = [
  ["position.180d", "180 日位置"],
  ["position.60d", "60 日位置"],
  ["position.30d", "30 日位置"],
  ["pe", "PE TTM"],
  ["pb", "PB"],
  ["roe", "ROE"],
  ["turnover", "换手率"],
  ["moneyflow", "主力净额"],
  ["rsi", "RSI"],
] as const;

function conditionFor(option: FilterOption): ScreenCondition {
  if (option.input === "period") {
    return {
      type: option.type,
      operator: "lt",
      value: option.type === "pos" ? 30 : 0,
      period: 180,
      level: null,
      null_policy: "exclude",
    };
  }
  if (option.input === "resonance") {
    return {
      type: option.type,
      operator: "gte",
      value: 2,
      period: null,
      level: "low",
      null_policy: "exclude",
    };
  }
  return {
    type: option.type,
    operator: "lt",
    value: option.type === "pe" ? 30 : 0,
    period: null,
    level: null,
    null_policy: "exclude",
  };
}

function cloneSpec(spec: ScreenSpec): ScreenSpec {
  return JSON.parse(JSON.stringify(spec)) as ScreenSpec;
}

function ScreenLibrary({
  screens,
  activeId,
  onOpen,
  onNew,
  isLoading,
}: {
  screens: SavedScreen[];
  activeId: string | null;
  onOpen: (screen: SavedScreen) => void;
  onNew: () => void;
  isLoading: boolean;
}) {
  return (
    <Card className="library-panel">
      <div className="panel-heading">
        <div>
          <span className="panel-kicker">规则库</span>
          <h2>我的 Screen</h2>
        </div>
        <Button variant="ghost" size="sm" onClick={onNew} aria-label="新建规则">
          <Plus size={16} />
        </Button>
      </div>
      <button type="button" className="new-screen-card" onClick={onNew}>
        <span><CirclePlus size={17} /></span>
        <div>
          <strong>新建选股规则</strong>
          <small>从一个清晰条件开始</small>
        </div>
      </button>
      <div className="library-list">
        {isLoading ? <Loading label="读取规则" /> : null}
        {!isLoading && screens.length === 0 ? (
          <p className="muted-copy">保存后的规则会出现在这里，并自动保留版本。</p>
        ) : null}
        {screens.map((screen) => (
          <button
            type="button"
            key={screen.screen_id}
            className={`library-item ${activeId === screen.screen_id ? "is-active" : ""}`}
            onClick={() => onOpen(screen)}
          >
            <span className="library-item__icon"><Bookmark size={15} /></span>
            <span className="library-item__body">
              <strong>{screen.name}</strong>
              <small>
                v{screen.current_version} · {screen.spec.conditions?.length ?? 0} 条件
              </small>
            </span>
            <span className="library-item__time">{shortDate(screen.updated_at)}</span>
          </button>
        ))}
      </div>
      <div className="library-note">
        <Sparkles size={16} />
        <p>Screen 是可复用规则；每次运行都会保存数据截止日、覆盖率与命中证据。</p>
      </div>
    </Card>
  );
}

function ConditionEditor({
  condition,
  options,
  onChange,
  onRemove,
}: {
  condition: ScreenCondition;
  options: FilterOption[];
  onChange: (condition: ScreenCondition) => void;
  onRemove: () => void;
}) {
  const selected =
    options.find((item) => item.type === condition.type) ?? FALLBACK_FILTERS[0]!;
  return (
    <div className="condition-row">
      <span className="condition-row__grip" aria-hidden="true">⋮⋮</span>
      <label className="condition-row__metric">
        <span className="sr-only">筛选指标</span>
        <select
          value={condition.type}
          onChange={(event) => {
            const option = options.find((item) => item.type === event.target.value);
            if (option) onChange(conditionFor(option));
          }}
        >
          {options.map((option) => (
            <option key={option.type} value={option.type}>{option.label}</option>
          ))}
        </select>
      </label>
      {selected.input === "period" ? (
        <label className="condition-row__period">
          <span className="sr-only">周期</span>
          <input
            type="number"
            min={2}
            max={360}
            value={condition.period ?? 180}
            onChange={(event) =>
              onChange({ ...condition, period: Number(event.target.value) })
            }
          />
          <small>日</small>
        </label>
      ) : null}
      {selected.input === "resonance" ? (
        <select
          aria-label="共振方向"
          value={condition.level ?? "low"}
          onChange={(event) =>
            onChange({ ...condition, level: event.target.value as "low" | "high" })
          }
        >
          <option value="low">低位共振</option>
          <option value="high">高位共振</option>
        </select>
      ) : null}
      <label className="condition-row__operator">
        <span className="sr-only">比较方式</span>
        <select
          value={condition.operator}
          onChange={(event) =>
            onChange({
              ...condition,
              operator: event.target.value as ScreenCondition["operator"],
            })
          }
        >
          {OPERATORS.map((operator) => (
            <option key={operator.value} value={operator.value}>{operator.label}</option>
          ))}
        </select>
      </label>
      <label className="condition-row__value">
        <span className="sr-only">阈值</span>
        <input
          type="number"
          step="any"
          value={condition.value}
          onChange={(event) =>
            onChange({ ...condition, value: Number(event.target.value) })
          }
        />
        {selected.unit ? <small>{selected.unit}</small> : null}
      </label>
      <label className="condition-row__null">
        <span className="sr-only">缺失值策略</span>
        <select
          value={condition.null_policy}
          onChange={(event) =>
            onChange({
              ...condition,
              null_policy: event.target.value as ScreenCondition["null_policy"],
            })
          }
          title="缺失值处理"
        >
          <option value="exclude">缺失排除</option>
          <option value="fail">缺失即失败</option>
        </select>
      </label>
      <button type="button" className="icon-button" onClick={onRemove} aria-label="删除条件">
        <X size={15} />
      </button>
      <div className="condition-row__meta">
        <span>{selected.source}</span>
        <span>·</span>
        <span>{selected.frequency}</span>
        {!selected.supports_all ? <Badge tone="warning">不支持全市场</Badge> : null}
      </div>
    </div>
  );
}

function Builder({
  spec,
  filterOptions,
  onChange,
}: {
  spec: ScreenSpec;
  filterOptions: FilterOption[];
  onChange: (spec: ScreenSpec) => void;
}) {
  const universe = spec.universe ?? defaultScreenSpec().universe!;
  const conditions = spec.conditions ?? [];
  const setUniverseKind = (kind: (typeof UNIVERSES)[number]["value"]) => {
    onChange({
      ...spec,
      universe: {
        kind,
        value: kind === "industry" || kind === "theme" ? "" : null,
        codes: kind === "codes" ? [] : [],
        group: null,
      },
    });
  };
  return (
    <div className="builder-stack">
      <Card className="builder-card">
        <div className="section-title">
          <span className="section-index">01</span>
          <div><h3>从哪里找</h3><p>先限定研究范围，再叠加客观条件。</p></div>
        </div>
        <Segmented
          label="股票池"
          value={universe.kind}
          options={[...UNIVERSES]}
          onChange={setUniverseKind}
        />
        {universe.kind === "codes" ? (
          <label className="field-block">
            <span>股票代码</span>
            <textarea
              rows={2}
              value={(universe.codes ?? []).join(", ")}
              placeholder="600519, 000858, 000568"
              onChange={(event) =>
                onChange({
                  ...spec,
                  universe: {
                    ...universe,
                    codes: event.target.value
                      .split(/[\s,，]+/)
                      .map((item) => item.trim())
                      .filter(Boolean),
                  },
                })
              }
            />
          </label>
        ) : null}
        {universe.kind === "industry" || universe.kind === "theme" ? (
          <label className="field-block">
            <span>{universe.kind === "industry" ? "行业名称" : "题材名称"}</span>
            <input
              value={universe.value ?? ""}
              placeholder={universe.kind === "industry" ? "例如：半导体" : "例如：AI 应用"}
              onChange={(event) =>
                onChange({ ...spec, universe: { ...universe, value: event.target.value } })
              }
            />
          </label>
        ) : null}
      </Card>

      <Card className="builder-card">
        <div className="section-title section-title--action">
          <span className="section-index">02</span>
          <div><h3>符合哪些条件</h3><p>条件由你定义，系统只负责计算与留证。</p></div>
          <Segmented
            label="条件匹配方式"
            value={spec.match_mode}
            options={[
              { value: "all", label: "全部满足" },
              { value: "any", label: "任一满足" },
            ]}
            onChange={(match_mode) => onChange({ ...spec, match_mode })}
          />
        </div>
        <div className="condition-list">
          {conditions.map((condition, index) => (
            <ConditionEditor
              key={`${index}-${condition.type}`}
              condition={condition}
              options={filterOptions}
              onChange={(next) => {
                const updated = [...conditions];
                updated[index] = next;
                onChange({ ...spec, conditions: updated });
              }}
              onRemove={() =>
                onChange({
                  ...spec,
                  conditions: conditions.filter((_, itemIndex) => itemIndex !== index),
                })
              }
            />
          ))}
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() =>
            onChange({
              ...spec,
              conditions: [...conditions, conditionFor(filterOptions[0]!)],
            })
          }
        >
          <Plus size={15} /> 添加条件
        </Button>
      </Card>

      <Card className="builder-card builder-card--compact">
        <div className="section-title">
          <span className="section-index">03</span>
          <div><h3>排除、排序与返回</h3><p>明确缺失与排序规则，复跑结果才可比较。</p></div>
        </div>
        <div className="builder-options">
          <div className="toggle-group" aria-label="排除规则">
            {([
              ["exclude_st", "排除 ST / *ST"],
              ["exclude_star", "排除科创板"],
              ["exclude_bj", "排除北交所"],
            ] as const).map(([field, label]) => (
              <label className="check-pill" key={field}>
                <input
                  type="checkbox"
                  checked={Boolean(spec[field as keyof ScreenSpec])}
                  onChange={(event) =>
                    onChange({ ...spec, [field]: event.target.checked })
                  }
                />
                <span><Check size={13} /> {label}</span>
              </label>
            ))}
          </div>
          <div className="sort-row">
            <ArrowDownUp size={16} />
            <label>
              <span>优先排序</span>
              <select
                value={spec.sort?.[0]?.field_id ?? "position.180d"}
                onChange={(event) =>
                  onChange({
                    ...spec,
                    sort: [{
                      field_id: event.target.value,
                      direction: spec.sort?.[0]?.direction ?? "asc",
                      nulls: "last",
                    }],
                  })
                }
              >
                {SORT_FIELDS.map(([field, label]) => (
                  <option key={field} value={field}>{label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>方向</span>
              <select
                value={spec.sort?.[0]?.direction ?? "asc"}
                onChange={(event) =>
                  onChange({
                    ...spec,
                    sort: [{
                      field_id: spec.sort?.[0]?.field_id ?? "position.180d",
                      direction: event.target.value as "asc" | "desc",
                      nulls: "last",
                    }],
                  })
                }
              >
                <option value="asc">从小到大</option>
                <option value="desc">从大到小</option>
              </select>
            </label>
            <label>
              <span>最多返回</span>
              <input
                type="number"
                min={1}
                max={10000}
                value={spec.limit}
                onChange={(event) => onChange({ ...spec, limit: Number(event.target.value) })}
              />
            </label>
          </div>
        </div>
      </Card>
    </div>
  );
}

function ResultsTable({
  run,
  selected,
  checked,
  onSelect,
  onCheck,
}: {
  run: ScreenRun | null;
  selected: string | null;
  checked: string[];
  onSelect: (row: ScreenRow) => void;
  onCheck: (symbol: string, active: boolean) => void;
}) {
  const rows = run?.rows ?? [];
  if (!run) {
    return (
      <EmptyState
        title="规则准备好了，就运行一次"
        detail="结果会带上覆盖率、数据截止日与逐条件命中证据；不会把缺失数据悄悄当成 0。"
      />
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        title="这次没有股票符合条件"
        detail="先检查数据覆盖与缺失提示，再决定是否调整股票池或阈值。"
      />
    );
  }
  return (
    <div className="result-table-wrap">
      <table className="result-table">
        <thead>
          <tr>
            <th aria-label="加入对比" />
            <th>#</th>
            <th>股票</th>
            <th>价格</th>
            <th>30 日位置</th>
            <th>60 日位置</th>
            <th>180 日位置</th>
            <th>PE</th>
            <th>换手率</th>
            <th>证据</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.symbol}
              className={selected === row.symbol ? "is-selected" : ""}
              onClick={() => onSelect(row)}
            >
              <td onClick={(event) => event.stopPropagation()}>
                <input
                  type="checkbox"
                  aria-label={`选择 ${row.name} 对比`}
                  checked={checked.includes(row.symbol)}
                  onChange={(event) => onCheck(row.symbol, event.target.checked)}
                />
              </td>
              <td className="rank-cell">{row.rank}</td>
              <td>
                <div className="stock-cell">
                  <strong>{row.name}</strong>
                  <span>{row.symbol}</span>
                </div>
              </td>
              <td>{number(row.price)}</td>
              <td>{percent(row.values?.["position.30d"] ?? row.positions?.["30"])}</td>
              <td>{percent(row.values?.["position.60d"] ?? row.positions?.["60"])}</td>
              <td>{percent(row.values?.["position.180d"] ?? row.positions?.["180"])}</td>
              <td>{number(row.values?.pe)}</td>
              <td>{percent(row.values?.turnover)}</td>
              <td><Badge tone="info">{row.evidence?.length ?? 0} 条</Badge></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Inspector({
  run,
  row,
  history,
  onHistory,
  onCandidate,
}: {
  run: ScreenRun | null;
  row: ScreenRow | null;
  history: ScreenRun[];
  onHistory: (run: ScreenRun) => void;
  onCandidate: (row: ScreenRow) => void;
}) {
  return (
    <Card className="inspector-panel">
      <div className="inspector-tabs">
        <button type="button" className="is-active">证据</button>
        <button type="button">运行记录</button>
      </div>
      {!run ? (
        <div className="inspector-placeholder">
          <ListFilter size={24} />
          <strong>等待一次运行</strong>
          <p>这里会解释结果为什么出现，以及本次与上次有什么变化。</p>
        </div>
      ) : null}
      {run ? (
        <>
          <div className="run-summary">
            <div className="run-summary__title">
              <span><Clock3 size={15} /> 本次运行</span>
              <Badge tone={run.coverage.stale ? "warning" : "positive"}>
                {run.coverage.stale ? "数据可能陈旧" : "截止日已记录"}
              </Badge>
            </div>
            <div className="metric-grid metric-grid--2">
              <div><span>评估覆盖</span><strong>{run.coverage.evaluated}/{run.coverage.universe_size}</strong></div>
              <div><span>符合 / 返回</span><strong>{run.coverage.matched}/{run.coverage.returned}</strong></div>
              <div><span>数据截止</span><strong>{run.coverage.data_cutoff ?? "—"}</strong></div>
              <div><span>耗时</span><strong>{run.duration_ms} ms</strong></div>
            </div>
            {run.warnings?.map((warning) => (
              <div className="inline-warning" key={warning}>{warning}</div>
            ))}
          </div>

          <div className="diff-summary">
            <h3>相对上次</h3>
            {run.diff?.previous_run_id ? (
              <div className="diff-chips">
                <Badge tone="positive">+{run.diff.added?.length ?? 0} 新增</Badge>
                <Badge tone="danger">−{run.diff.removed?.length ?? 0} 移出</Badge>
                <Badge tone="neutral">{run.diff.rank_changes?.length ?? 0} 排名变化</Badge>
              </div>
            ) : <p className="muted-copy">首次运行，暂无可比较历史。</p>}
          </div>

          {row ? (
            <div className="evidence-panel">
              <div className="evidence-panel__stock">
                <div>
                  <span>{row.symbol}</span>
                  <h3>{row.name}</h3>
                </div>
                <Button size="sm" variant="secondary" onClick={() => onCandidate(row)}>
                  <Plus size={14} /> 加入候选
                </Button>
              </div>
              <div className="evidence-list">
                {(row.evidence ?? []).map((evidence, index) => (
                  <article key={evidence.evidence_ref} className="evidence-item">
                    <span className="evidence-item__index">{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <strong>{evidence.filter_type}</strong>
                      <p>
                        实际 <b>{number(evidence.actual)}{evidence.unit}</b> · 阈值 {evidence.operator} {number(evidence.threshold)}{evidence.unit}
                      </p>
                      <small>{evidence.source ?? "本地计算"} · {evidence.data_date ?? "日期未提供"}</small>
                    </div>
                  </article>
                ))}
                {(row.evidence?.length ?? 0) === 0 ? (
                  <p className="muted-copy">排除规则命中不会生成数值证据；结果字段仍保留在运行快照中。</p>
                ) : null}
              </div>
            </div>
          ) : (
            <p className="inspector-hint">点击结果行，查看逐条件命中证据。</p>
          )}

          <div className="history-list">
            <h3><History size={15} /> 最近运行</h3>
            {history.slice(0, 6).map((item) => (
              <button type="button" key={item.run_id} onClick={() => onHistory(item)}>
                <span>{shortDate(item.created_at)}</span>
                <strong>{item.coverage.returned} 只</strong>
                <small>{compactId(item.snapshot_id)}</small>
              </button>
            ))}
          </div>
        </>
      ) : null}
    </Card>
  );
}

export function ScreenWorkbench() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [spec, setSpec] = useState<ScreenSpec>(() => defaultScreenSpec());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [run, setRun] = useState<ScreenRun | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [compareSymbols, setCompareSymbols] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  const screensQuery = useQuery({ queryKey: ["screens"], queryFn: api.screens });
  const filtersQuery = useQuery({ queryKey: ["filters"], queryFn: api.filters });
  const historyQuery = useQuery({
    queryKey: ["runs", activeId],
    queryFn: () => api.runs(activeId, 20),
    enabled: Boolean(activeId),
  });
  useEffect(() => {
    const latest = historyQuery.data?.[0];
    if (activeId && run === null && latest) {
      setRun(latest);
      setSelectedSymbol(latest.rows?.[0]?.symbol ?? null);
    }
  }, [activeId, historyQuery.data, run]);
  const options = useMemo(
    () => filtersQuery.data?.flatMap((group) => group.options) ?? FALLBACK_FILTERS,
    [filtersQuery.data],
  );

  const saveMutation = useMutation({
    mutationFn: () => api.saveScreen(spec, activeId),
    onSuccess: (saved) => {
      setActiveId(saved.screen_id);
      setSpec(cloneSpec(saved.spec));
      setNotice(`已保存 v${saved.current_version}`);
      void queryClient.invalidateQueries({ queryKey: ["screens"] });
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const runMutation = useMutation({
    mutationFn: async () => {
      const saved = await api.saveScreen(spec, activeId);
      const job = await api.startScreenJob({ screen_id: saved.screen_id, persist: true });
      const completed = await waitForJob(job.job_id, (current) => setNotice(current.message));
      if (completed.status !== "succeeded" || !completed.result_ref) {
        throw new Error(completed.error || completed.message || "选股任务未完成");
      }
      const result = await api.run(completed.result_ref);
      return { saved, result };
    },
    onSuccess: ({ saved, result }) => {
      setActiveId(saved.screen_id);
      setSpec(cloneSpec(saved.spec));
      setRun(result);
      setSelectedSymbol(result.rows?.[0]?.symbol ?? null);
      setCompareSymbols([]);
      setNotice(`运行完成：返回 ${result.coverage.returned} 只`);
      void queryClient.invalidateQueries({ queryKey: ["screens"] });
      void queryClient.invalidateQueries({ queryKey: ["runs", saved.screen_id] });
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const candidateMutation = useMutation({
    mutationFn: (row: ScreenRow) =>
      api.upsertCandidate("default", row.symbol, {
        name: row.name,
        status: "research",
        source_run_id: run?.run_id ?? null,
      }),
    onSuccess: (candidate) => {
      setNotice(`${candidate.name} 已加入研究候选`);
      void queryClient.invalidateQueries({ queryKey: ["candidate-lists"] });
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const compareMutation = useMutation({
    mutationFn: () =>
      api.saveCompareSet({
        name: `${spec.name} · ${new Date().toLocaleDateString("zh-CN")} 对比`,
        symbols: compareSymbols,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["compare-sets"] });
      navigate("/compare");
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const selectedRow =
    run?.rows?.find((row) => row.symbol === selectedSymbol) ?? null;
  const busy = saveMutation.isPending || runMutation.isPending;

  const openScreen = (saved: SavedScreen) => {
    setActiveId(saved.screen_id);
    setSpec(cloneSpec(saved.spec));
    setRun(null);
    setSelectedSymbol(null);
    setCompareSymbols([]);
    setNotice(null);
  };

  return (
    <div className="screen-page">
      <PageHeader
        eyebrow="Selection workbench"
        title="把选股变成一条可复跑的研究流水线"
        description="先定义股票池与客观阈值，再运行、留证、进入候选与对比。每一步都能回看。"
        actions={
          <>
            {notice ? <span className="notice-pill">{notice}</span> : null}
            <Button variant="secondary" onClick={() => saveMutation.mutate()} disabled={busy}>
              <Save size={16} /> 保存规则
            </Button>
            <Button onClick={() => runMutation.mutate()} disabled={busy}>
              <Play size={16} fill="currentColor" />
              {runMutation.isPending ? "正在运行" : "保存并运行"}
            </Button>
          </>
        }
      />

      <div className="workspace-grid">
        <ScreenLibrary
          screens={screensQuery.data ?? []}
          activeId={activeId}
          onOpen={openScreen}
          onNew={() => {
            setActiveId(null);
            setSpec(defaultScreenSpec());
            setRun(null);
            setSelectedSymbol(null);
          }}
          isLoading={screensQuery.isLoading}
        />

        <div className="workspace-center">
          <div className="rule-titlebar">
            <label>
              <span className="sr-only">规则名称</span>
              <input
                value={spec.name}
                onChange={(event) => setSpec({ ...spec, name: event.target.value })}
              />
            </label>
            <div>
              {activeId ? <Badge tone="neutral">ID {compactId(activeId)}</Badge> : <Badge tone="info">未保存</Badge>}
              <button
                type="button"
                className="icon-button"
                aria-label="复制规则"
                onClick={() => {
                  setActiveId(null);
                  setSpec({ ...cloneSpec(spec), name: `${spec.name} · 副本` });
                  setNotice("已复制为未保存规则");
                }}
              ><Copy size={15} /></button>
            </div>
          </div>
          <Builder spec={spec} filterOptions={options} onChange={setSpec} />

          <Card className="results-card">
            <div className="results-heading">
              <div>
                <span className="panel-kicker">Screen run</span>
                <h2>符合条件的股票</h2>
                <p>
                  {run
                    ? `${run.coverage.returned} 只 · 数据截止 ${run.coverage.data_cutoff ?? "未知"}`
                    : "运行后在这里查看结果与证据"}
                </p>
              </div>
              <div className="results-heading__actions">
                {compareSymbols.length ? <Badge tone="info">已选 {compareSymbols.length}/10</Badge> : null}
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={compareSymbols.length < 3 || compareMutation.isPending}
                  onClick={() => compareMutation.mutate()}
                >
                  <GitCompareArrows size={15} /> 进入对比
                </Button>
              </div>
            </div>
            <ResultsTable
              run={run}
              selected={selectedSymbol}
              checked={compareSymbols}
              onSelect={(row) => setSelectedSymbol(row.symbol)}
              onCheck={(symbol, active) =>
                setCompareSymbols((current) =>
                  active
                    ? [...new Set([...current, symbol])].slice(0, 10)
                    : current.filter((item) => item !== symbol),
                )
              }
            />
          </Card>
        </div>

        <Inspector
          run={run}
          row={selectedRow}
          history={historyQuery.data ?? []}
          onHistory={(item) => {
            setRun(item);
            setSelectedSymbol(item.rows?.[0]?.symbol ?? null);
          }}
          onCandidate={(row) => candidateMutation.mutate(row)}
        />
      </div>
    </div>
  );
}
