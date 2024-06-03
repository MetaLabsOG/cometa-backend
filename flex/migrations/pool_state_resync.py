import logging

from flex import db
from flex.data.pool_state import apply_creation_tx, get_or_create_user_state
from flex.data.pools import get_all_pools

logger = logging.getLogger(__name__)


def remove_previous_pool_states():
    removed_pool_states = db.pool_states.remove_all()
    logger.info(f'Removed {removed_pool_states} LP states')

    removed_user_states = db.user_states.remove_all()
    logger.info(f'Removed {removed_user_states} User states')

    removed_pool_transactions = db.pool_transactions.remove_all()
    logger.info(f'Removed {removed_pool_transactions} Pool transactions')


async def apply_creation_txns():
    logger.info('Applying creation txns...')

    pool_states = db.pool_states.get_all()
    logger.info(f'Found {len(pool_states)} pool states')

    all_pools = await get_all_pools()
    pool_info_by_id = {pool.id: pool for pool in all_pools}

    updated_pool_states = []
    for pool_state in pool_states:
        try:
            pool_info = pool_info_by_id.get(pool_state.pool_id)
            if pool_info is None:
                logger.error(f'Pool {pool_state.pool_id} not found')
                continue

            if pool_info.reward_token.id != pool_state.stake_token.id:
                logger.debug(f'Pool {pool_state.pool_id} is not distribution pool')
                continue

            pool_state = db.pool_states.get_one(pool_id=pool_state.pool_id)
            if pool_state.stake_amount_reduced_by_rewards:
                logger.info(f'Already reduced the rewards {pool_state.pool_id}')
                continue

            pool_txns = db.pool_transactions.get_many_by_query(query_dict={'pool_id': pool_state.pool_id}, limit=1)
            if not pool_txns:
                logger.error(f'Pool {pool_state.pool_id} not found')
                continue

            pool_txn = pool_txns[0]

            logger.info(f'Applying creation txn for pool {pool_state.pool_id} — {pool_state.stake_token.name}: {pool_txn}')

            user_state = await get_or_create_user_state(pool_txn.user_address)
            pool_state = await apply_creation_tx(pool_state, user_state, pool_txn)
            db.pool_states.update(pool_state)
            updated_pool_states.append(pool_state)
        except Exception as e:
            logger.error(f'Failed to apply creation txn for pool {pool_state.pool_id}: {e}', exc_info=True)

    logger.info(f'Updated {len(updated_pool_states)} pool states')

    return updated_pool_states
