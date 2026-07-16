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
export type TaskKey = components["schemas"]["TaskKey"];
export type TaskSettingResponse = components["schemas"]["TaskSettingResponse"];
export type TaskSettingUpdate = components["schemas"]["TaskSettingUpdate"];

export interface JsonObjectParseResult {
  value: Record<string, unknown> | null;
  error: { message: string; line: number; column: number } | null;
}

export interface AiSettingsApi {
  listProviders(signal?: AbortSignal): Promise<ProviderResponse[]>;
  listModels(signal?: AbortSignal): Promise<ModelResponse[]>;
  listTaskSettings(signal?: AbortSignal): Promise<TaskSettingResponse[]>;
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
  updateTaskSetting(
    taskKey: TaskKey,
    payload: TaskSettingUpdate,
  ): Promise<TaskSettingResponse>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown): boolean {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return true;
  }
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function isTaskSetting(value: unknown): value is TaskSettingResponse {
  return (
    isRecord(value) &&
    (value.task_key === "location_simulation" ||
      value.task_key === "attribute_memory_analysis") &&
    (value.model_id === null || typeof value.model_id === "number") &&
    (value.temperature === null || typeof value.temperature === "number") &&
    (value.max_output_tokens === null ||
      typeof value.max_output_tokens === "number") &&
    (value.reasoning_effort === null ||
      value.reasoning_effort === "high" ||
      value.reasoning_effort === "max") &&
    typeof value.timeout_seconds === "number" &&
    typeof value.extra_prompt === "string" &&
    (value.structured_output_mode === "auto" ||
      value.structured_output_mode === "native" ||
      value.structured_output_mode === "prompt") &&
    isRecord(value.provider_options) &&
    Object.values(value.provider_options).every(isJsonValue) &&
    (value.memory_target_chars === null ||
      typeof value.memory_target_chars === "number") &&
    (value.memory_max_chars === null ||
      typeof value.memory_max_chars === "number") &&
    typeof value.version === "number" &&
    typeof value.updated_at === "string"
  );
}

function sourcePosition(source: string, offset: number) {
  const safeOffset = Math.max(0, Math.min(offset, source.length));
  const lines = source.slice(0, safeOffset).split("\n");
  return { line: lines.length, column: (lines.at(-1)?.length ?? 0) + 1 };
}

function syntaxPosition(source: string, message: string) {
  const lineAndColumn = message.match(/line\s+(\d+)\s+column\s+(\d+)/i);
  if (lineAndColumn) {
    return {
      line: Number(lineAndColumn[1]),
      column: Number(lineAndColumn[2]),
    };
  }
  const offset = message.match(/position\s+(\d+)/i);
  return sourcePosition(source, offset ? Number(offset[1]) : 0);
}

export function parseJsonObjectEditor(source: string): JsonObjectParseResult {
  try {
    // JSON.parse 的返回类型在标准库中是 any，先收窄到 unknown 再逐层检查根节点。
    const parsed: unknown = JSON.parse(source);
    if (!isRecord(parsed)) {
      return {
        value: null,
        error: {
          message: "根节点必须是 JSON 对象。",
          line: 1,
          column: 1,
        },
      };
    }
    return { value: parsed, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "未知语法错误";
    return {
      value: null,
      error: {
        message: `JSON 语法错误：${message}`,
        ...syntaxPosition(source, message),
      },
    };
  }
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
  async listTaskSettings(signal) {
    return requestJson(
      "/api/ai-task-settings",
      { headers: { Accept: "application/json" }, signal },
      (value): value is TaskSettingResponse[] =>
        Array.isArray(value) && value.every(isTaskSetting),
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
  async updateTaskSetting(taskKey, payload) {
    return requestJson(
      `/api/ai-task-settings/${taskKey}`,
      { method: "PUT", headers: jsonHeaders, body: JSON.stringify(payload) },
      isTaskSetting,
    );
  },
};
