import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  type BoardPulseSnapshot,
  type BoardTrendSnapshot,
} from "../api/client";
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

const pulse: BoardPulseSnapshot = {
  schema_version: 1,
  query: { kind: "industry", value: "电子", level: 1, limit: 5, force: false },
  board_code: "801080",
  board_name: "电子",
  source: "tushare_daily_bars",
  data_cutoff: "2026-08-21",
  previous_date: "2026-08-20",
  partial: false,
  coverage: { total: 100, evaluated: 100, up: 62, down: 35, flat: 3, missing: 0 },
  up_ratio_pct: 62,
  down_ratio_pct: 35,
  median_change_pct: 0.8,
  top_up: [
    { rank: 1, code: "000001", name: "上涨成员甲", close: 11, change_pct: 10 },
  ],
  top_down: [
    { rank: 1, code: "000002", name: "下跌成员乙", close: 9, change_pct: -5 },
  ],
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
          <Route path="/history/board" element={<LocationProbe />} />
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
    const pulseQuery = vi.spyOn(api, "boardPulse").mockResolvedValue(pulse);

    renderPage();

    expect(
      await screen.findByText("先找正在形成趋势的板块，再看板块里的股票"),
    ).toBeInTheDocument();
    expect((await screen.findAllByText("电子")).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("已评估 31/31 个 · 命中 2 个")).toBeInTheDocument();
    expect(await screen.findByText("最新交易日，板块内部怎么动")).toBeInTheDocument();
    expect(screen.getByText("上涨成员甲")).toBeInTheDocument();
    expect(screen.getByText("下跌成员乙")).toBeInTheDocument();
    expect(screen.getByText("62 只")).toBeInTheDocument();
    expect(query).toHaveBeenCalledWith({
      kind: "industry",
      mode: "close",
      direction: "all",
      days: 3,
      sort: "streak",
      level: 1,
      limit: 50,
    });
    expect(pulseQuery).toHaveBeenCalledWith("industry", "801080", 1);

    fireEvent.click(screen.getByRole("button", { name: /用本板块选股/ }));

    expect(
      await screen.findByText("/screen?universe=industry&value=%E7%94%B5%E5%AD%90&source=trends"),
    ).toBeInTheDocument();
  });

  it("requeries when the trend definition changes", async () => {
    const query = vi.spyOn(api, "boardTrends").mockResolvedValue(snapshot);
    vi.spyOn(api, "boardPulse").mockResolvedValue(pulse);

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

  it("opens an explicit board-index history review without adding stock filters", async () => {
    vi.spyOn(api, "boardTrends").mockResolvedValue(snapshot);
    vi.spyOn(api, "boardPulse").mockResolvedValue(pulse);

    renderPage();
    await screen.findByText("申万行业指数");
    fireEvent.click(screen.getByRole("button", { name: /历史复核/ }));

    const location = await screen.findByText((content) =>
      content.startsWith("/history/board?") && content.includes("value=801080"),
    );
    expect(location.textContent).toContain("mode=close");
    expect(location.textContent).toContain("direction=up");
    expect(location.textContent).toContain("days=4");
    expect(location.textContent).not.toContain("conditions");
  });

  it("uses the theme name when loading members from a TuShare trend row", async () => {
    const themeSnapshot: BoardTrendSnapshot = {
      ...snapshot,
      query: { ...snapshot.query, kind: "theme" },
      source: "tushare",
      coverage: { total: 400, evaluated: 400, matched: 1, returned: 1, errors: 0 },
      rows: [
        {
          ...snapshot.rows![0]!,
          kind: "theme",
          code: "885781",
          name: "石墨电极",
        },
      ],
    };
    vi.spyOn(api, "boardTrends").mockImplementation((params) =>
      Promise.resolve(params.kind === "theme" ? themeSnapshot : snapshot),
    );
    const pulseQuery = vi.spyOn(api, "boardPulse").mockResolvedValue({
      ...pulse,
      query: { ...pulse.query, kind: "theme", value: "石墨电极" },
      board_code: "307512",
      board_name: "石墨电极",
    });

    renderPage();
    await screen.findByText("申万行业指数");
    fireEvent.click(screen.getByRole("radio", { name: "题材" }));

    await waitFor(() =>
      expect(pulseQuery).toHaveBeenCalledWith("theme", "石墨电极", 1),
    );
    expect(pulseQuery).not.toHaveBeenCalledWith("theme", "885781", 1);
  });
});
