import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/health";
import type { RoleResponse, RolesApi } from "../../api/roles";
import type { WorldRoleResponse, WorldsApi } from "../../api/worlds";
import { WorldRolesPage } from "./WorldRolesPage";

function libraryRole(overrides: Partial<RoleResponse> = {}): RoleResponse {
  return {
    id: 9,
    name: "天",
    persona: "谨慎",
    system_prompt: "",
    world_book: "",
    attributes: [
      {
        key: "level",
        display_name: "等级",
        data_type: "integer",
        base_value: 1,
        description: "当前等级",
        update_rule: "仅在升级时更新",
        allowed_operations: ["replace", "increment", "decrement"],
        minimum: 1,
        maximum: 100,
        enum_options: [],
        update_example: null,
        no_update_example: null,
      },
    ],
    effective_base_values: { level: 1 },
    portrait_url: "/portraits/tian",
    referenced_world_ids: [4],
    version: 1,
    created_at: "2026-07-14T00:00:00Z",
    updated_at: "2026-07-14T00:00:00Z",
    ...overrides,
  };
}

function worldRole(
  overrides: Partial<WorldRoleResponse> = {},
): WorldRoleResponse {
  return {
    world_id: 4,
    role_id: 9,
    name: "天",
    kind: "player",
    enabled: true,
    effective_attributes: { level: 11 },
    portrait_url: "/portraits/tian",
    version: 1,
    updated_at: "2026-07-14T00:00:00Z",
    ...overrides,
  };
}

function createWorldsApi(overrides: Partial<WorldsApi> = {}): WorldsApi {
  return {
    listWorlds: vi.fn(),
    createWorld: vi.fn(),
    deleteWorld: vi.fn(),
    listWorldRoles: vi
      .fn()
      .mockResolvedValue([
        worldRole({ role_id: 12, name: "莫莉莉", kind: "npc" }),
        worldRole(),
      ]),
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
    listRoles: vi.fn().mockResolvedValue([
      libraryRole(),
      libraryRole({
        id: 12,
        name: "莫莉莉",
        portrait_url: "/portraits/molly",
      }),
      libraryRole({
        id: 15,
        name: "安可儿",
        portrait_url: "/portraits/anker",
      }),
    ]),
    createRole: vi.fn(),
    updateRole: vi.fn(),
    deleteRole: vi.fn(),
    ...overrides,
  };
}

