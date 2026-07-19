import { useEffect, useMemo, useState } from "react";

import type { TurnResponse } from "../../api/turns";
import type { WorldRoleResponse } from "../../api/worlds";
import styles from "./GamePage.module.css";

type HistoryStatus = "loading" | "ready" | "error";

interface TurnHistoryProps {
  status: HistoryStatus;
  turns: ReadonlyArray<TurnResponse>;
  worldRoles: ReadonlyArray<WorldRoleResponse>;
  error: string | null;
  onRetry(): void;
  scrollToTurnId: number | null;
}

function displayValue(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function TurnHistory({
  status,
  turns,
  worldRoles,
  error,
  onRetry,
  scrollToTurnId,
}: TurnHistoryProps) {
  const latestTurnId = turns[0]?.turn_id ?? null;
  const scrollTargetExists =
    scrollToTurnId !== null &&
    turns.some((turn) => turn.turn_id === scrollToTurnId);
  const [openTurnId, setOpenTurnId] = useState<number | null>(latestTurnId);
  const roleById = useMemo(
    () => new Map(worldRoles.map((role) => [role.role_id, role])),
    [worldRoles],
  );

  useEffect(() => {
    setOpenTurnId(latestTurnId);
  }, [latestTurnId]);

  useEffect(() => {
    if (scrollToTurnId === null || !scrollTargetExists) return;
    document
      .querySelector<HTMLElement>(`[data-turn-id="${scrollToTurnId}"]`)
      ?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [scrollTargetExists, scrollToTurnId]);

  if (turns.length === 0 && status === "loading")
    return <p>正在加载历轮故事…</p>;
  if (turns.length === 0 && status === "error") {
    return (
      <section role="alert" className={styles.historyStatus}>
        <p>{error ?? "无法加载历轮故事。"}</p>
        <button type="button" onClick={onRetry}>
          重试加载历轮故事
        </button>
      </section>
    );
  }
  if (turns.length === 0) {
    return <p className={styles.historyStatus}>还没有成功轮次</p>;
  }

  return (
    <section className={styles.history} aria-label="历轮故事">
      {status === "loading" && (
        <p className={styles.historyStatus}>正在加载历轮故事…</p>
      )}
      {status === "error" && (
        <section role="alert" className={styles.historyStatus}>
          <p>{error ?? "无法加载历轮故事。"}</p>
          <button type="button" onClick={onRetry}>
            重试加载历轮故事
          </button>
        </section>
      )}
      {turns.map((turn) => {
        // 历史必须按完整 world roles 解释角色身份，不能借用当前地点的可见角色集合。
        const stories = [...turn.roles].sort((left, right) => {
          const leftRole = roleById.get(left.role_id);
          const rightRole = roleById.get(right.role_id);
          const leftKind = leftRole?.kind === "player" ? 0 : 1;
          const rightKind = rightRole?.kind === "player" ? 0 : 1;
          return leftKind - rightKind || left.role_id - right.role_id;
        });
        const changeKeyCounts = new Map<string, number>();
        const stateChanges = turn.state_changes.map((change) => {
          const contentKey = JSON.stringify(change);
          const occurrence = (changeKeyCounts.get(contentKey) ?? 0) + 1;
          changeKeyCounts.set(contentKey, occurrence);
          return { change, key: `${contentKey}-${occurrence}` };
        });
        return (
          <details
            key={turn.turn_id}
            data-testid="turn-card"
            data-turn-id={turn.turn_id}
            className={styles.turnCard}
            open={openTurnId === turn.turn_id}
            onToggle={(event) => {
              if (event.currentTarget.open) setOpenTurnId(turn.turn_id);
              else if (openTurnId === turn.turn_id) setOpenTurnId(null);
            }}
          >
            <summary>
              第 {turn.turn_id} 轮 · Day {turn.day} · {turn.time_slot} ·{" "}
              {turn.player_intent}
            </summary>
            <div className={styles.turnBody}>
              {stories.map((story) => {
                const role = roleById.get(story.role_id);
                const isPlayer = role?.kind === "player";
                return (
                  <section key={story.role_id}>
                    <h3>
                      {isPlayer ? "主角独立纪事" : "其他角色独立纪事"} ·{" "}
                      {role?.name ?? `角色 ${story.role_id}`}
                    </h3>
                    <p>
                      {story.offline
                        ? "该角色本轮处于离屏状态，未生成独立纪事。"
                        : story.content}
                    </p>
                  </section>
                );
              })}
              <section>
                <h3>客观事件</h3>
                {turn.events.length === 0 ? (
                  <p>本轮没有客观事件。</p>
                ) : (
                  <ul>
                    {turn.events.map((event) => (
                      <li key={event.event_id}>
                        {event.location_id} · {event.event_type} ·{" "}
                        {displayValue(event.fact)}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section>
                <h3>属性变化</h3>
                {turn.state_changes.length === 0 ? (
                  <p>本轮没有属性变化。</p>
                ) : (
                  <ul>
                    {stateChanges.map(({ change, key }) => (
                      <li key={key}>
                        {roleById.get(change.role_id)?.name ??
                          `角色 ${change.role_id}`}{" "}
                        · {change.attribute_key}：
                        {displayValue(change.old_value)} →{" "}
                        {displayValue(change.new_value)}（{change.reason}）
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </details>
        );
      })}
    </section>
  );
}
