import type { components } from "./generated";
import { ApiError } from "./health";

export type TurnResponse = components["schemas"]["TurnResponse"];
export type TurnRunCreated = components["schemas"]["TurnRunCreated"];
export type TurnRunEvent = components["schemas"]["TurnRunEventResponse"];
export type TurnRunStatus = components["schemas"]["TurnRunStatusResponse"];

export interface TurnRunClient {
  create(worldId: number, playerIntent: string): Promise<TurnRunCreated>;
  stream(
    runId: string,
    signal: AbortSignal,
    onEvent: (event: TurnRunEvent) => void,
  ): Promise<void>;
  cancel(runId: string): Promise<TurnRunStatus>;
  listTurns(worldId: number, signal?: AbortSignal): Promise<TurnResponse[]>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isPositiveInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value) && value > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value) && value >= 0;
}

function isEventKind(
  value: unknown,
): value is components["schemas"]["TurnEventKind"] {
  return (
    value === "node_started" ||
    value === "node_retrying" ||
    value === "node_succeeded" ||
    value === "map_completed" ||
    value === "node_failed" ||
    value === "run_succeeded" ||
    value === "run_failed" ||
    value === "run_cancelled"
  );
}

function isNodeKey(value: unknown): boolean {
  return (
    value === "location_simulation" || value === "attribute_memory_analysis"
  );
}

function isRunStatus(
  value: unknown,
): value is components["schemas"]["RunStatus"] {
  return (
    value === "pending" ||
    value === "running" ||
    value === "succeeded" ||
    value === "failed" ||
    value === "cancelled"
  );
}

function isTurnResponse(value: unknown): value is TurnResponse {
  if (!isRecord(value)) return false;
  const roles = value.roles;
  const events = value.events;
  const stateChanges = value.state_changes;
  return (
    isPositiveInteger(value.turn_id) &&
    isPositiveInteger(value.day) &&
    typeof value.time_slot === "string" &&
    typeof value.player_intent === "string" &&
    Array.isArray(roles) &&
    roles.every(
      (role) =>
        isRecord(role) &&
        isPositiveInteger(role.role_id) &&
        typeof role.content === "string" &&
        typeof role.offline === "boolean",
    ) &&
    Array.isArray(events) &&
    events.every(
      (event) =>
        isRecord(event) &&
        isPositiveInteger(event.event_id) &&
        typeof event.location_id === "string" &&
        typeof event.event_type === "string" &&
        isRecord(event.fact),
    ) &&
    Array.isArray(stateChanges) &&
    stateChanges.every(
      (change) =>
        isRecord(change) &&
        isPositiveInteger(change.role_id) &&
        typeof change.attribute_key === "string" &&
        typeof change.operation === "string" &&
        "old_value" in change &&
        "operand" in change &&
        "new_value" in change &&
        typeof change.reason === "string",
    )
  );
}

function isTurnRunCreated(value: unknown): value is TurnRunCreated {
  return (
    isRecord(value) &&
    typeof value.run_id === "string" &&
    value.run_id.length > 0 &&
    value.status === "pending"
  );
}

function isTurnRunStatus(value: unknown): value is TurnRunStatus {
  if (
    !isRecord(value) ||
    typeof value.run_id !== "string" ||
    !isRunStatus(value.status)
  ) {
    return false;
  }
  return (
    (value.turn_id === undefined ||
      value.turn_id === null ||
      isPositiveInteger(value.turn_id)) &&
    (value.error === undefined ||
      value.error === null ||
      typeof value.error === "string")
  );
}

