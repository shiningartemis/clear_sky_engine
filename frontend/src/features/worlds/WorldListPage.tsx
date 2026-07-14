import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../../api/health";
import { type RoleResponse, type RolesApi, rolesApi } from "../../api/roles";
import {
  type WorldResponse,
  type WorldsApi,
  worldsApi,
} from "../../api/worlds";
import styles from "./WorldPages.module.css";

interface WorldListPageProps {
  api?: WorldsApi;
  roleApi?: Pick<RolesApi, "listRoles">;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | {
      kind: "ready";
      worlds: WorldResponse[];
      roles: RoleResponse[];
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
  roleApi = rolesApi,
}: WorldListPageProps) {
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [showWizard, setShowWizard] = useState(false);
  const [protagonistRoleId, setProtagonistRoleId] = useState<number | null>(
    null,
  );
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
      roleApi.listRoles(controller.signal),
    ]).then(
      ([worlds, roles]) => {
        if (
          loadGeneration.current === generation &&
          activeController.current === controller
        ) {
          setProtagonistRoleId((current) =>
            current !== null && roles.some((role) => role.id === current)
              ? current
              : null,
          );
          setState({ kind: "ready", worlds, roles });
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
  }, [api, roleApi]);

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
    if (protagonistRoleId === null || mutationPending) {
      return;
    }
    const generation = loadGeneration.current;
    setCreating(true);
    setActionError(null);
    try {
      const world = await api.createWorld({
        protagonist_role_id: protagonistRoleId,
      });
      if (!isCurrentPage(generation)) return;
      navigate(`/worlds/${world.id}/roles`);
    } catch (error) {
      // 原子创建失败时保留稳定角色 ID；后端业务错误已经过安全裁剪。
      if (isCurrentPage(generation)) {
        const detail =
          error instanceof ApiError ? error.message : "请检查本地服务后重试。";
        setActionError(`创建世界失败；已保留主角选择。${detail}`);
      }
    } finally {
      if (isCurrentPage(generation)) setCreating(false);
    }
  }

  const selectedRole =
    state.kind === "ready" && protagonistRoleId !== null
      ? (state.roles.find((role) => role.id === protagonistRoleId) ?? null)
      : null;

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
          <p>世界和角色库都没有被更改，请检查本地服务后重试。</p>
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
              {state.roles.length === 0 && (
                <p
                  className={styles.disabledReason}
                  id="world-create-disabled-reason"
                >
                  请先在全局角色库创建角色并准备同名默认立绘。
                </p>
              )}
            </div>
            <button
              type="button"
              disabled={mutationPending || state.roles.length === 0}
              aria-describedby={
                state.roles.length === 0
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
                  主角角色
                  <select
                    value={protagonistRoleId ?? ""}
                    disabled={mutationPending}
                    onChange={(event) => {
                      const roleId = Number(event.target.value);
                      setProtagonistRoleId(
                        Number.isInteger(roleId) && roleId > 0 ? roleId : null,
                      );
                    }}
                  >
                    <option value="">请选择已有角色</option>
                    {state.roles.map((role) => (
                      <option key={role.id} value={role.id}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {selectedRole && (
                <section
                  className={styles.rolePreview}
                  aria-label={`已选主角 ${selectedRole.name}`}
                >
                  <img
                    className={styles.portrait}
                    src={selectedRole.portrait_url}
                    alt={`${selectedRole.name} 默认立绘`}
                  />
                  <div className={styles.roleSummary}>
                    <h3>{selectedRole.name}</h3>
                    <p>{selectedRole.persona}</p>
                    <small>{selectedRole.attributes.length} 个基础属性</small>
                  </div>
                </section>
              )}
              <p className={styles.disabledReason} id="create-submit-reason">
                {protagonistRoleId === null
                  ? "请选择全局角色库中的已有角色。"
                  : "世界、初始分支和主角引用将一次性创建。"}
              </p>
              <div className={styles.formActions}>
                <button
                  type="submit"
                  disabled={mutationPending || protagonistRoleId === null}
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
              <p>从角色库选择主角后，从星期一的晨间开始第一天。</p>
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
