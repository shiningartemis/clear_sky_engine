import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { AiSettingsApi } from "../api/aiSettings";
import type { HealthResponse } from "../api/health";
import type { RolesApi } from "../api/roles";
import type { WorldsApi } from "../api/worlds";
import { App } from "./App";
import {
  TurnRunNavigationGuard,
  TurnRunNavigationProvider,
  useTurnRunNavigation,
} from "./TurnRunContext";

vi.mock("../game/PhaserGame", () => ({
  createDefaultGameBridge: () => ({
    mount: vi.fn(),
    update: vi.fn(),
    setInputLocked: vi.fn(),
    subscribe: vi.fn(() => vi.fn()),
    destroy: vi.fn(),
  }),
}));

const healthyResponse: HealthResponse = {
  status: "ok",
  app_version: "0.1.0",
  database: "ok",
  sqlite_version: "3.53.1",
};

function createWorldsApi(overrides: Partial<WorldsApi> = {}): WorldsApi {
  return {
    listWorlds: vi.fn().mockResolvedValue([]),
    createWorld: vi.fn(),
    deleteWorld: vi.fn(),
    listWorldRoles: vi.fn().mockResolvedValue([]),
    addNpc: vi.fn(),
    setNpcEnabled: vi.fn(),
    removeNpc: vi.fn(),
    replaceLocationRules: vi.fn(),
    selectLocation: vi.fn(),
    getGameView: vi.fn(),
    ...overrides,
  };
}

function createRolesApi(overrides: Partial<RolesApi> = {}): RolesApi {
  return {
    listAssets: vi.fn().mockResolvedValue([]),
    listRoles: vi.fn().mockResolvedValue([]),
    createRole: vi.fn(),
    updateRole: vi.fn(),
    deleteRole: vi.fn(),
    ...overrides,
  };
}

function renderApp(element: React.ReactNode, path = "/") {
  return render(<MemoryRouter initialEntries={[path]}>{element}</MemoryRouter>);
}