function isTurnRunEvent(value: unknown): value is TurnRunEvent {
  if (
    !isRecord(value) ||
    typeof value.run_id !== "string" ||
    value.run_id.length === 0 ||
    !isEventKind(value.kind) ||
    (value.location_id !== null && typeof value.location_id !== "string") ||
    (value.node !== null && !isNodeKey(value.node)) ||
    (value.attempt !== null && !isPositiveInteger(value.attempt)) ||
    !isPositiveInteger(value.max_attempts) ||
    typeof value.retrying !== "boolean" ||
    !isNonNegativeInteger(value.completed_maps) ||
    !isNonNegativeInteger(value.total_maps) ||
    !isNonNegativeInteger(value.elapsed_ms) ||
    (value.error !== undefined &&
      value.error !== null &&
      typeof value.error !== "string") ||
    (value.turn !== undefined &&
      value.turn !== null &&
      !isTurnResponse(value.turn))
  ) {
    return false;
  }
  if (value.kind === "run_succeeded") return isTurnResponse(value.turn);
  if (value.kind === "run_failed") return typeof value.error === "string";
  return value.turn === undefined || value.turn === null;
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let message: string | null = null;
  try {
    const payload: unknown = await response.json();
    if (isRecord(payload) && typeof payload.detail === "string") {
      const normalized = payload.detail.trim().replace(/[\r\n\t]+/gu, " ");
      message = normalized.length > 0 ? normalized.slice(0, 500) : null;
    }
  } catch {
    // 错误响应体不可解析时保留稳定的通用消息，不将传输异常伪装成业务数据。
  }
  return new ApiError(message ?? "轮次请求失败。", response.status);
}

async function requestJson<T>(
  url: string,
  init: RequestInit,
  validate: (value: unknown) => value is T,
): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw await errorFromResponse(response);
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new ApiError("轮次响应格式无效。", response.status);
    }
    throw error;
  }
  if (!validate(payload))
    throw new ApiError("轮次响应格式无效。", response.status);
  return payload;
}

function consumeLine(
  line: string,
  onEvent: (event: TurnRunEvent) => void,
): boolean {
  const trimmed = line.trim();
  if (trimmed.length === 0) return false;
  let payload: unknown;
  try {
    payload = JSON.parse(trimmed);
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new ApiError("轮次进度流格式无效。", 200);
    }
    throw error;
  }
  if (!isTurnRunEvent(payload)) {
    throw new ApiError("轮次进度流格式无效。", 200);
  }
  onEvent(payload);
  return (
    payload.kind === "run_succeeded" ||
    payload.kind === "run_failed" ||
    payload.kind === "run_cancelled"
  );
}

async function streamTurnRun(
  runId: string,
  signal: AbortSignal,
  onEvent: (event: TurnRunEvent) => void,
): Promise<void> {
  const response = await fetch(
    `/api/turn-runs/${encodeURIComponent(runId)}/stream`,
    {
      headers: { Accept: "application/x-ndjson" },
      signal,
    },
  );
  if (!response.ok) throw await errorFromResponse(response);
  if (response.body === null) {
    throw new ApiError("轮次进度流格式无效。", response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let terminalSeen = false;
  try {
    while (!terminalSeen) {
      const result = await reader.read();
      if (result.done) break;
      pending += decoder.decode(result.value, { stream: true });
      let boundary = pending.indexOf("\n");
      while (boundary >= 0) {
        const line = pending.slice(0, boundary);
        pending = pending.slice(boundary + 1);
        terminalSeen = consumeLine(line, onEvent);
        if (terminalSeen) break;
        boundary = pending.indexOf("\n");
      }
    }
    if (!terminalSeen) {
      pending += decoder.decode();
      if (pending.length > 0) terminalSeen = consumeLine(pending, onEvent);
    }
    if (!terminalSeen) {
      // 未收到终态时连接结束不能视为成功，否则 UI 会永久保留幽灵活动轮次。
      throw new ApiError("轮次进度流意外断开。", response.status);
    }
  } finally {
    // 终态后不再读取后续字节，避免重复终态被再次交给 UI；主动释放读取锁。
    reader.releaseLock();
  }
}

const jsonHeaders = {
  Accept: "application/json",
  "Content-Type": "application/json",
} as const;

export const turnsApi: TurnRunClient = {
  create(worldId, playerIntent) {
    return requestJson(
      `/api/worlds/${worldId}/turn-runs`,
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ player_intent: playerIntent }),
      },
      isTurnRunCreated,
    );
  },
  stream: streamTurnRun,
  cancel(runId) {
    return requestJson(
      `/api/turn-runs/${encodeURIComponent(runId)}/cancel`,
      { method: "POST", headers: { Accept: "application/json" } },
      isTurnRunStatus,
    );
  },
  listTurns(worldId, signal) {
    return requestJson(
      `/api/worlds/${worldId}/turns`,
      { headers: { Accept: "application/json" }, signal },
      (value): value is TurnResponse[] =>
        Array.isArray(value) && value.every(isTurnResponse),
    );
  },
};