function renderWorldRoles(api = createWorldsApi(), roleApi = createRolesApi()) {
  return render(
    <MemoryRouter initialEntries={["/worlds/4/roles"]}>
      <Routes>
        <Route
          path="/worlds/:worldId/roles"
          element={<WorldRolesPage api={api} roleApi={roleApi} />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

function deferred<T>() {
  let resolve: ((value: T) => void) | undefined;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return {
    promise,
    resolve(value: T) {
      resolve?.(value);
    },
  };
}

describe("WorldRolesPage", () => {
  it("shows the player first and only effective attributes as text", async () => {
    renderWorldRoles();

    const cards = await screen.findAllByRole("article");
    expect(
      within(cards[0]).getByRole("heading", { name: "天" }),
    ).toBeInTheDocument();
    expect(within(cards[0]).getByText("主角")).toBeInTheDocument();
    expect(screen.getAllByText("等级 11")).toHaveLength(2);
    expect(screen.queryByText("世界变化值")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "等级" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "移除主角 天" }),
    ).not.toBeInTheDocument();
  });

  it("filters roles already in the world before adding an NPC", async () => {
    const user = userEvent.setup();
    const api = createWorldsApi({
      addNpc: vi
        .fn()
        .mockResolvedValue(
          worldRole({ role_id: 15, name: "安可儿", kind: "npc" }),
        ),
    });
    renderWorldRoles(api);

    const picker = await screen.findByLabelText("选择 NPC");
    expect(
      within(picker).queryByRole("option", { name: "天" }),
    ).not.toBeInTheDocument();
    expect(
      within(picker).queryByRole("option", { name: "莫莉莉" }),
    ).not.toBeInTheDocument();
    expect(
      within(picker).getByRole("option", { name: "安可儿" }),
    ).toBeInTheDocument();

    await user.selectOptions(picker, "15");
    await user.click(screen.getByRole("button", { name: "加入 NPC" }));
    expect(api.addNpc).toHaveBeenCalledWith(4, 15);
    expect(
      await screen.findByRole("heading", { name: "安可儿" }),
    ).toBeInTheDocument();
  });

  it("disables NPC selection and add at the 20 NPC limit", async () => {
    const worldRoles = [
      worldRole(),
      ...Array.from({ length: 20 }, (_, index) =>
        worldRole({
          role_id: 100 + index,
          name: `NPC ${index + 1}`,
          kind: "npc",
        }),
      ),
    ];
    const api = createWorldsApi({
      listWorldRoles: vi.fn().mockResolvedValue(worldRoles),
    });
    const roleApi = createRolesApi({
      listRoles: vi
        .fn()
        .mockResolvedValue([libraryRole({ id: 50, name: "候选 NPC" })]),
    });
    renderWorldRoles(api, roleApi);

    const picker = await screen.findByLabelText("选择 NPC");
    const addButton = screen.getByRole("button", { name: "加入 NPC" });
    expect(picker).toBeDisabled();
    expect(addButton).toBeDisabled();
    expect(picker).toHaveAccessibleDescription(
      "当前世界已达到 20 个 NPC 上限，需先移除一个 NPC。",
    );
    expect(addButton).toHaveAccessibleDescription(
      "当前世界已达到 20 个 NPC 上限，需先移除一个 NPC。",
    );
  });

  it("shows safe backend conflict detail with a reload action", async () => {
    const user = userEvent.setup();
    const api = createWorldsApi({
      addNpc: vi
        .fn()
        .mockRejectedValue(new ApiError("世界 NPC 已达到 20 个上限", 409)),
    });
    renderWorldRoles(api);

    const picker = await screen.findByLabelText("选择 NPC");
    await user.selectOptions(picker, "15");
    await user.click(screen.getByRole("button", { name: "加入 NPC" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "世界 NPC 已达到 20 个上限",
    );
    expect(
      screen.getByRole("button", { name: "重新加载世界角色" }),
    ).toBeInTheDocument();
  });

  it("confirms NPC removal and can toggle its enabled state", async () => {
    const user = userEvent.setup();
    const api = createWorldsApi({
      setNpcEnabled: vi.fn().mockResolvedValue(
        worldRole({
          role_id: 12,
          name: "莫莉莉",
          kind: "npc",
          enabled: false,
        }),
      ),
      removeNpc: vi.fn().mockResolvedValue(undefined),
    });
    renderWorldRoles(api);

    await user.click(
      await screen.findByRole("button", { name: "停用 NPC 莫莉莉" }),
    );
    expect(api.setNpcEnabled).toHaveBeenCalledWith(4, 12, false);
    expect(await screen.findByText("已停用")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "移除 NPC 莫莉莉" }));
    expect(
      screen.getByText("移除后，该世界的角色变化和位置规则会一并删除。"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认移除 莫莉莉" }));
    expect(api.removeNpc).toHaveBeenCalledWith(4, 12);
    expect(
      screen.queryByRole("heading", { name: "莫莉莉" }),
    ).not.toBeInTheDocument();
  });

  it("replaces the complete location-rule draft in one request", async () => {
    const user = userEvent.setup();
    const api = createWorldsApi({
      replaceLocationRules: vi.fn().mockResolvedValue([]),
    });
    renderWorldRoles(api);

    await user.click(
      await screen.findByRole("button", { name: "配置位置规则 莫莉莉" }),
    );
    await user.selectOptions(screen.getByLabelText("候选地点 1"), "the_guild");
    await user.clear(screen.getByLabelText("优先级"));
    await user.type(screen.getByLabelText("优先级"), "10");
    await user.click(screen.getByRole("button", { name: "保存全部位置规则" }));

    expect(api.replaceLocationRules).toHaveBeenCalledWith(4, 12, [
      {
        weekday_mask: 1,
        time_slot: "morning",
        mode: "fixed",
        priority: 10,
        enabled: true,
        candidates: [{ location_id: "the_guild", weight: 1 }],
      },
    ]);
    expect(await screen.findByText("位置规则已原子替换。")).toBeInTheDocument();
  });

  it("ignores an old-world mutation response after the route changes", async () => {
    const user = userEvent.setup();
    const addResult = deferred<WorldRoleResponse>();
    const api = createWorldsApi({
      listWorldRoles: vi.fn((requestedWorldId: number) =>
        Promise.resolve(
          requestedWorldId === 4
            ? [worldRole()]
            : [
                worldRole({
                  world_id: 5,
                  role_id: 20,
                  name: "新主角",
                }),
              ],
        ),
      ),
      addNpc: vi.fn(() => addResult.promise),
    });

    render(
      <MemoryRouter initialEntries={["/worlds/4/roles"]}>
        <Link to="/worlds/5/roles">切换世界</Link>
        <Routes>
          <Route
            path="/worlds/:worldId/roles"
            element={<WorldRolesPage api={api} roleApi={createRolesApi()} />}
          />
        </Routes>
      </MemoryRouter>,
    );

    const picker = await screen.findByLabelText("选择 NPC");
    await user.selectOptions(picker, "15");
    await user.click(screen.getByRole("button", { name: "加入 NPC" }));
    await user.click(screen.getByRole("link", { name: "切换世界" }));
    expect(
      await screen.findByRole("heading", { name: "新主角" }),
    ).toBeInTheDocument();

    await act(async () => {
      addResult.resolve(
        worldRole({ role_id: 15, name: "安可儿", kind: "npc" }),
      );
      await addResult.promise;
    });

    expect(
      screen.queryByRole("heading", { name: "安可儿" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "新主角" })).toBeInTheDocument();
  });

  it("keeps an invalid-route error when an old world load resolves", async () => {
    const user = userEvent.setup();
    const oldLoad = deferred<WorldRoleResponse[]>();
    const api = createWorldsApi({
      listWorldRoles: vi.fn(() => oldLoad.promise),
    });

    render(
      <MemoryRouter initialEntries={["/worlds/4/roles"]}>
        <Link to="/worlds/not-a-number/roles">打开无效地址</Link>
        <Routes>
          <Route
            path="/worlds/:worldId/roles"
            element={<WorldRolesPage api={api} roleApi={createRolesApi()} />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("link", { name: "打开无效地址" }));
    expect(
      await screen.findByText("世界地址无效，请返回世界列表重新选择。"),
    ).toBeInTheDocument();

    await act(async () => {
      oldLoad.resolve([worldRole()]);
      await oldLoad.promise;
    });

    expect(
      screen.getByText("世界地址无效，请返回世界列表重新选择。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "天" }),
    ).not.toBeInTheDocument();
  });

  it("offers loading, empty, error retry, and explained disabled states", async () => {
    const user = userEvent.setup();
    const listWorldRoles = vi
      .fn<WorldsApi["listWorldRoles"]>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce([]);
    const api = createWorldsApi({ listWorldRoles });
    const roleApi = createRolesApi({
      listRoles: vi.fn().mockResolvedValue([]),
    });
    renderWorldRoles(api, roleApi);

    expect(screen.getByText("正在加载世界角色…")).toBeInTheDocument();
    expect(await screen.findByText("无法加载世界角色")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(
      await screen.findByText("这个世界还没有可显示的角色"),
    ).toBeInTheDocument();
    const addButton = screen.getByRole("button", { name: "加入 NPC" });
    expect(addButton).toBeDisabled();
    expect(addButton).toHaveAccessibleDescription("角色库中没有可加入的 NPC。");
  });
});
