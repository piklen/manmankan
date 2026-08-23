import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  defaultScreenSpec,
  type BoardDailyReview,
  type BoardDailyReviewSummary,
  type CandidateList,
  type SavedScreen,
  type ScreenRun,
} from "../api/client";
import { DailyReviewPage } from "./DailyReviewPage";

const now = "2026-08-24T00:00:00Z";

const review: BoardDailyReview = {
  schema_version: 1,
  review_id: "review-current",
  created_at: now,
  mode: "close",
  industry_level: 1,
  result_hash: "a".repeat(64),
  previous_review_id: "review-previous",
  partial: false,
  sections: [
    {
      kind: "industry",
      snapshot: {
        schema_version: 1,
        query: {
          kind: "industry",
          mode: "close",
          up: null,
          down: null,
          min_streak: null,
          sort: "streak",
          level: 1,
          limit: null,
          force: false,
        },
        source: "sw",
        data_cutoff: "2026-08-21",
        partial: false,
        coverage: { total: 31, evaluated: 31, matched: 31, returned: 31, errors: 0 },
        rows: [],
        failures: [],
        warnings: [],
      },
      error_code: null,
      error_message: null,
      error_hint: null,
    },
    {
      kind: "theme",
      snapshot: {
        schema_version: 1,
        query: {
          kind: "theme",
          mode: "close",
          up: null,
          down: null,
          min_streak: null,
          sort: "streak",
          level: 1,
          limit: null,
          force: false,
        },
        source: "tushare",
        data_cutoff: "2026-08-21",
        partial: false,
        coverage: { total: 395, evaluated: 395, matched: 395, returned: 395, errors: 0 },
        rows: [],
        failures: [],
        warnings: [],
      },
      error_code: null,
      error_message: null,
      error_hint: null,
    },
  ],
  changes: [
    {
      kind: "industry",
      code: "801080",
      name: "延长板块",
      change_type: "streak_extended",
      previous_streak: 2,
      current_streak: 3,
      previous_rank: 4,
      current_rank: 2,
    },
  ],
  change_counts: {
    data_appeared: 0,
    data_unavailable: 0,
    direction_changed: 0,
    streak_extended: 1,
    streak_shortened: 0,
  },
  warnings: [],
};

const summary: BoardDailyReviewSummary = {
  schema_version: 1,
  review_id: review.review_id,
  created_at: review.created_at,
  mode: "close",
  industry_level: 1,
  result_hash: review.result_hash,
  previous_review_id: review.previous_review_id,
  partial: false,
  sections: [
    { kind: "industry", source: "sw", data_cutoff: "2026-08-21", partial: false, total: 31, evaluated: 31, error_code: null, error_message: null },
    { kind: "theme", source: "tushare", data_cutoff: "2026-08-21", partial: false, total: 395, evaluated: 395, error_code: null, error_message: null },
  ],
  change_counts: review.change_counts,
};

const screens: SavedScreen[] = [
  {
    screen_id: "screen-a",
    name: "趋势规则 A",
    current_version: 1,
    spec: { ...defaultScreenSpec(), name: "趋势规则 A", exclude_st: true },
    spec_hash: "hash-a",
    created_at: now,
    updated_at: now,
  },
  {
    screen_id: "screen-b",
    name: "趋势规则 B",
    current_version: 2,
    spec: { ...defaultScreenSpec(), name: "趋势规则 B", exclude_bj: true },
    spec_hash: "hash-b",
    created_at: now,
    updated_at: now,
  },
];

const candidateLists: CandidateList[] = [
  {
    list_id: "default",
    name: "研究候选",
    candidates: [
      {
        list_id: "default",
        symbol: "600000",
        name: "候选甲",
        status: "watch",
        note: "下次核对成交量是否仍完整",
        source_run_id: null,
        added_at: now,
        updated_at: now,
      },
    ],
    created_at: now,
    updated_at: now,
  },
];

function mockQueries() {
  vi.spyOn(api, "boardReviews").mockResolvedValue([summary]);
  vi.spyOn(api, "boardReview").mockResolvedValue(review);
  vi.spyOn(api, "screens").mockResolvedValue(screens);
  vi.spyOn(api, "runs").mockResolvedValue([]);
  vi.spyOn(api, "candidateLists").mockResolvedValue(candidateLists);
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/review"]}>
        <DailyReviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("DailyReviewPage", () => {
  it("shows board changes, saved screens, and the user's candidate note", async () => {
    mockQueries();
    renderPage();

    expect(await screen.findByText("把今天看到的变化，留给明天复核")).toBeInTheDocument();
    expect(await screen.findByText("延长板块")).toBeInTheDocument();
    expect(screen.getByText("连涨 2 天")).toBeInTheDocument();
    expect(screen.getByText("连涨 3 天")).toBeInTheDocument();
    expect(await screen.findByText("趋势规则 A")).toBeInTheDocument();
    expect(await screen.findByText("下次核对成交量是否仍完整")).toBeInTheDocument();
    expect(screen.getByText("31/31 个已评估")).toBeInTheDocument();
    expect(screen.getByText("395/395 个已评估")).toBeInTheDocument();
  });

  it("saves the visible review definition and reruns saved screens sequentially", async () => {
    mockQueries();
    const create = vi.spyOn(api, "createBoardReview").mockResolvedValue(review);
    const run = vi.spyOn(api, "runSavedScreen").mockResolvedValue({} as ScreenRun);
    renderPage();

    await screen.findByText("趋势规则 A");
    fireEvent.click(screen.getByRole("button", { name: /保存最新复看/ }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({
      mode: "close",
      industry_level: 1,
      force: false,
    }));

    fireEvent.click(screen.getByRole("button", { name: /顺序重跑全部/ }));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
    expect(run.mock.calls.map(([screenId]) => screenId)).toEqual(["screen-a", "screen-b"]);
  });
});
