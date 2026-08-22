import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  defaultScreenSpec,
  type SavedScreen,
  type ScreenRun,
  type WorkspaceJob,
} from "../api/client";
import { ScreenWorkbench } from "./ScreenWorkbench";

const saved: SavedScreen = {
  screen_id: "screen-1",
  name: "我的选股规则",
  current_version: 1,
  spec: defaultScreenSpec(),
  spec_hash: "spec-hash",
  created_at: "2026-08-23T00:00:00Z",
  updated_at: "2026-08-23T00:00:00Z",
};

const run: ScreenRun = {
  schema_version: 1,
  run_id: "run-1",
  screen_id: "screen-1",
  screen_version: 1,
  spec: defaultScreenSpec(),
  spec_hash: "spec-hash",
  snapshot_id: "snapshot-1",
  result_hash: "result-1",
  created_at: "2026-08-23T00:00:00Z",
  duration_ms: 22,
  coverage: {
    universe_size: 1,
    evaluated: 1,
    matched: 1,
    returned: 1,
    missing: 0,
    ratio: 1,
    stale: false,
    data_cutoff: "2026-08-22",
  },
  warnings: [],
  rows: [
    {
      symbol: "600519",
      name: "贵州茅台",
      rank: 1,
      price: 1500,
      in_watchlist: true,
      values: { "position.180d": 25, pe: 22 },
      positions: { "180": 25 },
      evidence: [],
    },
  ],
  diff: { previous_run_id: null, added: ["600519"], removed: [], rank_changes: [] },
};

const succeededJob: WorkspaceJob = {
  job_id: "job-1",
  kind: "screen_run",
  status: "succeeded",
  progress: 3,
  total: 3,
  watermark: "snapshot-1",
  message: "运行完成",
  error: null,
  result_ref: "run-1",
  created_at: "2026-08-23T00:00:00Z",
  updated_at: "2026-08-23T00:00:01Z",
};

function renderWorkbench() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ScreenWorkbench />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ScreenWorkbench", () => {
  it("builds a rule and adds another typed condition", async () => {
    vi.spyOn(api, "screens").mockResolvedValue([]);
    vi.spyOn(api, "filters").mockResolvedValue([]);

    renderWorkbench();

    expect(await screen.findByText("把选股变成一条可复跑的研究流水线")).toBeInTheDocument();
    expect(screen.queryAllByLabelText("筛选指标")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "保存并运行" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "添加条件" }));
    expect(screen.getAllByLabelText("筛选指标")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "保存并运行" })).toBeEnabled();
  });

  it("saves, starts a persistent job, and renders its auditable result", async () => {
    vi.spyOn(api, "screens").mockResolvedValue([]);
    vi.spyOn(api, "filters").mockResolvedValue([]);
    vi.spyOn(api, "saveScreen").mockResolvedValue(saved);
    vi.spyOn(api, "startScreenJob").mockResolvedValue(succeededJob);
    vi.spyOn(api, "job").mockResolvedValue(succeededJob);
    vi.spyOn(api, "run").mockResolvedValue(run);
    vi.spyOn(api, "runs").mockResolvedValue([run]);
    vi.spyOn(api, "screenVersions").mockResolvedValue([
      {
        screen_id: "screen-1",
        version: 1,
        spec: defaultScreenSpec(),
        spec_hash: "spec-hash",
        created_at: "2026-08-23T00:00:00Z",
      },
    ]);

    renderWorkbench();
    fireEvent.click(await screen.findByRole("button", { name: "添加条件" }));
    fireEvent.click(await screen.findByRole("button", { name: "保存并运行" }));

    await waitFor(() => expect(api.startScreenJob).toHaveBeenCalledWith({
      screen_id: "screen-1",
      persist: true,
    }));
    expect((await screen.findAllByText("贵州茅台")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("1 只 · 数据截止 2026-08-22")).toBeInTheDocument();
    expect(screen.getAllByText("1/1")).toHaveLength(2);
  });
});
