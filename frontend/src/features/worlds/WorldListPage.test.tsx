import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { RolesApi } from "../../api/roles";
import type { WorldResponse, WorldsApi } from "../../api/worlds";
import { WorldListPage } from "./WorldListPage";

function worldResponse(overrides: Partial<WorldResponse> = {}): WorldResponse {
  return {
    id: 4,
    display_name: "世界 4",
    active_branch_id: 5,
    day: 3,
    weekday: "wednesday",
    time_slot: "evening",
    player_role: {
      id: 9,
      name: "天",
      persona: "谨慎的冒险者",
      system_prompt: "",
      world_book: "",
      attributes: [],
      effective_base_values: {},
      portrait_url: "/portraits/tian",
      referenced_world_ids: [4],
      version: 1,
      created_at: "2026-07-14T00:00:00Z",
      updated_at: "2026-07-14T00:00:00Z",
    },
    npc_count: 2,
    last_played_at: "2026-07-14T08:30:00Z",
    ...overrides,
  };
}

function createWorldsApi(overrides: Partial<WorldsApi> = {}): WorldsApi {
  return {
    listWorlds: vi.fn().mockResolvedValue([]),
    createWorld: vi.fn(),
    deleteWorld: vi.fn(),
    listWorldRoles: vi.fn(),
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
    listAssets: vi.fn().mockResolvedValue([
      { role_name: "天", portrait_url: "/portraits/tian" },
      { role_name: "安可儿", portrait_url: "/portraits/anker" },
    ]),
    listRoles: vi.fn().mockResolvedValue([]),
    createRole: vi.fn(),
    updateRole: vi.fn(),
    deleteRole: vi.fn(),
    ...overrides,
  };
}

function renderWorldList(api = createWorldsApi(), assetApi = createRolesApi()) {
  return render(
    <MemoryRouter>
      <WorldListPage api={api} assetApi={assetApi} />
    </MemoryRouter>,
  );
}

function deferred<T>() {
  let resolve: ((value: T) => void) | undefined;
  let reject: ((reason?: unknown) => void) | undefined;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return {
    promise,
    resolve(value: T) {
      resolve?.(value);
    },
    reject(reason?: unknown) {
      reject?.(reason);
    },
  };
}

