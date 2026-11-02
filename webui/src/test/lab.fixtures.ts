import type {
  StudyEvidence,
  StudyQuery,
  StudyResult,
} from "../api/client";

export const bars = Array.from({ length: 28 }, (_, index) => ({
  date: `2026-10-${String(index + 1).padStart(2, "0")}`,
  open: 10 + index / 10,
  high: 10.3 + index / 10,
  low: 9.8 + index / 10,
  close: 10.1 + index / 10,
  volume: 1000 + index,
}));
export function resultFixture(query: StudyQuery): StudyResult {
  return {
    study_id: "study-test",
    run_id: "run-test",
    query: {
      title: query.title,
      universe: query.universe,
      codes: query.codes,
      lookback_days: query.lookback_days,
      as_of: query.as_of,
      forward_days: query.forward_days,
      sample_policy: query.sample_policy,
      conditions: query.conditions,
      reference: query.reference,
    },
    created_at: "2026-10-29T01:00:00Z",
    as_of: "2026-10-28",
    start_date: "2026-05-01",
    universe_note: "测试股票池的历史，不代表历史全市场。",
    coverage: {
      total_symbols: 1,
      cached_symbols: 1,
      missing_symbols: 0,
      calendar_days: 120,
      historical_stock_days: 120,
      valid_stock_days: 120,
      evaluated_stock_days: 90,
      matched_stock_days: 2,
      selected_events: 2,
      complete_events: 1,
      pending_events: 1,
      missing_events: 0,
      current_evaluated: 1,
      current_matches: 1,
      current_missing: 0,
      self_matches_excluded: 0,
    },
    distribution: {
      count: 1,
      positive: 1,
      negative: 0,
      flat: 0,
      positive_ratio_pct: 100,
      mean_pct: 2.5,
      median_pct: 2.5,
      p10_pct: 2.5,
      p90_pct: 2.5,
      bins: [{ label: "0–5%", count: 1 }],
    },
    current_matches: [
      {
        symbol: "600000",
        name: "测试股票甲",
        date: "2026-10-28",
        close: 12.8,
        change_pct: 1,
        values: {},
      },
    ],
    events: [
      {
        event_id: "event-one",
        symbol: "600000",
        name: "测试股票甲",
        event_date: "2026-10-20",
        event_close: 12,
        forward_date: "2026-10-27",
        status: "complete",
        return_pct: 2.5,
        max_return_pct: 3,
        min_return_pct: -1,
        values: {},
      },
      {
        event_id: "event-two",
        symbol: "600000",
        name: "测试股票甲",
        event_date: "2026-10-28",
        event_close: 12.8,
        forward_date: null,
        status: "pending",
        return_pct: null,
        values: {},
      },
    ],
    events_total: 2,
    diff: { previous_run_id: null, added: [], removed: [], unavailable: [] },
    warnings: [],
    reference_bars: query.reference ? bars.slice(-20) : [],
  };
}
export function evidenceFixture(
  date: string,
  query: StudyQuery,
): StudyEvidence {
  return {
    run_id: "run-test",
    symbol: "600000",
    name: "测试股票甲",
    event_date: date,
    source: "test-fixture",
    bars,
    conditions: query.conditions.map((condition) => ({
      condition,
      actual: condition.value,
      matched: true,
      bound: "exact",
    })),
    outcome:
      resultFixture(query).events.find((event) => event.event_date === date) ??
      null,
    warnings: [],
    reference_bars: query.reference ? bars.slice(-20) : [],
  };
}
