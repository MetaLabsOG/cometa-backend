import logging
import time

from telegram.constants import ParseMode

from bot.formatting import format_user_pool
from bot.user_pools import get_user_pools
from bot.context import app_context
from bot.db import users
from bot.db.model import CometaUser
from bot.phrase_manager import Phrases
from core.decorators import safe_async_method

logger = logging.getLogger(__name__)


@safe_async_method
async def notify_user(user: CometaUser):
    pools = await get_user_pools(user)

    text = f'{Phrases.greet()}️\n\n'

    ended_pools = list(filter(lambda p: p.ended_duration is not None, pools))
    if ended_pools:
        text += f'You still have stake/reward in <b>{len(ended_pools)} ended</b> pools!\n\n'
        for pool in ended_pools:  # TODO: use join
            text += format_user_pool(pool)
            text += '\n'

    live_pools = list(filter(lambda p: p.ended_duration is None, pools))
    compound_pools = []
    for pool in live_pools:
        percent = pool.reward_usd / pool.staked_usd * 100
        if percent > 1:  # TODO: user setting
            compound_pools.append((pool, percent))

    if compound_pools:
        text += f'What about some compounding?😏\n\n'
        for pool, percent in compound_pools:  # TODO: use join
            text += format_user_pool(pool)
            text += '\n'

    if ended_pools or compound_pools:
        text += 'It is the time.\nhttps://app.cometa.farm/\n'

        # TODO: save all notifications to DB
        logger.debug(text)

        await app_context.bot.send_message(text=text, chat_id=user.telegram_id, parse_mode=ParseMode.HTML)

    user.last_reminded = int(time.time())
    users.update_user(user)
