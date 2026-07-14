import type { GameBridgePort, GameEvent, GameViewState } from "./types";

export interface GameHandle {
  destroy(removeCanvas: boolean): void;
  update(state: GameViewState): void;
}

export type GameFactory = (
  container: HTMLElement,
  emit: (event: GameEvent) => void,
) => GameHandle;

export class GameBridge implements GameBridgePort {
  private game: GameHandle | undefined;
  private container: HTMLElement | undefined;
  private latestState: GameViewState | undefined;
  private readonly listeners = new Set<(event: GameEvent) => void>();

  constructor(private readonly gameFactory: GameFactory) {}

  mount(container: HTMLElement): void {
    if (this.game) return;

    // React 只管理容器生命周期；Phaser 场景与 Canvas 必须由桥接层统一销毁。
    this.container = container;
    this.game = this.gameFactory(container, (event) => {
      for (const listener of this.listeners) listener(event);
    });
    if (this.latestState) this.game.update(this.latestState);
  }

  update(state: GameViewState): void {
    this.latestState = state;
    this.game?.update(state);
  }

  subscribe(listener: (event: GameEvent) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  destroy(): void {
    this.game?.destroy(true);
    this.game = undefined;
    // Phaser 的销毁可能延迟到内部事件循环；同步清空专用容器可避免 StrictMode 重挂载留下双 Canvas。
    this.container?.replaceChildren();
    this.container = undefined;
    this.listeners.clear();
  }
}
