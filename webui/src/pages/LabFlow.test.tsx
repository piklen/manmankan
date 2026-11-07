import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import {
  api,
  type TrendSearchQuery,
  type TrendComparisonRow,
  type TrendSearchResult,
  type TrendSearchRow,
} from "../api/client";
import { bars, evidenceFixture, resultFixture } from "../test/lab.fixtures";

const row: TrendSearchRow = {
  symbol: "600000",
  name: "测试股票甲",
  industry: "测试行业",
  date: "2026-10-28",
  close: 12.8,
  change_pct: -1,
  values: { down_days: 5, up_days: 0, previous_up_days: 3 },
  lower_bounds: [],
  positions: { "30": 35, "60": 50, "180": 20 },
  returns: { "5": -3, "20": 8, "60": -2 },
  current_segment: {
    direction: "down",
    days: 5,
    bound: "exact",
    start_date: "2026-10-24",
    base_date: "2026-10-23",
    return_pct: -3,
  },
  source: "test-fixture",
  gap_dates: [],
  sparkline: bars.slice(-20).map(({ date, close }) => ({ date, close })),
};
function searchResult(query: TrendSearchQuery): TrendSearchResult {
  return {
    query,
    as_of: query.as_of ?? "2026-10-28",
    coverage: {
      total: 3,
      evaluated: 2,
      matched: 1,
      missing: 1,
      self_matches_excluded: 0,
    },
    common_data_date: "2026-10-28",
    common_data_count: 3,
    rows: [row],
    missing_rows: [
      { symbol: "000002", name: "测试缺口", reason: "截止日缺行情" },
    ],
    scope_codes: ["600000", "000001", "000002"],
    industries: [{ name: "测试行业", total: 3 }],
    warnings: [],
  };
}
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false, staleTime: Infinity },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter initialEntries={["/explore"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
function enter(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
function runDown() {
  fireEvent.click(screen.getByRole("button", { name: "连续下跌" }));
  enter("条件 1 数值", "5");
  fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
}
beforeEach(() => {
  sessionStorage.clear();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(api, "savedTrends").mockResolvedValue([]);
  vi.spyOn(api, "studyCatalog").mockResolvedValue([]);
  vi.spyOn(api, "studies").mockResolvedValue([]);
  vi.spyOn(api, "trendEvidence").mockImplementation(async (query) => ({
    query,
    as_of: "2026-10-28",
    row,
    bars: bars.map((bar) => ({ ...bar, change_pct: -1, body_pct: 0.5 })),
    conditions: (query.conditions ?? []).map((condition) => ({
      condition,
      actual: 5,
      bound: "exact",
      matched: true,
    })),
    reference_bars: [],
    reference_source: null,
    warnings: [],
  }));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("explicit current trend screening and optional historical research", () => {
  it("keeps day counts blank, makes at-most directional, and only saves/researches after explicit actions", async () => {
    const search = vi
      .spyOn(api, "searchTrends")
      .mockImplementation(async (query) => searchResult(query));
    const run = vi
      .spyOn(api, "runStudy")
      .mockImplementation(async (query) => resultFixture(query));
    vi.spyOn(api, "studyEvidence").mockImplementation(async (_, __, date) =>
      evidenceFixture(date, run.mock.calls.at(-1)![0]),
    );
    const save = vi
      .spyOn(api, "saveTrend")
      .mockImplementation(async (title, query) => ({
        id: "saved-1",
        title,
        query,
      }));
    const rerun = vi
      .spyOn(api, "rerunStudy")
      .mockImplementation(async () => resultFixture(run.mock.calls[0]![0]));
    mount();
    expect(search).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "连续下跌" }));
    expect(screen.getByLabelText("条件 1 数值")).toHaveValue(null);
    expect(screen.getByRole("button", { name: "开始筛选" })).toBeDisabled();
    enter("条件 1 数值", "5");
    enter("条件 1 比较关系", "lte");
    enter("筛选行业", "测试行业");
    expect(screen.getByText("该方向须已持续：1–5 天。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
    await screen.findByRole("button", { name: "查看 测试股票甲 600000" });
    expect(search.mock.calls[0]![0].conditions).toEqual([
      { field: "down_days", operator: "gt", value: 0, window: null },
      { field: "down_days", operator: "lte", value: 5, window: null },
    ]);
    expect(run).not.toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存筛选" }));
    enter("筛选名称", "我的连跌观察");
    fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save.mock.calls[0]![1].as_of).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "核对历史 / 保存研究" }),
    );
    expect(run).not.toHaveBeenCalled();
    expect(screen.getByLabelText("股票代码")).toHaveValue(
      "600000, 000001, 000002",
    );
    fireEvent.click(screen.getByRole("button", { name: "核对历史并保存" }));
    await screen.findByRole("heading", { name: "历史样本" });
    expect(run).toHaveBeenCalledOnce();
    expect(run.mock.calls[0]![0].codes).toEqual(["600000", "000001", "000002"]);
    expect(
      screen.getByRole("button", { name: /研究条件（2）/ }),
    ).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByRole("button", { name: "更新至最近收盘" }));
    await waitFor(() => expect(rerun).toHaveBeenCalledWith("study-test", true));
    fireEvent.click(screen.getByRole("link", { name: "趋势筛选" }));
    await screen.findByRole("button", { name: "查看 测试股票甲 600000" });
    expect(search).toHaveBeenCalledOnce();
  });

  it("retains both adjacent stages and validates interval counts without adding a hidden strategy", async () => {
    const search = vi
      .spyOn(api, "searchTrends")
      .mockImplementation(async (query) => searchResult(query));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "先跌后涨" }));
    enter("条件 1 数值", "4");
    expect(screen.getByRole("button", { name: "开始筛选" })).toBeDisabled();
    enter("条件 2 数值", "2");
    enter("条件 2 比较关系", "eq");
    fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
    await screen.findByRole("button", { name: "查看 测试股票甲 600000" });
    expect(search.mock.calls[0]![0].conditions).toEqual([
      { field: "previous_down_days", operator: "gte", value: 4, window: null },
      { field: "up_days", operator: "eq", value: 2, window: null },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "区间涨跌天数" }));
    enter("条件 1 观察窗口", "5");
    enter("条件 1 数值", "6");
    expect(screen.getByRole("button", { name: "开始筛选" })).toBeDisabled();
    enter("条件 1 涨跌方向", "falling_days");
    enter("条件 1 数值", "0");
    expect(screen.getByRole("button", { name: "开始筛选" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(search.mock.calls[1]![0].conditions).toEqual([
      { field: "falling_days", operator: "gte", value: 0, window: 5 },
    ]);
  });

  it("keeps a requested missing day and lets the user choose the local date; old results stay inert while loading", async () => {
    const search = vi
      .spyOn(api, "searchTrends")
      .mockImplementationOnce(async (query) => ({
        ...searchResult(query),
        as_of: "2026-11-02",
        rows: [],
        coverage: {
          total: 3,
          evaluated: 0,
          matched: 0,
          missing: 3,
          self_matches_excluded: 0,
        },
      }))
      .mockImplementationOnce(() => new Promise(() => {}));
    mount();
    runDown();
    expect(screen.getByRole("button", { name: "连续上涨" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "形态检索" })).toBeDisabled();
    expect(
      screen.queryByText("先说清楚，你在找什么走势"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("正在读取日线并核对当前条件，不计算历史样本。"),
    ).toBeInTheDocument();
    await screen.findByRole("button", { name: "查看这一天" });
    expect(
      screen.getByRole("heading", { name: "这个截止日暂无可判断的行情" }),
    ).toBeInTheDocument();
    expect(search.mock.calls[0]![0].as_of).toBeNull();
    expect(screen.getByText("数据日 2026-11-02")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看这一天" }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(search.mock.calls[1]![0].as_of).toBe("2026-10-28");
    expect(document.querySelector(".screen-result-body")).toHaveAttribute(
      "inert",
    );
    expect(
      screen.queryByText("条件已修改，点击开始筛选后更新结果。"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("数据日 2026-11-02")).toBeInTheDocument();
  });

  it("selects the first visible code, retains explicit selection, and makes short and long segments readable", async () => {
    const longBars = Array.from({ length: 80 }, (_, index) => ({
      ...bars[0]!,
      date: new Date(Date.UTC(2026, 7, 10 + index)).toISOString().slice(0, 10),
      close: 12 + index / 100,
      change_pct: -1,
      body_pct: 0.5,
    }));
    const ordered = Array.from({ length: 12 }, (_, index) => ({
      ...row,
      symbol: String(index + 1).padStart(6, "0"),
      name: `测试对象${index + 1}`,
      current_segment:
        index === 10
          ? {
              ...row.current_segment!,
              days: 70,
              start_date: longBars[10]!.date,
            }
          : row.current_segment,
    }));
    let dataSource = "test-fixture";
    const search = vi
      .spyOn(api, "searchTrends")
      .mockImplementation(async (query) => ({
        ...searchResult(query),
        rows: [...ordered]
          .reverse()
          .map((item) => ({ ...item, source: dataSource })),
      }));
    vi.mocked(api.trendEvidence).mockImplementation(async (query, symbol) => ({
      query,
      as_of: row.date,
      row: {
        ...ordered.find((item) => item.symbol === symbol)!,
        source: dataSource,
      },
      bars: longBars,
      conditions: [],
      reference_bars: [],
      reference_source: null,
      warnings: [],
    }));
    mount();
    runDown();
    const first = await screen.findByRole("button", {
      name: "查看 测试对象1 000001",
    });
    await waitFor(() => expect(first.closest("tr")).toHaveClass("selected"));
    expect(
      await screen.findByRole("button", { name: "本段附近" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText(
        `${longBars[50]!.date} — ${longBars[79]!.date} · 30 个交易日`,
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "完整窗口" }));
    expect(
      screen.getByText(
        `${longBars[0]!.date} — ${longBars[79]!.date} · 80 个交易日`,
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    fireEvent.click(
      screen.getByRole("button", { name: "查看 测试对象11 000011" }),
    );
    await screen.findByText(
      `${longBars[2]!.date} — ${longBars[79]!.date} · 78 个交易日`,
    );
    dataSource = "test-refreshed";
    fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    await screen.findByText(/来源：test-refreshed ·/);
    await waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: "查看 测试对象11 000011" })
          .closest("tr"),
      ).toHaveClass("selected"),
    );
    enter("搜索筛选结果", "000001");
    expect(
      screen.getByText("详情保留：测试对象11 000011（不在当前显示范围）"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "定位此行" }));
    expect(
      screen
        .getByRole("button", { name: "查看 测试对象11 000011" })
        .closest("tr"),
    ).toHaveClass("selected");
    enter("条件 1 数值", "6");
    fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "开始筛选" })).toBeEnabled(),
    );
    dataSource = "test-refreshed-again";
    enter("条件 1 数值", "5");
    fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(4));
    await screen.findByText(/来源：test-refreshed-again ·/);
  }, 15_000);

  it("shares results with map and shape searches without running historical research", async () => {
    const search = vi
      .spyOn(api, "searchTrends")
      .mockImplementation(async (query) => searchResult(query));
    const run = vi.spyOn(api, "runStudy");
    mount();
    runDown();
    await screen.findByRole("button", { name: "查看 测试股票甲 600000" });
    fireEvent.click(screen.getByRole("button", { name: "地图" }));
    enter("横轴位置", "30");
    enter("纵轴涨跌", "5");
    expect(search).toHaveBeenCalledOnce();
    expect(
      screen.getByRole("img", { name: /横轴30日位置，纵轴5日涨跌/ }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "输入框选范围" }));
    for (const [label, value] of [
      ["位置下限", "0"],
      ["位置上限", "60"],
      ["涨跌下限", "-10"],
      ["涨跌上限", "10"],
    ])
      enter(label!, value!);
    fireEvent.click(screen.getByRole("button", { name: "应用范围" }));
    fireEvent.click(screen.getByRole("button", { name: "把框选加入筛选条件" }));
    expect(search).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("条件 2 数值")).toHaveValue(0);
    fireEvent.click(screen.getByRole("button", { name: /按这段形态查找/ }));
    expect(screen.getByRole("button", { name: "开始筛选" })).toBeDisabled();
    expect(screen.getByLabelText("参照股票")).toHaveValue("600000");
    enter("条件 1 数值", "2.5");
    fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(search.mock.calls[1]![0].reference).toEqual({
      symbol: "600000",
      as_of: "2026-10-28",
    });
    expect(search.mock.calls[1]![0].conditions).toEqual([
      { field: "shape_distance", operator: "lte", value: 2.5, window: 20 },
    ]);
    expect(run).not.toHaveBeenCalled();
  });

  it("preserves explicit comparison settings and exposes both dates for exited and uncertain rows", async () => {
    const currentDate = "2026-10-28",
      previousDate = "2026-10-27";
    const query: TrendSearchQuery = {
      swing_reversal_pct: 5,
      universe: "all",
      as_of: currentDate,
      compare_to: "previous_session",
      conditions: [{ field: "down_days", operator: "gte", value: 5 }],
    };
    const snapshot = (actual: number | null, close: number | null) => ({
      matched: actual == null ? null : actual >= 5,
      close,
      conditions: [
        {
          condition: query.conditions![0]!,
          actual,
          matched: actual == null ? null : actual >= 5,
          bound: "exact" as const,
        },
      ],
      reason: actual == null ? "当前日缺少行情" : null,
    });
    const changes: TrendComparisonRow[] = [
      {
        symbol: "600000",
        name: row.name,
        status: "entered",
        previous: snapshot(4, 13),
        current: snapshot(5, 12.8),
      },
      {
        symbol: "000001",
        name: "测试退出",
        status: "exited",
        previous: snapshot(5, 10),
        current: snapshot(0, 10.2),
      },
      {
        symbol: "000002",
        name: "测试未知",
        status: "uncertain",
        previous: snapshot(5, 8),
        current: snapshot(null, null),
      },
      {
        symbol: "000003",
        name: "测试旧日缺口",
        status: "uncertain",
        previous: { ...snapshot(null, 9), reason: "对照日条件缺行情" },
        current: { ...snapshot(0, 9.2), reason: "当前不满足" },
      },
    ];
    const search = vi
      .spyOn(api, "searchTrends")
      .mockImplementation(async (input) => ({
        ...searchResult(input),
        coverage: {
          total: 4,
          evaluated: 3,
          matched: 1,
          missing: 1,
          self_matches_excluded: 0,
        },
        scope_codes: ["600000", "000001", "000002", "000003"],
        comparison: {
          as_of: previousDate,
          coverage: {
            comparable: 2,
            entered: 1,
            continued: 0,
            exited: 1,
            unchanged: 0,
            uncertain: 2,
            excluded: 0,
          },
          rows: changes,
          excluded_rows: [],
        },
      }));
    vi.mocked(api.savedTrends).mockResolvedValue([
      { id: "saved-comparison", title: "每日变化", query },
    ]);
    const save = vi
      .spyOn(api, "saveTrend")
      .mockImplementation(async (title, input) => ({
        id: "saved-copy",
        title,
        query: input,
      }));
    const run = vi.spyOn(api, "runStudy");
    vi.mocked(api.trendEvidence).mockImplementation(
      async (input, symbol, at) => {
        const selected = changes.find((item) => item.symbol === symbol)!;
        const actualDate = at ?? currentDate;
        const fact =
          actualDate === previousDate ? selected.previous : selected.current;
        if (fact.close == null)
          throw new Error("当前日缺少行情，选择对照日可查看已有证据");
        return {
          query: input,
          as_of: actualDate,
          row: {
            ...row,
            symbol,
            name: selected.name,
            date: actualDate,
            close: fact.close,
          },
          bars: bars.filter((bar) => bar.date <= actualDate),
          conditions: fact.conditions ?? [],
          reference_bars: [],
          warnings: [],
        };
      },
    );
    mount();
    expect(screen.getByLabelText("两日对比")).toHaveValue("none");
    fireEvent.click(screen.getByRole("button", { name: "连续下跌" }));
    enter("条件 1 数值", "5");
    enter("两日对比", "date");
    expect(screen.getByRole("button", { name: "开始筛选" })).toBeDisabled();
    enter("截止日期", currentDate);
    enter("对照日期", currentDate);
    expect(
      screen.getByText("对照日期必须早于当前截止日期。"),
    ).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
    fireEvent.click(
      await screen.findByRole("button", { name: /每日变化.*2026-10-28/ }),
    );
    expect(screen.getByLabelText("两日对比")).toHaveValue("previous_session");
    expect(search).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存筛选" }));
    enter("筛选名称", "每日变化副本");
    fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save.mock.calls[0]![1].compare_to).toBe("previous_session");
    fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
    await screen.findByRole("button", { name: /新出现\s*1/ });
    expect(search.mock.calls[0]![0].compare_to).toBe("previous_session");
    fireEvent.click(screen.getByRole("button", { name: /已退出\s*1/ }));
    fireEvent.click(
      await screen.findByRole("button", { name: "查看变化 测试退出 000001" }),
    );
    await screen.findByRole("heading", { name: /000001\s*测试退出/ });
    expect(
      screen.getByRole("heading", { name: "为什么已退出" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: `对照日 ${previousDate}` }),
    );
    await waitFor(() =>
      expect(api.trendEvidence).toHaveBeenLastCalledWith(
        expect.objectContaining({
          as_of: currentDate,
          compare_to: "previous_session",
        }),
        "000001",
        previousDate,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "返回筛选结果" }));
    fireEvent.click(screen.getByRole("button", { name: /无法确认\s*2/ }));
    expect(screen.getByText("对照日：对照日条件缺行情")).toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("button", { name: "查看变化 测试未知 000002" }),
    );
    await screen.findByRole("heading", { name: /000002\s*测试未知/ });
    expect(
      screen.getByRole("button", { name: `对照日 ${previousDate}` }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(
      screen.getByRole("button", { name: `当前日 ${currentDate}` }),
    );
    expect(
      await screen.findByText("当前日缺少行情 · 可切换另一日期核对已有证据。"),
    ).toBeInTheDocument();
    expect(api.trendEvidence).not.toHaveBeenCalledWith(
      expect.anything(),
      "000002",
      currentDate,
    );
    fireEvent.click(
      screen.getByRole("button", { name: `对照日 ${previousDate}` }),
    );
    expect(
      screen.getByRole("img", {
        name: /测试未知 日K与成交量，事件日 2026-10-27/,
      }),
    ).toBeInTheDocument();
    expect(run).not.toHaveBeenCalled();
  });

  it("screens explicit swing structure with adjustable scale and preserves causal evidence into history", async () => {
    const search = vi.spyOn(api, "searchTrends").mockImplementation(async (query) => ({
      ...searchResult(query),
      rows: [{ ...row, values: { "swing_structure.20": 1, "swing_direction.20": -1 } }],
    }));
    const save = vi.spyOn(api, "saveTrend").mockImplementation(async (title, query) => ({ id: "swings", title, query }));
    vi.mocked(api.savedTrends).mockImplementation(async () => save.mock.calls.length ? [{ id: "swings", title: save.mock.calls[0]![0], query: save.mock.calls[0]![1] }] : []);
    const run = vi.spyOn(api, "runStudy").mockImplementation(async (query) => resultFixture(query));
    vi.spyOn(api, "studyEvidence").mockImplementation(async (_, __, date) => evidenceFixture(date, run.mock.calls.at(-1)![0]));
    vi.mocked(api.trendEvidence).mockImplementation(async (query) => ({
      query, as_of: "2026-10-28", row: { ...row, close: 10.8 }, bars: bars.map((bar, index) => index === bars.length - 1 ? { ...bar, close: 10.8, low: 10.7 } : bar),
      conditions: (query.conditions ?? []).map((condition) => ({ condition, actual: condition.value, bound: "exact", matched: true })),
      warnings: [],
      swings: [{
        window: 20, reversal_pct: query.swing_reversal_pct, structure: 1, direction: -1, structure_broken: true,
        reason: null,
        pivots: [
          { date: "2026-10-10", price: 10, kind: "low", confirmed_at: "2026-10-11" },
          { date: "2026-10-14", price: 12, kind: "high", confirmed_at: "2026-10-15" },
          { date: "2026-10-18", price: 11, kind: "low", confirmed_at: "2026-10-19" },
          { date: "2026-10-23", price: 13, kind: "high", confirmed_at: "2026-10-24" },
        ],
        current: { start_date: "2026-10-23", start_price: 13, start_confirmed: true,
          extreme_date: "2026-10-28", extreme_price: 10.8, direction: "down", return_pct: -16.923, days: 5 },
      }],
    }));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "波段结构" }));
    expect(screen.getByLabelText("条件 1 波段状态")).toHaveValue("");
    expect(screen.getByRole("button", { name: "开始筛选" })).toBeDisabled();
    enter("条件 1 观察窗口", "20");
    enter("条件 1 波段状态", "1");
    enter("转折确认幅度", "0");
    expect(screen.getByRole("button", { name: "开始筛选" })).toBeDisabled();
    enter("转折确认幅度", "3");
    fireEvent.click(screen.getByRole("button", { name: "叠加位置、涨幅或其他条件" }));
    enter("条件 2 字段", "swing_direction");
    enter("条件 2 观察窗口", "20");
    enter("条件 2 波段状态", "-1");
    fireEvent.click(screen.getByRole("button", { name: "开始筛选" }));
    await screen.findByRole("heading", { name: "已确认上升结构 · 已越过最近波谷" });
    expect(search.mock.calls[0]![0]).toMatchObject({ swing_reversal_pct: 3, conditions: [
      { field: "swing_structure", operator: "eq", value: 1, window: 20 },
      { field: "swing_direction", operator: "eq", value: -1, window: 20 },
    ] });
    expect(within(screen.getByRole("region", { name: "波段结构证据" })).getByText("2026-10-24")).toBeInTheDocument();
    expect(document.querySelector(".swing-current-line")).toBeInTheDocument();
    expect(screen.getByText(/当前收盘已越过最近确认波谷/)).toBeInTheDocument();
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存筛选" }));
    enter("筛选名称", "波段结构核对");
    fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save.mock.calls[0]![1].swing_reversal_pct).toBe(3);
    fireEvent.click(screen.getByRole("button", { name: "区间阳阴线" }));
    enter("条件 1 观察窗口", "15");
    enter("条件 1 比较关系", "gt");
    enter("条件 1 数值", "0");
    expect(screen.getByRole("button", { name: "开始筛选" })).toBeEnabled();
    fireEvent.click(await screen.findByRole("button", { name: /^波段结构核对/ }));
    expect(screen.getByLabelText("转折确认幅度")).toHaveValue(3);
    expect(screen.getByLabelText("条件 1 波段状态")).toHaveValue("1");
    fireEvent.click(screen.getByRole("button", { name: "核对历史 / 保存研究" }));
    expect(screen.getByLabelText("转折确认幅度")).toHaveValue(3);
    expect(screen.getByLabelText("条件 1 波段状态")).toHaveValue("1");
    fireEvent.click(screen.getByRole("button", { name: "核对历史并保存" }));
    await waitFor(() => expect(run).toHaveBeenCalledOnce());
    expect(run.mock.calls[0]![0].swing_reversal_pct).toBe(3);
  });

});
