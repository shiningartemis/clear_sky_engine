import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import type { GameViewResponse, SceneId, WorldsApi } from "../../api/worlds";
import { worldsApi } from "../../api/worlds";
import { createDefaultGameBridge } from "../../game/PhaserGame";
import type { GameBridgePort, GameEvent } from "../../game/types";
import { toGameViewState } from "../../game/types";
import styles from "./GamePage.module.css";
import { PortraitStrip } from "./PortraitStrip";

interface GamePageProps {
  api?: WorldsApi;
  createBridge?: () => GameBridgePort;
}

type PageState =
  | { kind: "loading" }
  | { kind: "invalid" }
  | { kind: "error"; retrySceneId: SceneId }
  | { kind: "ready"; view: GameViewResponse };

export function GamePage({
  api = worldsApi,
  createBridge = createDefaultGameBridge,
}: GamePageProps) {
  const { worldId: worldIdParam } = useParams();
  const worldId = Number(worldIdParam);
  const validWorldId = Number.isInteger(worldId) && worldId > 0;
  const [state, setState] = useState<PageState>(
    validWorldId ? { kind: "loading" } : { kind: "invalid" },
  );
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const bridgeRef = useRef<GameBridgePort | null>(null);
  if (bridgeRef.current === null) bridgeRef.current = createBridge();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const activeController = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);

  const loadScene = useCallback(
    (sceneId: SceneId) => {
      if (!validWorldId) {
        setState({ kind: "invalid" });
        return;
      }
      activeController.current?.abort();
      const controller = new AbortController();
      activeController.current = controller;
      const generation = requestGeneration.current + 1;
      requestGeneration.current = generation;
      setState({ kind: "loading" });

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
            setState({ kind: "error", retrySceneId: sceneId });
          }
        },
      );
    },
    [api, validWorldId, worldId],
  );

  const selectLocation = useCallback(
    (locationId: Parameters<WorldsApi["selectLocation"]>[1]) => {
      if (!validWorldId) return;
      activeController.current?.abort();
      activeController.current = null;
      const generation = requestGeneration.current + 1;
      requestGeneration.current = generation;
      setState({ kind: "loading" });
      void api.selectLocation(worldId, locationId).then(
        (view) => {
          if (requestGeneration.current === generation) {
            setState({ kind: "ready", view });
          }
        },
        () => {
          if (requestGeneration.current === generation) {
            setState({ kind: "error", retrySceneId: "the_world_map" });
          }
        },
      );
    },
    [api, validWorldId, worldId],
  );

  useEffect(() => {
    loadScene("the_world_map");
    return () => {
      requestGeneration.current += 1;
      activeController.current?.abort();
      activeController.current = null;
    };
  }, [loadScene]);

  useEffect(() => {
    const bridge = bridgeRef.current;
    const container = containerRef.current;
    if (!validWorldId || !bridge || !container) return;
    const unsubscribe = bridge.subscribe((event: GameEvent) => {
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
        setState({ kind: "error", retrySceneId: "the_world_map" });
      }
    }
  }, [state]);

  useEffect(() => {
    const handleResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const readyView = state.kind === "ready" ? state.view : null;
  const locationView =
    readyView !== null && readyView.scene_id !== "the_world_map"
      ? readyView
      : null;

  return (
    <main className={styles.page}>
      <div
        ref={containerRef}
        className={styles.gameCanvas}
        role="img"
        aria-label={readyView ? "游戏地图" : "地图画布"}
      />

      {state.kind === "loading" && (
        <p className={styles.statusPanel} aria-live="polite">
          正在加载地图…
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
          <h1>无法加载地图</h1>
          <p>世界位置没有被更改，请检查本地服务后重试。</p>
          <button type="button" onClick={() => loadScene(state.retrySceneId)}>
            重试
          </button>
        </section>
      )}

      {locationView && (
        <>
          <button
            className={styles.mapButton}
            type="button"
            onClick={() => loadScene("the_world_map")}
          >
            地图
          </button>
          <PortraitStrip
            roles={locationView.visible_roles}
            viewportWidth={viewportWidth}
          />
        </>
      )}
    </main>
  );
}
