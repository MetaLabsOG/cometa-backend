import asyncio

import pytest

from core.util import with_exponential_backoff


class RetryableError(RuntimeError):
    pass


class PermanentError(RuntimeError):
    pass


def test_backoff_retries_only_explicit_retryable_errors(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async def eventually_succeeds() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RetryableError("temporary")
        return "ok"

    monkeypatch.setattr("core.util.asyncio.sleep", record_sleep)
    monkeypatch.setattr("core.util.random.uniform", lambda low, high: 1.0)

    result = asyncio.run(
        with_exponential_backoff(
            eventually_succeeds,
            max_retries=2,
            initial_delay=0.5,
            retry_on=(RetryableError,),
        ),
    )

    assert result == "ok"
    assert attempts == 3
    assert delays == [0.5, 1.0]


def test_backoff_does_not_retry_permanent_error() -> None:
    attempts = 0

    async def permanently_fails() -> None:
        nonlocal attempts
        attempts += 1
        raise PermanentError("invalid quote")

    with pytest.raises(PermanentError, match="invalid quote"):
        asyncio.run(
            with_exponential_backoff(
                permanently_fails,
                retry_on=(RetryableError,),
            ),
        )

    assert attempts == 1
