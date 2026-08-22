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

  it("keeps a fully explicit default ScreenSpec", () => {
    const spec = defaultScreenSpec();

    expect(spec.universe?.kind).toBe("watchlist");
    expect(spec.conditions).toHaveLength(1);
    expect(spec.conditions?.[0]).toMatchObject({
      type: "pos",
      period: 180,
      operator: "lt",
      null_policy: "exclude",
    });
    expect(spec.sort?.[0]?.field_id).toBe("position.180d");
  });
});
