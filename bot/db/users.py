from typing import Optional

from bot.db.model import BotUser
from core.db.db_manager import DbManager
from env import settings

bot_users = DbManager[BotUser](settings.db_name, 'bot_users', 'telegram_id', BotUser)


def create_user(algo_address: str, telegram_id: int) -> BotUser:
    user = BotUser(algo_address, telegram_id)
    return bot_users.create(user)


def get_user(args: dict) -> Optional[BotUser]:
    return bot_users.get_one(args)


def get_user_by_address(address: str) -> BotUser:
    return get_user({'algo_address': address})


def get_user_by_tg(tg_id: int) -> BotUser:
    return get_user({'telegram_id': tg_id})


def update_user(user: BotUser) -> BotUser:
    return bot_users.update(user)
