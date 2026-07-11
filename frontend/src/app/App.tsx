import { useCallback, useEffect, useRef, useState } from "react";

import { fetchHealth, type HealthResponse } from "../api/health";
import type { GameBridgePort } from "../game/GameBridge";
import styles from "./App.module.css";

type HealthLoader = (signal?: AbortSignal) => Promise<HealthResponse>;

interface AppProps {
  loadHealth?: HealthLoader;
  createGameBridge?: () => GameBridgePort;
}

type HealthState =
  | { kind: "loading" }
  | { kind: "ready"; health: HealthResponse }
  | { kind: "error" };

function GameCanvas({ createBridge }: { createBridge?: () => GameBridgePort }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return undefined;
    }

    if (createBridge) {
      const bridge = createBridge();
      bridge.mount(container);
      return () => bridge.destroy();
    }

    let active = true;
    let bridge: GameBridgePort | undefined;
    void import("../game/PhaserGame").then(({ createDefaultGameBridge }) => {
      bridge = createDefaultGameBridge();
      if (active) {
        bridge.mount(container);
      } else {
        bridge.destroy();
      }
    });
    return () => {
      active = false;
      bridge?.destroy();
    };
  }, [createBridge]);

  return (
    <div
      ref={containerRef}
      className={styles.gameCanvas}
      role="application"
      aria-label="游戏地图画布"
    />
  );
}

export function App({ loadHealth = fetchHealth, createGameBridge }: AppProps) {
  const [healthState, setHealthState] = useState<HealthState>({
    kind: "loading",
  });
  const requestSequence = useRef(0);
  const activeController = useRef<AbortController>(undefined);

  const checkHealth = useCallback(() => {
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    const requestId = requestSequence.current + 1;
    requestSequence.current = requestId;
    setHealthState({ kind: "loading" });

    void loadHealth(controller.signal).then(
      (health) => {
        if (requestSequence.current === requestId) {
          setHealthState({ kind: "ready", health });
        }
      },
      () => {
        if (requestSequence.current === requestId) {
          setHealthState({ kind: "error" });
        }
      },
    );
  }, [loadHealth]);

  useEffect(() => {
    checkHealth();
    return () => {
      requestSequence.current += 1;
      activeController.current?.abort();
    };
  }, [checkHealth]);

  return (
    <main className={styles.shell}>
      <GameCanvas createBridge={createGameBridge} />
      <section className={styles.statusPanel} aria-live="polite">
        <p className={styles.eyebrow}>CLEAR SKY ENGINE</p>
        {healthState.kind === "loading" && <p>正在连接本地服务…</p>}
        {healthState.kind === "error" && (
          <>
            <h1>无法连接本地服务</h1>
            <p>请确认本地后端仍在运行，然后重试。</p>
            <button type="button" onClick={checkHealth}>
              重试
            </button>
          </>
        )}
        {healthState.kind === "ready" && (
          <>
            <h1>本地服务已连接</h1>
            <p>Clear Sky Engine {healthState.health.app_version}</p>
            <p>SQLite {healthState.health.sqlite_version}</p>
          </>
        )}
      </section>
    </main>
  );
}
