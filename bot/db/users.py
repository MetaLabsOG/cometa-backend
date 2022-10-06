from typing import Optional, List

from bot.db.db_manager import DbManager
from bot.db.model import CometaUser
from bot.db.mongo import get_collection


collection = get_collection('users')

user_manager = DbManager[CometaUser]('users', 'telegram_id', CometaUser)


def create_user(algo_address: str, telegram_id: int, telegram_chat_id: int) -> CometaUser:
    user = CometaUser(algo_address, telegram_id, telegram_chat_id)
    return user_manager.create(user)


def get_user(args: dict) -> Optional[CometaUser]:
    return user_manager.get_one(args)


def get_users(args: dict) -> List[CometaUser]:
    return user_manager.get_many(args)


def get_user_by_address(address: str) -> CometaUser:
    return get_user({'algo_address': address})


def get_user_by_tg(tg_id: int) -> CometaUser:
    return get_user({'telegram_id': tg_id})


def update_user(user: CometaUser) -> CometaUser:
    return user_manager.update(user)
