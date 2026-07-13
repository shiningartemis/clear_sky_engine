import type { components } from "./generated";
import { ApiError } from "./health";

export type GameViewResponse = components["schemas"]["GameViewResponse"];
export type LocationRuleCreate = components["schemas"]["LocationRuleCreate"];
export type LocationRuleResponse =
  components["schemas"]["LocationRuleResponse"];
type RoleResponse = components["schemas"]["RoleResponse"];
export type WorldCreate = components["schemas"]["WorldCreate"];
export type WorldResponse = components["schemas"]["WorldResponse"];
export type WorldRoleResponse = components["schemas"]["WorldRoleResponse"];

export const locationIds = [
  "the_home",
  "the_dungeon",
  "the_mall",
  "the_guild",
  "the_hotel",
  "the_school",
] as const;
export type LocationId = (typeof locationIds)[number];
export type SceneId = "the_world_map" | LocationId;

export interface WorldsApi {
  listWorlds(signal?: AbortSignal): Promise<WorldResponse[]>;
  createWorld(payload: WorldCreate): Promise<WorldResponse>;
  deleteWorld(worldId: number): Promise<void>;
  listWorldRoles(
    worldId: number,
    signal?: AbortSignal,
  ): Promise<WorldRoleResponse[]>;
  addNpc(worldId: number, roleId: number): Promise<WorldRoleResponse>;
  setNpcEnabled(
    worldId: number,
    roleId: number,
    enabled: boolean,
  ): Promise<WorldRoleResponse>;
  removeNpc(worldId: number, roleId: number): Promise<void>;
  replaceLocationRules(
    worldId: number,
    roleId: number,
    rules: LocationRuleCreate[],
  ): Promise<LocationRuleResponse[]>;
  selectLocation(
    worldId: number,
    locationId: LocationId,
  ): Promise<GameViewResponse>;
  getGameView(
    worldId: number,
    sceneId: SceneId,
    signal?: AbortSignal,
  ): Promise<GameViewResponse>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isInteger(value: unknown): value is number {
  return isNumber(value) && Number.isInteger(value);
}

function isPositiveInteger(value: unknown): value is number {
  return isInteger(value) && value > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0;
}

function isScalar(value: unknown): value is number | string | boolean {
  return (
    isNumber(value) || typeof value === "string" || typeof value === "boolean"
  );
}

function isScalarRecord(
  value: unknown,
): value is Record<string, number | string | boolean> {
  return isRecord(value) && Object.values(value).every(isScalar);
}

function isLocationId(value: unknown): value is LocationId {
  return (
    typeof value === "string" &&
    locationIds.some((locationId) => locationId === value)
  );
}

function isSceneId(value: unknown): value is SceneId {
  return value === "the_world_map" || isLocationId(value);
}

function isTimeSlot(value: unknown): value is LocationRuleCreate["time_slot"] {
  return (
    value === "morning" ||
    value === "midday" ||
    value === "evening" ||
    value === "night"
  );
}

function isWeekday(value: unknown): boolean {
  return (
    value === "monday" ||
    value === "tuesday" ||
    value === "wednesday" ||
    value === "thursday" ||
    value === "friday" ||
    value === "saturday" ||
    value === "sunday"
  );
}

function isAttributeDefinition(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const dataType = value.data_type;
  const operations = value.allowed_operations;
  return (
    typeof value.key === "string" &&
    typeof value.display_name === "string" &&
    (dataType === "integer" ||
      dataType === "number" ||
      dataType === "string" ||
      dataType === "boolean" ||
      dataType === "enum") &&
    isScalar(value.base_value) &&
    typeof value.description === "string" &&
    typeof value.update_rule === "string" &&
    Array.isArray(operations) &&
    operations.every(
      (operation) =>
        operation === "replace" ||
        operation === "increment" ||
        operation === "decrement",
    ) &&
    (value.minimum === null ||
      value.minimum === undefined ||
      isNumber(value.minimum)) &&
    (value.maximum === null ||
      value.maximum === undefined ||
      isNumber(value.maximum)) &&
    Array.isArray(value.enum_options) &&
    value.enum_options.every((option) => typeof option === "string") &&
    (value.update_example === null ||
      value.update_example === undefined ||
      typeof value.update_example === "string") &&
    (value.no_update_example === null ||
      value.no_update_example === undefined ||
      typeof value.no_update_example === "string")
  );
}

function isRoleResponse(value: unknown): value is RoleResponse {
  return (
    isRecord(value) &&
    isPositiveInteger(value.id) &&
    typeof value.name === "string" &&
    typeof value.persona === "string" &&
    typeof value.system_prompt === "string" &&
    typeof value.world_book === "string" &&
    Array.isArray(value.attributes) &&
    value.attributes.every(isAttributeDefinition) &&
    isScalarRecord(value.effective_base_values) &&
    typeof value.portrait_url === "string" &&
    Array.isArray(value.referenced_world_ids) &&
    value.referenced_world_ids.every(isPositiveInteger) &&
    isPositiveInteger(value.version) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

function isWorldResponse(value: unknown): value is WorldResponse {
  return (
    isRecord(value) &&
    isPositiveInteger(value.id) &&
    typeof value.display_name === "string" &&
    value.display_name === `世界 ${value.id}` &&
    isPositiveInteger(value.active_branch_id) &&
    isPositiveInteger(value.day) &&
    isWeekday(value.weekday) &&
    isTimeSlot(value.time_slot) &&
    isRoleResponse(value.player_role) &&
    value.player_role.referenced_world_ids.includes(value.id) &&
    isNonNegativeInteger(value.npc_count) &&
    typeof value.last_played_at === "string"
  );
}

function isWorldRoleResponse(value: unknown): value is WorldRoleResponse {
  return (
    isRecord(value) &&
    isPositiveInteger(value.world_id) &&
    isPositiveInteger(value.role_id) &&
    typeof value.name === "string" &&
    (value.kind === "player" || value.kind === "npc") &&
    typeof value.enabled === "boolean" &&
    isScalarRecord(value.effective_attributes) &&
    typeof value.portrait_url === "string" &&
    isPositiveInteger(value.version) &&
    typeof value.updated_at === "string"
  );
}

function isLocationCandidate(value: unknown): boolean {
  return (
    isRecord(value) &&
    isLocationId(value.location_id) &&
    isPositiveInteger(value.weight)
  );
}

function isLocationRuleResponse(value: unknown): value is LocationRuleResponse {
  return (
    isRecord(value) &&
    isPositiveInteger(value.id) &&
    isPositiveInteger(value.world_id) &&
    isPositiveInteger(value.role_id) &&
    isInteger(value.weekday_mask) &&
    value.weekday_mask >= 1 &&
    value.weekday_mask <= 127 &&
    isTimeSlot(value.time_slot) &&
    (value.mode === "fixed" || value.mode === "random") &&
    isInteger(value.priority) &&
    typeof value.enabled === "boolean" &&
    Array.isArray(value.candidates) &&
    value.candidates.length > 0 &&
    (value.mode === "random" || value.candidates.length === 1) &&
    value.candidates.every(isLocationCandidate)
  );
}

function isMapLocation(value: unknown): boolean {
  return (
    isRecord(value) &&
    isLocationId(value.scene_id) &&
    typeof value.display_name === "string" &&
    isNonNegativeInteger(value.order) &&
    isNumber(value.anchor_x) &&
    value.anchor_x >= 0 &&
    value.anchor_x <= 1 &&
    isNumber(value.anchor_y) &&
    value.anchor_y >= 0 &&
    value.anchor_y <= 1
  );
}

function isGameViewResponse(value: unknown): value is GameViewResponse {
  return (
    isRecord(value) &&
    isPositiveInteger(value.world_id) &&
    isSceneId(value.scene_id) &&
    typeof value.background_url === "string" &&
    typeof value.fallback_background_url === "string" &&
    typeof value.player_marker_url === "string" &&
    isLocationId(value.player_location_id) &&
    Array.isArray(value.locations) &&
    value.locations.every(isMapLocation) &&
    Array.isArray(value.visible_roles) &&
    value.visible_roles.every(isWorldRoleResponse)
  );
}

function isWorldRoleFor(
  value: unknown,
  worldId: number,
  roleId?: number,
  kind?: WorldRoleResponse["kind"],
  enabled?: boolean,
): value is WorldRoleResponse {
  return (
    isWorldRoleResponse(value) &&
    value.world_id === worldId &&
    (roleId === undefined || value.role_id === roleId) &&
    (kind === undefined || value.kind === kind) &&
    (enabled === undefined || value.enabled === enabled)
  );
}

function isWorldRoleListFor(
  value: unknown,
  worldId: number,
): value is WorldRoleResponse[] {
  if (
    !Array.isArray(value) ||
    !value.every((role) => isWorldRoleFor(role, worldId))
  ) {
    return false;
  }
  const roleIds = new Set(value.map((role) => role.role_id));
  return (
    roleIds.size === value.length &&
    value.filter((role) => role.kind === "player").length === 1
  );
}

function isRuleListFor(
  value: unknown,
  worldId: number,
  roleId: number,
  expectedLength: number,
): value is LocationRuleResponse[] {
  if (
    !Array.isArray(value) ||
    value.length !== expectedLength ||
    !value.every(
      (rule) =>
        isLocationRuleResponse(rule) &&
        rule.world_id === worldId &&
        rule.role_id === roleId,
    )
  ) {
    return false;
  }
  return new Set(value.map((rule) => rule.id)).size === value.length;
}

function isGameViewFor(
  value: unknown,
  worldId: number,
  expectedSceneId?: SceneId,
  expectedPlayerLocationId?: LocationId,
): value is GameViewResponse {
  if (
    !isGameViewResponse(value) ||
    value.world_id !== worldId ||
    (expectedSceneId !== undefined && value.scene_id !== expectedSceneId) ||
    (expectedPlayerLocationId !== undefined &&
      value.player_location_id !== expectedPlayerLocationId) ||
    !value.visible_roles.every((role) => role.world_id === worldId)
  ) {
    return false;
  }
  const visibleRoleIds = new Set(
    value.visible_roles.map((role) => role.role_id),
  );
  const locationSceneIds = new Set(
    value.locations.map((location) => location.scene_id),
  );
  return (
    visibleRoleIds.size === value.visible_roles.length &&
    locationSceneIds.size === value.locations.length
  );
}

async function requestJson<T>(
  url: string,
  init: RequestInit,
  validate: (value: unknown) => value is T,
): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw await responseError(response);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    // 仅转换响应 JSON 语法错误；取消和网络错误保留原始语义。
    if (error instanceof SyntaxError) {
      throw new ApiError("世界响应格式无效。", response.status);
    }
    throw error;
  }
  if (!validate(payload)) {
    throw new ApiError("世界响应格式无效。", response.status);
  }
  return payload;
}

async function requestEmpty(url: string, init: RequestInit): Promise<void> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw await responseError(response);
  }
}

