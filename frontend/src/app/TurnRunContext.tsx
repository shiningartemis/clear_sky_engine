import {
  createContext,
  type MouseEvent,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocation } from "react-router-dom";

interface TurnRunNavigationContextValue {
  isNavigationLocked: boolean;
  acquire(controller: AbortController): () => void;
}

const TurnRunNavigationContext =
  createContext<TurnRunNavigationContextValue | null>(null);

export function TurnRunNavigationProvider({
  children,
}: {
  children: ReactNode;
}) {
  const activeController = useRef<AbortController | null>(null);
  const previousLocationKey = useRef<string | null>(null);
  const [isNavigationLocked, setNavigationLocked] = useState(false);
  const location = useLocation();

  const releaseActiveRun = useCallback(() => {
    const controller = activeController.current;
    if (controller === null) return;
    controller.abort();
    activeController.current = null;
    setNavigationLocked(false);
  }, []);

  useEffect(() => {
    // 刷新和应用退出必须中止 fetch，让后端把已领取但未结算的 run 取消。
    window.addEventListener("pagehide", releaseActiveRun);
    return () => {
      window.removeEventListener("pagehide", releaseActiveRun);
      releaseActiveRun();
    };
  }, [releaseActiveRun]);

  useEffect(() => {
    if (
      previousLocationKey.current !== null &&
      previousLocationKey.current !== location.key
    ) {
      // 链接外的程序化跳转和浏览器历史同样会改变 location，必须闭合流生命周期。
      releaseActiveRun();
    }
    previousLocationKey.current = location.key;
  }, [location.key, releaseActiveRun]);

  const acquire = useCallback(
    (controller: AbortController) => {
      if (
        activeController.current !== null &&
        activeController.current !== controller
      ) {
        throw new Error("已有活动轮次。");
      }
      activeController.current = controller;
      setNavigationLocked(true);
      let released = false;
      return () => {
        if (released) return;
        released = true;
        if (activeController.current === controller) {
          releaseActiveRun();
        }
      };
    },
    [releaseActiveRun],
  );

  const value = useMemo(
    () => ({ isNavigationLocked, acquire }),
    [acquire, isNavigationLocked],
  );
  return (
    <TurnRunNavigationContext.Provider value={value}>
      {children}
    </TurnRunNavigationContext.Provider>
  );
}

export function TurnRunNavigationGuard({ children }: { children: ReactNode }) {
  const { isNavigationLocked } = useTurnRunNavigation();

  function preventNavigation(event: MouseEvent<HTMLElement>) {
    if (!isNavigationLocked || !(event.target instanceof Element)) return;
    const link = event.target.closest("a[href]");
    if (link?.getAttribute("href")?.startsWith("/") === true) {
      // 活动 run 的 stream 与当前游戏页绑定；切换设置、角色或世界会断开流。
      event.preventDefault();
      event.stopPropagation();
    }
  }

  return <div onClickCapture={preventNavigation}>{children}</div>;
}

export function useTurnRunNavigation(): TurnRunNavigationContextValue {
  const value = useContext(TurnRunNavigationContext);
  if (value === null) {
    throw new Error("TurnRunNavigationProvider 缺失。");
  }
  return value;
}
