import type { components } from "./schema";

export type ApiMeta = components["schemas"]["ApiMeta"];
export type SavedScreen = components["schemas"]["SavedScreen"];
export type ScreenSpec = components["schemas"]["ScreenSpec"];
export type ScreenCondition = components["schemas"]["ScreenCondition"];
export type ScreenEvidence = components["schemas"]["ScreenEvidence"];
export type ScreenFilterType = components["schemas"]["ScreenFilterType"];
export type ScreenRun = components["schemas"]["ScreenRun"];
export type ScreenVersion = components["schemas"]["ScreenVersion"];
export type ScreenRow = components["schemas"]["ScreenRow"];
export type Candidate = components["schemas"]["Candidate"];
export type CandidateList = components["schemas"]["CandidateList"];
export type CandidateStatus = components["schemas"]["CandidateStatus"];
export type CompareSet = components["schemas"]["CompareSet"];
export type WorkspaceJob = components["schemas"]["WorkspaceJob"];
export type MarketOverview = components["schemas"]["MarketOverviewResponse"];
export type Portfolio = components["schemas"]["PortfolioResponse"];
export type SettingsFacts = components["schemas"]["SettingsFactsResponse"];
export type StockResearch = components["schemas"]["StockResearchResponse"];

export interface FilterOption {
  type: ScreenFilterType;
  label: string;
  unit: string;
  input: "scalar" | "period" | "resonance";
  flag: string;
  supports_all: boolean;
  source: string;
  frequency: string;
  missing_semantics: string;
}

export interface FilterGroup {
  label: string;
  options: FilterOption[];
}

export class ApiError extends Error {
  status: number;
  code: string;
  hint?: string;

  constructor(status: number, code: string, message: string, hint?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.hint = hint;
  }
}

function sessionToken(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="kan-session"]');
  const embedded = meta?.content ?? "";
  if (embedded && embedded !== "__KAN_SESSION_TOKEN__") return embedded;
  return new URLSearchParams(window.location.search).get("_kan_session") ?? "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const token = sessionToken();
  if (token) headers.set("x-kan-session", token);
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-Kan-Web", "1");
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  const payload = (await response.json().catch(() => null)) as unknown;
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail?: unknown }).detail
        : payload;
    if (detail && typeof detail === "object") {
      const error = detail as { code?: string; message?: string; hint?: string };
      throw new ApiError(
        response.status,
        error.code ?? "request_failed",
        error.message ?? `请求失败（${response.status}）`,
        error.hint,
      );
    }
    throw new ApiError(
      response.status,
      "request_failed",
      typeof detail === "string" ? detail : `请求失败（${response.status}）`,
    );
  }
  return payload as T;
}

const json = (value: unknown): string => JSON.stringify(value);

