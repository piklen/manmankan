import { afterEach, describe, expect, it, vi } from "vitest";
import { api, defaultScreenSpec } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  document.head.innerHTML = "";
});

describe("API client", () => {
  it("sends the embedded session and mutation guard headers", async () => {
    document.head.innerHTML = '<meta name="kan-session" content="session-test">';
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          screen_id: "screen-1",
          name: "我的选股规则",
          current_version: 1,
          spec: defaultScreenSpec(),
          spec_hash: "hash",
          created_at: "2026-08-23T00:00:00Z",
          updated_at: "2026-08-23T00:00:00Z",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.saveScreen(defaultScreenSpec());

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("x-kan-session")).toBe("session-test");
    expect(headers.get("X-Kan-Web")).toBe("1");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("starts without a hidden default strategy", () => {
    const spec = defaultScreenSpec();

    expect(spec.universe?.kind).toBe("watchlist");
    expect(spec.conditions).toHaveLength(0);
    expect(spec.exclude_st).toBe(false);
    expect(spec.sort).toHaveLength(0);
  });

  it("encodes board pulse paths without changing the board value", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.boardPulse("theme", "AI 应用", 1, 3);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/boards/theme/AI%20%E5%BA%94%E7%94%A8/pulse?level=1&limit=3",
    );
  });

  it("creates a typed daily board review without hidden thresholds", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.createBoardReview({
      mode: "close",
      industry_level: 1,
      force: false,
    });

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/v1/board-reviews");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      mode: "close",
      industry_level: 1,
      force: false,
    });
  });

  it("posts every visible board history parameter", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const payload = {
      kind: "theme" as const,
      value: "885781",
      level: 1,
      mode: "close" as const,
      direction: "up" as const,
      min_streak: 3,
      forward_days: 5,
      lookback_years: 5,
      sample_policy: "first_hit" as const,
      benchmark_code: "000300.SH",
      force: false,
    };

    await api.studyBoardHistory(payload);

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/v1/board-history-studies");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(payload);
  });
});
