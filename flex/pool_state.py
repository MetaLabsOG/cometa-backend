import logging

from core.db.contracts import get_contract, get_all_pool_contracts
from core.db.model import ContractInfo
from flex import db
from flex.blockchain import get_asset_info
from flex.db.model import PoolState, UserState, UserPoolState, PoolTransaction
from flex.meta_error import MetaError
from flex.pools import get_pool_address, pool_fetch_new_transactions


logger = logging.getLogger(__name__)


def create_pool_state_from_contract(contract: ContractInfo) -> PoolState:
    pool_address = get_pool_address(contract.id)
    if pool_address is None:
        raise MetaError(f'Pool {contract.id} address not found')

    stake_token_id = contract.metadata['stake_token_id']
    pool_state = PoolState(
        pool_id=contract.id,
        address=pool_address,
        stake_token=get_asset_info(stake_token_id)
    )
    db.pool_states.create(pool_state)
    logger.debug(f'Created new pool state:\n{pool_state.pretty_str()}')
    return pool_state


def get_or_create_from_contract(contract: ContractInfo) -> PoolState:
    pool_state = db.pool_states.get_one(pool_id=contract.id)
    if pool_state is None:
        pool_state = create_pool_state_from_contract(contract)
    return pool_state


def get_or_create_pool_state(pool_id: int) -> PoolState:
    pool_state = db.pool_states.get_one(pool_id=pool_id)
    if pool_state is None:
        contract_info = get_contract(pool_id)
        if contract_info is None:
            raise MetaError(f'Pool {pool_id} contract not found')
        pool_state = create_pool_state_from_contract(contract_info)
    return pool_state


# TODO: optimize and provide pooL-states
def process_transactions(transactions: list[PoolTransaction]) -> list[PoolState]:
    if len(transactions) == 0:
        return []

    db.pool_transactions.create_many(transactions)
    logger.debug(f'Saved {len(transactions)} to DB')

    user_state_by_address = {}
    pool_state_by_id = {}
    for tx in transactions:
        pool_state = pool_state_by_id.get(tx.pool_id)
        if pool_state is None:
            pool_state = get_or_create_pool_state(tx.pool_id)
            pool_state_by_id[tx.pool_id] = pool_state

        pool_state.staked_amount_micros += tx.delta_amount_micros
        pool_state.last_tx = tx.to_info()

        user_state = user_state_by_address.get(tx.user_address)
        if user_state is None:
            user_state = db.user_states.get_one(address=tx.user_address)
            if user_state is None:
                user_state = db.user_states.create(UserState(address=tx.user_address))
                logger.debug(f'Created new user state:\n{user_state.pretty_str()}')
            user_state_by_address[tx.user_address] = user_state

        user_pool_state = user_state.pool_by_id.get(pool_state.id)
        if user_pool_state is None:
            user_pool_state = UserPoolState(pool_id=pool_state.id, stake_token=pool_state.stake_token)
            user_state.pool_by_id[pool_state.id] = user_pool_state

        user_pool_state.staked_amount_micros += tx.delta_amount_micros
        user_pool_state.last_tx = tx.to_info()

    updated_pool_states = list(pool_state_by_id.values())
    for user_state in user_state_by_address.values():
        db.user_states.update(user_state)
    for pool_state in updated_pool_states:
        db.pool_states.update(pool_state)

    return updated_pool_states


def update_all_pool_states() -> list[PoolState]:
    all_contracts = get_all_pool_contracts()
    new_transactions = []
    for contract in all_contracts:
        pool_state = get_or_create_from_contract(contract)
        pool_transactions = pool_fetch_new_transactions(pool_state)
        new_transactions.extend(pool_transactions)

    # TODO: finish

    return []


def record_new_pool_transactions(pool_id: int) -> PoolState:
    logger.debug(f'Updating pool state {pool_id}')

    pool_state = get_or_create_pool_state(pool_id)
    new_transactions = pool_fetch_new_transactions(pool_state)
    if len(new_transactions) == 0:
        return pool_state

    updated_pool_states = process_transactions(new_transactions)
    return updated_pool_states[0]
