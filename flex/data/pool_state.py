import asyncio
import logging

from core.db.contracts import get_contract
from core.db.model import ContractInfo
from flex import db
from flex.data.pools import get_pools_by_query
from flex.data.transactions import pool_fetch_new_transactions
from flex.db.model.blockchain import PoolTransaction
from flex.db.model.pool_states import PoolState, UserState, UserPoolState
from flex.db.model.pools import PoolType
from flex.meta_error import MetaError


logger = logging.getLogger(__name__)


def get_pool_type_from_contract(contract: ContractInfo) -> PoolType:
    if contract.type == 'distribution':
        return PoolType.STAKING
    if contract.type == 'farm' and 'dex' in contract.metadata:
        return PoolType.FARMING
    return PoolType.STAKING


async def create_pool_state_from_contract(contract: ContractInfo) -> PoolState:
    logging.info(f'Creating new pool state for contract {contract.id} - {contract.description}')

    pool_type = get_pool_type_from_contract(contract)
    if pool_type == PoolType.STAKING:
        pool = db.staking_pools.get_by_primary_key(contract.id)
    else:
        pool = db.farming_pools.get_by_primary_key(contract.id)
    pool_state = PoolState(
        pool_id=contract.id,
        type=get_pool_type_from_contract(contract),
        address=pool.address,
        stake_token=pool.stake_token
    )

    db.pool_states.create(pool_state)
    logger.info(f'Created new pool state: address = {pool_state.address}')
    return pool_state


async def get_or_create_from_contract(contract: ContractInfo) -> PoolState:
    pool_state = db.pool_states.get_one(pool_id=contract.id)
    if pool_state is None:
        pool_state = await create_pool_state_from_contract(contract)
    return pool_state


async def get_or_create_pool_state(pool_id: int) -> PoolState:
    pool_state = db.pool_states.get_one(pool_id=pool_id)
    if pool_state is None:
        contract_info = get_contract(pool_id)
        if contract_info is None:
            raise MetaError(f'Pool {pool_id} contract not found')
        pool_state = await create_pool_state_from_contract(contract_info)
    return pool_state


def get_user_state_pool(user_state: UserState, pool_state: PoolState) -> UserPoolState:
    user_pool_state = user_state.pool_by_address.get(pool_state.address)
    if user_pool_state is None:
        user_pool_state = UserPoolState(
            pool_id=pool_state.pool_id,
            stake_token=pool_state.stake_token
        )
        user_state.pool_by_address[pool_state.address] = user_pool_state
    return user_pool_state


async def apply_creation_tx(pool_state: PoolState, user_state: UserState, tx: PoolTransaction) -> PoolState:
    if tx.asa_id != pool_state.stake_token.id:
        logger.debug(f'Pool {pool_state.pool_id} is not distribution pool')
        return pool_state
    if pool_state.stake_amount_reduced_by_rewards:
        logger.debug(f'Pool {pool_state.pool_id} already reduced rewards from the stake calc')
        return pool_state

    logger.info(f'Applying creation txn for pool {pool_state.pool_id}: {pool_state.stake_token.name}')

    user_pool_state = get_user_state_pool(user_state, pool_state)
    user_pool_state.staked_amount_micros -= tx.delta_amount_micros
    if user_pool_state.staked_amount_micros == 0:
        del user_state.pool_by_address[pool_state.address]
    user_state.last_tx = tx.to_info()
    db.user_states.update(user_state)

    pool_state.total_staked_micros -= tx.delta_amount_micros
    pool_state.last_tx = tx.to_info()
    pool_state.stake_amount_reduced_by_rewards = True
    db.pool_states.update(pool_state)

    return pool_state


async def update_pool_states_with_transactions(
        transactions: list[PoolTransaction],
        pool_states: list[PoolState] | None = None,
        reset_pool_states: bool = False
) -> list[PoolState]:
    if len(transactions) == 0:
        return pool_states or []

    pool_state_by_id = {pool_state.pool_id: pool_state for pool_state in pool_states or []}

    # TODO: remove after migration DIRTY HACKS
    if reset_pool_states:
        all_user_addresses = {user_state.address for user_state in db.user_states.get_all()}
        tx_addresses = {tx.user_address for tx in transactions}
        new_addresses = tx_addresses - all_user_addresses
        new_user_states = [UserState(address=address) for address in new_addresses]
        created_user_states = db.user_states.create_many(new_user_states)
        logger.info(f'IN BATCH Created {len(created_user_states)} new user states.')

    for tx in transactions:
        if db.pool_transactions.exists(id=tx.id):
            logger.debug(f'Transaction {tx.id} already recorded in DB')
            continue

        user_state = await get_or_create_user_state(tx.user_address)
        pool_state = await get_or_create_pool_state(tx.pool_id)

        # initial tx with rewards
        if pool_state.last_tx is None:
            pool_state = await apply_creation_tx(pool_state, user_state, tx)

        pool_state.total_staked_micros += tx.delta_amount_micros
        new_staked_micros = pool_state.staked_micros_by_address.setdefault(tx.user_address, 0) + tx.delta_amount_micros
        pool_state.staked_micros_by_address[tx.user_address] = new_staked_micros
        if new_staked_micros == 0:
            # remove 0 stakes from storing
            del pool_state.staked_micros_by_address[tx.user_address]

        pool_state.last_tx = tx.to_info()
        db.pool_states.update(pool_state)

        pool_state_by_id[pool_state.pool_id] = pool_state

        user_pool_state = get_user_state_pool(user_state, pool_state)
        user_pool_state.staked_amount_micros += tx.delta_amount_micros
        user_pool_state.last_tx = tx.to_info()
        user_state.pool_by_address[pool_state.address] = user_pool_state

        if user_pool_state.staked_amount_micros == 0:
            del user_state.pool_by_address[pool_state.address]
        user_state.last_tx = tx.to_info()
        db.user_states.update(user_state)

        db.pool_transactions.create(tx)

    logger.info(f'Updated {len(pool_state_by_id)} pool states with {len(transactions)} transactions')

    return list(pool_state_by_id.values())