export const api = {
  meta: () => request<ApiMeta>("/api/v1/meta"),
  market: () => request<MarketOverview>("/api/v1/market"),
  portfolio: () => request<Portfolio>("/api/v1/portfolio"),
  updateCash: (cash: number) =>
    request<Portfolio>("/api/v1/portfolio/cash", {
      method: "PUT",
      body: json({ cash }),
    }),
  addPosition: (payload: {
    code: string;
    cost: number;
    shares: number;
    name?: string;
    merge?: boolean;
  }) =>
    request<Portfolio>("/api/v1/portfolio/positions", {
      method: "POST",
      body: json(payload),
    }),
  deletePosition: (symbol: string) =>
    request<Portfolio>(
      `/api/v1/portfolio/positions/${encodeURIComponent(symbol)}`,
      { method: "DELETE" },
    ),
  settings: () => request<SettingsFacts>("/api/v1/settings"),
  stockResearch: (symbol: string) =>
    request<StockResearch>(`/api/v1/stocks/${encodeURIComponent(symbol)}`),
  stockHistory: <T>(symbol: string, period = 60) =>
    request<T>(
      `/api/v1/stocks/${encodeURIComponent(symbol)}/history?period=${period}`,
    ),
  filters: () => request<FilterGroup[]>("/api/v1/filters"),
  screens: () => request<SavedScreen[]>("/api/v1/screens"),
  screen: (screenId: string) =>
    request<SavedScreen>(`/api/v1/screens/${encodeURIComponent(screenId)}`),
  screenVersions: (screenId: string) =>
    request<ScreenVersion[]>(
      `/api/v1/screens/${encodeURIComponent(screenId)}/versions`,
    ),
  restoreScreenVersion: (screenId: string, version: number) =>
    request<SavedScreen>(
      `/api/v1/screens/${encodeURIComponent(screenId)}/versions/${version}/restore`,
      { method: "POST" },
    ),
  saveScreen: (spec: ScreenSpec, screenId?: string | null) =>
    request<SavedScreen>("/api/v1/screens", {
      method: "POST",
      body: json({ spec, screen_id: screenId ?? null }),
    }),
  deleteScreen: (screenId: string) =>
    request<{ deleted: boolean }>(
      `/api/v1/screens/${encodeURIComponent(screenId)}`,
      { method: "DELETE" },
    ),
  runSavedScreen: (screenId: string) =>
    request<ScreenRun>(
      `/api/v1/screens/${encodeURIComponent(screenId)}/runs`,
      { method: "POST" },
    ),
  runSpec: (spec: ScreenSpec, persist = true) =>
    request<ScreenRun>("/api/v1/runs", {
      method: "POST",
      body: json({ spec, persist }),
    }),
  runs: (screenId?: string | null, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (screenId) params.set("screen_id", screenId);
    return request<ScreenRun[]>(`/api/v1/runs?${params}`);
  },
  run: (runId: string) =>
    request<ScreenRun>(`/api/v1/runs/${encodeURIComponent(runId)}`),
  startScreenJob: (payload: { spec?: ScreenSpec; screen_id?: string; persist?: boolean }) =>
    request<WorkspaceJob>("/api/v1/jobs/screen-runs", {
      method: "POST",
      body: json(payload),
    }),
  startMarketRefresh: (scope: "default" | "all", force = false) =>
    request<WorkspaceJob>("/api/v1/jobs/market-refresh", {
      method: "POST",
      body: json({ scope, force, days: 360 }),
    }),
  job: (jobId: string) =>
    request<WorkspaceJob>(`/api/v1/jobs/${encodeURIComponent(jobId)}`),
  jobs: (limit = 50) => request<WorkspaceJob[]>(`/api/v1/jobs?limit=${limit}`),
  candidateLists: () =>
    request<CandidateList[]>("/api/v1/candidate-lists"),
  createCandidateList: (name: string) =>
    request<CandidateList>("/api/v1/candidate-lists", {
      method: "POST",
      body: json({ name }),
    }),
  renameCandidateList: (listId: string, name: string) =>
    request<CandidateList>(
      `/api/v1/candidate-lists/${encodeURIComponent(listId)}`,
      { method: "PATCH", body: json({ name }) },
    ),
  deleteCandidateList: (listId: string) =>
    request<{ deleted: boolean }>(
      `/api/v1/candidate-lists/${encodeURIComponent(listId)}`,
      { method: "DELETE" },
    ),
  upsertCandidate: (
    listId: string,
    symbol: string,
    payload: {
      name?: string;
      status?: CandidateStatus;
      note?: string;
      source_run_id?: string | null;
    },
  ) =>
    request<Candidate>(
      `/api/v1/candidate-lists/${encodeURIComponent(listId)}/candidates/${encodeURIComponent(symbol)}`,
      { method: "PUT", body: json(payload) },
    ),
  deleteCandidate: (listId: string, symbol: string) =>
    request<{ deleted: boolean }>(
      `/api/v1/candidate-lists/${encodeURIComponent(listId)}/candidates/${encodeURIComponent(symbol)}`,
      { method: "DELETE" },
    ),
  compareSets: () => request<CompareSet[]>("/api/v1/compare-sets"),
  saveCompareSet: (payload: {
    compare_id?: string | null;
    name: string;
    symbols: string[];
  }) =>
    request<CompareSet>("/api/v1/compare-sets", {
      method: "POST",
      body: json(payload),
    }),
  deleteCompareSet: (compareId: string) =>
    request<{ deleted: boolean }>(
      `/api/v1/compare-sets/${encodeURIComponent(compareId)}`,
      { method: "DELETE" },
    ),
};

export async function waitForJob(
  jobId: string,
  onUpdate?: (job: WorkspaceJob) => void,
): Promise<WorkspaceJob> {
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    const job = await api.job(jobId);
    onUpdate?.(job);
    if (["succeeded", "partial", "failed", "interrupted"].includes(job.status)) return job;
    await new Promise((resolve) => window.setTimeout(resolve, 250));
  }
  throw new ApiError(408, "job_timeout", "任务等待超过 10 分钟，可在任务记录中继续查看");
}

export const defaultScreenSpec = (): ScreenSpec => ({
  schema_version: 1,
  name: "我的选股规则",
  universe: { kind: "watchlist", value: null, codes: [], group: null },
  as_of: {
    trade_date: "latest_complete",
    timezone: "Asia/Shanghai",
    adjustment: "qfq",
    freshness_policy: "allow_stale",
  },
  match_mode: "all",
  conditions: [
    {
      type: "pos",
      operator: "lt",
      value: 30,
      period: 180,
      level: null,
      null_policy: "exclude",
    },
  ],
  exclude_st: true,
  exclude_star: false,
  exclude_bj: false,
  sort: [{ field_id: "position.180d", direction: "asc", nulls: "last" }],
  columns: [
    "symbol",
    "name",
    "price",
    "position.30d",
    "position.60d",
    "position.180d",
    "pe",
    "turnover",
  ],
  limit: 100,
});
