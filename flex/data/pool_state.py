import logging

from core.db.contracts import get_contract, get_all_pool_contracts
from core.db.model import ContractInfo
from flex import db
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
    if pool.stake_token.id == pool.reward_token.id:
        logger.info(f'Pool {contract.id} has same stake and reward token\n\nyo\n')
        # rewards and stakes are at the same address, we need only stakes
        pool_state.total_staked_micros = -pool.reward_amount_micros

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


async def update_pools_with_transactions(
        transactions: list[PoolTransaction],
        pool_states: list[PoolState] | None = None
) -> list[PoolState]:
    if len(transactions) == 0:
        return pool_states

    user_state_by_address = {}
    pool_state_by_id = {} if pool_states is None else {pool.pool_id: pool for pool in pool_states}
    for tx in transactions:
        if db.pool_transactions.exists(id=tx.id):
            logger.debug(f'Transaction {tx.id} already recorded in DB')
            continue

        pool_state = pool_state_by_id.get(tx.pool_id)
        if pool_state is None:
            pool_state = await get_or_create_pool_state(tx.pool_id)
            pool_state_by_id[tx.pool_id] = pool_state

        pool_state.total_staked_micros += tx.delta_amount_micros
        pool_state.last_tx = tx.to_info()
        pool_state.staked_micros_by_address[tx.user_address] = pool_state.staked_micros_by_address.get(tx.user_address, 0) + tx.delta_amount_micros

        user_state = user_state_by_address.get(tx.user_address)
        if user_state is None:
            user_state = db.user_states.get_one(address=tx.user_address)
            if user_state is None:
                user_state = db.user_states.create(UserState(address=tx.user_address))
                logger.debug(f'Created new user state: address = {user_state.address}')
            user_state_by_address[tx.user_address] = user_state

        user_pool_state = user_state.pool_by_address.get(pool_state.address)
        if user_pool_state is None:
            user_pool_state = UserPoolState(pool_id=pool_state.pool_id, stake_token=pool_state.stake_token)
            user_state.pool_by_address[pool_state.address] = user_pool_state

        user_pool_state.staked_amount_micros += tx.delta_amount_micros
        user_pool_state.last_tx = tx.to_info()
        user_state.last_tx = tx.to_info()

    for user_state in user_state_by_address.values():
        db.user_states.update(user_state)

    updated_pool_states = list(pool_state_by_id.values())
    for pool_state in updated_pool_states:
        db.pool_states.update(pool_state)

    db.pool_transactions.create_many(transactions)

    logger.info(f'Updated {len(pool_state_by_id)} pool states and {len(user_state_by_address)} user states with {len(transactions)} transactions')

    return updated_pool_states


async def update_all_pool_states() -> list[PoolState]:
    all_contracts = get_all_pool_contracts()
    logger.info(f'Updating {len(all_contracts)} pool states')

    new_transactions = []
    pool_states = []
    for contract in all_contracts:
        try:
            pool_state = await get_or_create_from_contract(contract)
            pool_transactions = await pool_fetch_new_transactions(pool_state)
            new_transactions.extend(pool_transactions)
            pool_states.append(pool_state)
        except Exception as e:
            logger.error(f'Failed to update pool state {contract.id}: {e}', exc_info=True)

    new_transactions = sorted(new_transactions, key=lambda tx: tx.confirmed_round)
    logger.info(f'Found {len(new_transactions)} new pool transactions')
    return await update_pools_with_transactions(new_transactions, pool_states)


async def update_all_pool_states_linear() -> list[PoolState]:
    pool_states = db.pool_states.get_all()
    logger.info(f'Updating {len(pool_states)} pool states')
    updated_pool_states = []
    ind = 1
    for pool_state in pool_states:
        try:
            logger.info(f'{ind}/{len(pool_states)} pool update = {pool_state.pool_id}')
            pool_state = await update_pool_state(pool_state)
            updated_pool_states.append(pool_state)
            ind += 1
        except Exception as e:
            logger.error(f'Failed to update pool state {pool_state.pool_id}: {e}', exc_info=True)

    logger.info(f'Fresh {len(updated_pool_states)} pool states!')
    return updated_pool_states


async def update_pool_state(pool_state: PoolState) -> PoolState:
    logger.debug(f'Updating pool state {pool_state.pool_id}')

    new_transactions = await pool_fetch_new_transactions(pool_state)
    if len(new_transactions) == 0:
        logger.debug(f'No new transactions for pool {pool_state.pool_id}')
        return pool_state

    updated_pool_states = await update_pools_with_transactions(new_transactions, pool_states=[pool_state])
    return updated_pool_states[0]


async def update_pool_state_by_id(pool_id: int) -> PoolState:
    logger.debug(f'Updating pool state {pool_id}')
    pool_state = await get_or_create_pool_state(pool_id)
    return await update_pool_state(pool_state)


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