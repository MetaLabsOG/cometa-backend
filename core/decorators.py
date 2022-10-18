import asyncio
import logging


def safe_async_method(fn):
    async def wrapper(*args, **kwargs):
        try:
            await fn(*args, **kwargs)
        except Exception as e:
            # TODO: 'TypeError: not all arguments converted during string formatting'
            # logging.error(f'Error in `{fn.__name__}(*{args}, **{kwargs})`: ', e)

            logging.error(f'Error in `{fn.__name__}: ', e)
    return wrapper


def repeat_every(seconds: int):
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            while True:
                await fn(*args, **kwargs)
                await asyncio.sleep(seconds)
        return wrapper
    return decorator
