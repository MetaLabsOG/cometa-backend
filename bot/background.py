import asyncio
import logging
import multiprocessing
from contextlib import contextmanager

from bot.notifier import notify_all
from bot.user_pools import update_users_pools
from core.decorators import repeat_every

spawn = multiprocessing.get_context('spawn')
logger = logging.getLogger(__name__)


@repeat_every(60)  # once in a minute
async def update_users():
    logger.info('Updating users...')

    await update_users_pools()
    await notify_all()


# TODO: graceful shutdown here (with signal handling?)
def run_background():
    async def tasks():
        await asyncio.gather(
            update_users()
        )

    logger.info('Started background tasks')
    asyncio.run(tasks())


@contextmanager
def start_bg_tasks():
    proc = spawn.Process(target=run_background)
    proc.start()
    logger.info("STARTED BG TASKS", proc)
    try:
        yield proc
    finally:
        proc.terminate()
        proc.join()

