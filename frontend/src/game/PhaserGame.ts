import Phaser from "phaser";

import { GameBridge } from "./GameBridge";

class BootScene extends Phaser.Scene {
  constructor() {
    super("boot");
  }

  create(): void {
    this.add
      .text(960, 540, "Clear Sky Engine", {
        color: "#dcecff",
        fontFamily: "Segoe UI, sans-serif",
        fontSize: "42px",
      })
      .setOrigin(0.5);
  }
}

export function createDefaultGameBridge(): GameBridge {
  return new GameBridge(
    (container) =>
      new Phaser.Game({
        type: Phaser.AUTO,
        parent: container,
        width: 1920,
        height: 1080,
        backgroundColor: "#08111f",
        scene: [BootScene],
        scale: {
          mode: Phaser.Scale.RESIZE,
          autoCenter: Phaser.Scale.CENTER_BOTH,
        },
      }),
  );
}
