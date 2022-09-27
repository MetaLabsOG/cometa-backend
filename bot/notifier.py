import logging
import time

from telegram.constants import ParseMode

from bot.user_pools import get_user_pools
from bot.context import app_context
from bot.db import users
from bot.db.model import CometaUser
from bot.phrase_manager import Phrases
from bot.utils import seconds_format, usd_format
from core.decorators import safe_async_method

logger = logging.getLogger(__name__)


async def notify_user(user: CometaUser):
    pools = await get_user_pools(user)

    text = f'{Phrases.greet()}️\n\n'

    ended_pools = list(filter(lambda p: p.ended_duration is not None, pools))
    if ended_pools:
        text += f'You still have stake/reward in <b>{len(ended_pools)} ended</b> pools!\n\n'
        for pool in ended_pools:
            text += f'❌<b>{pool.name}</b>\n' \
                    f'Staked = ${usd_format(pool.staked_usd)}, rewards = ${usd_format(pool.reward_usd)}\n' \
                    f'<i>It ended {seconds_format(pool.ended_duration)} ago :(</i>\n\n'

    live_pools = list(filter(lambda p: p.ended_duration is None, pools))
    compound_pools = []
    for pool in live_pools:
        percent = pool.reward_usd / pool.staked_usd
        if percent > 0.01:  # TODO: user setting
            compound_pools.append((pool, percent))

    if compound_pools:
        text += f'What about some compounding?😏\n\n'
        for pool, percent in compound_pools:
            text += f'✅<b>{pool.name}, {usd_format(pool.current_apr)}% APR.</b>\n' \
                    f'Staked = ${usd_format(pool.staked_usd)}, rewards = ${usd_format(pool.reward_usd)}\n' \
                    f'<i>You\'ve already farmed {usd_format(percent * 100)}% from your stake! Good time for compounding!</i>\n\n'

    if ended_pools or compound_pools:
        text += 'It is the time.\nhttps://app.cometa.farm/\n\n'
        text += '<i>(really soon I will be showing your APY ;)</i>'

        # TODO: save all notifications to DB
        logger.debug(text)

        await app_context.bot.send_message(text=text, chat_id=user.telegram_id, parse_mode=ParseMode.HTML)

    user.last_reminded = int(time.time())
    users.update_user(user)


@safe_async_method
async def notify_all():
    all_users = users.get_users({})

    for user in all_users:
        if user.should_remind():
            try:
                await notify_user(user)
            except Exception as e:
                logger.error(f'Failed to notify user {user.telegram_id}')
                logger.exception(e)
