import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type {
  CharacterAssetResponse,
  RoleResponse,
  RolesApi,
} from "../../api/roles";
import { RoleLibraryPage } from "./RoleLibraryPage";

const assets: CharacterAssetResponse[] = [
  { role_name: "安可儿", portrait_url: "/portraits/anker" },
  { role_name: "莫莉莉", portrait_url: "/portraits/molly" },
];

const savedRole: RoleResponse = {
  id: 3,
  name: "莫莉莉",
  persona: "开朗的学生",
  system_prompt: "保持角色自主性",
  world_book: "天空城居民",
  attributes: [
    {
      key: "level",
      display_name: "等级",
      data_type: "integer",
      base_value: 5,
      description: "当前等级",
      update_rule: "仅在明确升级时更新",
      allowed_operations: ["replace", "increment"],
      minimum: 1,
      maximum: 100,
      enum_options: [],
      update_example: "完成冒险后增加一级",
      no_update_example: "普通交谈不改变等级",
    },
  ],
  effective_base_values: { level: 5 },
  portrait_url: "/portraits/molly",
  referenced_world_ids: [],
  version: 1,
  created_at: "2026-07-13T00:00:00Z",
  updated_at: "2026-07-13T00:00:00Z",
};

function createRolesApiStub(overrides: Partial<RolesApi> = {}): RolesApi {
  return {
    listAssets: vi.fn().mockResolvedValue(assets),
    listRoles: vi.fn().mockResolvedValue([]),
    createRole: vi.fn().mockResolvedValue(savedRole),
    updateRole: vi.fn().mockResolvedValue(savedRole),
    deleteRole: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function renderPage(api: RolesApi) {
  return render(
    <MemoryRouter>
      <RoleLibraryPage api={api} />
    </MemoryRouter>,
  );
}

async function openCreateForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "创建角色" }));
}

