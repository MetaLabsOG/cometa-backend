import asyncio
import logging

from core.decorators import safe_async_method


def test_safe_async_method_preserves_return_value_and_metadata() -> None:
    @safe_async_method
    async def calculate(value: int) -> int:
        """Return a deterministic result."""
        return value * 2

    assert asyncio.run(calculate(21)) == 42
    assert calculate.__name__ == "calculate"
    assert calculate.__doc__ == "Return a deterministic result."


def test_safe_async_method_logs_failure_and_returns_none(caplog) -> None:
    @safe_async_method
    async def fail() -> None:
        raise RuntimeError("provider unavailable")

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(fail())

    assert result is None
    assert "provider unavailable" in caplog.text
