import logging

from cachetools import cached, TTLCache

from env import settings
from flex import db
from flex.blockchain.info import get_address_assets, get_address_assets_with_algo, get_current_round
from flex.data.assets import get_asset
from flex.data.lp_tokens import get_lp_token_by_id
from flex.meta_error import MetaError
from flex.providers.vestige import get_full_asset_price, get_algo_price_usd
from flex.db.model.blockchain import LpToken
from flex.db.model.liquidity_pools import LpState, LpTransaction, PricedLpStateInfo

logger = logging.getLogger(__name__)


def lp_state_to_priced_info(lp_state: LpState) -> PricedLpStateInfo:
    asset1 = get_asset(lp_state.asset1_id)
    asset2 = get_asset(lp_state.asset2_id)
    token_asset = get_asset(lp_state.token_id)

    asset1_reserve = asset1.micros_to_amount(lp_state.asset1_reserve_micros)
    asset2_reserve = asset2.micros_to_amount(lp_state.asset2_reserve_micros)
    issued_tokens = token_asset.micros_to_amount(lp_state.total_tokens_micros)

    if lp_state.total_tokens_micros == 0:
        token_price_algo = 0
        token_price_usd = 0
    else:
        asset1_price_full = get_full_asset_price(lp_state.asset1_id)
        token_price_algo = asset1_price_full.algo * asset1_reserve * 2 / issued_tokens # both reserves cost the same
        token_price_usd = token_price_algo * get_algo_price_usd()

    return PricedLpStateInfo(
        id=lp_state.id,
        token_id=lp_state.token_id,
        asset1_id=lp_state.asset1_id,
        asset2_id=lp_state.asset2_id,
        dex_provider=lp_state.dex_provider,
        address=lp_state.address,
        asset1_reserve_micros=lp_state.asset1_reserve_micros,
        asset2_reserve_micros=lp_state.asset2_reserve_micros,
        issued_tokens_micros=lp_state.total_tokens_micros,
        last_updated_round=lp_state.last_updated_round,
        swap_fee_apr=lp_state.swap_fee_apr,
        asset1_reserve=asset1_reserve,
        asset2_reserve=asset2_reserve,
        issued_tokens=issued_tokens,
        token_price_algo=token_price_algo,
        token_price_usd=token_price_usd
    )


# TODO: seconds to settings
@cached(cache=TTLCache(maxsize=256, ttl=30))
def get_priced_lp_state_by_lp_token_id(lp_token_id: int) -> PricedLpStateInfo:
    lp_state = db.lp_states.get_one(token_id=lp_token_id)
    if lp_state is None:
        raise MetaError(f'LP state not found for LP token ID {lp_token_id}')
    return lp_state_to_priced_info(lp_state)


def get_priced_lp_states_by_lp_token_ids(lp_token_ids: list[int]) -> list[PricedLpStateInfo]:
    lp_states = db.lp_states.get_by_array('token_id', lp_token_ids)
    return [lp_state_to_priced_info(lp_state) for lp_state in lp_states]


@cached(cache=TTLCache(maxsize=1, ttl=30))
def get_all_priced_lp_states() -> list[PricedLpStateInfo]:
    lp_states = db.lp_states.get_all()
    return [lp_state_to_priced_info(lp_state) for lp_state in lp_states]


# NO PRICE

def create_lp_state_from_lp_balances(lp_token: LpToken) -> LpState:
    if lp_token.asset1_id == 0 or lp_token.asset2_id == 0:
        balances = get_address_assets_with_algo(lp_token.address)
    else:
        balances = get_address_assets(lp_token.address)

    asset1_reserve_micros = balances[lp_token.asset1_id]
    asset2_reserve_micros = balances[lp_token.asset2_id]
    lp_token_reserve_micros = balances[lp_token.id]

    lp_token_total_supply_micros = get_asset(lp_token.id).total_supply_micros
    issued_lp_tokens_micros = lp_token_total_supply_micros - lp_token_reserve_micros

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
        last_updated_round=get_current_round(),
    )
    db.lp_states.create(lp_state)
    return lp_state


def create_lp_state_by_lp_token_id(lp_token_id: int) -> LpState:
    lp_token = get_lp_token_by_id(lp_token_id)
    return create_lp_state_from_lp_balances(lp_token)


def update_lp_state_from_lp_balances(lp_state: LpState) -> LpState:
    if lp_state.asset1_id == 0 or lp_state.asset2_id == 0:
        balances = get_address_assets_with_algo(lp_state.address)
    else:
        balances = get_address_assets(lp_state.address)

    lp_state.asset1_reserve_micros = balances[lp_state.asset1_id]
    lp_state.asset2_reserve_micros = balances[lp_state.asset2_id]

    lp_token_reserve_micros = balances[lp_state.token_id]
    lp_token_total_supply_micros = get_asset(lp_state.token_id).total_supply_micros
    lp_state.total_tokens_micros = lp_token_total_supply_micros - lp_token_reserve_micros

    lp_state.last_updated_round = get_current_round()

    db.lp_states.update(lp_state)
    return lp_state


def update_lp_state_by_lp_token_id(lp_token_id: int) -> LpState:
    lp_token = get_lp_token_by_id(lp_token_id)
    # TODO: optimize/cache lp_state fetch (probably store locally)
    lp_state = db.lp_states.get_one(token_id=lp_token_id)
    if lp_state is None:
        lp_state = create_lp_state_from_lp_balances(lp_token)
    else:
        lp_state = update_lp_state_from_lp_balances(lp_state)
    return lp_state


def get_lp_state_by_lp_token_id(lp_token_id: int) -> LpState:
    # TODO: optimize/cache lp_state fetch (probably store locally)
    lp_state = db.lp_states.get_one(token_id=lp_token_id)
    if lp_state is None:
        lp_state = create_lp_state_by_lp_token_id(lp_token_id)
    elif get_current_round() - lp_state.last_updated_round > settings.lp_state_ttl_rounds:
        lp_state = update_lp_state_from_lp_balances(lp_state)
    return lp_state


def create_lp_states() -> list[LpState]:
    farming_pools = db.farming_pools.get_all()
    new_lp_states = []
    for farming_pool in farming_pools:
        try:
            if db.lp_states.exists(token_id=farming_pool.stake_token.id):
                continue

            lp_state = create_lp_state_by_lp_token_id(farming_pool.stake_token.id)
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

    lp_states = list(updated_lp_states.values())
    for lp_state in lp_states:
        db.lp_states.update(lp_state)
    db.lp_transactions.create_many(transactions)

    logger.info(f'Updated {len(updated_lp_states)} LP states with {len(transactions)} transactions')
    return lp_states


def update_all_lp_states_linear() -> list[LpState]:
    lp_states = db.lp_states.get_all()
    logger.debug(f'Updating {len(lp_states)} LP states...')

    updated_lp_states = []
    for lp_state in lp_states:
        try:
            updated_lp_state = update_lp_state_from_lp_balances(lp_state)
            updated_lp_states.append(updated_lp_state)
        except Exception as e:
            logger.error(f'Error updating LP state {lp_state.id}: {e}', exc_info=True)

    logger.debug(f'Updated {len(updated_lp_states)} LP states')
    return updated_lp_states