describe("RoleLibraryPage", () => {
  it("shows loading and then an actionable empty state", async () => {
    renderPage(createRolesApiStub());

    expect(screen.getByText("正在加载角色库…")).toBeInTheDocument();
    expect(await screen.findByText("角色库还是空的")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建角色" })).toBeEnabled();
  });

  it("shows an error and retries both resource lists", async () => {
    const user = userEvent.setup();
    const listAssets = vi
      .fn<RolesApi["listAssets"]>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(assets);
    const listRoles = vi.fn<RolesApi["listRoles"]>().mockResolvedValue([]);
    renderPage(createRolesApiStub({ listAssets, listRoles }));

    expect(await screen.findByText("无法加载角色库")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("角色库还是空的")).toBeInTheDocument();
    expect(listAssets).toHaveBeenCalledTimes(2);
    expect(listRoles).toHaveBeenCalledTimes(2);
  });

  it("edits base attributes without exposing world changes", async () => {
    const user = userEvent.setup();
    renderPage(createRolesApiStub());

    await openCreateForm(user);
    await user.selectOptions(screen.getByLabelText("角色素材"), "莫莉莉");
    await user.type(screen.getByLabelText("基础人设"), "开朗的学生");
    await user.click(screen.getByRole("button", { name: "添加属性" }));
    await user.type(screen.getByLabelText("属性 key"), "level");
    await user.type(screen.getByLabelText("显示名称"), "等级");

    expect(screen.queryByLabelText("世界变化值")).not.toBeInTheDocument();
  });

  it("fixes the role name to the selected asset and keeps saved names immutable", async () => {
    const user = userEvent.setup();
    renderPage(
      createRolesApiStub({ listRoles: vi.fn().mockResolvedValue([savedRole]) }),
    );

    await user.click(
      await screen.findByRole("button", { name: "编辑角色 莫莉莉" }),
    );

    expect(screen.getByLabelText("角色名称")).toHaveValue("莫莉莉");
    expect(screen.getByLabelText("角色名称")).toBeDisabled();
    expect(screen.queryByLabelText("角色素材")).not.toBeInTheDocument();
  });

  it("locks keys for persisted attributes while new rows remain editable", async () => {
    const user = userEvent.setup();
    renderPage(
      createRolesApiStub({ listRoles: vi.fn().mockResolvedValue([savedRole]) }),
    );

    await user.click(
      await screen.findByRole("button", { name: "编辑角色 莫莉莉" }),
    );
    expect(screen.getByLabelText("属性 key")).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "添加属性" }));
    const keyInputs = screen.getAllByLabelText("属性 key");
    expect(keyInputs).toHaveLength(2);
    expect(keyInputs[1]).toBeEnabled();
  });

  it("lists world references and disables referenced deletion", async () => {
    renderPage(
      createRolesApiStub({
        listRoles: vi
          .fn()
          .mockResolvedValue([{ ...savedRole, referenced_world_ids: [7, 9] }]),
      }),
    );

    const card = await screen.findByRole("article", { name: "角色 莫莉莉" });
    expect(within(card).getByText("引用世界：7、9")).toBeInTheDocument();
    expect(
      within(card).getByRole("button", { name: "删除角色 莫莉莉" }),
    ).toBeDisabled();
  });

  it("requires explicit confirmation before deleting an unreferenced role", async () => {
    const user = userEvent.setup();
    const deleteRole = vi
      .fn<RolesApi["deleteRole"]>()
      .mockResolvedValue(undefined);
    renderPage(
      createRolesApiStub({
        listRoles: vi.fn().mockResolvedValue([savedRole]),
        deleteRole,
      }),
    );

    await user.click(
      await screen.findByRole("button", { name: "删除角色 莫莉莉" }),
    );
    expect(deleteRole).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "确认删除 莫莉莉" }));

    expect(deleteRole).toHaveBeenCalledWith(3);
    expect(await screen.findByText("角色库还是空的")).toBeInTheDocument();
  });

  it("rejects duplicate attribute keys before saving", async () => {
    const user = userEvent.setup();
    const createRole = vi
      .fn<RolesApi["createRole"]>()
      .mockResolvedValue(savedRole);
    renderPage(createRolesApiStub({ createRole }));
    await openCreateForm(user);
    await user.selectOptions(screen.getByLabelText("角色素材"), "莫莉莉");
    await user.type(screen.getByLabelText("基础人设"), "开朗的学生");

    await user.click(screen.getByRole("button", { name: "添加属性" }));
    await user.click(screen.getByRole("button", { name: "添加属性" }));
    const keys = screen.getAllByLabelText("属性 key");
    await user.type(keys[0], "level");
    await user.type(keys[1], "level");
    await user.click(screen.getByRole("button", { name: "保存角色" }));

    expect(screen.getByText("属性 key 不能重复")).toBeInTheDocument();
    expect(createRole).not.toHaveBeenCalled();
  });

  it("exposes numeric constraints and numeric operations", async () => {
    const user = userEvent.setup();
    renderPage(createRolesApiStub());
    await openCreateForm(user);
    await user.click(screen.getByRole("button", { name: "添加属性" }));
    await user.selectOptions(screen.getByLabelText("属性类型"), "integer");

    expect(screen.getByLabelText("最小值")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("最大值")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("允许增加")).toBeEnabled();
    expect(screen.getByLabelText("允许减少")).toBeEnabled();
  });

  it("rejects blank and out-of-range numeric base values before saving", async () => {
    const user = userEvent.setup();
    const createRole = vi
      .fn<RolesApi["createRole"]>()
      .mockResolvedValue(savedRole);
    renderPage(createRolesApiStub({ createRole }));
    await openCreateForm(user);
    await user.selectOptions(screen.getByLabelText("角色素材"), "莫莉莉");
    await user.type(screen.getByLabelText("基础人设"), "开朗的学生");
    await user.click(screen.getByRole("button", { name: "添加属性" }));
    await user.type(screen.getByLabelText("属性 key"), "level");
    await user.type(screen.getByLabelText("显示名称"), "等级");
    await user.selectOptions(screen.getByLabelText("属性类型"), "integer");
    await user.type(screen.getByLabelText("属性说明"), "当前等级");
    await user.type(screen.getByLabelText("更新规则"), "升级时更新");
    await user.click(screen.getByRole("button", { name: "保存角色" }));

    expect(screen.getByText("请填写有效的数值基础值")).toBeInTheDocument();
    expect(createRole).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("基础值"), "5");
    await user.type(screen.getByLabelText("最小值"), "10");
    await user.click(screen.getByRole("button", { name: "保存角色" }));
    expect(screen.getByText("基础值不能小于最小值")).toBeInTheDocument();
    expect(createRole).not.toHaveBeenCalled();
  });

  it("exposes enum options and limits enum updates to replacement", async () => {
    const user = userEvent.setup();
    renderPage(createRolesApiStub());
    await openCreateForm(user);
    await user.click(screen.getByRole("button", { name: "添加属性" }));
    await user.selectOptions(screen.getByLabelText("属性类型"), "enum");

    expect(screen.getByLabelText("枚举选项（每行一个）")).toBeInTheDocument();
    expect(screen.getByLabelText("允许替换")).toBeEnabled();
    expect(screen.getByLabelText("允许增加")).toBeDisabled();
    expect(screen.getByLabelText("允许减少")).toBeDisabled();
  });

  it("rejects duplicate enum options before saving", async () => {
    const user = userEvent.setup();
    const createRole = vi
      .fn<RolesApi["createRole"]>()
      .mockResolvedValue(savedRole);
    renderPage(createRolesApiStub({ createRole }));
    await openCreateForm(user);
    await user.selectOptions(screen.getByLabelText("角色素材"), "莫莉莉");
    await user.type(screen.getByLabelText("基础人设"), "开朗的学生");
    await user.click(screen.getByRole("button", { name: "添加属性" }));
    await user.type(screen.getByLabelText("属性 key"), "mood");
    await user.type(screen.getByLabelText("显示名称"), "心情");
    await user.selectOptions(screen.getByLabelText("属性类型"), "enum");
    await user.type(screen.getByLabelText("基础值"), "开心");
    await user.type(screen.getByLabelText("属性说明"), "当前心情");
    await user.type(screen.getByLabelText("更新规则"), "事件影响心情时更新");
    await user.type(
      screen.getByLabelText("枚举选项（每行一个）"),
      "开心\n开心",
    );
    await user.click(screen.getByRole("button", { name: "保存角色" }));

    expect(screen.getByText("枚举选项不能重复")).toBeInTheDocument();
    expect(createRole).not.toHaveBeenCalled();
  });

  it("locks other mutations while deletion is pending", async () => {
    const user = userEvent.setup();
    let finishDelete: () => void = () => undefined;
    const pendingDelete = new Promise<void>((resolve) => {
      finishDelete = resolve;
    });
    renderPage(
      createRolesApiStub({
        listRoles: vi.fn().mockResolvedValue([savedRole]),
        deleteRole: vi.fn().mockReturnValue(pendingDelete),
      }),
    );

    await user.click(await screen.findByRole("button", { name: "创建角色" }));
    await user.click(screen.getByRole("button", { name: "删除角色 莫莉莉" }));
    await user.click(screen.getByRole("button", { name: "确认删除 莫莉莉" }));

    expect(screen.getByRole("button", { name: "创建角色" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存角色" })).toBeDisabled();
    expect(screen.getByLabelText("角色素材")).toBeDisabled();

    finishDelete();
    expect(await screen.findByText("角色库还是空的")).toBeInTheDocument();
  });

  it("keeps keyboard focus visible through labeled controls", async () => {
    const user = userEvent.setup();
    renderPage(createRolesApiStub());
    await screen.findByText("角色库还是空的");

    await user.tab();
    expect(screen.getByRole("link", { name: "返回世界" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: "AI 设置" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "创建角色" })).toHaveFocus();
  });
});
