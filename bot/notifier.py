import logging
import time

from telegram.constants import ParseMode

from bot.context import app_context
from bot.db.model import BotUser
from bot.db.users import bot_users
from bot.formatting import format_user_pool
from bot.phrase_manager import Phrases
from core.db.cometa_users import filter_compoundable_pools, filter_ended_pools, get_address_pools
from core.db.new_pools import NewPoolInfo
from core.decorators import safe_async_method

logger = logging.getLogger(__name__)


@safe_async_method
async def notify_user(user: BotUser):
    pools = await get_address_pools(user.algo_address)

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
        bot_users.update(user)


@safe_async_method
async def notify_user_new_pool(user: BotUser, pool: NewPoolInfo):
    text = f'🤖 <i>{Phrases.greet()}️</i>\n\n'
    text += f'🎉 Good news! New {pool.type} pool has started on Cometa!\n\n'
    text += f'<b>{pool.name}</b>\n\n'
    text += f'<i>Be one of the first to grab juicy APR</i>😏\n\n'
    text += 'https://app.cometa.farm/'

    await app_context.bot.send_message(text=text, chat_id=user.telegram_id, parse_mode=ParseMode.HTML)
