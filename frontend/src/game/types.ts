import type { GameViewResponse, LocationId, SceneId } from "../api/worlds";
import { locationIds } from "../api/worlds";

export type GameEvent =
  | { type: "select_location"; locationId: LocationId }
  | { type: "enter_location"; locationId: LocationId }
  | { type: "return_to_the_world_map" };

export interface MapLocation {
  sceneId: LocationId;
  displayName: string;
  order: number;
  anchor: Readonly<{ x: number; y: number }>;
}

export interface GameViewState {
  sceneId: SceneId;
  backgroundUrl: string;
  fallbackBackgroundUrl: string;
  playerMarkerUrl: string;
  playerLocationId: LocationId;
  locations: ReadonlyArray<MapLocation>;
}

export interface MarkerPosition {
  x: number;
  y: number;
}

export function moveLocationMarker(
  current: MarkerPosition,
  delta: MarkerPosition,
): MarkerPosition {
  return {
    x: Math.min(1872, Math.max(48, current.x + delta.x)),
    y: Math.min(1032, Math.max(48, current.y + delta.y)),
  };
}

export interface CoverTransform {
  scale: number;
  offsetX: number;
  offsetY: number;
}

export function calculateCoverTransform(
  imageWidth: number,
  imageHeight: number,
  viewportWidth: number,
  viewportHeight: number,
): CoverTransform {
  const scale = Math.max(
    viewportWidth / imageWidth,
    viewportHeight / imageHeight,
  );
  return {
    scale,
    offsetX: (viewportWidth - imageWidth * scale) / 2,
    offsetY: (viewportHeight - imageHeight * scale) / 2,
  };
}

export function projectAnchor(
  anchor: Readonly<{ x: number; y: number }>,
  image: Readonly<{ width: number; height: number }>,
  transform: CoverTransform,
): Readonly<{ x: number; y: number }> {
  return {
    x: transform.offsetX + image.width * anchor.x * transform.scale,
    y: transform.offsetY + image.height * anchor.y * transform.scale,
  };
}

export function isValidMapAspectRatio(width: number, height: number): boolean {
  if (width <= 0 || height <= 0) return false;
  const expected = 16 / 9;
  return Math.abs(width / height - expected) / expected <= 0.01;
}

function isLocationId(value: string): value is LocationId {
  return locationIds.some((locationId) => locationId === value);
}

function isSceneId(value: string): value is SceneId {
  return value === "the_world_map" || isLocationId(value);
}

export function toGameViewState(response: GameViewResponse): GameViewState {
  if (
    !isSceneId(response.scene_id) ||
    !isLocationId(response.player_location_id)
  ) {
    throw new Error("游戏视图包含未知场景。");
  }

  return {
    sceneId: response.scene_id,
    backgroundUrl: response.background_url,
    fallbackBackgroundUrl: response.fallback_background_url,
    playerMarkerUrl: response.player_marker_url,
    playerLocationId: response.player_location_id,
    locations: response.locations.map((location) => ({
      sceneId: location.scene_id,
      displayName: location.display_name,
      order: location.order,
      anchor: { x: location.anchor_x, y: location.anchor_y },
    })),
  };
}

export interface GameBridgePort {
  mount(container: HTMLElement): void;
  update(state: GameViewState): void;
  subscribe(listener: (event: GameEvent) => void): () => void;
  destroy(): void;
}
