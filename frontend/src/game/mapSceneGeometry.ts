import { type CoverTransform, projectAnchor } from "./types";

const LOGICAL_WIDTH = 1920;
const LOGICAL_HEIGHT = 1080;
const MIN_OVERLAY_SCALE = 0.5;
const MARKER_RADIUS = 16;
const LABEL_OFFSET_Y = 58;
const LABEL_HEIGHT = 32;
const LABEL_CHARACTER_WIDTH = 18;
const LABEL_HORIZONTAL_PADDING = 20;

export interface LocationOverlayGeometry {
  viewportScale: number;
  marker: Readonly<{ x: number; y: number; radius: number }>;
  label: Readonly<{
    x: number;
    y: number;
    width: number;
    height: number;
  }>;
}

export function calculateLocationOverlayGeometry(
  anchor: Readonly<{ x: number; y: number }>,
  image: Readonly<{ width: number; height: number }>,
  transform: CoverTransform,
  viewportWidth: number,
  viewportHeight: number,
  displayName: string,
): LocationOverlayGeometry {
  // 小窗口保留最低可见尺寸；marker、标签和命中区必须共享同一缩放值。
  const viewportScale = Math.max(
    MIN_OVERLAY_SCALE,
    Math.min(viewportWidth / LOGICAL_WIDTH, viewportHeight / LOGICAL_HEIGHT),
  );
  const point = projectAnchor(anchor, image, transform);
  return {
    viewportScale,
    marker: {
      x: point.x,
      y: point.y,
      radius: MARKER_RADIUS * viewportScale,
    },
    label: {
      x: point.x,
      y: point.y + LABEL_OFFSET_Y * viewportScale,
      width:
        Math.max(
          48,
          displayName.length * LABEL_CHARACTER_WIDTH + LABEL_HORIZONTAL_PADDING,
        ) * viewportScale,
      height: LABEL_HEIGHT * viewportScale,
    },
  };
}

export function hitTestLocationOverlay(
  point: Readonly<{ x: number; y: number }>,
  geometry: LocationOverlayGeometry,
): boolean {
  const markerDistance = Math.hypot(
    point.x - geometry.marker.x,
    point.y - geometry.marker.y,
  );
  if (markerDistance <= geometry.marker.radius) return true;
  return (
    Math.abs(point.x - geometry.label.x) <= geometry.label.width / 2 &&
    Math.abs(point.y - geometry.label.y) <= geometry.label.height / 2
  );
}
