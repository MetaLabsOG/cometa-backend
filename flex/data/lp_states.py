import logging

from aiocache import cached

from env import settings
from flex import db
from flex.blockchain.info import get_address_assets, get_address_assets_with_algo, get_current_round
from flex.data.assets import micros_to_amount, get_asset_total_supply
from flex.data.lp_tokens import get_lp_token_by_id, lp_token_from_tinyman_pool
from flex.db.model.blockchain import LpToken
from flex.meta_error import MetaError
from flex.providers.tinyman import fetch_algo_tinyman_pool_by_asset_id
from flex.providers.vestige import vestige_full_asset_price
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.util import build_key_str

logger = logging.getLogger(__name__)


async def recalculate_lp_state_price_algo_with_micros(lp_state: LpState) -> LpState:
    if lp_state.total_tokens_micros == 0:
        lp_state.total_tokens = 0
        lp_state.token_price_algo = 0
        return lp_state

    lp_state.asset1_reserve = await micros_to_amount(lp_state.asset1_id, lp_state.asset1_reserve_micros)
    lp_state.asset2_reserve = await micros_to_amount(lp_state.asset2_id, lp_state.asset2_reserve_micros)
    lp_state.total_tokens = await micros_to_amount(lp_state.token_id, lp_state.total_tokens_micros)

    # TODO: check if not outdated price
    asset1_db_price = db.asset_prices.get_one(id=lp_state.asset1_id)
    if asset1_db_price is not None:
        asset1_price_algo = asset1_db_price.price_algo
    else:
        asset1_price_algo = (await vestige_full_asset_price(lp_state.asset1_id)).algo
    lp_state.token_price_algo = asset1_price_algo * lp_state.asset1_reserve * 2 / lp_state.total_tokens
    return lp_state


async def create_lp_state_by_lp_token_id(lp_token_id: int, current_round: int | None = None) -> LpState:
    lp_token = await get_lp_token_by_id(lp_token_id)
    if lp_token is None:
        raise MetaError(f'LP token not found for ID {lp_token_id}')

    return await create_lp_state_by_lp_token(lp_token, current_round)


async def create_lp_state_by_lp_token(lp_token: LpToken, current_round: int | None = None) -> LpState:
    if db.lp_states.exists(token_id=lp_token.id):
        raise MetaError(f'LP state already exists for LP token ID {lp_token.id}')

    # TODO: remove after test
    if lp_token.asset1_id == 0:
        raise MetaError(f'ALGO LP token asset1 ID = 0, not id2: {lp_token}')

    if lp_token.asset2_id == 0:
        balances = await get_address_assets_with_algo(lp_token.address)
    else:
        balances = await get_address_assets(lp_token.address)

    asset1_reserve_micros = balances[lp_token.asset1_id]
    asset2_reserve_micros = balances[lp_token.asset2_id]
    lp_token_reserve_micros = balances[lp_token.id]

    # TODO: add field total_supply_micros to LP token
    lp_token_total_supply_micros = await get_asset_total_supply(lp_token.id)
    issued_lp_tokens_micros = lp_token_total_supply_micros - lp_token_reserve_micros

    asset1_price_full = await vestige_full_asset_price(lp_token.asset1_id)
    asset1_reserve = await micros_to_amount(lp_token.asset1_id, asset1_reserve_micros)
    asset2_reserve = await micros_to_amount(lp_token.asset2_id, asset2_reserve_micros)
    issued_tokens = await micros_to_amount(lp_token.id, issued_lp_tokens_micros)
    lp_token_price_algo = asset1_price_full.algo * asset1_reserve * 2 / issued_tokens

    current_round = current_round or (await get_current_round())
    lp_state = LpState(
        id=lp_token.pool_id,
        token_id=lp_token.id,
        asset1_id=lp_token.asset1_id,
        asset2_id=lp_token.asset2_id,
        dex_provider=lp_token.dex_provider,
        address=lp_token.address,
        asset1_reserve_micros=asset1_reserve_micros,
        asset2_reserve_micros=asset2_reserve_micros,
        total_tokens_micros=issued_lp_tokens_micros,
        asset1_reserve=asset1_reserve,
        asset2_reserve=asset2_reserve,
        total_tokens=issued_tokens,
        token_price_algo=lp_token_price_algo,
        last_updated_round=current_round,
        is_algo_pool=lp_token.asset2_id == 0
    )
    if lp_state.is_algo_pool:
        logger.info(f'Created new LP state for ALGO pool, asa_id={lp_token.asset1_id}:\n{lp_state.pretty_str()}')

    db.lp_states.create(lp_state)
    return lp_state


