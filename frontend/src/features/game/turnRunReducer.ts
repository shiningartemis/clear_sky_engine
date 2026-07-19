import type { TurnResponse, TurnRunEvent } from "../../api/turns";

export interface MapNodeProgress {
  node: "location_simulation" | "attribute_memory_analysis" | null;
  attempt: number | null;
  maxAttempts: number;
  retrying: boolean;
  completed: boolean;
}

export interface ActiveTurnRun {
  runId: string;
  playerIntent: string;
}

export interface TurnRunTerminal {
  kind: "run_succeeded" | "run_failed" | "run_cancelled";
  error: string | null;
}

export interface TurnRecovery {
  runId: string;
  turnId: number | null;
  error: string;
}

export interface TurnRunState {
  playerIntent: string;
  activeRun: ActiveTurnRun | null;
  mapProgress: Record<string, MapNodeProgress>;
  completedMaps: number;
  totalMaps: number;
  elapsedMs: number;
  terminal: TurnRunTerminal | null;
  recovery: TurnRecovery | null;
  history: TurnResponse[];
}

export type TurnRunAction =
  | { type: "intent_changed"; playerIntent: string }
  | { type: "run_created"; runId: string; playerIntent: string }
  | { type: "event"; event: TurnRunEvent }
  | { type: "cancel_confirmed"; runId: string }
  | { type: "client_failed"; runId: string | null; error: string }
  | {
      type: "recovery_required";
      runId: string;
      turnId: number | null;
      error: string;
    }
  | { type: "turn_recovered"; runId: string; turn: TurnResponse }
  | { type: "history_loaded"; history: TurnResponse[] };

export const initialTurnRunState: TurnRunState = {
  playerIntent: "",
  activeRun: null,
  mapProgress: {},
  completedMaps: 0,
  totalMaps: 0,
  elapsedMs: 0,
  terminal: null,
  recovery: null,
  history: [],
};

function isTerminal(
  event: TurnRunEvent,
): event is TurnRunEvent & { kind: TurnRunTerminal["kind"] } {
  return (
    event.kind === "run_succeeded" ||
    event.kind === "run_failed" ||
    event.kind === "run_cancelled"
  );
}

function mergeHistory(
  ...sources: ReadonlyArray<ReadonlyArray<TurnResponse>>
): TurnResponse[] {
  const historyById = new Map<number, TurnResponse>();
  for (const source of sources) {
    for (const turn of source) historyById.set(turn.turn_id, turn);
  }
  return [...historyById.values()].sort(
    (left, right) => right.turn_id - left.turn_id,
  );
}

function progressForEvent(
  event: TurnRunEvent,
  current: Readonly<Record<string, MapNodeProgress>>,
): Record<string, MapNodeProgress> {
  if (event.location_id === null) return {};
  const previous = current[event.location_id];
  if (event.kind === "map_completed" && previous !== undefined) {
    return {
      [event.location_id]: {
        ...previous,
        retrying: false,
        completed: true,
      },
    };
  }
  return {
    [event.location_id]: {
      node: event.node,
      attempt: event.attempt,
      maxAttempts: event.max_attempts,
      retrying: event.retrying,
      completed: event.kind === "map_completed",
    },
  };
}

export function turnRunReducer(
  state: TurnRunState,
  action: TurnRunAction,
): TurnRunState {
  if (action.type === "intent_changed") {
    return { ...state, playerIntent: action.playerIntent };
  }
  if (action.type === "history_loaded") {
    return {
      ...state,
      history: mergeHistory(action.history, state.history),
    };
  }
  if (action.type === "run_created") {
    if (state.activeRun !== null) return state;
    return {
      ...state,
      playerIntent: action.playerIntent,
      activeRun: { runId: action.runId, playerIntent: action.playerIntent },
      mapProgress: {},
      completedMaps: 0,
      totalMaps: 0,
      elapsedMs: 0,
      terminal: null,
      recovery: null,
    };
  }
  if (action.type === "recovery_required") {
    if (state.activeRun?.runId !== action.runId) return state;
    return {
      ...state,
      recovery: {
        runId: action.runId,
        turnId: action.turnId,
        error: action.error,
      },
    };
  }
  if (action.type === "turn_recovered") {
    if (state.activeRun?.runId !== action.runId) return state;
    return {
      ...state,
      playerIntent: "",
      activeRun: null,
      recovery: null,
      terminal: { kind: "run_succeeded", error: null },
      history: mergeHistory(state.history, [action.turn]),
    };
  }
  if (action.type === "cancel_confirmed") {
    if (state.activeRun?.runId !== action.runId) return state;
    return {
      ...state,
      playerIntent: state.activeRun.playerIntent,
      activeRun: null,
      recovery: null,
      terminal: { kind: "run_cancelled", error: null },
    };
  }
  if (action.type === "client_failed") {
    if (
      (action.runId === null && state.activeRun !== null) ||
      (action.runId !== null && state.activeRun?.runId !== action.runId)
    ) {
      return state;
    }
    return {
      ...state,
      playerIntent: state.activeRun?.playerIntent ?? state.playerIntent,
      activeRun: null,
      recovery: null,
      terminal: { kind: "run_failed", error: action.error },
    };
  }
  if (
    state.activeRun === null ||
    action.event.run_id !== state.activeRun.runId
  ) {
    return state;
  }

  const originalPlayerIntent = state.activeRun.playerIntent;
  const elapsedMs = Math.max(state.elapsedMs, action.event.elapsed_ms);
  const completedMaps = Math.max(
    state.completedMaps,
    action.event.completed_maps,
  );
  const totalMaps = Math.max(state.totalMaps, action.event.total_maps);
  if (!isTerminal(action.event)) {
    return {
      ...state,
      elapsedMs,
      completedMaps,
      totalMaps,
      mapProgress: {
        ...state.mapProgress,
        ...progressForEvent(action.event, state.mapProgress),
      },
    };
  }

  // 只有服务端成功结算的 turn 才能进入历史，前端不能推断任何世界事实。
  if (action.event.kind === "run_succeeded") {
    if (action.event.turn === null || action.event.turn === undefined) {
      return {
        ...state,
        playerIntent: originalPlayerIntent,
        activeRun: null,
        recovery: null,
        elapsedMs,
        terminal: { kind: "run_failed", error: "轮次结果不完整。" },
      };
    }
    return {
      ...state,
      playerIntent: "",
      activeRun: null,
      recovery: null,
      elapsedMs,
      completedMaps,
      totalMaps,
      terminal: { kind: "run_succeeded", error: null },
      history: mergeHistory(state.history, [action.event.turn]),
    };
  }
  return {
    ...state,
    playerIntent: originalPlayerIntent,
    activeRun: null,
    recovery: null,
    elapsedMs,
    completedMaps,
    totalMaps,
    terminal: { kind: action.event.kind, error: action.event.error ?? null },
  };
}
