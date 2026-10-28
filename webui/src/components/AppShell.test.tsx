import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

function NavigationHarness() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/focus?symbol=600000")}>选择关注对象</button><button onClick={() => navigate("/settings")}>打开设置页</button></>;
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("AppShell navigation", () => {
  it("resets deep scroll between pages while keeping in-page selection in place", () => {
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    render(<MemoryRouter initialEntries={["/focus"]}><Routes><Route element={<AppShell />}><Route path="*" element={<NavigationHarness />} /></Route></Routes></MemoryRouter>);
    expect(scroll).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "选择关注对象" }));
    expect(scroll).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "打开设置页" }));
    expect(scroll).toHaveBeenCalledTimes(2);
    expect(scroll).toHaveBeenLastCalledWith(0, 0);
    expect(screen.getByText("创新低 ≠ 见底 · 创新高 ≠ 顶 · 历史价格不预示未来 · 仅供参考，不构成投资建议")).toBeInTheDocument();
  });
});
