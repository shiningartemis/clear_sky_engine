interface GameHandle {
  destroy(removeCanvas: boolean): void;
}

export interface GameBridgePort {
  mount(container: HTMLElement): void;
  destroy(): void;
}

export type GameFactory = (container: HTMLElement) => GameHandle;

export class GameBridge implements GameBridgePort {
  private game: GameHandle | undefined;

  constructor(private readonly gameFactory: GameFactory) {}

  mount(container: HTMLElement): void {
    if (this.game) {
      return;
    }

    // React 只管理容器生命周期；Phaser 的场景和 Canvas 必须由桥接层统一销毁。
    this.game = this.gameFactory(container);
  }

  destroy(): void {
    this.game?.destroy(true);
    this.game = undefined;
  }
}
