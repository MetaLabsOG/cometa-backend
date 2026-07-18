import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Optional, TypeVar

from env import settings

MINUTE_SECONDS = 60
HOUR_SECONDS = 60 * MINUTE_SECONDS
DAY_SECONDS = 24 * HOUR_SECONDS
YEAR_SECONDS = 365 * DAY_SECONDS

BLOCKS_IN_A_YEAR = YEAR_SECONDS / settings.block_time
T = TypeVar("T")


def pretty(json_smth) -> str:
    return json.dumps(json_smth, indent=4)


def get_second_arg(*args, **kwargs):
    return args[1]


def parse_bignum(obj) -> int:
    if obj is None:
        return 0
    if isinstance(obj, str):
        return int(obj, 16) if obj.startswith("0x") else int(obj)
    if isinstance(obj, int):
        return obj
    if isinstance(obj, dict) and obj.get("type") == "BigNumber" and "hex" in obj:
        return int(obj["hex"], 16)
    raise ValueError(f"Cannot parse as BigNumber: {obj!r}")


def parse_datetime(date_obj: Any) -> Optional[datetime]:
    if date_obj is None:
        return None
    if isinstance(date_obj, datetime):
        return date_obj
    if isinstance(date_obj, str):
        return datetime.fromisoformat(date_obj)
    if isinstance(date_obj, int):
        return datetime.fromtimestamp(date_obj)
    return None


def blocks_to_seconds(start_block: int, last_block: int) -> float:
    assert last_block >= start_block
    return (last_block - start_block + 1) / settings.block_time


def strip_version(version: str) -> str:
    return version.removeprefix("^")


async def with_exponential_backoff(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    initial_delay: float = 1,
    backoff_factor: float = 2,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """Execute an async function with jittered exponential backoff.

    Args:
        func: The async function to call
        *args: Arguments to pass to func
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay after each failed attempt
        retry_on: Explicit exception types that are safe to retry
        **kwargs: Keyword arguments to pass to func

    Returns:
        The return value of the function

    Raises:
        Exception: The last exception encountered after max_retries
    """
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    if initial_delay < 0:
        raise ValueError("initial_delay must be non-negative")
    if backoff_factor < 1:
        raise ValueError("backoff_factor must be at least 1")
    if not retry_on:
        raise ValueError("retry_on must not be empty")

    delay = initial_delay

    for retry in range(max_retries + 1):  # +1 for initial attempt
        try:
            return await func(*args, **kwargs)
        except retry_on as e:
            if retry >= max_retries:
                # We've exhausted our retries
                raise

            # Add jitter to prevent thundering herd
            jitter = random.uniform(0.75, 1.25)
            actual_delay = delay * jitter

            logging.warning(f"Error: {e}. Retrying in {actual_delay:.2f}s (attempt {retry + 1}/{max_retries})")

            await asyncio.sleep(actual_delay)
            delay *= backoff_factor  # Increase delay
