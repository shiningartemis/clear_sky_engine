import { describe, expect, it } from "vitest";

import {
  calculateCoverTransform,
  isValidMapAspectRatio,
  moveLocationMarker,
  projectAnchor,
} from "./types";
import { createWorldMapState, reduceWorldMap } from "./worldMapState";

const locations = [
  "the_home",
  "the_dungeon",
  "the_mall",
  "the_guild",
  "the_hotel",
  "the_school",
] as const;

describe("world map reducer", () => {
  it("moves, selects, and enters without advancing time", () => {
    const initial = createWorldMapState(locations, "the_home");
    const moved = reduceWorldMap(initial, { type: "move", direction: 1 });
    expect(moved.selectedLocationId).toBe("the_dungeon");
    expect(moved.pendingEvent).toEqual({
      type: "select_location",
      locationId: "the_dungeon",
    });

    const entered = reduceWorldMap(
      { ...moved, playerLocationId: "the_dungeon" },
      { type: "enter" },
    );
    expect(entered.pendingEvent).toEqual({
      type: "enter_location",
      locationId: "the_dungeon",
    });
  });

  it.each([
    ["left edge", "the_home", -1, "the_home"],
    ["right edge", "the_school", 1, "the_school"],
  ] as const)("clamps movement at the %s", (_label, start, direction, expected) => {
    const state = createWorldMapState(locations, start);
    const moved = reduceWorldMap(state, { type: "move", direction });

    expect(moved.selectedLocationId).toBe(expected);
    expect(moved.pendingEvent).toBeNull();
  });

  it("selects on the first click and enters on the second click after arrival", () => {
    const initial = createWorldMapState(locations, "the_home");
    const selected = reduceWorldMap(initial, {
      type: "select",
      locationId: "the_guild",
    });
    expect(selected.pendingEvent).toEqual({
      type: "select_location",
      locationId: "the_guild",
    });

    const entered = reduceWorldMap(
      { ...selected, playerLocationId: "the_guild" },
      { type: "select", locationId: "the_guild" },
    );
    expect(entered.pendingEvent).toEqual({
      type: "enter_location",
      locationId: "the_guild",
    });
  });

  it("does not enter before the player marker reaches the selected location", () => {
    const state = createWorldMapState(locations, "the_home");
    const selected = reduceWorldMap(state, {
      type: "select",
      locationId: "the_hotel",
    });

    expect(reduceWorldMap(selected, { type: "enter" }).pendingEvent).toBeNull();
  });

  it("emits the typed return-map event", () => {
    const state = createWorldMapState(locations, "the_home");
    expect(reduceWorldMap(state, { type: "return_map" }).pendingEvent).toEqual({
      type: "return_to_the_world_map",
    });
  });
});

describe("moveLocationMarker", () => {
  it.each([
    ["ArrowLeft", { x: -24, y: 0 }, { x: 936, y: 540 }],
    ["a", { x: -24, y: 0 }, { x: 936, y: 540 }],
    ["ArrowRight", { x: 24, y: 0 }, { x: 984, y: 540 }],
    ["d", { x: 24, y: 0 }, { x: 984, y: 540 }],
    ["ArrowUp", { x: 0, y: -24 }, { x: 960, y: 516 }],
    ["w", { x: 0, y: -24 }, { x: 960, y: 516 }],
    ["ArrowDown", { x: 0, y: 24 }, { x: 960, y: 564 }],
    ["s", { x: 0, y: 24 }, { x: 960, y: 564 }],
  ] as const)("applies the %s delta without a world event", (_key, delta, expected) => {
    expect(moveLocationMarker({ x: 960, y: 540 }, delta)).toEqual(expected);
  });

  it.each([
    [
      { x: 48, y: 48 },
      { x: -24, y: -24 },
      { x: 48, y: 48 },
    ],
    [
      { x: 1872, y: 1032 },
      { x: 24, y: 24 },
      { x: 1872, y: 1032 },
    ],
  ] as const)("keeps the 96x96 marker inside the safe rectangle", (current, delta, expected) => {
    expect(moveLocationMarker(current, delta)).toEqual(expected);
  });
});

describe("cover projection", () => {
  it.each([
    [1920, 1080, true],
    [1910, 1080, true],
    [1800, 1080, false],
    [1080, 1920, false],
    [0, 1080, false],
  ] as const)("validates %sx%s against 16:9 with one-percent tolerance", (width, height, expected) => {
    expect(isValidMapAspectRatio(width, height)).toBe(expected);
  });

  it.each([
    ["16:9", 1920, 1080, { scale: 1, offsetX: 0, offsetY: 0 }],
    ["ultrawide", 2560, 1080, { scale: 4 / 3, offsetX: 0, offsetY: -180 }],
    [
      "portrait",
      1080,
      1920,
      { scale: 16 / 9, offsetX: -1166.6666666666665, offsetY: 0 },
    ],
  ] as const)("calculates the %s viewport transform", (_name, width, height, expected) => {
    const transform = calculateCoverTransform(1920, 1080, width, height);
    expect(transform.scale).toBeCloseTo(expected.scale);
    expect(transform.offsetX).toBeCloseTo(expected.offsetX);
    expect(transform.offsetY).toBeCloseTo(expected.offsetY);
  });

  it("projects normalized anchors through the shared cover transform", () => {
    const transform = calculateCoverTransform(1920, 1080, 2560, 1080);
    expect(
      projectAnchor(
        { x: 0.5, y: 0.5 },
        { width: 1920, height: 1080 },
        transform,
      ),
    ).toEqual({
      x: 1280,
      y: 540,
    });
  });
});