describe("WorldListPage", () => {
  it("creates a world without asking for a world name or weekday", async () => {
    const user = userEvent.setup();
    renderWorldList();
    await user.click(await screen.findByRole("button", { name: "创建世界" }));

    expect(screen.queryByLabelText("世界名称")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("起始星期")).not.toBeInTheDocument();
    expect(screen.getByLabelText("主角名称")).toBeInTheDocument();
    expect(screen.getByLabelText("基础人设")).toBeInTheDocument();
    expect(
      screen.getByText("固定从星期一 · Day 1 · 晨间开始"),
    ).toBeInTheDocument();
  });

  it("retains protagonist input when atomic creation fails", async () => {
    const user = userEvent.setup();
    const api = createWorldsApi({
      createWorld: vi.fn().mockRejectedValue(new Error("conflict")),
    });
    renderWorldList(api);

    await user.click(await screen.findByRole("button", { name: "创建世界" }));
    await user.selectOptions(screen.getByLabelText("主角名称"), "天");
    await user.type(screen.getByLabelText("基础人设"), "谨慎的冒险者");
    await user.click(screen.getByRole("button", { name: "确认创建" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("创建世界失败");
    expect(screen.getByLabelText("主角名称")).toHaveValue("天");
    expect(screen.getByLabelText("基础人设")).toHaveValue("谨慎的冒险者");
  });

  it("navigates to world roles after successful creation", async () => {
    const user = userEvent.setup();
    const api = createWorldsApi({
      createWorld: vi.fn().mockResolvedValue(worldResponse()),
    });
    const assetApi = createRolesApi();

    render(
      <MemoryRouter>
        <Routes>
          <Route
            path="/"
            element={<WorldListPage api={api} assetApi={assetApi} />}
          />
          <Route path="/worlds/:worldId/roles" element={<p>世界角色页</p>} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "创建世界" }));
    await user.selectOptions(screen.getByLabelText("主角名称"), "天");
    await user.type(screen.getByLabelText("基础人设"), "谨慎的冒险者");
    await user.click(screen.getByRole("button", { name: "确认创建" }));

    expect(await screen.findByText("世界角色页")).toBeInTheDocument();
    expect(api.createWorld).toHaveBeenCalledWith({
      protagonist_name: "天",
      protagonist_persona: "谨慎的冒险者",
    });
  });

  it("does not navigate when a delayed create succeeds after leaving the page", async () => {
    const user = userEvent.setup();
    const createResult = deferred<WorldResponse>();
    const api = createWorldsApi({
      createWorld: vi.fn(() => createResult.promise),
    });

    render(
      <MemoryRouter>
        <Routes>
          <Route
            path="/"
            element={
              <>
                <Link to="/away">离开世界列表</Link>
                <WorldListPage api={api} assetApi={createRolesApi()} />
              </>
            }
          />
          <Route path="/away" element={<p>已离开世界列表</p>} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "创建世界" }));
    await user.selectOptions(screen.getByLabelText("主角名称"), "天");
    await user.type(screen.getByLabelText("基础人设"), "谨慎的冒险者");
    await user.click(screen.getByRole("button", { name: "确认创建" }));
    await user.click(screen.getByRole("link", { name: "离开世界列表" }));

    await act(async () => {
      createResult.resolve(worldResponse());
      await createResult.promise;
    });

    expect(screen.getByText("已离开世界列表")).toBeInTheDocument();
  });

  it("does not apply a delayed delete after the page reloads", async () => {
    const user = userEvent.setup();
    const deleteResult = deferred<void>();
    const firstApi = createWorldsApi({
      listWorlds: vi.fn().mockResolvedValue([worldResponse()]),
      deleteWorld: vi.fn(() => deleteResult.promise),
    });
    const secondApi = createWorldsApi({
      listWorlds: vi.fn().mockResolvedValue([worldResponse({ day: 9 })]),
    });
    const assetApi = createRolesApi();
    const view = render(
      <MemoryRouter>
        <WorldListPage api={firstApi} assetApi={assetApi} />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", { name: "删除世界 世界 4" }),
    );
    await user.click(screen.getByRole("button", { name: "确认删除 世界 4" }));
    view.rerender(
      <MemoryRouter>
        <WorldListPage api={secondApi} assetApi={assetApi} />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText("Day 9 · 星期三 · 傍晚"),
    ).toBeInTheDocument();

    await act(async () => {
      deleteResult.resolve(undefined);
      await deleteResult.promise;
    });

    expect(screen.getByText("Day 9 · 星期三 · 傍晚")).toBeInTheDocument();
  });

  it("does not show a delayed delete error after the page reloads", async () => {
    const user = userEvent.setup();
    const deleteResult = deferred<void>();
    const firstApi = createWorldsApi({
      listWorlds: vi.fn().mockResolvedValue([worldResponse()]),
      deleteWorld: vi.fn(() => deleteResult.promise),
    });
    const secondApi = createWorldsApi({
      listWorlds: vi.fn().mockResolvedValue([worldResponse({ day: 9 })]),
    });
    const assetApi = createRolesApi();
    const view = render(
      <MemoryRouter>
        <WorldListPage api={firstApi} assetApi={assetApi} />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", { name: "删除世界 世界 4" }),
    );
    await user.click(screen.getByRole("button", { name: "确认删除 世界 4" }));
    view.rerender(
      <MemoryRouter>
        <WorldListPage api={secondApi} assetApi={assetApi} />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText("Day 9 · 星期三 · 傍晚"),
    ).toBeInTheDocument();

    await act(async () => {
      deleteResult.reject(new Error("late failure"));
      await deleteResult.promise.catch(() => undefined);
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Day 9 · 星期三 · 傍晚")).toBeInTheDocument();
  });

  it("renders only server world facts and confirms deletion", async () => {
    const user = userEvent.setup();
    const api = createWorldsApi({
      listWorlds: vi.fn().mockResolvedValue([worldResponse()]),
      deleteWorld: vi.fn().mockResolvedValue(undefined),
    });
    renderWorldList(api);

    expect(
      await screen.findByRole("heading", { name: "世界 4" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Day 3 · 星期三 · 傍晚")).toBeInTheDocument();
    expect(screen.getByText("主角：天")).toBeInTheDocument();
    expect(screen.getByText("NPC：2")).toBeInTheDocument();
    expect(screen.getByText(/最后游玩：/)).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "世界名称" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "删除世界 世界 4" }));
    expect(screen.getByText("删除后无法恢复。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认删除 世界 4" }));
    expect(api.deleteWorld).toHaveBeenCalledWith(4);
    expect(
      screen.queryByRole("heading", { name: "世界 4" }),
    ).not.toBeInTheDocument();
  });

  it("offers loading, empty, error retry, and explained disabled states", async () => {
    const user = userEvent.setup();
    const listWorlds = vi
      .fn<WorldsApi["listWorlds"]>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce([]);
    const api = createWorldsApi({ listWorlds });
    const assetApi = createRolesApi({
      listAssets: vi.fn().mockResolvedValue([]),
    });
    renderWorldList(api, assetApi);

    expect(screen.getByText("正在加载世界…")).toBeInTheDocument();
    expect(await screen.findByText("无法加载世界列表")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("还没有世界")).toBeInTheDocument();
    const createButton = screen.getByRole("button", { name: "创建世界" });
    expect(createButton).toBeDisabled();
    expect(createButton).toHaveAccessibleDescription(
      "请先在角色资源目录添加主角的同名默认立绘。",
    );
  });
});
