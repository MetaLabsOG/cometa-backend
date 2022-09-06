from typing import Optional, List

from db.model import CometaUser, CometaEvent
from db.mongo import get_collection


collection = get_collection('users')


def create_user(algo_address: str, telegram_id: int, telegram_chat_id: int) -> CometaUser:
    user = CometaUser(algo_address, telegram_id, telegram_chat_id)
    collection.insert_one(user.to_dict())
    return user


def get_user(args: dict) -> Optional[CometaUser]:
    user = collection.find_one(args)
    return CometaUser.from_dict(user) if user is not None else None


def get_users(args: dict) -> List[CometaUser]:
    users = collection.find(args)
    return [CometaUser.from_dict(u) for u in users]


def get_user_by_address(address: str) -> CometaUser:
    return get_user({'algo_address': address})


def get_user_by_tg(tg_id: int) -> CometaUser:
    return get_user({'telegram_id': tg_id})


def update_user(user: CometaUser) -> CometaUser:
    collection.update_one({'telegram_id': user.telegram_id}, {'$set': user.to_dict()})
    return user


def update_user_event(user: CometaUser, event: CometaEvent) -> CometaUser:
    user.update(event)
    return update_user(user)
