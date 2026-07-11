import { describe, expect, it, vi } from "vitest";

import { GameBridge, type GameFactory } from "./GameBridge";

describe("GameBridge", () => {
  it("mounts one Phaser game into the supplied container", () => {
    const destroy = vi.fn();
    const factory = vi.fn<GameFactory>(() => ({ destroy }));
    const bridge = new GameBridge(factory);
    const container = document.createElement("div");

    bridge.mount(container);
    bridge.mount(container);

    expect(factory).toHaveBeenCalledTimes(1);
    expect(factory).toHaveBeenCalledWith(container);
  });

  it("destroys the Phaser game and remains safe when called twice", () => {
    const destroy = vi.fn();
    const factory = vi.fn<GameFactory>(() => ({ destroy }));
    const bridge = new GameBridge(factory);

    bridge.mount(document.createElement("div"));
    bridge.destroy();
    bridge.destroy();

    expect(destroy).toHaveBeenCalledTimes(1);
    expect(destroy).toHaveBeenCalledWith(true);
  });
});
