import { describe, expect, it } from "vitest";

import type { TurnResponse, TurnRunEvent } from "../../api/turns";
import { initialTurnRunState, turnRunReducer } from "./turnRunReducer";

const startedEvent = {
  run_id: "run-1",
  kind: "node_started",
  location_id: "the_home",
  node: "location_simulation",
  attempt: 1,
  max_attempts: 3,
  retrying: false,
  completed_maps: 0,
  total_maps: 1,
  elapsed_ms: 4,
} as const;

const successfulTurn: TurnResponse = {
  turn_id: 2,
  day: 1,
  time_slot: "midday",
  player_intent: "调查",
  roles: [],
  events: [],
  state_changes: [],
};

const successEvent: TurnRunEvent = {
  run_id: "run-1",
  kind: "run_succeeded",
  location_id: null,
  node: null,
  attempt: null,
  max_attempts: 3,
  retrying: false,
  completed_maps: 1,
  total_maps: 1,
  elapsed_ms: 9,
  turn: successfulTurn,
};

describe("turnRunReducer", () => {
  it("维护唯一活动 run 的节点进度、重试和 elapsed", () => {
    const started = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "调查",
    });
    const progressed = turnRunReducer(started, {
      type: "event",
      event: startedEvent,
    });
    const retried = turnRunReducer(progressed, {
      type: "event",
      event: {
        ...startedEvent,
        kind: "node_retrying",
        attempt: 2,
        retrying: true,
        elapsed_ms: 6,
      },
    });

    expect(retried.activeRun).toEqual({ runId: "run-1", playerIntent: "调查" });
    expect(retried.elapsedMs).toBe(6);
    expect(retried.completedMaps).toBe(0);
    expect(retried.totalMaps).toBe(1);
    expect(retried.mapProgress).toEqual({
      the_home: {
        node: "location_simulation",
        attempt: 2,
        maxAttempts: 3,
        retrying: true,
        completed: false,
      },
    });
  });

  it("传输失败时解除活动锁、保留冻结意图并给出可重试错误", () => {
    const active = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "调查缺席的安可儿",
    });
    const result = turnRunReducer(active, {
      type: "client_failed",
      runId: "run-1",
      error: "进度连接中断，请再次提交。",
    });

    expect(result.activeRun).toBeNull();
    expect(result.playerIntent).toBe("调查缺席的安可儿");
    expect(result.terminal).toEqual({
      kind: "run_failed",
      error: "进度连接中断，请再次提交。",
    });
    expect(result.history).toEqual([]);
  });

  it("地图完成事件保留最后节点与尝试信息", () => {
    const active = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "调查",
    });
    const progressed = turnRunReducer(active, {
      type: "event",
      event: { ...startedEvent, attempt: 3 },
    });
    const completed = turnRunReducer(progressed, {
      type: "event",
      event: {
        ...startedEvent,
        kind: "map_completed",
        node: null,
        attempt: null,
        completed_maps: 1,
      },
    });

    expect(completed.mapProgress.the_home).toEqual({
      node: "location_simulation",
      attempt: 3,
      maxAttempts: 3,
      retrying: false,
      completed: true,
    });
  });

  it("迟到的初始历史不会覆盖刚成功插入的服务端 turn", () => {
    const active = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "调查",
    });
    const completed = turnRunReducer(active, {
      type: "event",
      event: successEvent,
    });
    const lateHistory = turnRunReducer(completed, {
      type: "history_loaded",
      history: [
        {
          turn_id: 1,
          day: 1,
          time_slot: "morning",
          player_intent: "旧轮次",
          roles: [],
          events: [],
          state_changes: [],
        },
      ],
    });

    expect(lateHistory.history.map((turn) => turn.turn_id)).toEqual([2, 1]);
  });

  it("取消响应只终结匹配 run，并忽略迟到或过期响应", () => {
    const active = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-2",
      playerIntent: "冻结意图",
    });
    const stale = turnRunReducer(active, {
      type: "cancel_confirmed",
      runId: "run-old",
    });
    const cancelled = turnRunReducer(stale, {
      type: "cancel_confirmed",
      runId: "run-2",
    });
    const lateEvent = turnRunReducer(cancelled, {
      type: "event",
      event: { ...successEvent, run_id: "run-2" },
    });

    expect(stale).toBe(active);
    expect(cancelled.activeRun).toBeNull();
    expect(cancelled.playerIntent).toBe("冻结意图");
    expect(cancelled.terminal).toEqual({
      kind: "run_cancelled",
      error: null,
    });
    expect(lateEvent).toEqual(cancelled);
  });

  it("历史已含成功 turn 时按 turn_id 去重并保持倒序", () => {
    const existingTurn = successfulTurn;
    const withHistory = turnRunReducer(initialTurnRunState, {
      type: "history_loaded",
      history: [
        existingTurn,
        {
          ...existingTurn,
          turn_id: 1,
          player_intent: "旧轮次",
        },
      ],
    });
    const active = turnRunReducer(withHistory, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "调查",
    });
    const completed = turnRunReducer(active, {
      type: "event",
      event: successEvent,
    });

    expect(completed.history.map((turn) => turn.turn_id)).toEqual([2, 1]);
  });

  it("结果恢复只接受匹配 run，并在恢复后忽略迟到旧事件", () => {
    const active = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "可能已提交",
    });
    const waiting = turnRunReducer(active, {
      type: "recovery_required",
      runId: "run-1",
      turnId: 2,
      error: "结果同步失败。",
    });
    const staleRecovery = turnRunReducer(waiting, {
      type: "turn_recovered",
      runId: "run-old",
      turn: successfulTurn,
    });
    const recovered = turnRunReducer(staleRecovery, {
      type: "turn_recovered",
      runId: "run-1",
      turn: successfulTurn,
    });
    const lateEvent = turnRunReducer(recovered, {
      type: "event",
      event: { ...startedEvent, run_id: "run-1" },
    });

    expect(waiting.activeRun).toEqual({
      runId: "run-1",
      playerIntent: "可能已提交",
    });
    expect(waiting.recovery).toEqual({
      runId: "run-1",
      turnId: 2,
      error: "结果同步失败。",
    });
    expect(staleRecovery).toBe(waiting);
    expect(recovered.activeRun).toBeNull();
    expect(recovered.playerIntent).toBe("");
    expect(recovered.history.map((turn) => turn.turn_id)).toEqual([2]);
    expect(lateEvent).toEqual(recovered);
  });

  it("成功时只采用服务端 turn 更新历史并清空活动锁", () => {
    const active = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "调查",
    });
    const completed = turnRunReducer(active, {
      type: "event",
      event: successEvent,
    });

    expect(completed.activeRun).toBeNull();
    expect(completed.history).toEqual([successEvent.turn]);
    expect(completed.playerIntent).toBe("");
  });

  it.each([
    "run_failed",
    "run_cancelled",
  ] as const)("%s 清除活动锁但保留原始意图", (kind) => {
    const active = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "调查",
    });
    const edited = turnRunReducer(active, {
      type: "intent_changed",
      playerIntent: "活动中编辑",
    });
    const result = turnRunReducer(edited, {
      type: "event",
      event: {
        ...startedEvent,
        kind,
        location_id: null,
        node: null,
        attempt: null,
        error: kind === "run_failed" ? "安全错误" : undefined,
      },
    });

    expect(result.activeRun).toBeNull();
    expect(result.playerIntent).toBe("调查");
    expect(result.terminal).toEqual({
      kind,
      error: kind === "run_failed" ? "安全错误" : null,
    });
    expect(result.history).toEqual([]);
  });

  it("成功事件缺少 turn 时恢复原始意图并解锁", () => {
    const active = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "调查",
    });
    const edited = turnRunReducer(active, {
      type: "intent_changed",
      playerIntent: "活动中编辑",
    });
    const result = turnRunReducer(edited, {
      type: "event",
      event: { ...successEvent, turn: null },
    });

    expect(result.activeRun).toBeNull();
    expect(result.playerIntent).toBe("调查");
    expect(result.terminal).toEqual({
      kind: "run_failed",
      error: "轮次结果不完整。",
    });
  });

  it("忽略过期 run 和重复终态，避免二次结算", () => {
    const active = turnRunReducer(initialTurnRunState, {
      type: "run_created",
      runId: "run-1",
      playerIntent: "调查",
    });
    const completed = turnRunReducer(active, {
      type: "event",
      event: successEvent,
    });
    const duplicate = turnRunReducer(completed, {
      type: "event",
      event: successEvent,
    });
    const stale = turnRunReducer(completed, {
      type: "event",
      event: { ...startedEvent, run_id: "run-old" },
    });

    expect(duplicate).toEqual(completed);
    expect(stale).toEqual(completed);
  });
});
