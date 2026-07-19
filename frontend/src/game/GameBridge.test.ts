import { describe, expect, it, vi } from "vitest";

import { GameBridge, type GameFactory } from "./GameBridge";
import type { GameEvent, GameViewState } from "./types";

function worldMapView(): GameViewState {
  return {
    sceneId: "the_world_map",
    backgroundUrl: "/maps/world.jpg",
    fallbackBackgroundUrl: "/maps/fallback.jpg",
    playerMarkerUrl: "/portraits/player.png",
    playerLocationId: "the_home",
    locations: [],
  };
}

describe("GameBridge", () => {
  it("mounts one Phaser game into the supplied container", () => {
    const destroy = vi.fn();
    const update = vi.fn();
    const factory = vi.fn<GameFactory>(() => ({ destroy, update }));
    const bridge = new GameBridge(factory);
    const container = document.createElement("div");

    bridge.mount(container);
    bridge.mount(container);

    expect(factory).toHaveBeenCalledTimes(1);
    expect(factory).toHaveBeenCalledWith(container, expect.any(Function));
  });

  it("queues the latest view before mount and forwards it once mounted", () => {
    const update = vi.fn();
    const factory = vi.fn<GameFactory>(() => ({ destroy: vi.fn(), update }));
    const bridge = new GameBridge(factory);
    const first = worldMapView();
    const latest = { ...first, playerLocationId: "the_school" as const };

    bridge.update(first);
    bridge.update(latest);
    bridge.mount(document.createElement("div"));

    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith(latest);
  });

  it("forwards updates after mount", () => {
    const update = vi.fn();
    const factory = vi.fn<GameFactory>(() => ({ destroy: vi.fn(), update }));
    const bridge = new GameBridge(factory);
    const state = worldMapView();

    bridge.mount(document.createElement("div"));
    bridge.update(state);

    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith(state);
  });

  it("subscribes, unsubscribes, and removes remaining listeners on destroy", () => {
    let emit: ((event: GameEvent) => void) | undefined;
    const factory = vi.fn<GameFactory>((_container, gameEmit) => {
      emit = gameEmit;
      return { destroy: vi.fn(), update: vi.fn() };
    });
    const first = vi.fn();
    const second = vi.fn();
    const bridge = new GameBridge(factory);
    const unsubscribe = bridge.subscribe(first);
    bridge.subscribe(second);
    bridge.mount(document.createElement("div"));

    emit?.({ type: "return_to_the_world_map" });
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);

    unsubscribe();
    emit?.({ type: "return_to_the_world_map" });
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(2);

    bridge.destroy();
    emit?.({ type: "return_to_the_world_map" });
    expect(second).toHaveBeenCalledTimes(2);
  });

  it("活动轮次拒绝 Phaser 键鼠事件，结束后恢复并保持监听清理", () => {
    let emit: ((event: GameEvent) => void) | undefined;
    const factory = vi.fn<GameFactory>((_container, gameEmit) => {
      emit = gameEmit;
      return { destroy: vi.fn(), update: vi.fn() };
    });
    const listener = vi.fn();
    const bridge = new GameBridge(factory);
    const unsubscribe = bridge.subscribe(listener);
    bridge.mount(document.createElement("div"));

    bridge.setInputLocked(true);
    emit?.({ type: "select_location", locationId: "the_school" });
    emit?.({ type: "enter_location", locationId: "the_school" });
    expect(listener).not.toHaveBeenCalled();

    bridge.setInputLocked(false);
    emit?.({ type: "select_location", locationId: "the_school" });
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    emit?.({ type: "return_to_the_world_map" });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("destroys the Phaser game and remains safe when called twice", () => {
    const destroy = vi.fn();
    const factory = vi.fn<GameFactory>(() => ({ destroy, update: vi.fn() }));
    const bridge = new GameBridge(factory);

    bridge.mount(document.createElement("div"));
    bridge.destroy();
    bridge.destroy();

    expect(destroy).toHaveBeenCalledTimes(1);
    expect(destroy).toHaveBeenCalledWith(true);
  });

  it("removes a stale canvas synchronously before StrictMode remounts", () => {
    const factory = vi.fn<GameFactory>((container) => {
      container.append(document.createElement("canvas"));
      return { destroy: vi.fn(), update: vi.fn() };
    });
    const bridge = new GameBridge(factory);
    const container = document.createElement("div");

    bridge.mount(container);
    bridge.destroy();
    bridge.mount(container);

    expect(factory).toHaveBeenCalledTimes(2);
    expect(container.querySelectorAll("canvas")).toHaveLength(1);
  });
});
