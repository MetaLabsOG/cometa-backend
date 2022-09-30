import logging
from typing import List

from bot.db import users
from bot.db.model import CometaUser
from core.cometa import fetch_user_pools
from core.decorators import safe_async_method
from core.model import UserPool


logger = logging.getLogger(__name__)


@safe_async_method
async def update_user_pools(user: CometaUser) -> List[UserPool]:
    user_pools = await fetch_user_pools(user.algo_address)
    if user_pools:
        user.pools = {p.pool_id: p for p in user_pools}
        users.update_user(user)
    return user_pools


async def get_user_pools(user: CometaUser) -> List[UserPool]:
    if not user.pools:
        await update_user_pools(user)
    return list(user.pools.values())


def filter_ended_pools(pools: List[UserPool]) -> List[UserPool]:
    return list(filter(lambda p: p.is_ended(), pools))


def filter_compoundable_pools(pools: List[UserPool]) -> List[UserPool]:
    return list(filter(lambda p: p.needs_compound() and not p.is_ended(), pools))


def filter_no_action_pools(pools: List[UserPool]) -> List[UserPool]:
    return list(filter(lambda p: not p.needs_compound() and not p.is_ended(), pools))
