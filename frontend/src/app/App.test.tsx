import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { HealthResponse } from "../api/health";
import { App } from "./App";

const healthyResponse: HealthResponse = {
  status: "ok",
  app_version: "0.1.0",
  database: "ok",
  sqlite_version: "3.53.1",
};

describe("App", () => {
  it("shows loading and then the connected application shell", async () => {
    const loadHealth = vi.fn<() => Promise<HealthResponse>>();
    loadHealth.mockResolvedValue(healthyResponse);
    const createGameBridge = () => ({ mount: vi.fn(), destroy: vi.fn() });

    render(<App loadHealth={loadHealth} createGameBridge={createGameBridge} />);

    expect(screen.getByText("正在连接本地服务…")).toBeInTheDocument();
    expect(await screen.findByText("本地服务已连接")).toBeInTheDocument();
    expect(screen.getByText("SQLite 3.53.1")).toBeInTheDocument();
    expect(screen.getByLabelText("游戏地图画布")).toBeInTheDocument();
  });

  it("shows a retry action when the backend cannot be reached", async () => {
    const user = userEvent.setup();
    const loadHealth = vi.fn<() => Promise<HealthResponse>>();
    loadHealth
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(healthyResponse);
    const createGameBridge = () => ({ mount: vi.fn(), destroy: vi.fn() });

    render(<App loadHealth={loadHealth} createGameBridge={createGameBridge} />);

    expect(await screen.findByText("无法连接本地服务")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("本地服务已连接")).toBeInTheDocument();
    expect(loadHealth).toHaveBeenCalledTimes(2);
  });

  it("destroys the game bridge when the application unmounts", () => {
    const loadHealth = vi.fn<() => Promise<HealthResponse>>();
    loadHealth.mockResolvedValue(healthyResponse);
    const destroy = vi.fn();
    const createGameBridge = () => ({ mount: vi.fn(), destroy });

    const { unmount } = render(
      <App loadHealth={loadHealth} createGameBridge={createGameBridge} />,
    );
    unmount();

    expect(destroy).toHaveBeenCalledTimes(1);
  });
});
