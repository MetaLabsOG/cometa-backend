import asyncio
import logging
import time
from datetime import datetime
from threading import Thread

from telegram.constants import ParseMode

from bot.cometa import get_user_pools
from bot.context import app_context
from bot.db import users
from bot.db.model import PoolInfo, CometaUser
from bot.env import MONITOR_LOG_DELAY
from bot.phrase_manager import Phrases
from bot.utils import td_format, seconds_format

logger = logging.getLogger(__name__)


def pool_info(info: PoolInfo):
    # TODO: calculate pool APY and show
    return f'<b>{info.name}</b> was claimed <b>{td_format(info.no_interact_for)}</b> ago :(\n' \
           f'<i>You could be so rich...</i>\nAnd you still may be! Just compound ;)'


async def notify_user(user: CometaUser):
    pools = await get_user_pools(user.algo_address)

    text = f'{Phrases.greet()}️\n\n'

    ended_pools = list(filter(lambda p: p.ended_duration is not None, pools))
    if ended_pools:
        text += f'You still have stake in {len(ended_pools)} pools!\n\n'
        for pool in ended_pools:
            text += f'<b>{pool.name}</b>\n' \
                    f'Staked = ${pool.staked_usd}, rewards = ?\n' \
                    f'<i>It ended {seconds_format(pool.ended_duration)} ago :(</i>\n\n'

    live_pools = list(filter(lambda p: p.ended_duration is None, pools))

    if live_pools:
        text += f'What about some compounding?😏\n'
        text += '\n'

    if ended_pools or live_pools:
        text += 'It is the time.\nhttps://app.cometa.farm/\n\n'
        text += '<i>(really soon I will be showing your APY ;)</i>'

        # TODO: save all notifications to DB
        logger.debug(text)

        await app_context.bot.send_message(text=text, chat_id=user.telegram_id, parse_mode=ParseMode.HTML)

    user.last_reminded = int(time.time())
    users.update_user(user)


async def monitor_and_notify_all():
    iterations = 0
    prev_log_time = datetime.utcnow()
    while True:
        all_users = users.get_users({})

        for user in all_users:
            if not user.should_remind():
                continue

            await notify_user(user)

        iterations += 1
        time.sleep(1)

        now = datetime.utcnow()
        if now - prev_log_time > MONITOR_LOG_DELAY:
            logger.debug(f'Monitoring all the time. {iterations} iterations since start.')
            prev_log_time = now


def schedule_notifications():
    # TODO: use executor
    daemon = Thread(target=asyncio.run, args=(monitor_and_notify_all(),), daemon=True, name='Notifier')
    daemon.start()
