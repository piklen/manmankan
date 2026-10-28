import type { components } from "./schema";

export type TrendMapQuery = components["schemas"]["TrendMapQuery"];
export type TrendMapSnapshot = components["schemas"]["TrendMapSnapshot"];
export type TrendMapRow = components["schemas"]["TrendMapRow"];
export type TrendStockSnapshot = components["schemas"]["TrendStockSnapshot"];
export type StudyQuery = components["schemas"]["StudyQuery"];
export type StudyCondition = components["schemas"]["StudyCondition"];
export type StudyResult = components["schemas"]["StudyResult"];
export type StudySummary = components["schemas"]["StudySummary"];
export type StudyEvent = components["schemas"]["StudyEvent"];
export type StudyMatch = components["schemas"]["StudyMatch"];
export type StudyEvidence = components["schemas"]["StudyEvidence"];
export type StudyEventPage = components["schemas"]["StudyEventPage"];
export type StudyDistribution = components["schemas"]["StudyDistribution"];
export type StudyBar = components["schemas"]["StudyBar"];
export type WorkspaceJob = components["schemas"]["WorkspaceJob"];
export type Candidate = components["schemas"]["Candidate"];
export type CandidateList = components["schemas"]["CandidateList"];
export type FocusSnapshot = components["schemas"]["FocusSnapshot"];
export type Portfolio = components["schemas"]["PortfolioResponse"];
export type SettingsFacts = components["schemas"]["SettingsFactsResponse"];
export type ApiMeta = components["schemas"]["ApiMeta"];

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public hint?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function sessionToken(): string {
  const embedded = document.querySelector<HTMLMetaElement>(
    'meta[name="kan-session"]',
  )?.content;
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
    if (init.body !== undefined)
      headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail ?? payload;
    const validation = Array.isArray(detail)
      ? detail
          .map((item: { msg?: string }) => item.msg)
          .filter(Boolean)
          .join("；")
      : undefined;
    throw new ApiError(
      response.status,
      detail?.code ?? "request_failed",
      validation ||
        detail?.message ||
        (typeof detail === "string"
          ? detail
          : `请求失败（${response.status}）`),
      detail?.hint,
    );
  }
  return payload as T;
}
const body = (value: unknown) => JSON.stringify(value);
const encode = encodeURIComponent;

export const api = {
  trendMap: (query: TrendMapQuery) =>
    request<TrendMapSnapshot>("/api/v1/trends/map", {
      method: "POST",
      body: body(query),
    }),
  trendStock: (symbol: string, asOf: string, days = 120) =>
    request<TrendStockSnapshot>("/api/v1/trends/stock", {
      method: "POST",
      body: body({ symbol, as_of: asOf, days }),
    }),
  studyCatalog: () =>
    request<
      Array<{
        field: StudyCondition["field"];
        label: string;
        unit: string;
        window: boolean;
        definition: string;
      }>
    >("/api/v1/studies/catalog"),
  runStudy: (query: StudyQuery) =>
    request<StudyResult>("/api/v1/studies/run", {
      method: "POST",
      body: body(query),
    }),
  studies: () => request<StudySummary[]>("/api/v1/studies"),
  study: (id: string) => request<StudyResult>(`/api/v1/studies/${encode(id)}`),
  rerunStudy: (id: string, latest = false) =>
    request<StudyResult>(
      `/api/v1/studies/${encode(id)}/rerun?latest=${latest}`,
      { method: "POST" },
    ),
  studyEvents: (run: string, offset = 0, limit = 50) =>
    request<StudyEventPage>(
      `/api/v1/studies/runs/${encode(run)}/events?offset=${offset}&limit=${limit}`,
    ),
  studyEvidence: (run: string, symbol: string, date: string) =>
    request<StudyEvidence>(
      `/api/v1/studies/runs/${encode(run)}/evidence?symbol=${encode(symbol)}&date=${encode(date)}`,
    ),
  refreshStudyData: (query: {
    universe: StudyQuery["universe"];
    codes: string[];
    days?: number;
  }) =>
    request<WorkspaceJob>("/api/v1/studies/refresh", {
      method: "POST",
      body: body(query),
    }),
  jobs: () => request<WorkspaceJob[]>("/api/v1/jobs?limit=30"),
  job: (id: string) => request<WorkspaceJob>(`/api/v1/jobs/${encode(id)}`),
  settings: () => request<SettingsFacts>("/api/v1/settings"),
  meta: () => request<ApiMeta>("/api/v1/meta"),
  focus: () => request<FocusSnapshot>("/api/v1/focus"),
  addFocus: (symbol: string) =>
    request<Candidate>("/api/v1/focus", {
      method: "POST",
      body: body({ symbol }),
    }),
  candidateLists: () => request<CandidateList[]>("/api/v1/candidate-lists"),
  updateCandidate: (
    candidate: Candidate,
    updates: Partial<Pick<Candidate, "note" | "status">>,
  ) =>
    request<Candidate>(
      `/api/v1/candidate-lists/${encode(candidate.list_id)}/candidates/${encode(candidate.symbol)}`,
      {
        method: "PUT",
        body: body({
          name: candidate.name,
          status: candidate.status,
          note: candidate.note,
          source_run_id: candidate.source_run_id,
          ...updates,
        }),
      },
    ),
  deleteCandidate: (candidate: Candidate) =>
    request<{ deleted: boolean }>(
      `/api/v1/candidate-lists/${encode(candidate.list_id)}/candidates/${encode(candidate.symbol)}`,
      { method: "DELETE" },
    ),
  portfolio: () => request<Portfolio>("/api/v1/portfolio"),
  updateCash: (cash: number) =>
    request<Portfolio>("/api/v1/portfolio/cash", {
      method: "PUT",
      body: body({ cash }),
    }),
  addPosition: (payload: { code: string; cost: number; shares: number }) =>
    request<Portfolio>("/api/v1/portfolio/positions", {
      method: "POST",
      body: body(payload),
    }),
  deletePosition: (symbol: string) =>
    request<Portfolio>(`/api/v1/portfolio/positions/${encode(symbol)}`, {
      method: "DELETE",
    }),
};
