import logging
from typing import List

from core.cometa import fetch_user_pools
from core.db.db_manager import DbManager
from core.db.model import UserPool, CometaUser
from core.decorators import safe_async_method
from env import settings

logger = logging.getLogger(__name__)

cometa_users = DbManager[CometaUser](settings.db_name, 'cometa_users', 'address', CometaUser)


@safe_async_method
async def update_user_pools(user: CometaUser) -> list[UserPool]:
    user_pools = await fetch_user_pools(user.address)
    if user_pools:
        user.pools = user_pools
        cometa_users.update(user)
    return user_pools


async def get_user_pools(user: CometaUser) -> list[UserPool]:
    if not user.pools:
        await update_user_pools(user)
    return user.pools


async def get_address_pools(address: str) -> list[UserPool]:
    user = cometa_users.get_by_primary_key(address)
    if not user:
        pools = await fetch_user_pools(address)
        if pools:
            cometa_users.create(CometaUser(address=address, pools=pools))
        return pools
    return user.pools


def filter_ended_pools(pools: List[UserPool]) -> list[UserPool]:
    return list(filter(lambda p: p.is_ended(), pools))


def filter_compoundable_pools(pools: List[UserPool]) -> list[UserPool]:
    return list(filter(lambda p: p.needs_compound() and not p.is_ended(), pools))


def filter_no_action_pools(pools: List[UserPool]) -> list[UserPool]:
    return list(filter(lambda p: not p.needs_compound() and not p.is_ended(), pools))
