import asyncio

import pytest

from app.ai.errors import AiErrorCategory, AiProviderError
from app.workflow.retry import RetryPolicy


def _error(category: AiErrorCategory) -> AiProviderError:
    return AiProviderError(category=category, message="测试失败", retryable=True)


async def test_retry_policy_returns_the_third_successful_attempt() -> None:
    attempts: list[int] = []

    async def operation(attempt: int) -> str:
        attempts.append(attempt)
        if attempt < 3:
            raise _error(AiErrorCategory.NETWORK)
        return "ok"

    result = await RetryPolicy(max_attempts=3, backoff_seconds=0).run(operation)

    assert result.value == "ok"
    assert result.attempt == 3
    assert attempts == [1, 2, 3]


async def test_retry_policy_reports_each_attempt_using_its_single_counter() -> None:
    observed: list[tuple[int, bool]] = []

    async def observe(attempt: int, retrying: bool) -> None:
        observed.append((attempt, retrying))

    async def operation(attempt: int) -> str:
        if attempt == 1:
            raise _error(AiErrorCategory.NETWORK)
        return "ok"

    result = await RetryPolicy(max_attempts=3, backoff_seconds=0).run(
        operation,
        on_attempt=observe,
    )

    assert result.attempt == 2
    assert observed == [(1, False), (2, True)]


async def test_retry_policy_exhausts_three_retryable_attempts() -> None:
    attempts: list[int] = []

    async def operation(attempt: int) -> str:
        attempts.append(attempt)
        raise _error(AiErrorCategory.INVALID_RESPONSE)

    with pytest.raises(AiProviderError) as captured:
        await RetryPolicy(max_attempts=3, backoff_seconds=0).run(operation)

    assert captured.value.category is AiErrorCategory.INVALID_RESPONSE
    assert attempts == [1, 2, 3]


async def test_retry_policy_does_not_retry_non_retryable_category() -> None:
    attempts: list[int] = []

    async def operation(attempt: int) -> str:
        attempts.append(attempt)
        raise _error(AiErrorCategory.AUTHENTICATION)

    with pytest.raises(AiProviderError) as captured:
        await RetryPolicy(max_attempts=3, backoff_seconds=0).run(operation)

    assert captured.value.category is AiErrorCategory.AUTHENTICATION
    assert attempts == [1]


async def test_cancellation_interrupts_retry_backoff() -> None:
    started = asyncio.Event()

    async def operation(_attempt: int) -> str:
        raise _error(AiErrorCategory.TIMEOUT)

    async def wait_forever(_delay: float) -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        RetryPolicy(max_attempts=3, backoff_seconds=1, sleep=wait_forever).run(operation)
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
