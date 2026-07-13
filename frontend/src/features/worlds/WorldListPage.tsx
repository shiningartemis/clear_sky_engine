import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  type CharacterAssetResponse,
  type RolesApi,
  rolesApi,
} from "../../api/roles";
import {
  type WorldResponse,
  type WorldsApi,
  worldsApi,
} from "../../api/worlds";
import styles from "./WorldPages.module.css";

interface WorldListPageProps {
  api?: WorldsApi;
  assetApi?: Pick<RolesApi, "listAssets">;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | {
      kind: "ready";
      worlds: WorldResponse[];
      assets: CharacterAssetResponse[];
    };

const timeSlotLabels: Record<string, string> = {
  morning: "晨间",
  midday: "午间",
  evening: "傍晚",
  night: "夜晚",
};

const weekdayLabels: Record<string, string> = {
  monday: "星期一",
  tuesday: "星期二",
  wednesday: "星期三",
  thursday: "星期四",
  friday: "星期五",
  saturday: "星期六",
  sunday: "星期日",
};

function lastPlayedText(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function WorldListPage({
  api = worldsApi,
  assetApi = rolesApi,
}: WorldListPageProps) {
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [showWizard, setShowWizard] = useState(false);
  const [protagonistName, setProtagonistName] = useState("");
  const [protagonistPersona, setProtagonistPersona] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const activeController = useRef<AbortController | null>(null);
  const loadGeneration = useRef(0);
  const mutationPending = creating || deletingId !== null;

  const load = useCallback(() => {
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    const generation = loadGeneration.current + 1;
    loadGeneration.current = generation;
    setCreating(false);
    setDeletingId(null);
    setConfirmDeleteId(null);
    setState({ kind: "loading" });
    setActionError(null);

    void Promise.all([
      api.listWorlds(controller.signal),
      assetApi.listAssets(controller.signal),
    ]).then(
      ([worlds, assets]) => {
        if (
          loadGeneration.current === generation &&
          activeController.current === controller
        ) {
          setState({ kind: "ready", worlds, assets });
        }
      },
      () => {
        if (
          loadGeneration.current === generation &&
          activeController.current === controller &&
          !controller.signal.aborted
        ) {
          setState({ kind: "error" });
        }
      },
    );
  }, [api, assetApi]);

  useEffect(() => {
    load();
    return () => {
      // 卸载或重载后禁止忽略 AbortSignal 的旧 Promise 回写页面。
      loadGeneration.current += 1;
      activeController.current?.abort();
      activeController.current = null;
    };
  }, [load]);

  function isCurrentPage(generation: number): boolean {
    return loadGeneration.current === generation;
  }

  async function createWorld(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!protagonistName || !protagonistPersona.trim() || mutationPending) {
      return;
    }
    const generation = loadGeneration.current;
    setCreating(true);
    setActionError(null);
    try {
      const world = await api.createWorld({
        protagonist_name: protagonistName,
        protagonist_persona: protagonistPersona.trim(),
      });
      if (!isCurrentPage(generation)) return;
      navigate(`/worlds/${world.id}/roles`);
    } catch {
      // 原子创建失败时保留表单，方便用户修正素材或重试。
      if (isCurrentPage(generation)) {
        setActionError("创建世界失败；输入已保留，请检查主角素材后重试。");
      }
    } finally {
      if (isCurrentPage(generation)) setCreating(false);
    }
  }

  async function deleteWorld(world: WorldResponse) {
    if (mutationPending) return;
    const generation = loadGeneration.current;
    setDeletingId(world.id);
    setActionError(null);
    try {
      await api.deleteWorld(world.id);
      if (!isCurrentPage(generation)) return;
      setState((current) =>
        current.kind === "ready"
          ? {
              ...current,
              worlds: current.worlds.filter((item) => item.id !== world.id),
            }
          : current,
      );
      setConfirmDeleteId(null);
    } catch {
      if (isCurrentPage(generation)) {
        setActionError("删除世界失败；世界未被更改，请重试。");
      }
    } finally {
      if (isCurrentPage(generation)) setDeletingId(null);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>CLEAR SKY ENGINE</p>
          <h1>世界</h1>
          <p>选择一个世界继续，或从唯一主角开始新的故事。</p>
        </div>
        <nav className={styles.navigation} aria-label="全局导航">
          <Link className={styles.pillLink} to="/roles">
            角色库
          </Link>
          <Link className={styles.pillLink} to="/settings/ai">
            AI 设置
          </Link>
        </nav>
      </header>

      {state.kind === "loading" && (
        <p className={styles.stateCard}>正在加载世界…</p>
      )}
      {state.kind === "error" && (
        <section className={styles.stateCard}>
          <h2>无法加载世界列表</h2>
          <p>世界和主角素材都没有被更改，请检查本地服务后重试。</p>
          <button type="button" onClick={load}>
            重试
          </button>
        </section>
      )}

      {state.kind === "ready" && (
        <>
          <section className={styles.toolbar}>
            <div>
              <strong>{state.worlds.length}</strong> 个世界
              {state.assets.length === 0 && (
                <p
                  className={styles.disabledReason}
                  id="world-create-disabled-reason"
                >
                  请先在角色资源目录添加主角的同名默认立绘。
                </p>
              )}
            </div>
            <button
              type="button"
              disabled={mutationPending || state.assets.length === 0}
              aria-describedby={
                state.assets.length === 0
                  ? "world-create-disabled-reason"
                  : undefined
              }
              onClick={() => {
                setShowWizard(true);
                setActionError(null);
              }}
            >
              创建世界
            </button>
          </section>

          {actionError && (
            <p className={styles.errorBanner} role="alert">
              {actionError}
            </p>
          )}

          {showWizard && (
            <form
              className={styles.formCard}
              aria-busy={creating}
              onSubmit={(event) => void createWorld(event)}
            >
              <div className={styles.formHeading}>
                <div>
                  <span className={styles.badge}>新世界</span>
                  <h2>选择唯一主角</h2>
                  <p>固定从星期一 · Day 1 · 晨间开始</p>
                </div>
                <button
                  type="button"
                  disabled={mutationPending}
                  onClick={() => setShowWizard(false)}
                >
                  取消
                </button>
              </div>
              <div className={styles.formGrid}>
                <label>
                  主角名称
                  <select
                    value={protagonistName}
                    disabled={mutationPending}
                    onChange={(event) => setProtagonistName(event.target.value)}
                  >
                    <option value="">请选择角色素材</option>
                    {state.assets.map((asset) => (
                      <option key={asset.role_name} value={asset.role_name}>
                        {asset.role_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.fullWidth}>
                  基础人设
                  <textarea
                    value={protagonistPersona}
                    disabled={mutationPending}
                    maxLength={8000}
                    onChange={(event) =>
                      setProtagonistPersona(event.target.value)
                    }
                  />
                </label>
              </div>
              <p className={styles.disabledReason} id="create-submit-reason">
                {!protagonistName || !protagonistPersona.trim()
                  ? "请选择主角素材并填写基础人设后才能创建。"
                  : "世界、初始分支和主角将一次性创建。"}
              </p>
              <div className={styles.formActions}>
                <button
                  type="submit"
                  disabled={
                    mutationPending ||
                    !protagonistName ||
                    !protagonistPersona.trim()
                  }
                  aria-describedby="create-submit-reason"
                >
                  {creating ? "正在创建…" : "确认创建"}
                </button>
              </div>
            </form>
          )}

          {state.worlds.length === 0 ? (
            <section className={styles.stateCard}>
              <h2>还没有世界</h2>
              <p>准备好主角素材后，从星期一的晨间开始第一天。</p>
            </section>
          ) : (
            <section className={styles.cardGrid} aria-label="世界列表">
              {state.worlds.map((world) => (
                <article className={styles.worldCard} key={world.id}>
                  <div>
                    <span className={styles.badge}>
                      分支 {world.active_branch_id}
                    </span>
                    <h2>{world.display_name}</h2>
                    <p>
                      Day {world.day} ·{" "}
                      {weekdayLabels[world.weekday] ?? world.weekday} ·{" "}
                      {timeSlotLabels[world.time_slot] ?? world.time_slot}
                    </p>
                    <p>主角：{world.player_role.name}</p>
                    <p>NPC：{world.npc_count}</p>
                    <small>
                      最后游玩：{lastPlayedText(world.last_played_at)}
                    </small>
                  </div>
                  <div className={styles.cardActions}>
                    <Link
                      className={styles.pillLink}
                      to={`/worlds/${world.id}/roles`}
                    >
                      管理角色
                    </Link>
                    <Link
                      className={styles.primaryLink}
                      to={`/worlds/${world.id}/game`}
                    >
                      进入世界
                    </Link>
                    <button
                      type="button"
                      disabled={mutationPending}
                      aria-label={`删除世界 ${world.display_name}`}
                      onClick={() => setConfirmDeleteId(world.id)}
                    >
                      删除
                    </button>
                    {confirmDeleteId === world.id && (
                      <div className={styles.confirmation} role="alert">
                        <span>删除后无法恢复。</span>
                        <button
                          type="button"
                          disabled={mutationPending}
                          aria-label={`确认删除 ${world.display_name}`}
                          onClick={() => void deleteWorld(world)}
                        >
                          {deletingId === world.id ? "正在删除…" : "确认删除"}
                        </button>
                        <button
                          type="button"
                          disabled={mutationPending}
                          onClick={() => setConfirmDeleteId(null)}
                        >
                          取消删除
                        </button>
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </section>
          )}
        </>
      )}
    </main>
  );
}
