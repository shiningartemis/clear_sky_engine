import type { components } from "./generated";
import { ApiError } from "./health";

export type AttributeDefinition = components["schemas"]["AttributeDefinition"];
export type CharacterAssetResponse =
  components["schemas"]["CharacterAssetResponse"];
export type RoleCreate = components["schemas"]["RoleCreate"];
export type RoleResponse = components["schemas"]["RoleResponse"];
export type RoleUpdate = components["schemas"]["RoleUpdate"];

export interface RolesApi {
  listAssets(signal?: AbortSignal): Promise<CharacterAssetResponse[]>;
  listRoles(signal?: AbortSignal): Promise<RoleResponse[]>;
  createRole(payload: RoleCreate): Promise<RoleResponse>;
  updateRole(id: number, payload: RoleUpdate): Promise<RoleResponse>;
  deleteRole(id: number): Promise<void>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

function isNumberArray(value: unknown): value is number[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "number")
  );
}

function isScalar(value: unknown): value is number | string | boolean {
  return (
    typeof value === "number" ||
    typeof value === "string" ||
    typeof value === "boolean"
  );
}

function isOptionalNumber(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || typeof value === "number";
}

function isOptionalString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === "string";
}

function isAttributeDefinition(value: unknown): value is AttributeDefinition {
  return (
    isRecord(value) &&
    typeof value.key === "string" &&
    typeof value.display_name === "string" &&
    (value.data_type === "integer" ||
      value.data_type === "number" ||
      value.data_type === "string" ||
      value.data_type === "boolean" ||
      value.data_type === "enum") &&
    isScalar(value.base_value) &&
    typeof value.description === "string" &&
    typeof value.update_rule === "string" &&
    Array.isArray(value.allowed_operations) &&
    value.allowed_operations.every(
      (operation) =>
        operation === "replace" ||
        operation === "increment" ||
        operation === "decrement",
    ) &&
    isOptionalNumber(value.minimum) &&
    isOptionalNumber(value.maximum) &&
    isStringArray(value.enum_options) &&
    isOptionalString(value.update_example) &&
    isOptionalString(value.no_update_example)
  );
}

function isCharacterAsset(value: unknown): value is CharacterAssetResponse {
  return (
    isRecord(value) &&
    typeof value.role_name === "string" &&
    typeof value.portrait_url === "string"
  );
}

function isScalarRecord(
  value: unknown,
): value is Record<string, number | string | boolean> {
  return isRecord(value) && Object.values(value).every(isScalar);
}

function isRole(value: unknown): value is RoleResponse {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    typeof value.name === "string" &&
    typeof value.persona === "string" &&
    typeof value.system_prompt === "string" &&
    typeof value.world_book === "string" &&
    Array.isArray(value.attributes) &&
    value.attributes.every(isAttributeDefinition) &&
    isScalarRecord(value.effective_base_values) &&
    typeof value.portrait_url === "string" &&
    isNumberArray(value.referenced_world_ids) &&
    typeof value.version === "number" &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

async function requestJson<T>(
  url: string,
  init: RequestInit,
  validate: (value: unknown) => value is T,
): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new ApiError("角色库请求失败。", response.status);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    // 只转换 JSON 语法错误；请求取消与网络异常必须保留原始语义。
    if (error instanceof SyntaxError) {
      throw new ApiError("角色库响应格式无效。", response.status);
    }
    throw error;
  }
  if (!validate(payload)) {
    throw new ApiError("角色库响应格式无效。", response.status);
  }
  return payload;
}

const jsonHeaders = {
  Accept: "application/json",
  "Content-Type": "application/json",
} as const;

export const rolesApi: RolesApi = {
  async listAssets(signal) {
    const assets = await requestJson(
      "/api/assets/characters",
      { headers: { Accept: "application/json" }, signal },
      (value): value is CharacterAssetResponse[] =>
        Array.isArray(value) && value.every(isCharacterAsset),
    );
    return [...assets].sort((left, right) =>
      left.role_name.localeCompare(right.role_name, "zh-CN"),
    );
  },
  async listRoles(signal) {
    return requestJson(
      "/api/roles",
      { headers: { Accept: "application/json" }, signal },
      (value): value is RoleResponse[] =>
        Array.isArray(value) && value.every(isRole),
    );
  },
  async createRole(payload) {
    return requestJson(
      "/api/roles",
      { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) },
      isRole,
    );
  },
  async updateRole(id, payload) {
    return requestJson(
      `/api/roles/${id}`,
      { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(payload) },
      isRole,
    );
  },
  async deleteRole(id) {
    const response = await fetch(`/api/roles/${id}`, { method: "DELETE" });
    if (!response.ok) {
      throw new ApiError("删除角色失败。", response.status);
    }
  },
};
