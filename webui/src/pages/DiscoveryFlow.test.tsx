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
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../App";
import {
  api,
  ApiError,
  type DiscoveryGroup,
  type DiscoveryResult,
  type ObservationRecord,
  type ObservationReviewResult,
} from "../api/client";
import { bars } from "../test/lab.fixtures";

const observationBars = Array.from({ length: 90 }, (_, index) => {
  const date = new Date(Date.UTC(2026, 9, 28 - 89 + index));
  return { date, day: date.toISOString().slice(0, 10) };
})
  .filter(({ date }) => date.getUTCDay() !== 0 && date.getUTCDay() !== 6)
  .map(({ day }, index) => ({
    ...bars[0]!,
    date: day,
    close: 10 + index / 10,
  }));

const group: DiscoveryGroup = {
  fingerprint: "a".repeat(24),
  name: "测试行业",
  total: 3,
  current: {
    total: 3,
    available: 2,
    missing: 1,
    up: 1,
    down: 1,
    flat: 0,
    positive_share: 50,
    median_return: 1,
    q25: -2,
    q75: 4,
  },
  comparison: {
    available: 2,
    missing: 1,
    current_positive_share: 50,
    previous_positive_share: 0,
    breadth_delta_pp: 50,
    current_median: 1,
    previous_median: -3,
  },
  history_available: 2,
  history: [
    {
      date: "2026-10-27",
      available: 2,
      up: 0,
      down: 2,
      flat: 0,
      positive_share: 0,
      median_return: -3,
    },
    {
      date: "2026-10-28",
      available: 2,
      up: 1,
      down: 1,
      flat: 0,
      positive_share: 50,
      median_return: 1,
    },
  ],
  transitions: [
    { key: "down_up", label: "前跌后涨", count: 1 },
    { key: "down_down", label: "两期下跌", count: 1 },
    { key: "unknown", label: "两段无法比较", count: 1 },
  ],
  distribution: [
    { key: "negative", label: "−5% 至 0%", count: 1 },
    { key: "positive", label: "0% 至 5%", count: 1 },
  ],
  observations: [
    {
      kind: "comparison",
      title: "上涨占比增加",
      detail: "同一批 2 只成员中，上涨占比从 0% 变为 50%。",
    },
  ],
};
const result: DiscoveryResult = {
  query: {
    universe: "all",
    codes: [],
    industries: [],
    window: 20,
    as_of: null,
  },
  as_of: "2026-10-28",
  current_start: observationBars.at(-21)!.date,
  previous_as_of: observationBars.at(-21)!.date,
  previous_start: observationBars.at(-41)!.date,
  common_data_date: "2026-10-28",
  common_data_count: 3,
  data_gaps: [{ date: "2026-10-27", missing: 1 }],
  market: { ...group, name: "全部 A 股" },
  industries: [group],
  warnings: ["使用当前上市范围与当前行业归属。"],
  members: [
    {
      symbol: "000001",
      name: "测试甲",
      industry: "测试行业",
      latest_available: true,
      return_pct: 4,
      previous_return_pct: -3,
      change_pct: 1,
      transition: "down_up",
      distribution_bin: "positive",
      source: "test",
      reason: null,
    },
    {
      symbol: "000002",
      name: "测试乙",
      industry: "测试行业",
      latest_available: true,
      return_pct: -2,
      previous_return_pct: -3,
      change_pct: -1,
      transition: "down_down",
      distribution_bin: "negative",
      source: "test",
      reason: null,
    },
    {
      symbol: "000003",
      name: "测试缺口",
      industry: "测试行业",
      latest_available: false,
      return_pct: null,
      previous_return_pct: null,
      change_pct: null,
      transition: "unknown",
      distribution_bin: null,
      source: "test",
      reason: "截止日缺行情",
    },
  ],
};
function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  sessionStorage.clear();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("links whole-population observations to industry, exact distribution members and same-date price evidence", async () => {
  const discover = vi.spyOn(api, "discover").mockResolvedValue(result);
  vi.spyOn(api, "savedTrends").mockResolvedValue([]);
  vi.spyOn(api, "searchTrends").mockImplementation(async (query) => ({
    query,
    as_of: result.as_of,
    common_data_count: 0,
    coverage: {
      total: 3,
      evaluated: 0,
      matched: 0,
      missing: 3,
      self_matches_excluded: 0,
    },
    rows: [],
    missing_rows: result.members.map((member) => ({
      symbol: member.symbol,
      name: member.name,
      reason: "测试筛选不读取行情",
    })),
    scope_codes: result.members.map((member) => member.symbol),
    industries: [],
    warnings: [],
  }));
  const evidence = vi
    .spyOn(api, "trendEvidence")
    .mockImplementation(async (query) => ({
      query,
      as_of: "2026-10-28",
      row: {
        symbol: "000001",
        name: "测试甲",
        industry: "测试行业",
        date: "2026-10-28",
        close: 12,
        change_pct: 1,
        values: {},
        lower_bounds: [],
        positions: {},
        returns: {},
        source: "test",
        gap_dates: [],
        sparkline: [],
      },
      bars: observationBars,
      conditions: [],
      warnings: [],
    }));
  mount();
  await screen.findByRole("heading", { name: "行业剖面" });
  expect(screen.getByText("行情存在共同缺口：2026-10-27 · 1 只")).toBeVisible();
  expect(discover).toHaveBeenCalledWith({
    universe: "all",
    codes: [],
    industries: [],
    as_of: null,
    window: 20,
  });
  expect(
    screen.getByRole("button", { name: "查看 测试缺口 000003 价格证据" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "测试行业" }));
  expect(
    screen.getByRole("heading", { name: "测试行业 · 拆开看" }),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "0% 至 5%，1只，查看成员" }),
  );
  expect(
    screen.queryByRole("button", { name: "查看 测试乙 000002 价格证据" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "查看 测试甲 000001 价格证据" }),
  );
  await screen.findByRole("region", { name: "测试甲价格证据" });
  await waitFor(() =>
    expect(evidence).toHaveBeenCalledWith(
      expect.objectContaining({
        universe: "codes",
        codes: ["000001"],
        as_of: "2026-10-28",
        conditions: [],
      }),
      "000001",
    ),
  );
  expect(
    await screen.findByText(
      `${result.previous_start} — ${result.as_of} · 41 个交易日`,
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("前期 20 日")).toBeInTheDocument();
  expect(screen.getByText("本期 20 日")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "查找成员" }), {
    target: { value: "测试甲" },
  });
  fireEvent.click(screen.getByRole("link", { name: "在这个完整范围继续筛选" }));
  await screen.findByRole("heading", { name: "筛出你要找的走势" });
  fireEvent.click(screen.getByRole("link", { name: "市场观察" }));
  await screen.findByRole("heading", { name: "测试行业 · 拆开看" });
  expect(
    screen.getByRole("button", { name: "0% 至 5%，1只，查看成员" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("textbox", { name: "查找成员" })).toHaveValue(
    "测试甲",
  );
  expect(
    screen.getByRole("region", { name: "测试甲价格证据" }),
  ).toBeInTheDocument();
  expect(discover).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "关闭价格证据" }));
  fireEvent.click(screen.getByRole("button", { name: "清除分组" }));
  fireEvent.click(
    screen.getByRole("button", { name: "两段无法比较，1只，查看成员" }),
  );
  expect(
    screen.getByRole("button", { name: "查看 测试缺口 000003 价格证据" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "查看 测试甲 000001 价格证据" }),
  ).not.toBeInTheDocument();
  expect(discover).toHaveBeenCalledTimes(1);
});

