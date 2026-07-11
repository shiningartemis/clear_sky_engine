import type { components } from "./generated";

export type HealthResponse = components["schemas"]["HealthResponse"];

export class ApiError extends Error {
  override readonly name = "ApiError";

  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isHealthResponse(value: unknown): value is HealthResponse {
  return (
    isRecord(value) &&
    value.status === "ok" &&
    typeof value.app_version === "string" &&
    value.database === "ok" &&
    typeof value.sqlite_version === "string"
  );
}

export async function fetchHealth(
  signal?: AbortSignal,
): Promise<HealthResponse> {
  const response = await fetch("/api/health", {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new ApiError("后端健康检查失败。", response.status);
  }

  const payload: unknown = await response.json();
  if (!isHealthResponse(payload)) {
    throw new ApiError("后端健康检查响应格式无效。", response.status);
  }
  return payload;
}
