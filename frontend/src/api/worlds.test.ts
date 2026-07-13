import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./health";
import {
  type GameViewResponse,
  type LocationRuleCreate,
  type WorldResponse,
  type WorldRoleResponse,
  worldsApi,
} from "./worlds";

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

function roleResponse() {
  return {
    id: 9,
    name: "天",
    persona: "谨慎的冒险者",
    system_prompt: "",
    world_book: "",
    attributes: [],
    effective_base_values: {},
    portrait_url: "/api/assets/characters/tian/default",
    referenced_world_ids: [4],
    version: 1,
    created_at: "2026-07-14T00:00:00Z",
    updated_at: "2026-07-14T00:00:00Z",
  };
}

function worldResponse(overrides: Partial<WorldResponse> = {}): WorldResponse {
  return {
    id: 4,
    display_name: "世界 4",
    active_branch_id: 5,
    day: 1,
    weekday: "monday",
    time_slot: "morning",
    player_role: roleResponse(),
    npc_count: 0,
    last_played_at: "2026-07-14T00:00:00Z",
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
    portrait_url: "/api/assets/characters/tian/default",
    version: 1,
    updated_at: "2026-07-14T00:00:00Z",
    ...overrides,
  };
}

function gameView(): GameViewResponse {
  return {
    world_id: 4,
    scene_id: "the_world_map",
    background_url: "/maps/world.jpg",
    fallback_background_url: "/maps/fallback.jpg",
    player_marker_url: "/characters/tian.jpg",
    player_location_id: "the_home",
    locations: [
      {
        scene_id: "the_home",
        display_name: "家",
        order: 1,
        anchor_x: 0.2,
        anchor_y: 0.4,
      },
    ],
    visible_roles: [worldRole()],
  };
}

const locationRules: LocationRuleCreate[] = [
  {
    weekday_mask: 31,
    time_slot: "morning",
    mode: "fixed",
    priority: 10,
    enabled: true,
    candidates: [{ location_id: "the_guild", weight: 1 }],
  },
];

