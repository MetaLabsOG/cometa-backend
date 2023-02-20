import logging

from bot.db.model import BotUser
from core.db.model import CometaUser
from core.db.mongodb import get_db_collection
from env import settings

logger = logging.getLogger(__name__)


def migrate():
    logger.info('Migrating users...')

    users = get_db_collection('COMETA_BOT', 'users')
    cometa_users = get_db_collection(settings.db_name, 'cometa_users')
    bot_users = get_db_collection(settings.db_name, 'bot_users')

    cnt = 0
    for user in users.find():
        cometa_users.insert_one(CometaUser(user['algo_address'], user['pools']).to_dict())
        bot_users.insert_one(BotUser(user['algo_address'], user['telegram_id']).to_dict())
        cnt += 1

    logger.info(f'Migrated {cnt} users')
