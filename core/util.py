import json
import random
import asyncio
import logging
from datetime import datetime
from typing import Any, Optional, Callable

from env import settings

MINUTE_SECONDS = 60
HOUR_SECONDS = 60 * MINUTE_SECONDS
DAY_SECONDS = 24 * HOUR_SECONDS
YEAR_SECONDS = 365 * DAY_SECONDS

BLOCK_TIME = 3.7
BLOCKS_IN_A_YEAR = YEAR_SECONDS / BLOCK_TIME


def pretty(json_smth) -> str:
    return json.dumps(json_smth, indent=4)


def get_second_arg(*args, **kwargs):
    return args[1]


def parse_bignum(obj: dict) -> int:
    assert 'type' in obj and 'hex' in obj and obj['type'] == 'BigNumber'
    return int(obj['hex'], 16)


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
    if version[0] == '^':
        return version[1:]
    return version


async def with_exponential_backoff(func, *args, max_retries=3, initial_delay=1, 
                                  backoff_factor=2, **kwargs):
    """Execute function with exponential backoff on failure
    
    Args:
        func: The async function to call
        *args: Arguments to pass to func
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay after each failed attempt
        **kwargs: Keyword arguments to pass to func
        
    Returns:
        The return value of the function
        
    Raises:
        Exception: The last exception encountered after max_retries
    """
    delay = initial_delay
    last_exception = None
    
    for retry in range(max_retries + 1):  # +1 for initial attempt
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            if retry >= max_retries:
                # We've exhausted our retries
                raise
            
            # Add jitter to prevent thundering herd
            jitter = random.uniform(0.75, 1.25)
            actual_delay = delay * jitter
            
            logging.warning(
                f"Error: {e}. Retrying in {actual_delay:.2f}s "
                f"(attempt {retry+1}/{max_retries})"
            )
            
            await asyncio.sleep(actual_delay)
            delay *= backoff_factor  # Increase delay
