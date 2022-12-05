import asyncio
import logging
import multiprocessing
from contextlib import contextmanager

from bot.db.users import bot_users
from bot.env import bot_settings
from bot.notifier import notify_user, notify_user_new_pool
from core.db.new_pools import new_pools
from core.decorators import repeat_every, safe_async_method

spawn = multiprocessing.get_context('spawn')
logger = logging.getLogger(__name__)


@safe_async_method
async def notify_users():
    all_users = bot_users.get_all()

    for user in all_users:
        if user.should_remind():
            await notify_user(user)


@safe_async_method
async def notify_new_pools():
    pools = new_pools.get_all()
    if pools:
        all_users = bot_users.get_all()
        for pool in pools:
            for user in all_users:
                await notify_user_new_pool(user, pool)
            new_pools.remove(pool)
            logger.info(f'Notified users about new pool: {pool}')


@repeat_every(bot_settings.user_pools_cache_ttl_seconds)
async def notify_all():
    logger.info('Notifying...')

    await notify_users()
    await notify_new_pools()


def run_background():
    async def tasks():
        await asyncio.gather(
            notify_all()
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