describe("worldsApi", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists and deletes worlds with exact endpoints", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([worldResponse()]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(worldsApi.listWorlds()).resolves.toHaveLength(1);
    await worldsApi.deleteWorld(4);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/worlds", {
      headers: { Accept: "application/json" },
      signal: undefined,
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/worlds/4", {
      method: "DELETE",
    });
  });

  it("creates a Monday Day 1 world through the protagonist endpoint", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(worldResponse(), 201));
    vi.stubGlobal("fetch", fetchMock);

    await worldsApi.createWorld({
      protagonist_name: "天",
      protagonist_persona: "谨慎的冒险者",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/worlds", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        protagonist_name: "天",
        protagonist_persona: "谨慎的冒险者",
      }),
    });
  });

  it("lists, adds, toggles, and removes world NPCs", async () => {
    const npc = worldRole({ role_id: 12, name: "莫莉莉", kind: "npc" });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([worldRole(), npc]))
      .mockResolvedValueOnce(jsonResponse(npc, 201))
      .mockResolvedValueOnce(jsonResponse({ ...npc, enabled: false }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await worldsApi.listWorldRoles(4);
    await worldsApi.addNpc(4, 12);
    await worldsApi.setNpcEnabled(4, 12, false);
    await worldsApi.removeNpc(4, 12);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/worlds/4/roles", {
      headers: { Accept: "application/json" },
      signal: undefined,
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/worlds/4/roles", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ role_id: 12 }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/worlds/4/roles/12", {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify({ enabled: false }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(4, "/api/worlds/4/roles/12", {
      method: "DELETE",
    });
  });

  it("atomically replaces a role's complete location-rule set", async () => {
    const responseRules = [
      {
        id: 7,
        world_id: 4,
        role_id: 12,
        ...locationRules[0],
      },
    ];
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(responseRules));
    vi.stubGlobal("fetch", fetchMock);

    await worldsApi.replaceLocationRules(4, 12, locationRules);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/worlds/4/roles/12/location-rules",
      {
        method: "PUT",
        headers: jsonHeaders,
        body: JSON.stringify(locationRules),
      },
    );
  });

  it("selects a location and parses the returned game view", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(gameView()));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      worldsApi.selectLocation(4, "the_home"),
    ).resolves.toMatchObject({ player_location_id: "the_home" });

    expect(fetchMock).toHaveBeenCalledWith("/api/worlds/4/location", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ location_id: "the_home" }),
    });
  });

  it("gets a validated game view for the encoded scene", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(gameView()));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await worldsApi.getGameView(4, "the_world_map", controller.signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/worlds/4/game-view?scene_id=the_world_map",
      {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      },
    );
  });

  it("rejects malformed world, role, rule, and game-view payloads", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(jsonResponse([{ id: 4 }]))
        .mockResolvedValueOnce(jsonResponse([{ world_id: 4 }]))
        .mockResolvedValueOnce(jsonResponse([{ id: 7 }]))
        .mockResolvedValueOnce(jsonResponse({ world_id: 4 })),
    );

    await expect(worldsApi.listWorlds()).rejects.toBeInstanceOf(ApiError);
    await expect(worldsApi.listWorldRoles(4)).rejects.toBeInstanceOf(ApiError);
    await expect(
      worldsApi.replaceLocationRules(4, 12, locationRules),
    ).rejects.toBeInstanceOf(ApiError);
    await expect(
      worldsApi.getGameView(4, "the_world_map"),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects world payloads outside stable numeric domains", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(jsonResponse([worldResponse({ day: 0 })])),
    );

    await expect(worldsApi.listWorlds()).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects a world whose nested player references another world", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse([
          {
            ...worldResponse(),
            player_role: {
              ...roleResponse(),
              referenced_world_ids: [99],
            },
          },
        ]),
      ),
    );

    await expect(worldsApi.listWorlds()).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects arrays where scalar records are required", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(
          jsonResponse([
            {
              ...worldResponse(),
              player_role: { ...roleResponse(), effective_base_values: [] },
            },
          ]),
        )
        .mockResolvedValueOnce(
          jsonResponse([{ ...worldRole(), effective_attributes: [] }]),
        ),
    );

    await expect(worldsApi.listWorlds()).rejects.toBeInstanceOf(ApiError);
    await expect(worldsApi.listWorldRoles(4)).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects shape-valid responses belonging to another request context", async () => {
    const wrongRule = {
      id: 7,
      world_id: 99,
      role_id: 12,
      ...locationRules[0],
      candidates: [],
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(jsonResponse([worldRole({ world_id: 99 })]))
        .mockResolvedValueOnce(
          jsonResponse(
            worldRole({ role_id: 12, name: "莫莉莉", kind: "player" }),
          ),
        )
        .mockResolvedValueOnce(jsonResponse([wrongRule]))
        .mockResolvedValueOnce(jsonResponse({ ...gameView(), world_id: 99 })),
    );

    await expect(worldsApi.listWorldRoles(4)).rejects.toBeInstanceOf(ApiError);
    await expect(worldsApi.addNpc(4, 12)).rejects.toBeInstanceOf(ApiError);
    await expect(
      worldsApi.replaceLocationRules(4, 12, locationRules),
    ).rejects.toBeInstanceOf(ApiError);
    await expect(
      worldsApi.getGameView(4, "the_world_map"),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects context-valid responses that violate location semantics", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({
          ...gameView(),
          scene_id: "the_guild",
          player_location_id: "the_home",
        }),
      ),
    );

    await expect(
      worldsApi.selectLocation(4, "the_home"),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects fixed location rules with multiple candidates", async () => {
    const fixedWithTwoCandidates = {
      id: 7,
      world_id: 4,
      role_id: 12,
      ...locationRules[0],
      candidates: [
        { location_id: "the_home", weight: 1 },
        { location_id: "the_guild", weight: 1 },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(jsonResponse([fixedWithTwoCandidates])),
    );

    await expect(
      worldsApi.replaceLocationRules(4, 12, locationRules),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("preserves failure status and propagates abort rejection", async () => {
    const abortError = new DOMException("aborted", "AbortError");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ detail: "conflict" }, 409))
      .mockRejectedValueOnce(abortError);
    vi.stubGlobal("fetch", fetchMock);

    await expect(worldsApi.deleteWorld(4)).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
    });
    await expect(worldsApi.listWorlds()).rejects.toBe(abortError);
  });

  it("safely preserves backend conflict detail with its status", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          jsonResponse({ detail: "世界 NPC 已达到 20 个上限" }, 409),
        ),
    );

    await expect(worldsApi.addNpc(4, 12)).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      message: "世界 NPC 已达到 20 个上限",
    });
  });
});