describe("App", () => {
  it("活动轮次阻止设置、角色和世界导航，并在刷新时中止流", async () => {
    const controller = new AbortController();
    const user = userEvent.setup();

    function LockProbe() {
      const navigation = useTurnRunNavigation();
      useEffect(() => navigation.acquire(controller), [navigation.acquire]);
      return <p>{navigation.isNavigationLocked ? "已锁定" : "未锁定"}</p>;
    }

    const { unmount } = render(
      <MemoryRouter initialEntries={["/"]}>
        <TurnRunNavigationProvider>
          <LockProbe />
          <TurnRunNavigationGuard>
            <Routes>
              <Route
                path="/"
                element={<Link to="/settings/ai">AI 设置</Link>}
              />
              <Route path="/settings/ai" element={<p>设置页面</p>} />
            </Routes>
          </TurnRunNavigationGuard>
        </TurnRunNavigationProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText("已锁定")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "AI 设置" }));
    expect(screen.queryByText("设置页面")).not.toBeInTheDocument();

    window.dispatchEvent(new Event("pagehide"));
    expect(controller.signal.aborted).toBe(true);
    unmount();
  });

  it("程序化跳转离开页面时中止并释放活动轮次锁", async () => {
    const controller = new AbortController();
    const user = userEvent.setup();

    function LockProbe() {
      const navigation = useTurnRunNavigation();
      useEffect(() => navigation.acquire(controller), [navigation.acquire]);
      return <p>{navigation.isNavigationLocked ? "已锁定" : "未锁定"}</p>;
    }

    function ProgrammaticNavigation() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => navigate("/settings/ai")}>
          程序化跳转
        </button>
      );
    }

    render(
      <MemoryRouter initialEntries={["/"]}>
        <TurnRunNavigationProvider>
          <LockProbe />
          <TurnRunNavigationGuard>
            <Routes>
              <Route path="/" element={<ProgrammaticNavigation />} />
              <Route path="/settings/ai" element={<p>设置页面</p>} />
            </Routes>
          </TurnRunNavigationGuard>
        </TurnRunNavigationProvider>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "程序化跳转" }));

    expect(await screen.findByText("设置页面")).toBeInTheDocument();
    await waitFor(() => expect(controller.signal.aborted).toBe(true));
    expect(screen.getByText("未锁定")).toBeInTheDocument();
  });

  it("浏览器历史返回离开页面时中止并释放活动轮次锁", async () => {
    const controller = new AbortController();
    const user = userEvent.setup();

    function LockProbe() {
      const navigation = useTurnRunNavigation();
      useEffect(() => navigation.acquire(controller), [navigation.acquire]);
      return <p>{navigation.isNavigationLocked ? "已锁定" : "未锁定"}</p>;
    }

    function BackNavigation() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => navigate(-1)}>
          返回上一页
        </button>
      );
    }

    render(
      <MemoryRouter initialEntries={["/", "/settings/ai"]} initialIndex={1}>
        <TurnRunNavigationProvider>
          <LockProbe />
          <TurnRunNavigationGuard>
            <Routes>
              <Route path="/" element={<p>世界页面</p>} />
              <Route path="/settings/ai" element={<BackNavigation />} />
            </Routes>
          </TurnRunNavigationGuard>
        </TurnRunNavigationProvider>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "返回上一页" }));

    expect(await screen.findByText("世界页面")).toBeInTheDocument();
    await waitFor(() => expect(controller.signal.aborted).toBe(true));
    expect(screen.getByText("未锁定")).toBeInTheDocument();
  });

  it("keeps health as a lightweight gate before rendering the world route", async () => {
    let resolveHealth: ((health: HealthResponse) => void) | undefined;
    const loadHealth = vi.fn(
      () =>
        new Promise<HealthResponse>((resolve) => {
          resolveHealth = resolve;
        }),
    );
    const worldsApi = createWorldsApi();
    const rolesApi = createRolesApi();

    renderApp(
      <App loadHealth={loadHealth} worldsApi={worldsApi} rolesApi={rolesApi} />,
    );

    expect(screen.getByText("正在连接本地服务…")).toBeInTheDocument();
    expect(worldsApi.listWorlds).not.toHaveBeenCalled();
    resolveHealth?.(healthyResponse);

    expect(await screen.findByText("还没有世界")).toBeInTheDocument();
    expect(worldsApi.listWorlds).toHaveBeenCalledTimes(1);
  });

  it("preserves health failure handling and retry before routes", async () => {
    const user = userEvent.setup();
    const loadHealth = vi
      .fn<() => Promise<HealthResponse>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(healthyResponse);

    renderApp(
      <App
        loadHealth={loadHealth}
        worldsApi={createWorldsApi()}
        rolesApi={createRolesApi()}
      />,
    );

    expect(await screen.findByText("无法连接本地服务")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("还没有世界")).toBeInTheDocument();
    expect(loadHealth).toHaveBeenCalledTimes(2);
  });

  it("preserves the global role-library route behind health bootstrap", async () => {
    const rolesApi = createRolesApi();
    renderApp(
      <App
        loadHealth={vi.fn().mockResolvedValue(healthyResponse)}
        rolesApi={rolesApi}
      />,
      "/roles",
    );

    expect(await screen.findByText("角色库还是空的")).toBeInTheDocument();
    expect(rolesApi.listRoles).toHaveBeenCalledTimes(1);
  });

  it("routes a world to its read-only role page", async () => {
    const worldsApi = createWorldsApi();
    const rolesApi = createRolesApi();
    renderApp(
      <App
        loadHealth={vi.fn().mockResolvedValue(healthyResponse)}
        worldsApi={worldsApi}
        rolesApi={rolesApi}
      />,
      "/worlds/4/roles",
    );

    expect(
      await screen.findByRole("heading", { name: "世界角色" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(worldsApi.listWorldRoles).toHaveBeenCalledWith(
        4,
        expect.any(AbortSignal),
      );
    });
  });

  it("navigates from world roles to the real game route", async () => {
    const user = userEvent.setup();
    const worldsApi = createWorldsApi({
      getGameView: vi.fn().mockResolvedValue({
        world_id: 4,
        scene_id: "the_world_map",
        background_url: "/maps/world.jpg",
        fallback_background_url: "/maps/fallback.jpg",
        player_marker_url: "/portraits/player.png",
        player_location_id: "the_home",
        locations: [],
        visible_roles: [],
      }),
    });

    renderApp(
      <App
        loadHealth={vi.fn().mockResolvedValue(healthyResponse)}
        worldsApi={worldsApi}
        rolesApi={createRolesApi()}
      />,
      "/worlds/4/roles",
    );

    await user.click(await screen.findByRole("link", { name: "进入世界" }));

    expect(await screen.findByLabelText("游戏地图")).toBeInTheDocument();
    expect(worldsApi.getGameView).toHaveBeenCalledWith(
      4,
      "the_world_map",
      expect.any(AbortSignal),
    );
  });

  it("preserves global AI settings routing", async () => {
    const settingsApi: AiSettingsApi = {
      listProviders: vi.fn().mockResolvedValue([]),
      listModels: vi.fn().mockResolvedValue([]),
      listTaskSettings: vi.fn().mockResolvedValue([]),
      createProvider: vi.fn(),
      updateProvider: vi.fn(),
      deleteProvider: vi.fn(),
      createModel: vi.fn(),
      updateModel: vi.fn(),
      deleteModel: vi.fn(),
      testConnection: vi.fn(),
      updateTaskSetting: vi.fn(),
    };

    renderApp(
      <App
        loadHealth={vi.fn().mockResolvedValue(healthyResponse)}
        settingsApi={settingsApi}
      />,
      "/settings/ai",
    );

    expect(
      await screen.findByRole("heading", { name: "Provider 与模型" }),
    ).toBeInTheDocument();
  });
});
