import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type BoardTrendSnapshot } from "../api/client";
import { TrendDiscoveryPage } from "./TrendDiscoveryPage";

const snapshot: BoardTrendSnapshot = {
  schema_version: 1,
  query: {
    kind: "industry",
    mode: "close",
    up: 3,
    down: null,
    min_streak: null,
    sort: "streak",
    level: 1,
    limit: 50,
    force: false,
  },
  source: "sw",
  data_cutoff: "2026-08-21",
  partial: false,
  coverage: { total: 31, evaluated: 31, matched: 2, returned: 2, errors: 0 },
  rows: [
    {
      rank: 1,
      kind: "industry",
      code: "801080",
      name: "电子",
      current_price: 5123.4,
      streak: 4,
      streak_pct: 6.2,
      direction: "涨4天",
      latest_change_pct: 1.2,
      moneyflow_net: 10888,
      daily_changes: [
        { date: "2026-08-21", change_pct: 1.2 },
        { date: "2026-08-20", change_pct: 2.1 },
        { date: "2026-08-19", change_pct: 1.5 },
      ],
    },
    {
      rank: 2,
      kind: "industry",
      code: "801710",
      name: "建筑材料",
      current_price: 2421.8,
      streak: 3,
      streak_pct: 3.1,
      direction: "涨3天",
      latest_change_pct: 0.7,
      moneyflow_net: null,
      daily_changes: [
        { date: "2026-08-21", change_pct: 0.7 },
        { date: "2026-08-20", change_pct: 1.1 },
      ],
    },
  ],
  failures: [],
  warnings: [],
};

function LocationProbe() {
  const location = useLocation();
  return <div>{`${location.pathname}${location.search}`}</div>;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/trends"]}>
        <Routes>
          <Route path="/trends" element={<TrendDiscoveryPage />} />
          <Route path="/screen" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("TrendDiscoveryPage", () => {
  it("shows the shared board trend snapshot and drills into Screen", async () => {
    const query = vi.spyOn(api, "boardTrends").mockResolvedValue(snapshot);

    renderPage();

    expect(
      await screen.findByText("先找正在形成趋势的板块，再看板块里的股票"),
    ).toBeInTheDocument();
    expect((await screen.findAllByText("电子")).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("已评估 31/31 个 · 命中 2 个")).toBeInTheDocument();
    expect(query).toHaveBeenCalledWith({
      kind: "industry",
      mode: "close",
      direction: "all",
      days: 3,
      sort: "streak",
      level: 1,
      limit: 50,
    });

    fireEvent.click(screen.getByRole("button", { name: /用本板块选股/ }));

    expect(
      await screen.findByText("/screen?universe=industry&value=%E7%94%B5%E5%AD%90&source=trends"),
    ).toBeInTheDocument();
  });

  it("requeries when the trend definition changes", async () => {
    const query = vi.spyOn(api, "boardTrends").mockResolvedValue(snapshot);

    renderPage();
    await screen.findByText("申万行业指数");
    fireEvent.click(screen.getByRole("radio", { name: "题材" }));
    fireEvent.click(screen.getByRole("radio", { name: "阳线连续" }));
    fireEvent.click(screen.getByRole("radio", { name: "连续下跌" }));

    await waitFor(() =>
      expect(query).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "theme", mode: "candle", direction: "down" }),
      ),
    );
  });
});