it("keeps the requested date visible until the user explicitly chooses the local data date", async () => {
  const empty = {
    ...group,
    current: {
      ...group.current,
      available: 0,
      missing: 3,
      up: 0,
      down: 0,
      positive_share: null,
      median_return: null,
      q25: null,
      q75: null,
    },
  };
  const discover = vi
    .spyOn(api, "discover")
    .mockResolvedValueOnce({ ...result, as_of: "2026-11-06", market: empty })
    .mockResolvedValue(result);
  mount();
  await screen.findByRole("heading", { name: "这个日期，暂时还看不清整体" });
  expect(screen.getByText("2026-11-06")).toBeInTheDocument();
  expect(discover).toHaveBeenCalledTimes(1);
  fireEvent.click(
    screen.getByRole("button", { name: "查看本地数据日 2026-10-28" }),
  );
  await screen.findByRole("heading", { name: "行业剖面" });
  expect(discover).toHaveBeenLastCalledWith(
    expect.objectContaining({ as_of: "2026-10-28" }),
  );
});

it("saves the complete observation beyond the displayed subgroup and reviews a common cohort without replacing the original thought", async () => {
  const thought = "先记下参与范围的变化，下次核对是不是仍然集中在少数成员。";
  const title = "参与范围是否持续改变";
  const record: ObservationRecord = {
    id: "observation-test",
    title,
    note: thought,
    created_at: "2026-10-29T01:00:00Z",
    scope_label: "测试行业",
    query: {
      ...result.query,
      industries: ["测试行业"],
      as_of: result.as_of,
    },
    snapshot: {
      as_of: result.as_of,
      current_start: result.current_start,
      previous_as_of: result.previous_as_of,
      previous_start: result.previous_start,
      group,
      members: result.members,
    },
  };
  const reviewResult: ObservationReviewResult = {
    observation: record,
    current: {
      ...record.snapshot,
      as_of: "2026-11-04",
      group: {
        ...group,
        current: {
          total: 3,
          available: 1,
          missing: 2,
          up: 0,
          down: 1,
          flat: 0,
          positive_share: 0,
          median_return: -1,
          q25: -1,
          q75: -1,
        },
      },
      members: result.members.map((member, index) => ({
        ...member,
        return_pct: index === 0 ? -1 : null,
        reason: index === 0 ? null : "本次窗口资料不足",
      })),
    },
    comparison: {
      available: 1,
      missing: 2,
      current_positive_share: 0,
      previous_positive_share: 100,
      breadth_delta_pp: -100,
      current_median: -1,
      previous_median: 4,
    },
    transitions: [
      { key: "up_down", label: "原观察上涨 · 本次下跌", count: 1 },
      { key: "unknown", label: "两次无法比较", count: 2 },
    ],
  };
  const otherMember = {
    ...result.members[0]!,
    symbol: "000004",
    name: "测试另一行业成员",
    industry: "另一行业",
    return_pct: 2,
    previous_return_pct: 1,
    transition: "up_up" as const,
  };
  const otherGroup: DiscoveryGroup = {
    ...group,
    name: "另一行业",
    total: 1,
    current: {
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
    },
    comparison: {
      available: 1,
      missing: 0,
      current_positive_share: 100,
      previous_positive_share: 100,
      breadth_delta_pp: 0,
      current_median: 2,
      previous_median: 1,
    },
    history_available: 1,
    history: group.history.map((point) => ({
      ...point,
      available: 1,
      up: 1,
      down: 0,
      flat: 0,
      positive_share: 100,
      median_return: 2,
    })),
    transitions: [{ key: "up_up", label: "两段均上涨", count: 1 }],
    distribution: [{ key: "positive", label: "0% 至 5%", count: 1 }],
    observations: [],
  };
  const broaderResult: DiscoveryResult = {
    ...result,
    members: [...result.members, otherMember],
    industries: [...result.industries, otherGroup],
    market: {
      ...result.market,
      total: 4,
      current: {
        total: 4,
        available: 3,
        missing: 1,
        up: 2,
        down: 1,
        flat: 0,
        positive_share: 200 / 3,
        median_return: 2,
        q25: 0,
        q75: 3,
      },
      comparison: {
        ...result.market.comparison,
        available: 3,
        current_positive_share: 200 / 3,
        previous_positive_share: 100 / 3,
        breadth_delta_pp: 100 / 3,
        current_median: 2,
      },
      history_available: 3,
      history: result.market.history.map((point) => ({
        ...point,
        available: 3,
        up: point.up + 1,
        positive_share: ((point.up + 1) / 3) * 100,
        median_return: point.up ? 2 : -3,
      })),
      distribution: [
        { key: "negative", label: "−5% 至 0%", count: 1 },
        { key: "positive", label: "0% 至 5%", count: 2 },
      ],
      transitions: [
        ...group.transitions,
        { key: "up_up", label: "两段均上涨", count: 1 },
      ],
      observations: [],
    },
  };
  let sourceUpdated = false;
  const discover = vi
    .spyOn(api, "discover")
    .mockImplementation(async (query) => {
      const current = query.universe === "codes" ? result : broaderResult;
      if (!sourceUpdated) return { ...current, query };
      return {
        ...current,
        query,
        market: { ...current.market, fingerprint: "e".repeat(24) },
        industries: current.industries.map((item) =>
          item.name === "测试行业"
            ? { ...item, fingerprint: "d".repeat(24) }
            : item,
        ),
        members: current.members.map((member) =>
          member.industry === "测试行业"
            ? { ...member, source: "test-refreshed" }
            : member,
        ),
      };
    });
  record.snapshot.group = {
    ...record.snapshot.group,
    fingerprint: "d".repeat(24),
  };
  record.snapshot.members = record.snapshot.members.map((member) => ({
    ...member,
    source: "test-refreshed",
  }));
  const save = vi
    .spyOn(api, "saveObservation")
    .mockImplementationOnce(async () => {
      sourceUpdated = true;
      throw new ApiError(409, "observation_changed", "保存前资料已变化");
    })
    .mockResolvedValue(record);
  const edit = vi.spyOn(api, "updateObservation").mockResolvedValue(record);
  let deleted = false;
  vi.spyOn(api, "observations").mockImplementation(async () =>
    deleted
      ? []
      : [
          {
            id: record.id,
            title,
            note: thought,
            created_at: record.created_at,
            as_of: result.as_of,
            window: 20,
            scope_label: record.scope_label,
            total: 3,
          },
        ],
  );
  const read = vi.spyOn(api, "observation").mockResolvedValue(record);
  const review = vi
    .spyOn(api, "reviewObservation")
    .mockResolvedValue(reviewResult);
  const remove = vi
    .spyOn(api, "deleteObservation")
    .mockImplementation(async () => {
      deleted = true;
      return { deleted: true };
    });
  vi.spyOn(api, "studies").mockResolvedValue([]);
  mount();
  await screen.findByRole("heading", { name: "行业剖面" });
  fireEvent.click(screen.getByRole("button", { name: "测试行业" }));
  fireEvent.click(
    screen.getByRole("button", { name: "0% 至 5%，1只，查看成员" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "记下测试行业观察" }));
  expect(
    screen.getByText(/保存「测试行业」的完整 3 只范围/),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("观察标题"), {
    target: { value: title },
  });
  fireEvent.change(screen.getByLabelText("当时的想法"), {
    target: { value: thought },
  });
  fireEvent.click(screen.getByRole("button", { name: "另一行业" }));
  fireEvent.click(screen.getByRole("button", { name: "记下另一行业观察" }));
  expect(screen.getByLabelText("当时的想法")).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "取消记录并清除草稿" }));
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "测试行业" }));
  expect(screen.getByLabelText("当时的想法")).toHaveValue(thought);
  expect(
    screen.getByText(/已恢复这个范围、日期与窗口的草稿/),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重新观察" }));
  await screen.findByRole("heading", { name: "行业剖面" });
  fireEvent.click(screen.getByRole("button", { name: "测试行业" }));
  expect(screen.getByLabelText("观察标题")).toHaveValue(title);
  expect(screen.getByLabelText("当时的想法")).toHaveValue(thought);
  fireEvent.click(screen.getByRole("button", { name: "保存观察与想法" }));
  await screen.findByRole("heading", { name: "保存前发现资料变化，尚未保存" });
  expect(screen.getByLabelText("当时的想法")).toHaveValue(thought);
  expect(screen.getByRole("button", { name: "保存观察与想法" })).toBeDisabled();
  expect(save).toHaveBeenLastCalledWith({
    title,
    note: thought,
    expected_fingerprint: "a".repeat(24),
    query: { ...result.query, as_of: result.as_of, industries: ["测试行业"] },
  });
  fireEvent.click(screen.getByRole("button", { name: "查看更新后的事实" }));
  await screen.findByRole("button", { name: "已核对当前事实，继续填写" });
  expect(screen.getByLabelText("观察标题")).toHaveValue(title);
  expect(screen.getByLabelText("当时的想法")).toHaveValue(thought);
  expect(screen.getByRole("button", { name: "保存观察与想法" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "已核对当前事实，继续填写" }),
  );
  expect(save).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "保存观察与想法" }));
  await screen.findByRole("heading", { name: title });
  expect(save).toHaveBeenLastCalledWith({
    title,
    note: thought,
    expected_fingerprint: "d".repeat(24),
    query: { ...result.query, as_of: result.as_of, industries: ["测试行业"] },
  });
  expect(screen.getByText(thought)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "回到这个范围" }));
  await screen.findByRole("heading", { name: "行业剖面" });
  expect(discover).toHaveBeenLastCalledWith({
    ...record.query,
    universe: "codes",
    codes: record.snapshot.members.map((member) => member.symbol),
    industries: [],
    as_of: record.snapshot.as_of,
  });
  fireEvent.click(screen.getByRole("button", { name: "测试行业" }));
  expect(screen.queryByLabelText("当时的想法")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "记下测试行业观察" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("link", { name: "我的研究" })[0]!);
  await screen.findByRole("heading", { name: "我的研究" });
  fireEvent.click(await screen.findByRole("link", { name: new RegExp(title) }));
  await screen.findByRole("heading", { name: title });
  expect(read).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(/复看截至日期/), {
    target: { value: "2026-11-04" },
  });
  fireEvent.click(screen.getByRole("button", { name: "开始复看" }));
  const comparison = await screen.findByRole("region", {
    name: "原观察与本次复看比较",
  });
  expect(review).toHaveBeenCalledWith(record.id, "2026-11-04");
  expect(within(comparison).getByText("100%")).toBeInTheDocument();
  expect(within(comparison).getByText("0%")).toBeInTheDocument();
  expect(within(comparison).getByText("两次无法比较")).toBeInTheDocument();
  expect(screen.getByText(thought)).toBeInTheDocument();
  expect(discover).toHaveBeenCalledTimes(4);
  fireEvent.click(screen.getByRole("button", { name: "编辑标题与想法" }));
  fireEvent.change(screen.getByLabelText("自己的想法"), {
    target: { value: "尚未保存的文字" },
  });
  expect(screen.getByRole("button", { name: "删除这条观察" })).toBeDisabled();
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getAllByRole("link", { name: "我的研究" })[0]!);
  await screen.findByRole("heading", { name: "我的研究" });
  fireEvent.click(await screen.findByRole("link", { name: new RegExp(title) }));
  expect(await screen.findByLabelText("自己的想法")).toHaveValue(
    "尚未保存的文字",
  );
  expect(
    screen.getByText("已恢复尚未保存的编辑草稿，原记录还没有改变。"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(edit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "删除这条观察" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "保存的原始事实和自己的想法都会被删除，无法恢复",
  );
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认删除这条观察" }));
  await screen.findByRole("heading", { name: "把一个观察，留给下一次核对" });
  expect(remove).toHaveBeenCalledExactlyOnceWith(record.id);
  expect(
    screen.queryByRole("heading", { name: title }),
  ).not.toBeInTheDocument();
});
