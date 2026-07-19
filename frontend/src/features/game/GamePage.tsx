import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import type { TurnRunClient, TurnRunStatus } from "../../api/turns";
import { turnsApi } from "../../api/turns";
import type {
  GameViewResponse,
  SceneId,
  WorldRoleResponse,
  WorldsApi,
} from "../../api/worlds";
import { locationIds, worldsApi } from "../../api/worlds";
import { useTurnRunNavigation } from "../../app/TurnRunContext";
import { createDefaultGameBridge } from "../../game/PhaserGame";
import type { GameBridgePort, GameEvent } from "../../game/types";
import { toGameViewState } from "../../game/types";
import styles from "./GamePage.module.css";
import { PortraitStrip } from "./PortraitStrip";
import { TurnHistory } from "./TurnHistory";
import { TurnProgress } from "./TurnProgress";
import { initialTurnRunState, turnRunReducer } from "./turnRunReducer";

interface GamePageProps {
  api?: WorldsApi;
  turnApi?: TurnRunClient;
  createBridge?: () => GameBridgePort;
}

interface RunLifecycle {
  controller: AbortController;
  recoveryController: AbortController | null;
  recoveryPending: boolean;
  release: () => void;
  runId: string | null;
}

const cancelWatchdogMs = 5_000;

function cancelWithWatchdog(
  turnApi: TurnRunClient,
  runId: string,
): ReturnType<TurnRunClient["cancel"]> {
  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(
      () => reject(new Error("取消请求超时。")),
      cancelWatchdogMs,
    );
    void turnApi.cancel(runId).then(
      (status) => {
        window.clearTimeout(timeoutId);
        resolve(status);
      },
      (error: unknown) => {
        window.clearTimeout(timeoutId);
        reject(error);
      },
    );
  });
}

async function bestEffortCancel(
  turnApi: TurnRunClient,
  runId: string,
): Promise<TurnRunStatus | null> {
  try {
    return await cancelWithWatchdog(turnApi, runId);
  } catch {
    // 流已失效时取消只是服务端清理；失败不能覆盖原始传输错误，watchdog 只负责避免 UI 永久锁死。
    return null;
  }
}

type PageState =
  | { kind: "loading"; message: string }
  | { kind: "invalid" }
  | { kind: "error"; title: string; retrySceneId: SceneId }
  | { kind: "ready"; view: GameViewResponse };

type HistoryState =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "error"; message: string };

const weekdayLabels: Readonly<Record<string, string>> = {
  monday: "星期一",
  tuesday: "星期二",
  wednesday: "星期三",
  thursday: "星期四",
  friday: "星期五",
  saturday: "星期六",
  sunday: "星期日",
};

const timeSlotLabels: Readonly<Record<string, string>> = {
  morning: "晨间",
  midday: "午间",
  evening: "傍晚",
  night: "夜晚",
};

function isLocationSceneId(
  sceneId: string,
): sceneId is (typeof locationIds)[number] {
  return locationIds.some((locationId) => locationId === sceneId);
}

export function GamePage(props: GamePageProps) {
  const { worldId } = useParams();
  // world_id 是页面全部事实与异步生命周期的边界；参数变化必须重建页面状态，不能合并两个世界。
  return <GamePageForWorld key={worldId ?? "invalid-world"} {...props} />;
}

