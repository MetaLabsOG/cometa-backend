import logging
import time

from telegram.constants import ParseMode

from bot.formatting import format_user_pool
from bot.user_pools import get_user_pools, filter_compoundable_pools, filter_ended_pools
from bot.context import app_context
from bot.db import users
from bot.db.model import CometaUser
from bot.phrase_manager import Phrases
from core.decorators import safe_async_method

logger = logging.getLogger(__name__)


@safe_async_method
async def notify_user(user: CometaUser):
    pools = await get_user_pools(user)

    text = f'🤖 <i>{Phrases.greet()}️</i>\n'

    compound_pools = filter_compoundable_pools(pools)
    if compound_pools:
        text += '\n\n✅ <b>Need compounding:</b>\n\n'
        text += '\n'.join([format_user_pool(pool) for pool in compound_pools])

    ended_pools = filter_ended_pools(pools)
    if ended_pools:
        text += '\n\n❌ <b>Need withdraw:</b>\n\n'
        text += '\n'.join([format_user_pool(pool) for pool in ended_pools])

    if ended_pools or compound_pools:
        text += '\n\n<i>It is the time.</i>\n\nhttps://app.cometa.farm/\n'

        # TODO: save all notifications to DB
        logger.debug(text)

        await app_context.bot.send_message(text=text, chat_id=user.telegram_id, parse_mode=ParseMode.HTML)

        user.last_reminded = int(time.time())
        users.update_user(user)
