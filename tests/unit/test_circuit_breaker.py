import asyncio
from dataclasses import dataclass

import pytest

from core.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


@dataclass
class ManualClock:
    current: float = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def test_failure_threshold_opens_circuit_and_subsequent_call_fails_fast() -> None:
    async def scenario() -> None:
        clock = ManualClock(100.0)
        breaker = CircuitBreaker(
            name="prices",
            failure_threshold=2,
            recovery_timeout=10,
            clock=clock,
        )
        attempts = 0

        async def fail() -> None:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("provider unavailable")

        with pytest.raises(RuntimeError, match="provider unavailable"):
            await breaker.execute(fail)
        assert breaker.state is CircuitState.CLOSED
        assert breaker.failure_count == 1

        with pytest.raises(RuntimeError, match="provider unavailable"):
            await breaker.execute(fail)
        assert breaker.state is CircuitState.OPEN
        assert breaker.failure_count == 2

        with pytest.raises(CircuitOpenError) as exc_info:
            await breaker.execute(fail)

        assert attempts == 2
        assert exc_info.value.retry_after == 10

    asyncio.run(scenario())


def test_only_one_half_open_probe_can_run_and_success_closes_circuit() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            name="vestige",
            failure_threshold=1,
            recovery_timeout=5,
            clock=clock,
        )

        async def fail() -> None:
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await breaker.execute(fail)
        clock.advance(5)

        probe_started = asyncio.Event()
        release_probe = asyncio.Event()
        probe_calls = 0

        async def probe() -> str:
            nonlocal probe_calls
            probe_calls += 1
            probe_started.set()
            await release_probe.wait()
            return "recovered"

        first_probe = asyncio.create_task(breaker.execute(probe))
        await probe_started.wait()

        with pytest.raises(CircuitOpenError) as exc_info:
            await breaker.execute(probe)

        assert exc_info.value.retry_after == 0
        assert probe_calls == 1
        assert breaker.state is CircuitState.HALF_OPEN

        release_probe.set()
        assert await first_probe == "recovered"
        assert breaker.state is CircuitState.CLOSED
        assert breaker.failure_count == 0

    asyncio.run(scenario())


def test_cancelled_half_open_probe_releases_slot_without_counting_failure() -> None:
    async def scenario() -> None:
        clock = ManualClock(50)
        breaker = CircuitBreaker(
            name="algod",
            failure_threshold=1,
            recovery_timeout=3,
            clock=clock,
        )

        async def fail() -> None:
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await breaker.execute(fail)
        clock.advance(3)

        probe_started = asyncio.Event()
        wait_forever = asyncio.Event()

        async def cancelled_probe() -> None:
            probe_started.set()
            await wait_forever.wait()

        task = asyncio.create_task(breaker.execute(cancelled_probe))
        await probe_started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert breaker.state is CircuitState.OPEN
        assert breaker.failure_count == 1

        async def recovered() -> str:
            return "ok"

        assert await breaker.execute(recovered) == "ok"
        assert breaker.state is CircuitState.CLOSED
        assert breaker.failure_count == 0

    asyncio.run(scenario())


def test_non_retryable_error_does_not_count_toward_failure_threshold() -> None:
    async def scenario() -> None:
        breaker = CircuitBreaker(
            name="prices",
            failure_threshold=1,
        )

        async def invalid_quote() -> None:
            raise ValueError("permanent invalid data")

        with pytest.raises(ValueError, match="invalid data"):
            await breaker.execute(
                invalid_quote,
                record_failure=lambda exc: not isinstance(exc, ValueError),
            )

        assert breaker.state is CircuitState.CLOSED
        assert breaker.failure_count == 0

    asyncio.run(scenario())