function GamePageForWorld({
  api = worldsApi,
  turnApi = turnsApi,
  createBridge = createDefaultGameBridge,
}: GamePageProps) {
  const navigation = useTurnRunNavigation();
  const { worldId: worldIdParam } = useParams();
  const worldId = Number(worldIdParam);
  const validWorldId = Number.isInteger(worldId) && worldId > 0;
  const [state, setState] = useState<PageState>(
    validWorldId
      ? { kind: "loading", message: "正在加载地图…" }
      : { kind: "invalid" },
  );
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [turnState, dispatchTurn] = useReducer(
    turnRunReducer,
    initialTurnRunState,
  );
  const [historyState, setHistoryState] = useState<HistoryState>({
    kind: "loading",
  });
  const [worldRoles, setWorldRoles] = useState<WorldRoleResponse[]>([]);
  const [submissionPending, setSubmissionPending] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isRecoverySyncing, setIsRecoverySyncing] = useState(false);
  const [scrollToTurnId, setScrollToTurnId] = useState<number | null>(null);
  const [viewRefreshError, setViewRefreshError] = useState<string | null>(null);
  const bridgeRef = useRef<GameBridgePort | null>(null);
  if (bridgeRef.current === null) bridgeRef.current = createBridge();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const activeController = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);
  const locationWritePending = useRef(false);
  const historyController = useRef<AbortController | null>(null);
  const submissionPendingRef = useRef(false);
  const runLifecycleRef = useRef<RunLifecycle | null>(null);

  const loadScene = useCallback(
    (sceneId: SceneId) => {
      if (!validWorldId) {
        setState({ kind: "invalid" });
        return;
      }
      locationWritePending.current = false;
      activeController.current?.abort();
      const controller = new AbortController();
      activeController.current = controller;
      const generation = requestGeneration.current + 1;
      requestGeneration.current = generation;
      setState({ kind: "loading", message: "正在加载地图…" });

      void api.getGameView(worldId, sceneId, controller.signal).then(
        (view) => {
          if (
            requestGeneration.current === generation &&
            activeController.current === controller
          ) {
            setState({ kind: "ready", view });
          }
        },
        () => {
          if (
            requestGeneration.current === generation &&
            activeController.current === controller &&
            !controller.signal.aborted
          ) {
            setState({
              kind: "error",
              title: "无法加载地图",
              retrySceneId: sceneId,
            });
          }
        },
      );
    },
    [api, validWorldId, worldId],
  );

  const selectLocation = useCallback(
    (locationId: Parameters<WorldsApi["selectLocation"]>[1]) => {
      if (!validWorldId || locationWritePending.current) return;
      // POST 不能取消；在权威响应返回前串行化位置写入，避免旧请求晚到覆盖新选择。
      locationWritePending.current = true;
      activeController.current?.abort();
      activeController.current = null;
      const generation = requestGeneration.current + 1;
      requestGeneration.current = generation;
      setState({ kind: "loading", message: "正在移动到所选地点…" });
      void api.selectLocation(worldId, locationId).then(
        (view) => {
          if (requestGeneration.current === generation) {
            locationWritePending.current = false;
            setState({ kind: "ready", view });
          }
        },
        () => {
          if (requestGeneration.current === generation) {
            locationWritePending.current = false;
            setState({
              kind: "error",
              title: "无法移动到地点",
              retrySceneId: "the_world_map",
            });
          }
        },
      );
    },
    [api, validWorldId, worldId],
  );

  const refreshScene = useCallback(
    (sceneId: SceneId) => {
      if (!validWorldId) return;
      activeController.current?.abort();
      const controller = new AbortController();
      activeController.current = controller;
      const generation = requestGeneration.current + 1;
      requestGeneration.current = generation;
      setViewRefreshError(null);
      void api.getGameView(worldId, sceneId, controller.signal).then(
        (view) => {
          if (
            requestGeneration.current === generation &&
            activeController.current === controller
          ) {
            setState({ kind: "ready", view });
          }
        },
        () => {
          if (
            requestGeneration.current === generation &&
            activeController.current === controller &&
            !controller.signal.aborted
          ) {
            setViewRefreshError("轮次已成功，但地图刷新失败，请重试刷新。");
          }
        },
      );
    },
    [api, validWorldId, worldId],
  );

  const loadHistory = useCallback(() => {
    if (!validWorldId) return;
    historyController.current?.abort();
    const controller = new AbortController();
    historyController.current = controller;
    setHistoryState({ kind: "loading" });
    void Promise.all([
      api.listWorldRoles(worldId, controller.signal),
      turnApi.listTurns(worldId, controller.signal),
    ]).then(
      ([roles, history]) => {
        if (historyController.current !== controller) return;
        setWorldRoles(roles);
        dispatchTurn({ type: "history_loaded", history });
        setHistoryState({ kind: "ready" });
      },
      () => {
        if (
          historyController.current === controller &&
          !controller.signal.aborted
        ) {
          setHistoryState({
            kind: "error",
            message: "无法加载历轮故事，请检查本地服务后重试。",
          });
        }
      },
    );
  }, [api, turnApi, validWorldId, worldId]);

  useEffect(() => {
    loadScene("the_world_map");
    loadHistory();
    return () => {
      requestGeneration.current += 1;
      locationWritePending.current = false;
      activeController.current?.abort();
      activeController.current = null;
      historyController.current?.abort();
      historyController.current = null;
    };
  }, [loadHistory, loadScene]);

  useEffect(() => {
    const bridge = bridgeRef.current;
    const container = containerRef.current;
    if (!validWorldId || !bridge || !container) return;
    const unsubscribe = bridge.subscribe((event: GameEvent) => {
      if (locationWritePending.current) return;
      if (event.type === "select_location") {
        selectLocation(event.locationId);
      } else if (event.type === "enter_location") {
        loadScene(event.locationId);
      } else {
        loadScene("the_world_map");
      }
    });
    bridge.mount(container);
    return () => {
      unsubscribe();
      bridge.destroy();
    };
  }, [loadScene, selectLocation, validWorldId]);

  useEffect(() => {
    if (state.kind === "ready") {
      try {
        // Phaser 只接收后端事实的窄化视图，角色可见性仍由 React 使用原响应渲染。
        bridgeRef.current?.update(toGameViewState(state.view));
      } catch {
        setState({
          kind: "error",
          title: "无法加载地图",
          retrySceneId: "the_world_map",
        });
      }
    }
  }, [state]);

  const runLocked = submissionPending || turnState.activeRun !== null;

  useEffect(() => {
    bridgeRef.current?.setInputLocked(runLocked);
  }, [runLocked]);

  useEffect(() => {
    const handleResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const readyView = state.kind === "ready" ? state.view : null;
  const locationSceneId =
    readyView !== null && isLocationSceneId(readyView.scene_id)
      ? readyView.scene_id
      : null;
  const locationView =
    readyView !== null && locationSceneId !== null ? readyView : null;

  const terminalMessage =
    turnState.terminal?.kind === "run_cancelled"
      ? "轮次已取消，可以修改意图后再次提交。"
      : turnState.terminal?.kind === "run_failed"
        ? (turnState.terminal.error ?? "轮次失败，请再次提交。")
        : null;

  const releaseRunLifecycle = useCallback((lifecycle: RunLifecycle) => {
    lifecycle.controller.abort();
    lifecycle.recoveryController?.abort();
    lifecycle.release();
    if (runLifecycleRef.current !== lifecycle) return;
    runLifecycleRef.current = null;
    submissionPendingRef.current = false;
    setSubmissionPending(false);
    setIsCancelling(false);
    setIsRecoverySyncing(false);
  }, []);

  useEffect(
    () => () => {
      const lifecycle = runLifecycleRef.current;
      if (lifecycle !== null) releaseRunLifecycle(lifecycle);
    },
    [releaseRunLifecycle],
  );

  const syncRecoveredTurn = useCallback(
    async (lifecycle: RunLifecycle, turnId: number): Promise<boolean> => {
      const runId = lifecycle.runId;
      if (runId === null) return false;
      const controller = new AbortController();
      lifecycle.recoveryController?.abort();
      lifecycle.recoveryController = controller;
      try {
        const history = await turnApi.listTurns(worldId, controller.signal);
        if (runLifecycleRef.current !== lifecycle) return false;
        const turn = history.find((item) => item.turn_id === turnId);
        if (turn === undefined) return false;
        // 只能用服务端历史中与 turn_id 精确匹配的完整结果恢复，不能依据意图或时间猜测。
        dispatchTurn({
          type: "turn_recovered",
          runId,
          turn,
        });
        setScrollToTurnId(turn.turn_id);
        if (locationSceneId !== null) refreshScene(locationSceneId);
        return true;
      } catch {
        return false;
      } finally {
        if (lifecycle.recoveryController === controller) {
          lifecycle.recoveryController = null;
        }
      }
    },
    [locationSceneId, refreshScene, turnApi, worldId],
  );

  const submitTurn = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const playerIntent = turnState.playerIntent.trim();
      if (
        !validWorldId ||
        locationView === null ||
        locationSceneId === null ||
        playerIntent.length === 0 ||
        submissionPendingRef.current ||
        turnState.activeRun !== null
      ) {
        return;
      }

      submissionPendingRef.current = true;
      setSubmissionPending(true);
      setScrollToTurnId(null);
      dispatchTurn({ type: "intent_changed", playerIntent });
      const controller = new AbortController();
      const release = navigation.acquire(controller);
      const lifecycle: RunLifecycle = {
        controller,
        recoveryController: null,
        recoveryPending: false,
        release,
        runId: null,
      };
      runLifecycleRef.current = lifecycle;
      let terminalReceived = false;
      let preserveLifecycle = false;

      try {
        const created = await turnApi.create(worldId, playerIntent);
        lifecycle.runId = created.run_id;
        if (controller.signal.aborted) {
          await bestEffortCancel(turnApi, created.run_id);
          return;
        }
        dispatchTurn({
          type: "run_created",
          runId: created.run_id,
          playerIntent,
        });
        setSubmissionPending(false);

        await turnApi.stream(created.run_id, controller.signal, (runEvent) => {
          if (
            runLifecycleRef.current !== lifecycle ||
            lifecycle.runId === null ||
            runEvent.run_id !== lifecycle.runId
          ) {
            return;
          }
          dispatchTurn({ type: "event", event: runEvent });
          if (
            runEvent.kind === "run_succeeded" ||
            runEvent.kind === "run_failed" ||
            runEvent.kind === "run_cancelled"
          ) {
            terminalReceived = true;
          }
          if (runEvent.kind === "run_succeeded" && runEvent.turn != null) {
            // 成功后仍以服务端 game view 刷新时间、位置和属性，不能从 turn 在前端推导世界事实。
            setScrollToTurnId(runEvent.turn.turn_id);
            refreshScene(locationSceneId);
          }
        });
        if (!terminalReceived) {
          throw new Error("轮次进度流未提供当前轮次终态。");
        }
      } catch (error) {
        if (
          !controller.signal.aborted &&
          !terminalReceived &&
          runLifecycleRef.current === lifecycle
        ) {
          if (lifecycle.runId !== null) {
            const cleanupStatus = await bestEffortCancel(
              turnApi,
              lifecycle.runId,
            );
            if (
              cleanupStatus !== null &&
              cleanupStatus.run_id !== lifecycle.runId &&
              runLifecycleRef.current === lifecycle
            ) {
              dispatchTurn({
                type: "recovery_required",
                runId: lifecycle.runId,
                turnId: null,
                error: "轮次同步响应与当前轮次不匹配。",
              });
              preserveLifecycle = true;
              return;
            }
            if (
              cleanupStatus?.status === "succeeded" &&
              runLifecycleRef.current === lifecycle
            ) {
              const turnId = cleanupStatus.turn_id ?? null;
              dispatchTurn({
                type: "recovery_required",
                runId: lifecycle.runId,
                turnId,
                error: "结果同步失败，请重试同步结果。",
              });
              const recovered =
                turnId !== null && (await syncRecoveredTurn(lifecycle, turnId));
              if (!recovered) {
                preserveLifecycle = true;
                return;
              }
              return;
            }
          }
          if (runLifecycleRef.current !== lifecycle) return;
          const message =
            error instanceof Error && error.message.trim().length > 0
              ? error.message
              : "轮次请求失败，请再次提交。";
          dispatchTurn({
            type: "client_failed",
            runId: lifecycle.runId,
            error: message,
          });
        }
      } finally {
        if (!preserveLifecycle && !lifecycle.recoveryPending) {
          releaseRunLifecycle(lifecycle);
        }
      }
    },
    [
      locationView,
      locationSceneId,
      navigation,
      refreshScene,
      releaseRunLifecycle,
      syncRecoveredTurn,
      turnApi,
      turnState.activeRun,
      turnState.playerIntent,
      validWorldId,
      worldId,
    ],
  );

  const cancelTurn = useCallback(async () => {
    const runId = turnState.activeRun?.runId;
    const lifecycle = runLifecycleRef.current;
    if (
      runId === undefined ||
      lifecycle === null ||
      lifecycle.runId !== runId ||
      isCancelling
    ) {
      return;
    }
    setIsCancelling(true);
    try {
      const status = await cancelWithWatchdog(turnApi, runId);
      if (runLifecycleRef.current !== lifecycle) return;
      if (status.run_id !== runId) {
        dispatchTurn({
          type: "client_failed",
          runId,
          error: "取消响应与当前轮次不匹配，请再次提交。",
        });
        releaseRunLifecycle(lifecycle);
        return;
      }
      if (status.status === "cancelled") {
        // cancel API 的 cancelled 是权威终态，不再等待可能永不返回的流。
        dispatchTurn({ type: "cancel_confirmed", runId });
        releaseRunLifecycle(lifecycle);
      } else if (status.status === "failed") {
        dispatchTurn({
          type: "client_failed",
          runId,
          error: status.error ?? "轮次失败，请再次提交。",
        });
        releaseRunLifecycle(lifecycle);
      } else if (status.status === "succeeded") {
        const turnId = status.turn_id ?? null;
        lifecycle.recoveryPending = true;
        dispatchTurn({
          type: "recovery_required",
          runId,
          turnId,
          error: "结果同步失败，请重试同步结果。",
        });
        // cancel 已确认服务端成功后，进度流不再是事实来源；立即停止它并按精确 turn_id 同步。
        lifecycle.controller.abort();
        const recovered =
          turnId !== null && (await syncRecoveredTurn(lifecycle, turnId));
        if (runLifecycleRef.current !== lifecycle) return;
        if (recovered) {
          releaseRunLifecycle(lifecycle);
          return;
        }
        dispatchTurn({
          type: "recovery_required",
          runId,
          turnId,
          error: "结果同步失败，请重试同步结果。",
        });
        setIsCancelling(false);
      }
    } catch {
      if (runLifecycleRef.current !== lifecycle) return;
      dispatchTurn({
        type: "client_failed",
        runId,
        error: "取消请求失败，轮次已停止，请再次提交。",
      });
      releaseRunLifecycle(lifecycle);
    }
  }, [
    isCancelling,
    releaseRunLifecycle,
    syncRecoveredTurn,
    turnApi,
    turnState.activeRun?.runId,
  ]);

  const retryTurnRecovery = useCallback(async () => {
    const recovery = turnState.recovery;
    const lifecycle = runLifecycleRef.current;
    if (
      recovery === null ||
      lifecycle === null ||
      lifecycle.runId !== recovery.runId ||
      isRecoverySyncing
    ) {
      return;
    }
    setIsRecoverySyncing(true);
    let turnId = recovery.turnId;
    if (turnId === null) {
      try {
        const status = await cancelWithWatchdog(turnApi, recovery.runId);
        if (runLifecycleRef.current !== lifecycle) return;
        if (status.run_id !== recovery.runId) {
          dispatchTurn({
            type: "recovery_required",
            runId: recovery.runId,
            turnId: null,
            error: "轮次同步响应与当前轮次不匹配。",
          });
          setIsRecoverySyncing(false);
          return;
        }
        turnId =
          status.status === "succeeded" ? (status.turn_id ?? null) : null;
      } catch {
        turnId = null;
      }
    }
    const recovered =
      turnId !== null && (await syncRecoveredTurn(lifecycle, turnId));
    if (runLifecycleRef.current !== lifecycle) return;
    if (recovered) {
      releaseRunLifecycle(lifecycle);
      return;
    }
    dispatchTurn({
      type: "recovery_required",
      runId: recovery.runId,
      turnId,
      error: "结果同步失败，请重试同步结果。",
    });
    setIsRecoverySyncing(false);
  }, [
    isRecoverySyncing,
    releaseRunLifecycle,
    syncRecoveredTurn,
    turnApi,
    turnState.recovery,
  ]);

  return (
    <main className={styles.page}>
      <div
        ref={containerRef}
        className={`${styles.gameCanvas} ${
          state.kind === "loading" ? styles.gameCanvasBusy : ""
        }`}
        role="img"
        aria-label={readyView ? "游戏地图" : "地图画布"}
        aria-busy={state.kind === "loading"}
      />

      {readyView && (
        <p className={styles.timePanel} role="status" aria-label="世界时间">
          {"Day " +
            readyView.day +
            " · " +
            (weekdayLabels[readyView.weekday] ?? readyView.weekday) +
            " · " +
            (timeSlotLabels[readyView.time_slot] ?? readyView.time_slot)}
        </p>
      )}

      {state.kind === "loading" && (
        <p className={styles.statusPanel} aria-live="polite">
          {state.message}
        </p>
      )}
      {state.kind === "invalid" && (
        <section className={styles.statusPanel} role="alert">
          <h1>世界地址无效</h1>
          <p>请返回世界列表重新选择。</p>
        </section>
      )}
      {state.kind === "error" && (
        <section className={styles.statusPanel} role="alert">
          <h1>{state.title}</h1>
          <p>世界位置没有被更改，请检查本地服务后重试。</p>
          <button type="button" onClick={() => loadScene(state.retrySceneId)}>
            重试
          </button>
        </section>
      )}

      {locationView && locationSceneId && (
        <>
          <button
            className={styles.mapButton}
            type="button"
            disabled={runLocked}
            onClick={() => loadScene("the_world_map")}
          >
            地图
          </button>
          <PortraitStrip
            roles={locationView.visible_roles}
            viewportWidth={viewportWidth}
          />
          <aside className={styles.turnWorkspace} aria-label="轮次工作区">
            <form className={styles.intentPanel} onSubmit={submitTurn}>
              <label htmlFor="player-intent">主角准备尝试什么</label>
              <p>描述主角的尝试；故事结果仍由世界推演决定。</p>
              <textarea
                id="player-intent"
                value={turnState.playerIntent}
                disabled={runLocked}
                rows={3}
                onChange={(event) =>
                  dispatchTurn({
                    type: "intent_changed",
                    playerIntent: event.target.value,
                  })
                }
              />
              <button
                type="submit"
                disabled={
                  runLocked || turnState.playerIntent.trim().length === 0
                }
              >
                {terminalMessage === null ? "提交尝试" : "再次提交"}
              </button>
            </form>

            {runLocked &&
              turnState.activeRun !== null &&
              turnState.recovery === null && (
                <TurnProgress
                  locations={locationView.locations.map((location) => ({
                    sceneId: location.scene_id,
                    displayName: location.display_name,
                    order: location.order,
                  }))}
                  mapProgress={turnState.mapProgress}
                  completedMaps={turnState.completedMaps}
                  totalMaps={turnState.totalMaps}
                  elapsedMs={turnState.elapsedMs}
                  isCancelling={isCancelling}
                  cancelError={null}
                  onCancel={cancelTurn}
                />
              )}
            {turnState.recovery !== null && (
              <div className={styles.turnError} role="alert">
                <p>轮次可能已成功，结果同步失败。</p>
                <p>{turnState.recovery.error}</p>
                <p>为避免重复提交，移动和导航会保持锁定。</p>
                <button
                  type="button"
                  disabled={isRecoverySyncing}
                  onClick={retryTurnRecovery}
                >
                  {isRecoverySyncing ? "正在同步结果…" : "重试同步结果"}
                </button>
              </div>
            )}
            {submissionPending && turnState.activeRun === null && (
              <p className={styles.historyStatus} aria-live="polite">
                正在创建轮次…
              </p>
            )}

            {terminalMessage !== null && (
              <p className={styles.turnError} role="alert">
                {terminalMessage}
              </p>
            )}
            {viewRefreshError !== null && (
              <div className={styles.turnError} role="alert">
                <p>{viewRefreshError}</p>
                <button
                  type="button"
                  onClick={() => refreshScene(locationSceneId)}
                >
                  重试刷新地图
                </button>
              </div>
            )}

            <TurnHistory
              status={historyState.kind}
              turns={turnState.history}
              worldRoles={worldRoles}
              error={
                historyState.kind === "error" ? historyState.message : null
              }
              onRetry={loadHistory}
              scrollToTurnId={scrollToTurnId}
            />
          </aside>
        </>
      )}
    </main>
  );
}
