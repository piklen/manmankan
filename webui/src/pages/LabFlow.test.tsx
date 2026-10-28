import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { api, type StudyQuery } from "../api/client";
import {
  bars,
  evidenceFixture,
  mapFixture,
  resultFixture,
} from "../test/lab.fixtures";

function mount(entry = "/") {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
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
  vi.spyOn(api, "studyCatalog").mockResolvedValue([]);
  vi.spyOn(api, "studies").mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("trend discovery to reproducible research", () => {
  it("switches server-computed axes without fetching again and runs only an explicitly bounded region", async () => {
    const map = vi.spyOn(api, "trendMap").mockResolvedValue(mapFixture());
    let submitted: StudyQuery | undefined;
    const run = vi.spyOn(api, "runStudy").mockImplementation(async (query) => {
      submitted = query;
      return resultFixture(query);
    });
    const evidence = vi
      .spyOn(api, "studyEvidence")
      .mockImplementation(async (_, __, date) =>
        evidenceFixture(date, submitted!),
      );
    const rerun = vi.spyOn(api, "rerunStudy").mockImplementation(async () => ({
      ...resultFixture(submitted!),
      run_id: "run-latest",
      diff: {
        previous_run_id: "run-test",
        previous_as_of: "2026-10-28",
        added: [],
        removed: [],
        unavailable: ["000001"],
      },
    }));
    mount();
    await screen.findByRole("button", { name: "查看 测试股票甲 600000" });
    expect(run).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: /验证这片区域/ }),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: /区间位置/ }), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /区间涨跌/ }), {
      target: { value: "5" },
    });
    expect(map).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("img", { name: /横轴30日位置，纵轴5日涨跌/ }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "输入范围" }));
    for (const [label, value] of [
      ["位置下限", "0"],
      ["位置上限", "60"],
      ["涨跌下限", "-10"],
      ["涨跌上限", "10"],
    ])
      fireEvent.change(screen.getByLabelText(label!), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "应用范围" }));
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /验证这片区域/ }));
    await screen.findByRole("heading", { name: "历史样本" });
    expect(run).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: /研究条件（4）/ }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.getByRole("button", { name: "更新至最近收盘" }),
    ).toBeEnabled();
    expect(submitted?.conditions).toEqual([
      { field: "position", window: 30, operator: "gte", value: 0 },
      { field: "position", window: 30, operator: "lte", value: 60 },
      { field: "return_pct", window: 5, operator: "gte", value: -10 },
      { field: "return_pct", window: 5, operator: "lte", value: 10 },
    ]);
    expect(submitted?.universe).toBe("all");
    fireEvent.click(
      screen.getByRole("button", { name: "查看 600000 2026-10-28 样本" }),
    );
    await waitFor(() =>
      expect(evidence).toHaveBeenLastCalledWith(
        "run-test",
        "600000",
        "2026-10-28",
      ),
    );
    expect(
      await screen.findByText("观察窗口尚未结束，未计入历史分布。"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "更新至最近收盘" }));
    await waitFor(() => expect(rerun).toHaveBeenCalledWith("study-test", true));
    fireEvent.click(screen.getByRole("button", { name: "运行变化" }));
    expect(await screen.findByText("当前无法核对")).toBeInTheDocument();
    expect(screen.getByText("000001")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "发现趋势" }));
    await screen.findByRole("img", { name: /横轴30日位置，纵轴5日涨跌/ });
    expect(map).toHaveBeenCalledTimes(1);
  });

  it("makes shape distance an explicit choice and carries the selected reference into frozen research", async () => {
    const snapshot = mapFixture();
    vi.spyOn(api, "trendMap").mockResolvedValue(snapshot);
    vi.spyOn(api, "trendStock").mockResolvedValue({
      symbol: "600000",
      name: "测试股票甲",
      as_of: "2026-10-28",
      source: "test-fixture",
      industry: "测试行业",
      bars,
      positions: snapshot.rows[0]!.positions!,
      returns: snapshot.rows[0]!.returns!,
    });
    let submitted: StudyQuery | undefined;
    const run = vi.spyOn(api, "runStudy").mockImplementation(async (query) => {
      submitted = query;
      return resultFixture(query);
    });
    vi.spyOn(api, "studyEvidence").mockImplementation(async (_, __, date) =>
      evidenceFixture(date, submitted!),
    );
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "查看 测试股票甲 600000" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "按这段形态查找" }));
    expect(screen.getByRole("button", { name: "查找并验证" })).toBeDisabled();
    expect(run).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/最大均方根距离/), {
      target: { value: "2.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "查找并验证" }));
    await screen.findByRole("heading", { name: "与参照形态叠加" });
    expect(submitted?.reference).toEqual({
      symbol: "600000",
      as_of: "2026-10-28",
    });
    expect(submitted?.conditions).toEqual([
      { field: "shape_distance", window: 20, operator: "lte", value: 2.5 },
    ]);
    expect(
      screen.getByText("比较已经发生的价格形态；相似不表示后续走势相同。"),
    ).toBeInTheDocument();
  });

  it("uses each server view's coverage and allows shorter valid windows without reviving stale-day data", async () => {
    const snapshot = mapFixture();
    snapshot.total = 2;
    snapshot.rows.push({
      ...snapshot.rows[0]!,
      symbol: "000001",
      name: "测试缺口对象",
      available: false,
      data_cutoff: null,
      positions: {},
      returns: {},
      trail: [],
    });
    snapshot.rows[0] = {
      ...snapshot.rows[0]!,
      available: false,
      x: null,
      y: null,
      positions: { "30": 35, "60": null, "180": null },
      returns: { "5": 1, "20": null, "60": null },
    };
    snapshot.plotted = 0;
    snapshot.missing = 1;
    snapshot.views = snapshot.views.map((view) => ({
      ...view,
      plotted:
        view.position_window === 30 && view.momentum_window === 5 ? 1 : 0,
      missing:
        view.position_window === 30 && view.momentum_window === 5 ? 0 : 1,
    }));
    const map = vi.spyOn(api, "trendMap").mockResolvedValue(snapshot);
    mount();
    await screen.findByRole("img", { name: /0只股票/ });
    fireEvent.change(screen.getByRole("combobox", { name: /区间位置/ }), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /区间涨跌/ }), {
      target: { value: "5" },
    });
    expect(screen.getByRole("img", { name: /1只股票/ })).toBeInTheDocument();
    expect(map).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("button", { name: "查看 测试缺口对象 000001" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^缺口/ }));
    expect(
      screen.getByRole("button", { name: "查看 测试缺口对象 000001" }),
    ).toBeInTheDocument();
  });

  it("keeps the true old date visible and prevents interactions while loading a new dated snapshot", async () => {
    const snapshot = mapFixture();
    vi.spyOn(api, "trendMap")
      .mockResolvedValueOnce(snapshot)
      .mockImplementation(() => new Promise(() => {}));
    vi.spyOn(api, "trendStock").mockResolvedValue({
      symbol: "600000",
      name: "测试股票甲",
      as_of: "2026-10-28",
      source: "test-fixture",
      industry: "测试行业",
      bars,
      positions: snapshot.rows[0]!.positions!,
      returns: snapshot.rows[0]!.returns!,
    });
    const view = mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "查看 测试股票甲 600000" }),
    );
    fireEvent.change(screen.getByLabelText("地图截止日期"), {
      target: { value: "2026-09-04" },
    });
    expect(
      await screen.findByText("正在加载 2026-09-04 的地图"),
    ).toBeInTheDocument();
    expect(screen.getByText(/当前保留 2026-10-28 的旧图/)).toBeInTheDocument();
    expect(view.container.querySelector(".map-layout")).toHaveAttribute(
      "inert",
    );
    expect(
      screen.getByRole("button", { name: "按这段形态查找" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "定义历史研究" })).toBeDisabled();
  });
});