async def update_lp_state(lp_state: LpState) -> LpState:
    if lp_state.asset1_id == 0 or lp_state.asset2_id == 0:
        # TODO: take values from DB sync
        balances = await get_address_assets_with_algo(lp_state.address)
    else:
        balances = await get_address_assets(lp_state.address)

    lp_state.asset1_reserve_micros = balances[lp_state.asset1_id]
    lp_state.asset2_reserve_micros = balances[lp_state.asset2_id]

    lp_token_reserve_micros = balances[lp_state.token_id]
    lp_token_total_supply_micros = await get_asset_total_supply(lp_state.token_id)
    lp_state.total_tokens_micros = lp_token_total_supply_micros - lp_token_reserve_micros

    lp_state = await recalculate_lp_state_price_algo_with_micros(lp_state)
    lp_state.last_updated_round = await get_current_round()
    db.lp_states.update(lp_state)

    return lp_state


async def create_lp_states_from_all_pools() -> list[LpState]:
    farming_pools = db.farming_pools.get_all()
    new_lp_states = []
    for farming_pool in farming_pools:
        try:
            if db.lp_states.exists(token_id=farming_pool.stake_token.id):
                continue

            lp_state = await create_lp_state_by_lp_token_id(farming_pool.stake_token.id)
            new_lp_states.append(lp_state)
        except Exception as e:
            logger.error(f'Failed to create LP state: {e}\n{farming_pool.pretty_str()}', exc_info=True)

    return new_lp_states


async def update_lp_states_with_transactions(
        transactions: list[LpTransaction]
) -> list[LpState]:
    if len(transactions) == 0:
        return []

    updated_lp_states = {}
    for tx in transactions:
        if db.lp_transactions.exists(id=tx.id):
            logger.debug(f'Transaction {tx.id} already recorded in DB')
            continue

        lp_state = updated_lp_states.get(tx.pool_address)
        if lp_state is None:
            # TODO: cache
            lp_state = db.lp_states.get_one(address=tx.pool_address)
            if lp_state is None:
                logger.error(f'LP state not found for address {tx.pool_address}')
                continue
            updated_lp_states[tx.pool_address] = lp_state

        if tx.asa_id == lp_state.token_id:
            lp_state.total_tokens_micros += -tx.delta_amount_micros
        elif tx.asa_id == lp_state.asset1_id:
            lp_state.asset1_reserve_micros += tx.delta_amount_micros
        elif tx.asa_id == lp_state.asset2_id:
            lp_state.asset2_reserve_micros += tx.delta_amount_micros
        else:
            logger.error(f'Invalid tx {tx.id} ASA ID {tx.asa_id} for LP state {lp_state.id}')
            continue

        lp_state.last_updated_round = tx.confirmed_round

    lp_states = []
    for lp_state in updated_lp_states.values():
        # TODO: optimize calculate only changed fields
        lp_state = await recalculate_lp_state_price_algo_with_micros(lp_state)
        db.lp_states.update(lp_state)
        lp_states.append(lp_state)

    db.lp_transactions.create_many(transactions)

    logger.info(f'Updated {len(lp_states)} LP states with {len(transactions)} transactions')
    return lp_states


async def update_all_lp_states_linear() -> list[LpState]:
    lp_states = db.lp_states.get_all()
    logger.debug(f'Updating {len(lp_states)} LP states...')

    updated_lp_states = []
    for lp_state in lp_states:
        try:
            updated_lp_state = await update_lp_state(lp_state)
            updated_lp_states.append(updated_lp_state)
        except Exception as e:
            logger.error(f'Error updating state of LP {lp_state.id}: {e}', exc_info=True)

    logger.debug(f'Updated {len(updated_lp_states)} LP states')
    return updated_lp_states


@cached(ttl=settings.lp_token_prices_ttl, namespace='lp_state_by_id', key_builder=build_key_str)
async def get_lp_state_by_lp_token_id(lp_token_id: int) -> LpState:
    lp_state = db.lp_states.get_one(token_id=lp_token_id)
    if lp_state is None:
        lp_state = await create_lp_state_by_lp_token_id(lp_token_id)
    # TODO: add setting: do update or not
    elif (await get_current_round()) - lp_state.last_updated_round > settings.lp_state_ttl_rounds:
        lp_state = await update_lp_state(lp_state)
    return lp_state


@cached(ttl=60, namespace='lp_state_by_address', key_builder=build_key_str)
async def get_lp_state_by_address(address: str) -> LpState:
    return db.lp_states.get_one(address=address)


@cached(ttl=120, namespace='tinyman_lp_state', key_builder=build_key_str)
async def get_tinyman_pool_lp_state_by_asset_id(asset_id: int) -> LpState | None:
    tiny_lp_state = db.lp_states.get_one(asset1_id=asset_id, asset2_id=0)
    if tiny_lp_state is not None:
        return tiny_lp_state

    tinyman_pool = await fetch_algo_tinyman_pool_by_asset_id(asset_id)
    if tinyman_pool is None or tinyman_pool.lp_token_id is None:
        logger.debug(f'Tinyman pool for asset {asset_id} not found')
        return None

    lp_token = db.lp_tokens.get_by_primary_key(tinyman_pool.lp_token_id, throw_ex=False)
    if lp_token is None:
        lp_token = await lp_token_from_tinyman_pool(tinyman_pool)
        db.lp_tokens.create(lp_token)

    return await create_lp_state_by_lp_token(lp_token)
