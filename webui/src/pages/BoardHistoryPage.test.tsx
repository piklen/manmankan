import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type BoardHistoryStudy } from "../api/client";
import { BoardHistoryPage } from "./BoardHistoryPage";

const study: BoardHistoryStudy = {
  schema_version: 1,
  query: {
    kind: "industry",
    value: "801080",
    level: 1,
    mode: "close",
    direction: "up",
    min_streak: 4,
    forward_days: 5,
    lookback_years: 5,
    sample_policy: "first_hit",
    benchmark_code: "000300.SH",
    force: false,
  },
  board_code: "801080",
  board_name: "电子",
  source: "sw_index_history",
  benchmark_name: "沪深300",
  benchmark_source: "fixture",
  data_start: "2021-08-17",
  data_cutoff: "2026-08-21",
  coverage: {
    observations: 1206,
    first_hits: 2,
    selected: 2,
    completed: 2,
    censored: 0,
    benchmark_aligned: 2,
  },
  events: [
    {
      event_date: "2025-03-04",
      forward_date: "2025-03-11",
      streak: 4,
      event_close: 5100,
      forward_close: 5202,
      return_pct: 2,
      benchmark_return_pct: 0.5,
      relative_return_pct: 1.5,
    },
    {
      event_date: "2024-01-08",
      forward_date: "2024-01-15",
      streak: 4,
      event_close: 4800,
      forward_close: 4704,
      return_pct: -2,
      benchmark_return_pct: -1,
      relative_return_pct: -1,
    },
  ],
  raw_distribution: {
    count: 2, positive: 1, negative: 1, flat: 0, positive_ratio_pct: 50,
    mean_pct: 0, median_pct: 0, p25_pct: -1, p75_pct: 1, min_pct: -2, max_pct: 2,
  },
  benchmark_distribution: {
    count: 2, positive: 1, negative: 1, flat: 0, positive_ratio_pct: 50,
    mean_pct: -0.25, median_pct: -0.25, p25_pct: -0.625, p75_pct: 0.125,
    min_pct: -1, max_pct: 0.5,
  },
  relative_distribution: {
    count: 2, positive: 1, negative: 1, flat: 0, positive_ratio_pct: 50,
    mean_pct: 0.25, median_pct: 0.25, p25_pct: -0.375, p75_pct: 0.875,
    min_pct: -1, max_pct: 1.5,
  },
  audit: {
    scope: "provider_board_index_series",
    uses_current_constituents: false,
    reconstructs_historical_stock_pool: false,
    provider_vintage_archive: false,
    benchmark_exact_date_alignment: true,
    notes: ["只使用板块指数历史"],
  },
  warnings: [],
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[
        "/history/board?kind=industry&value=801080&name=%E7%94%B5%E5%AD%90&level=1&mode=close&direction=up&days=4&forward=5&years=5&sample=first_hit",
      ]}>
        <Routes><Route path="/history/board" element={<BoardHistoryPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("BoardHistoryPage", () => {
  it("shows auditable event distributions from explicit URL parameters", async () => {
    const query = vi.spyOn(api, "studyBoardHistory").mockResolvedValue(study);
    renderPage();

    expect(await screen.findByText("把一次趋势，放回历史里看")).toBeInTheDocument();
    expect(await screen.findByText("上涨样本占比")).toBeInTheDocument();
    expect(screen.getAllByText("50%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("每个历史事件都能回看")).toBeInTheDocument();
    expect(screen.getByText("当前成分股回填过去")).toBeInTheDocument();
    expect(screen.getByText("未使用")).toBeInTheDocument();
    expect(screen.getByText("数据源逐日历史版本")).toBeInTheDocument();
    expect(screen.getByText("未归档")).toBeInTheDocument();
    expect(query).toHaveBeenCalledWith(study.query);
  });

  it("only reruns after the user submits changed visible parameters", async () => {
    const query = vi.spyOn(api, "studyBoardHistory").mockResolvedValue(study);
    renderPage();
    await screen.findByText("每个历史事件都能回看");

    fireEvent.change(screen.getByLabelText("未来交易日"), { target: { value: "10" } });
    expect(query).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /按这些条件复核/ }));

    await waitFor(() => expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ forward_days: 10 }),
    ));
  });
});
