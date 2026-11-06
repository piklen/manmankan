import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import App from "../App";
import {
  api,
  type DiscoveryQuery,
  type DiscoveryResult,
  type SettingsFacts,
  type WorkspaceJob,
} from "../api/client";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

it("recovers a fresh observation through explicit local configuration and data update without changing its query", async () => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  const query: DiscoveryQuery = {
    universe: "all",
    codes: [],
    industries: [],
    as_of: "2026-10-28",
    window: 45,
  };
  sessionStorage.setItem("manmankan.discovery.v1", JSON.stringify(query));
  const stats = {
    total: 1,
    available: 1,
    missing: 0,
    up: 1,
    down: 0,
    flat: 0,
    positive_share: 100,
    median_return: 2,
    q25: 2,
    q75: 2,
  };
  const result: DiscoveryResult = {
    query,
    as_of: "2026-10-28",
    current_start: "2026-08-26",
    previous_as_of: "2026-08-26",
    previous_start: "2026-06-24",
    common_data_date: "2026-10-28",
    common_data_count: 1,
    market: {
      name: "全部范围",
      total: 1,
      current: stats,
      comparison: {
        available: 1,
        missing: 0,
        current_positive_share: 100,
        previous_positive_share: 0,
        breadth_delta_pp: 100,
        current_median: 2,
        previous_median: -2,
      },
      history: [],
      history_available: 0,
      transitions: [],
      distribution: [],
      observations: [],
    },
    industries: [],
    members: [],
    warnings: [],
  };
  let settings: SettingsFacts = {
    data_dir: "fixture",
    workspace_db: "fixture",
    kline_cache_files: 0,
    tushare_endpoint_domain: "api.tushare.pro",
    tushare_configured: false,
    tushare_masked: null,
    tushare_token_source: "unconfigured",
    tushare_endpoint_source: "default",
    state_backend: "sqlite",
  };
  let jobs: WorkspaceJob[] = [];
  const job: WorkspaceJob = {
    job_id: "fixture-refresh",
    kind: "market_refresh:all",
    status: "queued",
    progress: 0,
    total: 1,
    message: "等待更新",
    created_at: "2026-10-28T16:00:00Z",
    updated_at: "2026-10-28T16:00:00Z",
  };
  const discover = vi
    .spyOn(api, "discover")
    .mockRejectedValueOnce(new Error("无法取得完整上市股票名单；请配置来源"))
    .mockResolvedValue(result);
  vi.spyOn(api, "settings").mockImplementation(async () => settings);
  vi.spyOn(api, "jobs").mockImplementation(async () => jobs);
  const prepare = vi
    .spyOn(api, "discoveryDataPlan")
    .mockImplementation(async (received) => ({
      query: received,
      refresh: { universe: "all", codes: [], days: 91 },
      required_start: "2026-06-24",
      latest: "2026-10-28",
      message: "为原观察准备91个交易日",
    }));
  const configure = vi
    .spyOn(api, "updateSettings")
    .mockImplementation(async () => {
      settings = {
        ...settings,
        tushare_configured: true,
        tushare_masked: "***ture",
        tushare_token_source: "config",
      };
      return settings;
    });
  const refresh = vi
    .spyOn(api, "refreshStudyData")
    .mockImplementation(async () => {
      jobs = [{ ...job, status: "succeeded", progress: 1, message: "已更新" }];
      return job;
    });
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByRole("link", { name: /检查数据配置/ }));
  await waitFor(() => expect(prepare).toHaveBeenCalledWith(query));
  expect(screen.getByLabelText("更新范围")).toHaveValue("all");
  await waitFor(() =>
    expect(screen.getByLabelText("获取日数")).toHaveValue(91),
  );
  expect(screen.getByRole("button", { name: "更新日线" })).toBeDisabled();
  const password = screen.getByLabelText("TuShare token（留空保留）");
  fireEvent.change(password, { target: { value: "isolated-token-fixture" } });
  fireEvent.click(screen.getByRole("button", { name: "保存连接配置" }));
  await waitFor(() =>
    expect(configure).toHaveBeenCalledWith({
      token: "isolated-token-fixture",
      endpoint: undefined,
    }),
  );
  await waitFor(() => expect(password).toHaveValue(""));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "更新日线" })).toBeEnabled(),
  );
  expect(
    screen.queryByRole("link", { name: "回到原观察并重新计算" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "更新日线" }));
  fireEvent.click(
    await screen.findByRole("link", { name: "回到原观察并重新计算" }),
  );
  await waitFor(() => expect(discover).toHaveBeenCalledTimes(2));
  expect(discover).toHaveBeenLastCalledWith(query);
  expect(refresh).toHaveBeenCalledWith({
    universe: "all",
    codes: [],
    days: 91,
  });
  expect(
    await screen.findByText("2026-10-28", { selector: "strong" }),
  ).toBeInTheDocument();
});
