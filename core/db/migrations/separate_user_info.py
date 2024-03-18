import logging
from datetime import datetime

from bot.db.model import BotUser
from core.db.contracts import get_all_pool_contracts, update_contract_with
from core.db.model import CometaUser
from core.db.mongodb import get_db_collection
from env import settings

logger = logging.getLogger(__name__)


def migrate_users():
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


def migrate_contract_dates():
    contracts = get_all_pool_contracts()
    for contract in contracts:
        print(f'Before:\n{contract.format_str()}\n')
        contract.begin_date = datetime.fromisoformat(contract.begin_date)
        contract.end_date = datetime.fromisoformat(contract.end_date)
        contract.metadata['begin_date'] = contract.begin_date
        contract.metadata['end_date'] = contract.end_date
        update_contract_with(contract.id, metadata=contract.metadata, begin_date=contract.begin_date, end_date=contract.end_date)
        print(f'After:\n{contract.format_str()}\n')
