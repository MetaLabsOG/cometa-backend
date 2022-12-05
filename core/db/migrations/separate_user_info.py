from bot.db.model import BotUser
from core.db.model import CometaUser
from core.db.mongodb import get_db_collection
from env import settings


def migrate():
    users = get_db_collection(settings.db_name, 'users')
    cometa_users = get_db_collection(settings.db_name, 'cometa_users')
    bot_users = get_db_collection(settings.db_name, 'bot_users')

    for user in users.find():
        cometa_users.insert_one(CometaUser(user.address, user.pools).to_dict())
        bot_users.insert_one(BotUser(user.address, user.telegram_id).to_dict())
