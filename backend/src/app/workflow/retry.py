"""工作流节点唯一的重试策略。"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.ai.errors import AiErrorCategory, AiProviderError

type AttemptObserver = Callable[[int, bool], Awaitable[None]]

RETRYABLE_CATEGORIES = frozenset(
    {
        AiErrorCategory.RATE_LIMITED,
        AiErrorCategory.TIMEOUT,
        AiErrorCategory.NETWORK,
        AiErrorCategory.UNAVAILABLE,
        AiErrorCategory.INVALID_RESPONSE,
    }
)


@dataclass(frozen=True)
class AttemptResult[T]:
    """成功值及其从一开始计数的节点尝试次数。"""

    value: T
    attempt: int


@dataclass(frozen=True)
class RetryPolicy:
    """节点重试的唯一计数器，避免 Provider 与工作流嵌套放大请求次数。"""

    max_attempts: int = 3
    backoff_seconds: float = 0.1
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("最大尝试次数必须至少为 1")
        if self.backoff_seconds < 0:
            raise ValueError("退避时间不得小于 0")

    async def run[T](
        self,
        operation: Callable[[int], Awaitable[T]],
        *,
        on_attempt: AttemptObserver | None = None,
    ) -> AttemptResult[T]:
        for attempt in range(1, self.max_attempts + 1):
            if on_attempt is not None:
                # 尝试次数由唯一 RetryPolicy 产生，进度层不得自行推断或重新计数。
                await on_attempt(attempt, attempt > 1)
            try:
                return AttemptResult(value=await operation(attempt), attempt=attempt)
            except AiProviderError as error:
                if error.category not in RETRYABLE_CATEGORIES or attempt == self.max_attempts:
                    raise
                # 退避必须可取消；取消后不得悄悄开始下一次 Provider 请求。
                await self.sleep(self.backoff_seconds)
        raise RuntimeError("不可达的节点重试状态")
