import logging

from core.db.contracts import get_contract, get_all_pool_contracts
from core.db.model import ContractInfo
from core.util import parse_bignum
from flex import db
from flex.blockchain import get_asset_info
from flex.db.model import PoolState, UserState, UserPoolState, PoolTransaction
from flex.db.util import dict_get_nested_field
from flex.meta_error import MetaError
from flex.pools import get_pool_address, pool_fetch_new_transactions


logger = logging.getLogger(__name__)


async def create_pool_state_from_contract(contract: ContractInfo) -> PoolState:
    pool_address = get_pool_address(contract.id)
    if pool_address is None:
        raise MetaError(f'Pool {contract.id} address not found')

    stake_token_id = contract.metadata['stake_token_id']

    total_rewards_micros = contract.metadata.get('total_rewards_micros')
    if total_rewards_micros is None:
        total_rewards_encoded = dict_get_nested_field(contract.metadata, 'cache', 'initial', 'totalRewardsMicros')
        total_rewards_micros = parse_bignum(total_rewards_encoded) if total_rewards_encoded is not None else 0

    pool_state = PoolState(
        pool_id=contract.id,
        address=pool_address,
        stake_token=get_asset_info(stake_token_id),
        total_staked_micros=-total_rewards_micros,  # Rewards in transactions. TODO: calculate this when process transactions
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


async def update_pools_with_transactions(
        transactions: list[PoolTransaction],
        pool_states: list[PoolState] | None = None
) -> list[PoolState]:
    if len(transactions) == 0:
        return pool_states

    db.pool_transactions.create_many(transactions)
    logger.debug(f'Saved {len(transactions)} transactions to DB')

    user_state_by_address = {}
    pool_state_by_id = {} if pool_states is None else {pool.pool_id: pool for pool in pool_states}
    for tx in transactions:
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

    updated_pool_states = list(pool_state_by_id.values())
    for user_state in user_state_by_address.values():
        db.user_states.update(user_state)
    for pool_state in updated_pool_states:
        db.pool_states.update(pool_state)

    logger.info(f'Updated {len(updated_pool_states)} pool states')
    return updated_pool_states


async def update_all_pool_states() -> list[PoolState]:
    all_contracts = get_all_pool_contracts()
    logger.info(f'Updating {len(all_contracts)} pool states')

    new_transactions = []
    pool_states = []
    for contract in all_contracts:
        pool_state = await get_or_create_from_contract(contract)
        pool_transactions = await pool_fetch_new_transactions(pool_state)
        new_transactions.extend(pool_transactions)
        pool_states.append(pool_state)

    new_transactions = sorted(new_transactions, key=lambda tx: tx.confirmed_round)
    logger.info(f'Found {len(new_transactions)} new pool transactions')
    return await update_pools_with_transactions(new_transactions, pool_states)


async def update_pool_state(pool_id: int) -> PoolState:
    logger.debug(f'Updating pool state {pool_id}')

    pool_state = await get_or_create_pool_state(pool_id)
    new_transactions = await pool_fetch_new_transactions(pool_state)
    if len(new_transactions) == 0:
        logger.debug(f'No new transactions for pool {pool_id}')
        return pool_state

    updated_pool_states = await update_pools_with_transactions(new_transactions, pool_states=[pool_state])
    return updated_pool_states[0]


async def update_user_state(address: str) -> UserState | None:
    logger.debug(f'Updating user state {address}')
    _ = await update_all_pool_states()

    user_state = db.user_states.get_one(address=address)
    return user_state
