import { useCallback, useEffect, useRef, useState } from "react";
import { Route, Routes } from "react-router-dom";

import type { AiSettingsApi } from "../api/aiSettings";
import { fetchHealth, type HealthResponse } from "../api/health";
import type { RolesApi } from "../api/roles";
import type { WorldsApi } from "../api/worlds";
import { AiSettingsPage } from "../features/ai-settings/AiSettingsPage";
import { GamePage } from "../features/game/GamePage";
import { RoleLibraryPage } from "../features/roles/RoleLibraryPage";
import { WorldListPage } from "../features/worlds/WorldListPage";
import { WorldRolesPage } from "../features/worlds/WorldRolesPage";
import styles from "./App.module.css";

type HealthLoader = (signal?: AbortSignal) => Promise<HealthResponse>;

interface AppProps {
  loadHealth?: HealthLoader;
  settingsApi?: AiSettingsApi;
  rolesApi?: RolesApi;
  worldsApi?: WorldsApi;
}

type HealthState = { kind: "loading" } | { kind: "ready" } | { kind: "error" };

function HealthBootstrap({
  loadHealth,
  children,
}: {
  loadHealth: HealthLoader;
  children: React.ReactNode;
}) {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const requestSequence = useRef(0);
  const activeController = useRef<AbortController | null>(null);

  const checkHealth = useCallback(() => {
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    const requestId = requestSequence.current + 1;
    requestSequence.current = requestId;
    setState({ kind: "loading" });

    void loadHealth(controller.signal).then(
      () => {
        if (
          requestSequence.current === requestId &&
          activeController.current === controller
        ) {
          setState({ kind: "ready" });
        }
      },
      () => {
        if (
          requestSequence.current === requestId &&
          activeController.current === controller &&
          !controller.signal.aborted
        ) {
          setState({ kind: "error" });
        }
      },
    );
  }, [loadHealth]);

  useEffect(() => {
    checkHealth();
    return () => {
      // 健康检查只是路由门禁，卸载后不得让旧请求重新打开页面。
      requestSequence.current += 1;
      activeController.current?.abort();
      activeController.current = null;
    };
  }, [checkHealth]);

  if (state.kind === "ready") return children;

  return (
    <main className={styles.shell}>
      <section className={styles.statusPanel} aria-live="polite">
        <p className={styles.eyebrow}>CLEAR SKY ENGINE</p>
        {state.kind === "loading" ? (
          <p>正在连接本地服务…</p>
        ) : (
          <>
            <h1>无法连接本地服务</h1>
            <p>请确认本地后端仍在运行，然后重试。</p>
            <button type="button" onClick={checkHealth}>
              重试
            </button>
          </>
        )}
      </section>
    </main>
  );
}

export function App({
  loadHealth = fetchHealth,
  settingsApi,
  rolesApi,
  worldsApi,
}: AppProps) {
  return (
    <HealthBootstrap loadHealth={loadHealth}>
      <Routes>
        <Route
          path="/"
          element={<WorldListPage api={worldsApi} assetApi={rolesApi} />}
        />
        <Route path="/roles" element={<RoleLibraryPage api={rolesApi} />} />
        <Route
          path="/worlds/:worldId/roles"
          element={<WorldRolesPage api={worldsApi} roleApi={rolesApi} />}
        />
        <Route
          path="/worlds/:worldId/game"
          element={<GamePage api={worldsApi} />}
        />
        <Route
          path="/settings/ai"
          element={<AiSettingsPage api={settingsApi} />}
        />
      </Routes>
    </HealthBootstrap>
  );
}
