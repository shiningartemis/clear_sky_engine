import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../../api/health";
import { type RoleResponse, type RolesApi, rolesApi } from "../../api/roles";
import {
  type LocationId,
  type LocationRuleCreate,
  locationIds,
  type WorldRoleResponse,
  type WorldsApi,
  worldsApi,
} from "../../api/worlds";
import styles from "./WorldPages.module.css";

interface WorldRolesPageProps {
  api?: WorldsApi;
  roleApi?: Pick<RolesApi, "listRoles">;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; worldRoles: WorldRoleResponse[]; roles: RoleResponse[] };

interface CandidateDraft {
  draftId: string;
  locationId: LocationId;
  weight: number;
}

interface RuleDraft {
  draftId: string;
  weekdayMask: number;
  timeSlot: LocationRuleCreate["time_slot"];
  mode: LocationRuleCreate["mode"];
  priority: number;
  enabled: boolean;
  candidates: CandidateDraft[];
}

const locationLabels: Record<LocationId, string> = {
  the_home: "家",
  the_dungeon: "地下城",
  the_mall: "商场",
  the_guild: "公会",
  the_hotel: "旅店",
  the_school: "学校",
};

const weekdays = [
  { label: "星期一", bit: 1 },
  { label: "星期二", bit: 2 },
  { label: "星期三", bit: 4 },
  { label: "星期四", bit: 8 },
  { label: "星期五", bit: 16 },
  { label: "星期六", bit: 32 },
  { label: "星期日", bit: 64 },
] as const;

let draftSequence = 0;

function nextDraftId(prefix: "rule" | "candidate"): string {
  draftSequence += 1;
  return `${prefix}-${draftSequence}`;
}

function emptyCandidate(): CandidateDraft {
  return {
    draftId: nextDraftId("candidate"),
    locationId: "the_home",
    weight: 1,
  };
}

function emptyRule(): RuleDraft {
  return {
    draftId: nextDraftId("rule"),
    weekdayMask: 1,
    timeSlot: "morning",
    mode: "fixed",
    priority: 0,
    enabled: true,
    candidates: [emptyCandidate()],
  };
}

function isLocationId(value: string): value is LocationId {
  return locationIds.some((locationId) => locationId === value);
}

function isTimeSlot(value: string): value is LocationRuleCreate["time_slot"] {
  return (
    value === "morning" ||
    value === "midday" ||
    value === "evening" ||
    value === "night"
  );
}

function isRuleMode(value: string): value is LocationRuleCreate["mode"] {
  return value === "fixed" || value === "random";
}

function scalarText(value: number | string | boolean): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function sortedWorldRoles(roles: WorldRoleResponse[]): WorldRoleResponse[] {
  return [...roles].sort((left, right) => {
    if (left.kind !== right.kind) return left.kind === "player" ? -1 : 1;
    return left.role_id - right.role_id;
  });
}

function actionErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status === 409) {
    const detail = error.message.trim().replace(/[。；;]+$/u, "");
    if (detail) return `${detail}；请重新加载世界角色后重试。`;
  }
  return fallback;
}

