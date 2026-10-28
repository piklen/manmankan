import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Candidate, type FocusRow, type FocusSnapshot, type WorkspaceJob } from "../api/client";
import { FocusPage } from "./FocusPage";

const makeRow = (symbol = "600000", name = "测试对象甲"): FocusRow => ({
  symbol, name, sources: ["candidate"], source: "test-cache", data_hash: `hash-${symbol}`,
  available: true, price: 12.3, change_pct: 1.5, data_cutoff: "2026-10-28",
  previous_cutoff: "2026-10-26", stale: true, note: "等待核对现金流", candidate_list_id: "default",
  reviewed: false, periods: [{ period: 30, position_pct: 42, previous_position_pct: 40, change_pp: 2 }],
  review_history: [], candidates: [],
});
const snapshot = (rows: FocusRow[]): FocusSnapshot => ({
  generated_at: "2026-10-29T00:00:00Z", expected_cutoff: null,
  total: rows.length, available: rows.filter((row) => row.available).length,
  stale: rows.filter((row) => row.stale).length, rows, warnings: [],
});

function renderPage(entry = "/focus") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><FocusPage /></MemoryRouter></QueryClientProvider>);
}

beforeEach(() => { sessionStorage.clear(); vi.spyOn(api, "jobs").mockResolvedValue([]); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear(); });

