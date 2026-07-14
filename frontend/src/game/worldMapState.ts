import type { LocationId } from "../api/worlds";
import type { GameEvent } from "./types";

export interface WorldMapState {
  locationIds: ReadonlyArray<LocationId>;
  selectedLocationId: LocationId;
  playerLocationId: LocationId;
  pendingEvent: GameEvent | null;
}

export type WorldMapAction =
  | { type: "move"; direction: -1 | 1 }
  | { type: "select"; locationId: LocationId }
  | { type: "enter" }
  | { type: "return_map" };

export function createWorldMapState(
  locationIds: ReadonlyArray<LocationId>,
  playerLocationId: LocationId,
): WorldMapState {
  return {
    locationIds,
    selectedLocationId: playerLocationId,
    playerLocationId,
    pendingEvent: null,
  };
}

export function reduceWorldMap(
  state: WorldMapState,
  action: WorldMapAction,
): WorldMapState {
  if (action.type === "return_map") {
    return { ...state, pendingEvent: { type: "return_to_the_world_map" } };
  }

  if (action.type === "move") {
    const currentIndex = state.locationIds.indexOf(state.selectedLocationId);
    const nextIndex = Math.min(
      state.locationIds.length - 1,
      Math.max(0, currentIndex + action.direction),
    );
    const nextLocationId = state.locationIds[nextIndex];
    if (
      nextLocationId === undefined ||
      nextLocationId === state.selectedLocationId
    ) {
      return { ...state, pendingEvent: null };
    }
    return {
      ...state,
      selectedLocationId: nextLocationId,
      pendingEvent: { type: "select_location", locationId: nextLocationId },
    };
  }

  if (action.type === "select") {
    if (
      action.locationId === state.selectedLocationId &&
      action.locationId === state.playerLocationId
    ) {
      return {
        ...state,
        pendingEvent: { type: "enter_location", locationId: action.locationId },
      };
    }
    if (action.locationId === state.selectedLocationId) {
      return { ...state, pendingEvent: null };
    }
    return {
      ...state,
      selectedLocationId: action.locationId,
      pendingEvent: { type: "select_location", locationId: action.locationId },
    };
  }

  if (state.selectedLocationId !== state.playerLocationId) {
    // 选择只提交位置意图；后端确认主角抵达前，Enter 不能进入地点或推进时间。
    return { ...state, pendingEvent: null };
  }
  return {
    ...state,
    pendingEvent: {
      type: "enter_location",
      locationId: state.selectedLocationId,
    },
  };
}