export function WorldRolesPage({
  api = worldsApi,
  roleApi = rolesApi,
}: WorldRolesPageProps) {
  const { worldId: worldIdParam } = useParams();
  const worldId = Number(worldIdParam);
  const validWorldId = Number.isInteger(worldId) && worldId > 0;
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [confirmRemoveId, setConfirmRemoveId] = useState<number | null>(null);
  const [editingRuleRoleId, setEditingRuleRoleId] = useState<number | null>(
    null,
  );
  const [ruleDrafts, setRuleDrafts] = useState<RuleDraft[]>([emptyRule()]);
  const activeController = useRef<AbortController | null>(null);
  const loadGeneration = useRef(0);
  const currentWorldId = useRef<number | null>(validWorldId ? worldId : null);
  currentWorldId.current = validWorldId ? worldId : null;
  const mutationPending = pendingAction !== null;

  const load = useCallback(() => {
    activeController.current?.abort();
    activeController.current = null;
    const generation = loadGeneration.current + 1;
    loadGeneration.current = generation;
    setPendingAction(null);
    setConfirmRemoveId(null);
    setEditingRuleRoleId(null);
    setSelectedRoleId("");
    setActionError(null);
    setSuccessMessage(null);
    if (!validWorldId) {
      setState({ kind: "error" });
      return;
    }
    const controller = new AbortController();
    activeController.current = controller;
    setState({ kind: "loading" });

    void Promise.all([
      api.listWorldRoles(worldId, controller.signal),
      roleApi.listRoles(controller.signal),
    ]).then(
      ([worldRoles, roles]) => {
        if (
          loadGeneration.current === generation &&
          activeController.current === controller
        ) {
          setState({
            kind: "ready",
            worldRoles: sortedWorldRoles(worldRoles),
            roles,
          });
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
  }, [api, roleApi, validWorldId, worldId]);

  useEffect(() => {
    load();
    return () => {
      // API 切换或卸载时，旧的并行读取结果不能覆盖当前世界。
      loadGeneration.current += 1;
      activeController.current?.abort();
      activeController.current = null;
    };
  }, [load]);

  function isCurrentPage(generation: number, targetWorldId: number): boolean {
    return (
      loadGeneration.current === generation &&
      currentWorldId.current === targetWorldId
    );
  }

  const availableRoles = useMemo(() => {
    if (state.kind !== "ready") return [];
    const existingIds = new Set(state.worldRoles.map((role) => role.role_id));
    return state.roles.filter((role) => !existingIds.has(role.id));
  }, [state]);
  const npcCount =
    state.kind === "ready"
      ? state.worldRoles.filter((role) => role.kind === "npc").length
      : 0;
  const npcLimitReached = npcCount >= 20;

  function updateWorldRole(updated: WorldRoleResponse) {
    setState((current) =>
      current.kind === "ready"
        ? {
            ...current,
            worldRoles: sortedWorldRoles(
              current.worldRoles.map((role) =>
                role.role_id === updated.role_id ? updated : role,
              ),
            ),
          }
        : current,
    );
  }

  async function addNpc() {
    const roleId = Number(selectedRoleId);
    if (
      !Number.isInteger(roleId) ||
      roleId <= 0 ||
      mutationPending ||
      npcLimitReached
    ) {
      return;
    }
    const generation = loadGeneration.current;
    const targetWorldId = worldId;
    setPendingAction("add");
    setActionError(null);
    setSuccessMessage(null);
    try {
      const added = await api.addNpc(targetWorldId, roleId);
      if (!isCurrentPage(generation, targetWorldId)) return;
      setState((current) =>
        current.kind === "ready"
          ? {
              ...current,
              worldRoles: sortedWorldRoles([...current.worldRoles, added]),
            }
          : current,
      );
      setSelectedRoleId("");
    } catch (error) {
      if (isCurrentPage(generation, targetWorldId)) {
        setActionError(
          actionErrorMessage(
            error,
            "加入 NPC 失败；世界角色没有被更改，请重试。",
          ),
        );
      }
    } finally {
      if (isCurrentPage(generation, targetWorldId)) setPendingAction(null);
    }
  }

  async function toggleNpc(role: WorldRoleResponse) {
    if (role.kind !== "npc" || mutationPending) return;
    const generation = loadGeneration.current;
    const targetWorldId = worldId;
    setPendingAction(`toggle-${role.role_id}`);
    setActionError(null);
    setSuccessMessage(null);
    try {
      const updated = await api.setNpcEnabled(
        targetWorldId,
        role.role_id,
        !role.enabled,
      );
      if (!isCurrentPage(generation, targetWorldId)) return;
      updateWorldRole(updated);
    } catch (error) {
      if (isCurrentPage(generation, targetWorldId)) {
        setActionError(
          actionErrorMessage(
            error,
            "更新 NPC 启用状态失败；原状态已保留，请重试。",
          ),
        );
      }
    } finally {
      if (isCurrentPage(generation, targetWorldId)) setPendingAction(null);
    }
  }

  async function removeNpc(role: WorldRoleResponse) {
    if (role.kind !== "npc" || mutationPending) return;
    const generation = loadGeneration.current;
    const targetWorldId = worldId;
    setPendingAction(`remove-${role.role_id}`);
    setActionError(null);
    setSuccessMessage(null);
    try {
      await api.removeNpc(targetWorldId, role.role_id);
      if (!isCurrentPage(generation, targetWorldId)) return;
      setState((current) =>
        current.kind === "ready"
          ? {
              ...current,
              worldRoles: current.worldRoles.filter(
                (item) => item.role_id !== role.role_id,
              ),
            }
          : current,
      );
      if (editingRuleRoleId === role.role_id) setEditingRuleRoleId(null);
      setConfirmRemoveId(null);
    } catch (error) {
      if (isCurrentPage(generation, targetWorldId)) {
        setActionError(
          actionErrorMessage(
            error,
            "移除 NPC 失败；角色和规则没有被更改，请重试。",
          ),
        );
      }
    } finally {
      if (isCurrentPage(generation, targetWorldId)) setPendingAction(null);
    }
  }

  function updateRule(index: number, update: Partial<RuleDraft>) {
    setRuleDrafts((current) =>
      current.map((rule, candidateIndex) =>
        candidateIndex === index ? { ...rule, ...update } : rule,
      ),
    );
  }

  function updateCandidate(
    ruleIndex: number,
    candidateIndex: number,
    update: Partial<CandidateDraft>,
  ) {
    setRuleDrafts((current) =>
      current.map((rule, currentRuleIndex) =>
        currentRuleIndex === ruleIndex
          ? {
              ...rule,
              candidates: rule.candidates.map((candidate, currentIndex) =>
                currentIndex === candidateIndex
                  ? { ...candidate, ...update }
                  : candidate,
              ),
            }
          : rule,
      ),
    );
  }

  function locationPayload(): LocationRuleCreate[] | null {
    const invalid = ruleDrafts.some(
      (rule) =>
        rule.weekdayMask < 1 ||
        !Number.isInteger(rule.priority) ||
        rule.candidates.length === 0 ||
        rule.candidates.some(
          (candidate) =>
            !Number.isInteger(candidate.weight) || candidate.weight < 1,
        ),
    );
    if (invalid) return null;
    return ruleDrafts.map((rule) => ({
      weekday_mask: rule.weekdayMask,
      time_slot: rule.timeSlot,
      mode: rule.mode,
      priority: rule.priority,
      enabled: rule.enabled,
      candidates: rule.candidates.map((candidate) => ({
        location_id: candidate.locationId,
        weight: candidate.weight,
      })),
    }));
  }

  async function saveLocationRules() {
    if (editingRuleRoleId === null || mutationPending) return;
    const generation = loadGeneration.current;
    const targetWorldId = worldId;
    const targetRoleId = editingRuleRoleId;
    const payload = locationPayload();
    if (!payload) {
      setActionError(
        "每条规则必须选择星期、保留候选地点，并使用有效整数权重。",
      );
      return;
    }
    setPendingAction(`rules-${editingRuleRoleId}`);
    setActionError(null);
    setSuccessMessage(null);
    try {
      // 后端以整组 PUT 为唯一写入口，任一规则无效都不会留下部分更新。
      await api.replaceLocationRules(targetWorldId, targetRoleId, payload);
      if (!isCurrentPage(generation, targetWorldId)) return;
      setSuccessMessage("位置规则已原子替换。");
    } catch (error) {
      if (isCurrentPage(generation, targetWorldId)) {
        setActionError(
          actionErrorMessage(
            error,
            "保存位置规则失败；原规则完整保留，请检查后重试。",
          ),
        );
      }
    } finally {
      if (isCurrentPage(generation, targetWorldId)) setPendingAction(null);
    }
  }

  function attributeRows(role: WorldRoleResponse, libraryRole?: RoleResponse) {
    const definitions = new Map(
      (libraryRole?.attributes ?? []).map((attribute) => [
        attribute.key,
        attribute.display_name,
      ]),
    );
    return Object.entries(role.effective_attributes).map(([key, value]) => ({
      key,
      label: definitions.get(key) ?? key,
      value,
    }));
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>WORLD {validWorldId ? worldId : "—"}</p>
          <h1>世界角色</h1>
          <p>最终属性只读；NPC 引用、启用状态和位置规则按世界隔离。</p>
        </div>
        <nav className={styles.navigation} aria-label="世界导航">
          <Link className={styles.pillLink} to="/">
            返回世界
          </Link>
          {validWorldId && (
            <Link className={styles.primaryLink} to={`/worlds/${worldId}/game`}>
              进入世界
            </Link>
          )}
          <Link className={styles.pillLink} to="/roles">
            全局角色库
          </Link>
        </nav>
      </header>

      {state.kind === "loading" && (
        <p className={styles.stateCard}>正在加载世界角色…</p>
      )}
      {state.kind === "error" && (
        <section className={styles.stateCard}>
          <h2>无法加载世界角色</h2>
          <p>
            {validWorldId
              ? "角色引用和位置规则都没有被更改，请检查本地服务后重试。"
              : "世界地址无效，请返回世界列表重新选择。"}
          </p>
          {validWorldId ? (
            <button type="button" onClick={load}>
              重试
            </button>
          ) : (
            <Link className={styles.pillLink} to="/">
              返回世界列表
            </Link>
          )}
        </section>
      )}

      {state.kind === "ready" && (
        <>
          <section className={styles.toolbar}>
            <label className={styles.pickerLabel}>
              选择 NPC
              <select
                value={selectedRoleId}
                disabled={
                  mutationPending ||
                  availableRoles.length === 0 ||
                  npcLimitReached
                }
                aria-describedby="add-npc-disabled-reason"
                onChange={(event) => setSelectedRoleId(event.target.value)}
              >
                <option value="">请选择全局角色</option>
                {availableRoles.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </select>
            </label>
            <div>
              <button
                type="button"
                disabled={mutationPending || !selectedRoleId || npcLimitReached}
                aria-describedby="add-npc-disabled-reason"
                onClick={() => void addNpc()}
              >
                {pendingAction === "add" ? "正在加入…" : "加入 NPC"}
              </button>
              <p className={styles.disabledReason} id="add-npc-disabled-reason">
                {npcLimitReached
                  ? "当前世界已达到 20 个 NPC 上限，需先移除一个 NPC。"
                  : availableRoles.length === 0
                    ? "角色库中没有可加入的 NPC。"
                    : selectedRoleId
                      ? "角色会作为全局引用加入当前世界。"
                      : "请先选择一个尚未加入的全局角色。"}
              </p>
            </div>
          </section>

          {actionError && (
            <div className={styles.errorBanner} role="alert">
              <span>{actionError}</span>
              <button type="button" onClick={load}>
                重新加载世界角色
              </button>
            </div>
          )}
          {successMessage && (
            <p className={styles.successBanner} role="status">
              {successMessage}
            </p>
          )}

          {state.worldRoles.length === 0 ? (
            <section className={styles.stateCard}>
              <h2>这个世界还没有可显示的角色</h2>
              <p>请返回世界列表确认世界创建结果，或重试加载。</p>
              <button type="button" onClick={load}>
                重新加载
              </button>
            </section>
          ) : (
            <section className={styles.roleList} aria-label="世界角色列表">
              {state.worldRoles.map((role) => {
                const libraryRole = state.roles.find(
                  (item) => item.id === role.role_id,
                );
                const rows = attributeRows(role, libraryRole);
                return (
                  <article className={styles.roleCard} key={role.role_id}>
                    <img
                      className={styles.portrait}
                      src={role.portrait_url}
                      alt={`${role.name} 默认立绘`}
                    />
                    <div className={styles.roleSummary}>
                      <div className={styles.roleHeading}>
                        <div>
                          <span className={styles.badge}>
                            {role.kind === "player" ? "主角" : "NPC"}
                          </span>
                          <h2>{role.name}</h2>
                        </div>
                        <span
                          className={
                            role.enabled ? styles.enabled : styles.disabled
                          }
                        >
                          {role.enabled ? "已启用" : "已停用"}
                        </span>
                      </div>
                      <h3>最终属性</h3>
                      {rows.length === 0 ? (
                        <p className={styles.inlineEmpty}>没有动态属性</p>
                      ) : (
                        <ul className={styles.attributeValues}>
                          {rows.map((row) => (
                            <li key={row.key}>
                              {row.label} {scalarText(row.value)}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    {role.kind === "npc" && (
                      <div className={styles.cardActions}>
                        <button
                          type="button"
                          disabled={mutationPending}
                          aria-label={`${role.enabled ? "停用" : "启用"} NPC ${role.name}`}
                          onClick={() => void toggleNpc(role)}
                        >
                          {pendingAction === `toggle-${role.role_id}`
                            ? "正在更新…"
                            : role.enabled
                              ? "停用"
                              : "启用"}
                        </button>
                        <button
                          type="button"
                          disabled={mutationPending}
                          aria-label={`配置位置规则 ${role.name}`}
                          onClick={() => {
                            setEditingRuleRoleId(role.role_id);
                            setRuleDrafts([emptyRule()]);
                            setActionError(null);
                            setSuccessMessage(null);
                          }}
                        >
                          位置规则
                        </button>
                        <button
                          type="button"
                          disabled={mutationPending}
                          aria-label={`移除 NPC ${role.name}`}
                          onClick={() => setConfirmRemoveId(role.role_id)}
                        >
                          移除
                        </button>
                        {confirmRemoveId === role.role_id && (
                          <div className={styles.confirmation} role="alert">
                            <span>
                              移除后，该世界的角色变化和位置规则会一并删除。
                            </span>
                            <button
                              type="button"
                              disabled={mutationPending}
                              aria-label={`确认移除 ${role.name}`}
                              onClick={() => void removeNpc(role)}
                            >
                              {pendingAction === `remove-${role.role_id}`
                                ? "正在移除…"
                                : "确认移除"}
                            </button>
                            <button
                              type="button"
                              disabled={mutationPending}
                              onClick={() => setConfirmRemoveId(null)}
                            >
                              取消
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                );
              })}
            </section>
          )}

          {editingRuleRoleId !== null && (
            <section className={styles.ruleEditor} aria-label="位置规则编辑器">
              <div className={styles.formHeading}>
                <div>
                  <span className={styles.badge}>整组替换</span>
                  <h2>
                    {
                      state.worldRoles.find(
                        (role) => role.role_id === editingRuleRoleId,
                      )?.name
                    }{" "}
                    的位置规则
                  </h2>
                  <p>保存时一次提交全部草稿；失败不会保留部分规则。</p>
                </div>
                <button
                  type="button"
                  disabled={mutationPending}
                  onClick={() => setEditingRuleRoleId(null)}
                >
                  关闭
                </button>
              </div>

              {ruleDrafts.length === 0 && (
                <p className={styles.inlineEmpty}>
                  当前草稿为空；保存后会清除该 NPC 的全部位置规则。
                </p>
              )}
              {ruleDrafts.map((rule, ruleIndex) => (
                <fieldset className={styles.ruleCard} key={rule.draftId}>
                  <legend>规则 {ruleIndex + 1}</legend>
                  <div className={styles.weekdays}>
                    {weekdays.map((weekday) => (
                      <label key={weekday.bit}>
                        <input
                          type="checkbox"
                          checked={(rule.weekdayMask & weekday.bit) !== 0}
                          disabled={mutationPending}
                          onChange={(event) =>
                            updateRule(ruleIndex, {
                              weekdayMask: event.target.checked
                                ? rule.weekdayMask | weekday.bit
                                : rule.weekdayMask & ~weekday.bit,
                            })
                          }
                        />
                        {weekday.label}
                      </label>
                    ))}
                  </div>
                  <div className={styles.formGrid}>
                    <label>
                      时间段
                      <select
                        value={rule.timeSlot}
                        disabled={mutationPending}
                        onChange={(event) => {
                          if (isTimeSlot(event.target.value)) {
                            updateRule(ruleIndex, {
                              timeSlot: event.target.value,
                            });
                          }
                        }}
                      >
                        <option value="morning">晨间</option>
                        <option value="midday">午间</option>
                        <option value="evening">傍晚</option>
                        <option value="night">夜晚</option>
                      </select>
                    </label>
                    <label>
                      模式
                      <select
                        value={rule.mode}
                        disabled={mutationPending}
                        onChange={(event) => {
                          if (!isRuleMode(event.target.value)) return;
                          const mode = event.target.value;
                          updateRule(ruleIndex, {
                            mode,
                            candidates:
                              mode === "fixed"
                                ? rule.candidates.slice(0, 1)
                                : rule.candidates,
                          });
                        }}
                      >
                        <option value="fixed">固定地点</option>
                        <option value="random">候选地点随机</option>
                      </select>
                    </label>
                    <label>
                      优先级
                      <input
                        type="number"
                        value={rule.priority}
                        disabled={mutationPending}
                        onChange={(event) =>
                          updateRule(ruleIndex, {
                            priority: Number(event.target.value),
                          })
                        }
                      />
                    </label>
                    <label className={styles.checkboxLabel}>
                      <input
                        type="checkbox"
                        checked={rule.enabled}
                        disabled={mutationPending}
                        onChange={(event) =>
                          updateRule(ruleIndex, {
                            enabled: event.target.checked,
                          })
                        }
                      />
                      启用规则
                    </label>
                  </div>

                  <div className={styles.candidateList}>
                    {rule.candidates.map((candidate, candidateIndex) => (
                      <div
                        className={styles.candidateRow}
                        key={candidate.draftId}
                      >
                        <label>
                          候选地点 {candidateIndex + 1}
                          <select
                            value={candidate.locationId}
                            disabled={mutationPending}
                            onChange={(event) => {
                              if (isLocationId(event.target.value)) {
                                updateCandidate(ruleIndex, candidateIndex, {
                                  locationId: event.target.value,
                                });
                              }
                            }}
                          >
                            {locationIds.map((locationId) => (
                              <option key={locationId} value={locationId}>
                                {locationLabels[locationId]}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          权重 {candidateIndex + 1}
                          <input
                            type="number"
                            min="1"
                            value={candidate.weight}
                            disabled={mutationPending}
                            onChange={(event) =>
                              updateCandidate(ruleIndex, candidateIndex, {
                                weight: Number(event.target.value),
                              })
                            }
                          />
                        </label>
                        <button
                          type="button"
                          disabled={
                            mutationPending || rule.candidates.length === 1
                          }
                          aria-label={`删除候选地点 ${candidateIndex + 1}`}
                          aria-describedby={
                            rule.candidates.length === 1
                              ? `last-candidate-reason-${ruleIndex}`
                              : undefined
                          }
                          onClick={() =>
                            updateRule(ruleIndex, {
                              candidates: rule.candidates.filter(
                                (_, index) => index !== candidateIndex,
                              ),
                            })
                          }
                        >
                          删除候选
                        </button>
                      </div>
                    ))}
                    <p
                      className={styles.disabledReason}
                      id={`last-candidate-reason-${ruleIndex}`}
                    >
                      每条规则至少保留一个候选地点；固定模式只使用一个地点。
                    </p>
                    <button
                      type="button"
                      disabled={mutationPending || rule.mode === "fixed"}
                      aria-describedby={
                        rule.mode === "fixed"
                          ? `last-candidate-reason-${ruleIndex}`
                          : undefined
                      }
                      onClick={() =>
                        updateRule(ruleIndex, {
                          candidates: [...rule.candidates, emptyCandidate()],
                        })
                      }
                    >
                      添加候选地点
                    </button>
                  </div>

                  <button
                    type="button"
                    disabled={mutationPending}
                    onClick={() =>
                      setRuleDrafts((current) =>
                        current.filter((_, index) => index !== ruleIndex),
                      )
                    }
                  >
                    删除这条规则
                  </button>
                </fieldset>
              ))}

              <div className={styles.formActions}>
                <button
                  type="button"
                  disabled={mutationPending}
                  onClick={() =>
                    setRuleDrafts((current) => [...current, emptyRule()])
                  }
                >
                  添加规则
                </button>
                <button
                  type="button"
                  disabled={mutationPending}
                  onClick={() => void saveLocationRules()}
                >
                  {pendingAction === `rules-${editingRuleRoleId}`
                    ? "正在保存…"
                    : "保存全部位置规则"}
                </button>
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}