describe("FocusPage", () => {
  it("starts with the user's own objects and never refreshes or seeds a selection automatically", async () => {
    vi.spyOn(api, "focus").mockResolvedValue(snapshot([]));
    const refresh = vi.spyOn(api, "startMarketRefresh");
    const add = vi.spyOn(api, "addFocus").mockResolvedValue({ symbol: "600000" } as Candidate);
    renderPage();
    expect(await screen.findByText("从你正在研究的一只股票开始")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更新关注数据" })).toBeDisabled();
    expect(refresh).not.toHaveBeenCalled();
    expect(add).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "添加第一个关注" }));
    expect(screen.getByRole("button", { name: "添加" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("添加明确的研究对象"), { target: { value: "600000" } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => expect(add).toHaveBeenCalledWith("600000"));
  });

  it("searches real objects and preserves note drafts while switching objects and remounting", async () => {
    vi.spyOn(api, "focus").mockResolvedValue(snapshot([makeRow(), makeRow("000001", "测试对象乙")]));
    const view = renderPage();
    await screen.findByRole("button", { name: "查看 测试对象甲 600000" });
    fireEvent.change(screen.getByLabelText("观察笔记"), { target: { value: "未保存但不能丢失的观察" } });
    fireEvent.click(screen.getByRole("button", { name: "查看 测试对象乙 000001" }));
    expect(screen.getByLabelText("观察笔记")).toHaveValue("等待核对现金流");
    fireEvent.click(screen.getByRole("button", { name: "查看 测试对象甲 600000" }));
    expect(screen.getByLabelText("观察笔记")).toHaveValue("未保存但不能丢失的观察");
    view.unmount();
    renderPage();
    await screen.findByRole("button", { name: "查看 测试对象甲 600000" });
    expect(screen.getByLabelText("观察笔记")).toHaveValue("未保存但不能丢失的观察");
    fireEvent.change(screen.getByLabelText("搜索关注名称或代码"), { target: { value: "000001" } });
    expect(screen.queryByRole("button", { name: "查看 测试对象甲 600000" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看 测试对象乙 000001" })).toBeInTheDocument();
  });

  it("saves the draft before review and submits the exact visible data hash and note", async () => {
    const row = makeRow();
    vi.spyOn(api, "focus").mockResolvedValue(snapshot([row]));
    const saved = vi.spyOn(api, "saveFocusNote").mockImplementation(async (_, note) => {
      row.note = note; return { symbol: row.symbol, note } as Candidate;
    });
    const reviewed = vi.spyOn(api, "reviewFocus").mockImplementation(async () => {
      row.reviewed = true; return { reviewed_at: "2026-10-29T01:00:00Z", data_cutoff: "2026-10-28", note: row.note, price: 12.3, positions: { "30": 42 }, data_hash: "hash-600000" };
    });
    renderPage();
    await screen.findByLabelText("观察笔记");
    expect(screen.getByText(/对比日 2026-10-26/)).toBeInTheDocument();
    expect(screen.getByText("较上一条行情")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("观察笔记"), { target: { value: "已经核对这次数据" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并复看" }));
    await waitFor(() => expect(reviewed).toHaveBeenCalledWith("600000", "hash-600000", "已经核对这次数据"));
    expect(saved).toHaveBeenCalledWith("600000", "已经核对这次数据", "default");
    expect(saved.mock.invocationCallOrder[0]).toBeLessThan(reviewed.mock.invocationCallOrder[0]!);
    expect(await screen.findByRole("status")).toHaveTextContent("已保存这次复看");
    await waitFor(() => expect(sessionStorage.getItem("manmankan.focus-drafts.v1")).toBeNull());
  });

  it("keeps a failed save editable and does not permit a missing-data review", async () => {
    const row = { ...makeRow(), available: false, price: null, message: "缓存暂不可用", note: "", periods: [] };
    vi.spyOn(api, "focus").mockResolvedValue(snapshot([row]));
    vi.spyOn(api, "saveFocusNote").mockRejectedValue(new Error("写入失败，请重试"));
    renderPage();
    await screen.findByLabelText("观察笔记");
    expect(screen.getByRole("button", { name: "标记已复看" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("观察笔记"), { target: { value: "需要保留的草稿" } });
    fireEvent.click(screen.getByRole("button", { name: "保存笔记" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("写入失败，请重试");
    expect(screen.getByLabelText("观察笔记")).toHaveValue("需要保留的草稿");
    expect(screen.getByRole("button", { name: "保存并复看" })).toBeDisabled();
  });

  it("lets the user reopen the facts captured with an earlier review", async () => {
    const row = makeRow();
    row.review_history = [{
      reviewed_at: "2026-10-27T01:00:00Z", data_cutoff: "2026-10-26", note: "上次核对的观察",
      price: 10.25, positions: { "30": 31.5, "60": null }, data_hash: "historical-hash",
    }];
    vi.spyOn(api, "focus").mockResolvedValue(snapshot([row]));
    renderPage();
    await screen.findByText("上次核对的观察");
    const summary = screen.getByText("查看当时数据");
    fireEvent.click(summary);
    expect(summary.closest("details")).toHaveAttribute("open");
    expect(screen.getByText("10.25")).toBeInTheDocument();
    expect(screen.getByText("31.5%")).toBeInTheDocument();
    expect(screen.getByText("这是本次复看时保存的事实，之后的数据更新不会改写它。")).toBeInTheDocument();
  });

  it("does not substitute another stock when a direct-link target is absent", async () => {
    vi.spyOn(api, "focus").mockResolvedValue(snapshot([makeRow()]));
    renderPage("/focus?symbol=000001");
    expect(await screen.findByText("000001 不在当前关注列表中。")).toBeInTheDocument();
    expect(screen.queryByLabelText("测试对象甲 观察详情")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回全部关注" }));
    expect(screen.getByLabelText("测试对象甲 观察详情")).toBeInTheDocument();
  });

  it("updates only the focus scope when explicitly requested and shows persistent progress", async () => {
    vi.spyOn(api, "focus").mockResolvedValue(snapshot([makeRow()]));
    const job = { job_id: "focus-job", kind: "market_refresh:focus", status: "running", progress: 1, total: 2, message: "更新 600000", error: null } as WorkspaceJob;
    const refresh = vi.spyOn(api, "startMarketRefresh").mockResolvedValue(job);
    vi.spyOn(api, "job").mockResolvedValue(job);
    renderPage();
    await screen.findByRole("button", { name: "查看 测试对象甲 600000" });
    expect(refresh).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "更新关注数据" }));
    await waitFor(() => expect(refresh).toHaveBeenCalledWith("focus"));
    expect(await screen.findByText(/更新 600000/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "正在更新" })).toBeDisabled();
  });
});
