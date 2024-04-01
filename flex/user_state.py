import logging

from flex import db
from flex.db.model import UserState, UserPoolState

logger = logging.getLogger(__name__)


def update_user_state(user_address: str) -> UserState:
    logger.debug(f'Updating user state for address {user_address}')

    user_state = db.user_states.get_one(address=user_address)
    if user_state is None:
        user_state = UserState(address=user_address)
        db.user_states.create(user_state)
        logger.debug(f'Created new user state:\n{user_state.pretty_str()}')


    new_transactions = []

    if len(new_transactions) > 0:
        db.pool_transactions.create_many(new_transactions)
        logger.debug(f'User {user_address}: saved {len(new_transactions)} new txns')

        for tx in new_transactions:
            pool_state = next((pool for pool in user_state.pools if pool.pool_id == tx.pool_id), None)
            if pool_state is None:
                stake_token = db.get_asset_info(tx.asa_id)
                pool_state = UserPoolState(pool_id=tx.pool_id, stake_token=stake_token)
                user_state.pools.append(pool_state)

            pool_state.staked_amount_micros += tx.delta_amount_micros
            pool_state.last_tx = tx.to_info()

            user_state.last_tx = tx.to_info()

        db.user_states.update(user_state)

    return user_state
