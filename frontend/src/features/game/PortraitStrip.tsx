import { useMemo, useState } from "react";

import type { WorldRoleResponse } from "../../api/worlds";
import styles from "./GamePage.module.css";

interface PortraitStripProps {
  roles: ReadonlyArray<WorldRoleResponse>;
  viewportWidth: number;
}

export function calculatePortraitSize(
  viewportWidth: number,
  count: number,
): number | null {
  if (count === 0) return null;
  const available = viewportWidth - 80 - Math.max(0, count - 1) * 12;
  const size = Math.floor(available / count);
  return size < 128 ? null : Math.min(220, size);
}

export function PortraitStrip({ roles, viewportWidth }: PortraitStripProps) {
  const visibleRoles = useMemo(
    () =>
      // 这里只排序并执行六人显示上限，不推断角色是否位于当前地点。
      [...roles]
        .sort((left, right) => {
          if (left.kind !== right.kind) return left.kind === "player" ? -1 : 1;
          return left.role_id - right.role_id;
        })
        .slice(0, 6),
    [roles],
  );
  const [brokenPortraits, setBrokenPortraits] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const portraitSize = calculatePortraitSize(
    viewportWidth,
    visibleRoles.length,
  );

  if (visibleRoles.length === 0) return null;
  if (portraitSize === null) {
    return (
      <p className={styles.resizeWarning} role="status">
        当前窗口过窄，请加宽窗口以完整显示地点角色。
      </p>
    );
  }

  return (
    <section className={styles.portraitStrip} aria-label="当前地点角色">
      {visibleRoles.map((role) => {
        const portraitKey = `${role.role_id}:${role.portrait_url}`;
        const broken = brokenPortraits.has(portraitKey);
        return (
          <figure
            className={styles.portraitCard}
            key={role.role_id}
            style={{ width: portraitSize }}
          >
            <div
              className={styles.portraitFrame}
              data-testid="portrait-frame"
              style={{ aspectRatio: "1 / 1" }}
            >
              {broken ? (
                <p className={styles.portraitError} role="alert">
                  {role.name} 的立绘无法显示
                </p>
              ) : (
                <img
                  className={styles.portraitImage}
                  src={role.portrait_url}
                  alt={role.name}
                  onError={() => {
                    setBrokenPortraits(
                      (current) => new Set([...current, portraitKey]),
                    );
                  }}
                />
              )}
            </div>
            <figcaption>{role.name}</figcaption>
          </figure>
        );
      })}
    </section>
  );
}
