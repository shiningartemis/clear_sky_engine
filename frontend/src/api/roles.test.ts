import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./health";
import { type RoleCreate, type RoleResponse, rolesApi } from "./roles";

const jsonHeaders = {
  Accept: "application/json",
  "Content-Type": "application/json",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function roleCreatePayload(name = "莫莉莉"): RoleCreate {
  return {
    name,
    persona: "开朗的学生",
    system_prompt: "保持角色自主性",
    world_book: "天空城居民",
    attributes: [
      {
        key: "level",
        display_name: "等级",
        data_type: "integer",
        base_value: 1,
        description: "当前等级",
        update_rule: "仅在明确升级时更新",
        allowed_operations: ["replace", "increment", "decrement"],
        minimum: 1,
        maximum: 100,
        enum_options: [],
        update_example: "完成冒险后增加一级",
        no_update_example: "普通交谈不改变等级",
      },
    ],
  };
}

function roleResponse(overrides: Partial<RoleResponse> = {}): RoleResponse {
  const create = roleCreatePayload();
  return {
    id: 3,
    name: create.name,
    persona: create.persona,
    system_prompt: create.system_prompt,
    world_book: create.world_book,
    attributes: create.attributes ?? [],
    effective_base_values: { level: 1 },
    portrait_url: "/api/assets/characters/%E8%8E%AB%E8%8E%89%E8%8E%89/default",
    referenced_world_ids: [],
    version: 1,
    created_at: "2026-07-13T00:00:00Z",
    updated_at: "2026-07-13T00:00:00Z",
    ...overrides,
  };
}

describe("rolesApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a role with structured attributes", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(roleResponse(), 201));
    vi.stubGlobal("fetch", fetchMock);

    await rolesApi.createRole(roleCreatePayload());

    expect(fetchMock).toHaveBeenCalledWith("/api/roles", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(roleCreatePayload()),
    });
  });

  it("rejects a malformed role response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(jsonResponse([{ id: 3 }])),
    );

    await expect(rolesApi.listRoles()).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
    });
  });

  it("turns invalid JSON into ApiError with the response status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response('{"id":', {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(rolesApi.listRoles()).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
    });
  });

  it("sorts validated character assets by role name", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse([
          { role_name: "天", portrait_url: "/portrait/tian" },
          { role_name: "安可儿", portrait_url: "/portrait/anker" },
        ]),
      ),
    );

    await expect(rolesApi.listAssets()).resolves.toEqual([
      { role_name: "安可儿", portrait_url: "/portrait/anker" },
      { role_name: "天", portrait_url: "/portrait/tian" },
    ]);
  });

  it("passes the abort signal to list requests", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await rolesApi.listRoles(controller.signal);

    expect(fetchMock).toHaveBeenCalledWith("/api/roles", {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
  });

  it("propagates abort rejection without wrapping it", async () => {
    const abortError = new DOMException("aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockRejectedValue(abortError));

    await expect(rolesApi.listAssets()).rejects.toBe(abortError);
  });

  it("propagates network rejection without wrapping it", async () => {
    const networkError = new TypeError("network offline");
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockRejectedValue(networkError),
    );

    await expect(rolesApi.listRoles()).rejects.toBe(networkError);
  });

  it("preserves non-success status in ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(jsonResponse({ detail: "invalid" }, 422)),
    );

    const error = await rolesApi
      .createRole(roleCreatePayload())
      .catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422 });
  });

  it("propagates delete conflicts with their status", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          jsonResponse(
            { detail: { message: "角色仍被引用", world_ids: [7] } },
            409,
          ),
        ),
    );

    await expect(rolesApi.deleteRole(3)).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
    });
  });
});
