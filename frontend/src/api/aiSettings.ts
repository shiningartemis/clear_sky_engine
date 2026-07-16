import type { components } from "./generated";
import { ApiError } from "./health";

export type ProviderCreate = components["schemas"]["ProviderCreate"];
export type ProviderUpdate = components["schemas"]["ProviderUpdate"];
export type ProviderResponse = components["schemas"]["ProviderResponse"];
export type ModelCreate = components["schemas"]["ModelCreate"];
export type ModelUpdate = components["schemas"]["ModelUpdate"];
export type ModelResponse = components["schemas"]["ModelResponse"];
export type ConnectionTestResponse =
  components["schemas"]["ConnectionTestResponse"];

export interface AiSettingsApi {
  listProviders(signal?: AbortSignal): Promise<ProviderResponse[]>;
  listModels(signal?: AbortSignal): Promise<ModelResponse[]>;
  createProvider(payload: ProviderCreate): Promise<ProviderResponse>;
  updateProvider(
    id: number,
    payload: ProviderUpdate,
  ): Promise<ProviderResponse>;
  deleteProvider(id: number): Promise<void>;
  createModel(payload: ModelCreate): Promise<ModelResponse>;
  updateModel(id: number, payload: ModelUpdate): Promise<ModelResponse>;
  deleteModel(id: number): Promise<void>;
  testConnection(
    providerId: number,
    modelId: number,
  ): Promise<ConnectionTestResponse>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isProvider(value: unknown): value is ProviderResponse {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    typeof value.name === "string" &&
    (value.provider_type === "deepseek" ||
      value.provider_type === "openai_compatible") &&
    typeof value.base_url === "string" &&
    typeof value.enabled === "boolean" &&
    typeof value.has_api_key === "boolean" &&
    isRecord(value.extra) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

function isModel(value: unknown): value is ModelResponse {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    typeof value.provider_id === "number" &&
    typeof value.display_name === "string" &&
    typeof value.remote_model === "string" &&
    typeof value.enabled === "boolean" &&
    isRecord(value.capabilities) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

function isUsage(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.input_tokens === "number" &&
    typeof value.output_tokens === "number" &&
    typeof value.total_tokens === "number"
  );
}

function isConnectionTest(value: unknown): value is ConnectionTestResponse {
  return (
    isRecord(value) &&
    typeof value.success === "boolean" &&
    (value.provider_type === "deepseek" ||
      value.provider_type === "openai_compatible") &&
    typeof value.remote_model === "string" &&
    isRecord(value.capabilities) &&
    typeof value.diagnostic === "string" &&
    (value.error_category === null ||
      typeof value.error_category === "string") &&
    (value.usage === null || isUsage(value.usage))
  );
}

async function requestJson<T>(
  url: string,
  init: RequestInit,
  validate: (value: unknown) => value is T,
): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new ApiError("AI 配置请求失败。", response.status);
  }
  const payload: unknown = await response.json();
  if (!validate(payload)) {
    throw new ApiError("AI 配置响应格式无效。", response.status);
  }
  return payload;
}

const jsonHeaders = {
  Accept: "application/json",
  "Content-Type": "application/json",
} as const;

export const aiSettingsApi: AiSettingsApi = {
  async listProviders(signal) {
    return requestJson(
      "/api/providers",
      { headers: { Accept: "application/json" }, signal },
      (value): value is ProviderResponse[] =>
        Array.isArray(value) && value.every(isProvider),
    );
  },
  async listModels(signal) {
    return requestJson(
      "/api/models",
      { headers: { Accept: "application/json" }, signal },
      (value): value is ModelResponse[] =>
        Array.isArray(value) && value.every(isModel),
    );
  },
  async createProvider(payload) {
    return requestJson(
      "/api/providers",
      { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) },
      isProvider,
    );
  },
  async updateProvider(id, payload) {
    return requestJson(
      `/api/providers/${id}`,
      { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(payload) },
      isProvider,
    );
  },
  async deleteProvider(id) {
    const response = await fetch(`/api/providers/${id}`, { method: "DELETE" });
    if (!response.ok) {
      throw new ApiError("删除 Provider 失败。", response.status);
    }
  },
  async createModel(payload) {
    return requestJson(
      "/api/models",
      { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) },
      isModel,
    );
  },
  async updateModel(id, payload) {
    return requestJson(
      `/api/models/${id}`,
      { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(payload) },
      isModel,
    );
  },
  async deleteModel(id) {
    const response = await fetch(`/api/models/${id}`, { method: "DELETE" });
    if (!response.ok) {
      throw new ApiError("删除模型失败。", response.status);
    }
  },
  async testConnection(providerId, modelId) {
    return requestJson(
      `/api/providers/${providerId}/test-connection`,
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ model_id: modelId }),
      },
      isConnectionTest,
    );
  },
};
