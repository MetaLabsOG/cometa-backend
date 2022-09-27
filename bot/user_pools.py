import logging
from typing import List

from bot.db import users
from bot.db.model import CometaUser
from core.cometa import fetch_user_pools
from core.model import UserPool


logger = logging.getLogger(__name__)


async def update_user_pools(user: CometaUser) -> List[UserPool]:
    user_pools = await fetch_user_pools(user.algo_address)
    if user_pools:
        user.pools = {p.pool_id: p for p in user_pools}
        users.update_user(user)
    return user_pools


async def update_users_pools():
    all_users = users.get_users({})

    for user in all_users:
        try:
            await update_user_pools(user)
        except Exception as e:
            logger.error(f'Failed to update user {user.telegram_id} pools')
            logger.exception(e)


async def get_user_pools(user: CometaUser) -> List[UserPool]:
    if not user.pools:
        await update_user_pools(user)
    return list(user.pools.values())
