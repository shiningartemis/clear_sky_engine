import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { AiSettingsApi } from "../api/aiSettings";
import type { HealthResponse } from "../api/health";
import type { RolesApi } from "../api/roles";
import { App } from "./App";

const healthyResponse: HealthResponse = {
  status: "ok",
  app_version: "0.1.0",
  database: "ok",
  sqlite_version: "3.53.1",
};

function renderApp(element: React.ReactNode) {
  return render(<MemoryRouter>{element}</MemoryRouter>);
}

describe("App", () => {
  it("shows loading and then the connected application shell", async () => {
    const loadHealth = vi.fn<() => Promise<HealthResponse>>();
    loadHealth.mockResolvedValue(healthyResponse);
    const createGameBridge = () => ({ mount: vi.fn(), destroy: vi.fn() });

    renderApp(
      <App loadHealth={loadHealth} createGameBridge={createGameBridge} />,
    );

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

    renderApp(
      <App loadHealth={loadHealth} createGameBridge={createGameBridge} />,
    );

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

    const { unmount } = renderApp(
      <App loadHealth={loadHealth} createGameBridge={createGameBridge} />,
    );
    unmount();

    expect(destroy).toHaveBeenCalledTimes(1);
  });

  it("navigates from the game shell to global AI settings", async () => {
    const user = userEvent.setup();
    const loadHealth = vi
      .fn<() => Promise<HealthResponse>>()
      .mockResolvedValue(healthyResponse);
    const settingsApi: AiSettingsApi = {
      listProviders: vi.fn().mockResolvedValue([]),
      listModels: vi.fn().mockResolvedValue([]),
      createProvider: vi.fn(),
      updateProvider: vi.fn(),
      deleteProvider: vi.fn(),
      createModel: vi.fn(),
      updateModel: vi.fn(),
      deleteModel: vi.fn(),
      testConnection: vi.fn(),
    };

    renderApp(
      <App
        loadHealth={loadHealth}
        createGameBridge={() => ({ mount: vi.fn(), destroy: vi.fn() })}
        settingsApi={settingsApi}
      />,
    );

    await user.click(await screen.findByRole("link", { name: "AI 设置" }));
    expect(
      await screen.findByRole("heading", { name: "Provider 与模型" }),
    ).toBeInTheDocument();
  });

  it("renders the role library route with its injected API", async () => {
    const rolesApi: RolesApi = {
      listAssets: vi.fn().mockResolvedValue([]),
      listRoles: vi.fn().mockResolvedValue([]),
      createRole: vi.fn(),
      updateRole: vi.fn(),
      deleteRole: vi.fn(),
    };

    render(
      <MemoryRouter initialEntries={["/roles"]}>
        <App rolesApi={rolesApi} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("角色库还是空的")).toBeInTheDocument();
    expect(rolesApi.listRoles).toHaveBeenCalledTimes(1);
  });
});