async def update_all_pool_states_linear(reset_pool_states: bool = False) -> list[PoolState]:
    if reset_pool_states:
        logger.info('Removing all pool states')
        db.pool_states.remove_all()
        db.user_states.remove_all()

    all_pools = await get_pools_by_query({})
    pool_states = db.pool_states.get_all()

    missing_cnt = len(all_pools) - len(pool_states)
    if missing_cnt > 0:
        pool_state_ids = {pool_state.pool_id for pool_state in pool_states}
        logger.info(f'Creating {missing_cnt} new pool states')
        ind = 1
        for pool in all_pools:
            if pool.id not in pool_state_ids:
                try:
                    logging.info(f'\n#{ind}/{missing_cnt} pool id = {pool.id} - {pool.description}\n')
                    pool_state = await get_or_create_pool_state(pool.id)
                    pool_states.append(pool_state)
                    ind += 1
                except Exception as e:
                    logger.error(f'Failed to create pool state {pool.id}: {e}', exc_info=True)

    logger.info(f'Updating {len(pool_states)} pool states')

    # ASYNC
    # ind = 1
    # update_pool_state_cors = []
    # for pool_state in pool_states:
    #     update_co = update_pool_state(pool_state, msg=f'\n{ind}/{len(pool_states)}')
    #     update_pool_state_cors.append(update_co)
    #     ind += 1
    #
    # updated_pool_states = await asyncio.gather(*update_pool_state_cors)

    # SYNC
    ind = 1
    updated_pool_states = []
    for pool_state in pool_states:
        try:
            logger.info(f'\n{ind}/{len(pool_states)} pool id = {pool_state.pool_id}\n')
            pool_state = await update_pool_state(pool_state, reset_pool_states=reset_pool_states)
            updated_pool_states.append(pool_state)
            ind += 1
        except Exception as e:
            logger.error(f'Failed to update pool state {pool_state.pool_id}: {e}', exc_info=True)

    logger.info(f'Fresh {len(updated_pool_states)} pool states!')
    return list(updated_pool_states)


async def update_pool_state(pool_state: PoolState, reset_pool_states: bool = False) -> PoolState:
    logger.debug(f'Updating pool state {pool_state.pool_id} {pool_state.stake_token.name}')

    if reset_pool_states:
        new_transactions = db.pool_transactions.get_many(pool_id=pool_state.pool_id)
        db.pool_transactions.remove_by(pool_id=pool_state.pool_id)
    else:
        new_transactions = await pool_fetch_new_transactions(pool_state)
    if len(new_transactions) == 0:
        logger.debug(f'No new transactions for pool {pool_state.pool_id}')
        return pool_state

    updated_pool_states = await update_pool_states_with_transactions(new_transactions, pool_states=[pool_state], reset_pool_states=reset_pool_states)
    return updated_pool_states[0]


async def update_pool_state_by_id(pool_id: int) -> PoolState:
    logger.debug(f'Updating pool state {pool_id}')
    pool_state = await get_or_create_pool_state(pool_id)
    return await update_pool_state(pool_state)


async def get_or_create_user_state(address: str) -> UserState:
    user_state = db.user_states.get_one(address=address)
    if user_state is None:
        user_state = db.user_states.create(UserState(address=address))
        logger.info(f'Created new user state: address = {user_state.address}')
    return user_state


async def update_user_state_by_address(address: str) -> UserState:
    logger.debug(f'Updating user state {address}')
    user_state = db.user_states.get_one(address=address)
    if user_state is None:
        raise MetaError(f'User with address {address} is not found')
    return await update_user_state(user_state)


async def update_user_state(user_state: UserState) -> UserState:
    for addr, user_pools_state in user_state.pool_by_address.items():
        _ = await update_pool_state_by_id(user_pools_state.pool_id)
    return db.user_states.get_one(address=user_state.address)
