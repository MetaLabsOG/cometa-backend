import logging

from flex import db


logger = logging.getLogger(__name__)


def remove_previous_data():
    removed_lp_states = db.pool_states.remove_all()
    logger.info(f'Removed {removed_lp_states} LP states')

    removed_user_states = db.user_states.remove_all()
    logger.info(f'Removed {removed_user_states} User states')

    removed_pool_transactions = db.pool_transactions.remove_all()
    logger.info(f'Removed {removed_pool_transactions} Pool transactions')
