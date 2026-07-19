import type { LocationId } from "../../api/worlds";
import styles from "./GamePage.module.css";
import type { MapNodeProgress } from "./turnRunReducer";

interface ProgressLocation {
  sceneId: LocationId;
  displayName: string;
  order: number;
}

interface TurnProgressProps {
  locations: ReadonlyArray<ProgressLocation>;
  mapProgress: Readonly<Record<string, MapNodeProgress>>;
  completedMaps: number;
  totalMaps: number;
  elapsedMs: number;
  isCancelling: boolean;
  cancelError: string | null;
  onCancel(): void;
}

const nodeLabels: Readonly<
  Record<NonNullable<MapNodeProgress["node"]>, string>
> = {
  location_simulation: "地点推演",
  attribute_memory_analysis: "属性与记忆分析",
};

function progressLabel(
  locationName: string,
  progress: MapNodeProgress,
): string {
  const nodeLabel =
    progress.node === null ? "等待节点" : nodeLabels[progress.node];
  const attemptLabel =
    progress.attempt === null
      ? "等待尝试"
      : `尝试 ${progress.attempt}/${progress.maxAttempts}`;
  const statusLabel = progress.completed
    ? "已完成"
    : progress.retrying
      ? "自动重试"
      : "进行中";
  return `${locationName} · ${nodeLabel} · ${attemptLabel} · ${statusLabel}`;
}

export function TurnProgress({
  locations,
  mapProgress,
  completedMaps,
  totalMaps,
  elapsedMs,
  isCancelling,
  cancelError,
  onCancel,
}: TurnProgressProps) {
  const locationById = new Map<string, ProgressLocation>(
    locations.map((location) => [location.sceneId, location]),
  );
  const entries = Object.entries(mapProgress).sort(([left], [right]) => {
    const leftOrder = locationById.get(left)?.order ?? Number.MAX_SAFE_INTEGER;
    const rightOrder =
      locationById.get(right)?.order ?? Number.MAX_SAFE_INTEGER;
    return leftOrder - rightOrder || left.localeCompare(right);
  });

  return (
    <section
      className={styles.progressPanel}
      aria-label="轮次进度"
      aria-live="polite"
    >
      <div className={styles.progressHeader}>
        <h2>轮次推演中</h2>
        <button type="button" onClick={onCancel} disabled={isCancelling}>
          {isCancelling ? "正在取消…" : "取消轮次"}
        </button>
      </div>
      {entries.length === 0 ? (
        <p>正在准备轮次节点…</p>
      ) : (
        <ol className={styles.progressList}>
          {entries.map(([locationId, progress]) => (
            <li key={locationId}>
              {progressLabel(
                locationById.get(locationId)?.displayName ?? locationId,
                progress,
              )}
            </li>
          ))}
        </ol>
      )}
      <p className={styles.progressSummary}>
        已完成 {completedMaps}/{totalMaps} 张地图 · 总耗时{" "}
        {(elapsedMs / 1000).toFixed(1)} 秒
      </p>
      {cancelError !== null && <p role="alert">{cancelError}</p>}
    </section>
  );
}
