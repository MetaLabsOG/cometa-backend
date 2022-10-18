import asyncio
import logging
import multiprocessing
from contextlib import contextmanager

from bot.db import users
from bot.env import bot_settings
from bot.notifier import notify_user
from bot.user_pools import update_user_pools
from core.decorators import repeat_every, safe_async_method

spawn = multiprocessing.get_context('spawn')
logger = logging.getLogger(__name__)


@safe_async_method
async def update_and_notify():
    all_users = users.get_users({})

    for user in all_users:
        await update_user_pools(user)
        if user.should_remind():
            await notify_user(user)


@repeat_every(bot_settings.user_pools_cache_ttl_seconds)
async def update_users():
    logger.info('Updating users...')

    await update_and_notify()


def run_background():
    async def tasks():
        await asyncio.gather(
            update_users()
        )

    asyncio.run(tasks())


@contextmanager
def start_bg_tasks():
    proc = spawn.Process(target=run_background)
    proc.start()
    logger.info(f'STARTED BG TASKS: {proc}')
    try:
        yield proc
    finally:
        proc.terminate()
        proc.join()

