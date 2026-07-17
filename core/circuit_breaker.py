"""Process-local async circuit breaker with deterministic recovery probes."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a dependency is unavailable and calls must fail fast."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = max(0.0, retry_after)
        super().__init__(f"Circuit '{name}' is open; retry after {self.retry_after:.1f}s")


@dataclass(slots=True)
class CircuitBreaker:
    """Protect one process from repeatedly calling a failing dependency."""

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    clock: Callable[[], float] = field(default=monotonic, repr=False)
    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    failure_count: int = field(default=0, init=False)
    last_failure_time: float | None = field(default=None, init=False)
    _probe_in_flight: bool = field(default=False, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("circuit breaker name must not be empty")
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if self.recovery_timeout < 0:
            raise ValueError("recovery_timeout must be non-negative")

    async def execute[T](
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        record_failure: Callable[[Exception], bool] | None = None,
        **kwargs: Any,
    ) -> T:
        await self._before_call()
        try:
            result = await func(*args, **kwargs)
        except asyncio.CancelledError:
            await self._record_cancellation()
            raise
        except Exception as exc:
            if record_failure is None or record_failure(exc):
                await self._record_failure()
            else:
                await self._record_success()
            raise
        await self._record_success()
        return result

    async def _before_call(self) -> None:
        async with self._lock:
            now = self.clock()
            if self.state is CircuitState.OPEN:
                retry_after = self._retry_after(now)
                if retry_after > 0:
                    raise CircuitOpenError(self.name, retry_after)
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit '%s' state: open -> half_open", self.name)

            if self.state is CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    raise CircuitOpenError(self.name, 0)
                self._probe_in_flight = True

    def _retry_after(self, now: float) -> float:
        if self.last_failure_time is None:
            return self.recovery_timeout
        elapsed = max(0.0, now - self.last_failure_time)
        return max(0.0, self.recovery_timeout - elapsed)

    async def _record_success(self) -> None:
        async with self._lock:
            self.failure_count = 0
            if self.state is CircuitState.HALF_OPEN:
                logger.info("Circuit '%s' state: half_open -> closed", self.name)
                self.state = CircuitState.CLOSED
            self._probe_in_flight = False

    async def _record_failure(self) -> None:
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = self.clock()
            should_open = self.state is CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold
            if should_open:
                if self.state is not CircuitState.OPEN:
                    logger.warning("Circuit '%s' state: %s -> open", self.name, self.state)
                self.state = CircuitState.OPEN
            self._probe_in_flight = False

    async def _record_cancellation(self) -> None:
        async with self._lock:
            if self.state is CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
            self._probe_in_flight = False


_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """Return the process-local circuit breaker registered for ``name``."""

    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    return _circuit_breakers[name]