function safeErrorDetail(value: unknown): string | null {
  if (!isRecord(value)) return null;
  const detail = value.detail;
  const message =
    typeof detail === "string"
      ? detail
      : isRecord(detail) && typeof detail.message === "string"
        ? detail.message
        : null;
  if (!message) return null;
  const normalized = message.trim().replace(/[\r\n\t]+/gu, " ");
  return normalized.length > 0 ? normalized.slice(0, 500) : null;
}

async function responseError(response: Response): Promise<ApiError> {
  let detail: string | null = null;
  try {
    const payload: unknown = await response.json();
    detail = safeErrorDetail(payload);
  } catch {
    // 错误体不可解析时只保留稳定的通用消息和 HTTP 状态。
  }
  return new ApiError(detail ?? "世界请求失败。", response.status);
}

const jsonHeaders = {
  Accept: "application/json",
  "Content-Type": "application/json",
} as const;

export const worldsApi: WorldsApi = {
  async listWorlds(signal) {
    return requestJson(
      "/api/worlds",
      { headers: { Accept: "application/json" }, signal },
      (value): value is WorldResponse[] => {
        if (!Array.isArray(value) || !value.every(isWorldResponse))
          return false;
        return new Set(value.map((world) => world.id)).size === value.length;
      },
    );
  },
  async createWorld(payload) {
    return requestJson(
      "/api/worlds",
      { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) },
      (value): value is WorldResponse =>
        isWorldResponse(value) &&
        value.day === 1 &&
        value.weekday === "monday" &&
        value.time_slot === "morning",
    );
  },
  async deleteWorld(worldId) {
    return requestEmpty(`/api/worlds/${worldId}`, { method: "DELETE" });
  },
  async listWorldRoles(worldId, signal) {
    return requestJson(
      `/api/worlds/${worldId}/roles`,
      { headers: { Accept: "application/json" }, signal },
      (value): value is WorldRoleResponse[] =>
        isWorldRoleListFor(value, worldId),
    );
  },
  async addNpc(worldId, roleId) {
    return requestJson(
      `/api/worlds/${worldId}/roles`,
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ role_id: roleId }),
      },
      (value): value is WorldRoleResponse =>
        isWorldRoleFor(value, worldId, roleId, "npc", true),
    );
  },
  async setNpcEnabled(worldId, roleId, enabled) {
    return requestJson(
      `/api/worlds/${worldId}/roles/${roleId}`,
      {
        method: "PATCH",
        headers: jsonHeaders,
        body: JSON.stringify({ enabled }),
      },
      (value): value is WorldRoleResponse =>
        isWorldRoleFor(value, worldId, roleId, "npc", enabled),
    );
  },
  async removeNpc(worldId, roleId) {
    return requestEmpty(`/api/worlds/${worldId}/roles/${roleId}`, {
      method: "DELETE",
    });
  },
  async replaceLocationRules(worldId, roleId, rules) {
    return requestJson(
      `/api/worlds/${worldId}/roles/${roleId}/location-rules`,
      { method: "PUT", headers: jsonHeaders, body: JSON.stringify(rules) },
      (value): value is LocationRuleResponse[] =>
        isRuleListFor(value, worldId, roleId, rules.length),
    );
  },
  async selectLocation(worldId, locationId) {
    return requestJson(
      `/api/worlds/${worldId}/location`,
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ location_id: locationId }),
      },
      (value): value is GameViewResponse =>
        isGameViewFor(value, worldId, "the_world_map", locationId),
    );
  },
  async getGameView(worldId, sceneId, signal) {
    return requestJson(
      `/api/worlds/${worldId}/game-view?scene_id=${encodeURIComponent(sceneId)}`,
      { headers: { Accept: "application/json" }, signal },
      (value): value is GameViewResponse =>
        isGameViewFor(value, worldId, sceneId),
    );
  },
};
