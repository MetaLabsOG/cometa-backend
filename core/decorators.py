import asyncio
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def safe_async_method(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            logger.error(
                'Error in `%s`: %s',
                fn.__qualname__,
                e,
                exc_info=True,
            )
    return wrapper


def repeat_every(seconds: int):
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            while True:
                await fn(*args, **kwargs)
                await asyncio.sleep(seconds)
        return wrapper
    return decorator
