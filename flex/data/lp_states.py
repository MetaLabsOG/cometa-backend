import asyncio
import logging
from dataclasses import dataclass

from cachetools import cached, TTLCache
from dataclasses_json import dataclass_json

from flex import db
from flex.blockchain.info import get_address_assets, get_address_assets_with_algo, get_current_round
from flex.data.assets import get_asset
from flex.data.lp_tokens import get_lp_token_info_by_id
from flex.data.tinyman import get_tinyman_pool_info
from flex.data.vestige import DexProvider, get_asset_price
from flex.db.model.blockchain import LpToken
from flex.db.model.liquidity_pools import LpState


logger = logging.getLogger(__name__)


@dataclass_json
@dataclass
class PricedLpState:
    id: int
    token_id: int
    asset1_id: int
    asset2_id: int
    dex_provider: str
    address: str

    asset1_reserve: int
    asset2_reserve: int
    issued_tokens: int

    token_price: float
    token_price_usd: float

    swap_fee_apr: float | None = None


def create_lp_state_with_price(
        id: int,
        token_id: int,
        asset1_id: int,
        asset2_id: int,
        dex_provider: str,
        address: str,
        asset1_reserve: int,
        asset2_reserve: int,
        issued_tokens: int,
        swap_fee_apr: float | None = None
) -> PricedLpState:
    if issued_tokens == 0:
        token_price = 0
        token_price_usd = 0
    else:
        asset1_price = get_asset_price(asset1_id)
        asset1 = get_asset(asset1_id)
        token_asset = get_asset(token_id)

        token_price = asset1_price.algo * asset1.micros_to_amount(asset1_reserve) * 2 / token_asset.micros_to_amount(issued_tokens)  # both reserves cost the same
        token_price_usd = asset1_price.usd * asset1.micros_to_amount(asset1_reserve) * 2 / token_asset.micros_to_amount(issued_tokens)  # optimize not fetching algo price

    return PricedLpState(
        id=id,
        token_id=token_id,
        asset1_id=asset1_id,
        asset2_id=asset2_id,
        dex_provider=dex_provider,
        address=address,
        asset1_reserve=asset1_reserve,
        asset2_reserve=asset2_reserve,
        issued_tokens=issued_tokens,
        swap_fee_apr=swap_fee_apr,
        token_price=token_price,
        token_price_usd=token_price_usd
    )


def priced_lp_state_from_lp_balances(lp_token: LpToken) -> PricedLpState:
    lp_state = lp_state_from_lp_balances(lp_token)
    return create_lp_state_with_price(
        id=lp_token.pool_id,
        token_id=lp_token.id,
        asset1_id=lp_token.asset1_id,
        asset2_id=lp_token.asset2_id,
        dex_provider=lp_token.dex_provider,
        address=lp_token.address,
        asset1_reserve=lp_state.asset1_reserve_micros,
        asset2_reserve=lp_state.asset2_reserve_micros,
        issued_tokens=lp_state.total_tokens_micros
    )


def fetch_priced_lp_state_by_token(lp_token: LpToken) -> PricedLpState:
    if lp_token.dex_provider == DexProvider.TINYMAN_V2:
        pool_info = get_tinyman_pool_info(lp_token.asset1_id, lp_token.asset2_id)
        return create_lp_state_with_price(
            id=lp_token.pool_id,
            token_id=lp_token.id,
            asset1_id=lp_token.asset1_id,
            asset2_id=lp_token.asset2_id,
            dex_provider=lp_token.dex_provider,
            address=lp_token.address,
            asset1_reserve=pool_info.asset1_reserve_micros,
            asset2_reserve=pool_info.asset2_reserve_micros,
            issued_tokens=pool_info.total_lp_tokens_micros
        )

    return priced_lp_state_from_lp_balances(lp_token)


@cached(cache=TTLCache(maxsize=1024, ttl=30))
def get_priced_lp_state_by_id(lp_token_id: int) -> PricedLpState:
    lp_token = get_lp_token_info_by_id(lp_token_id)
    return fetch_priced_lp_state_by_token(lp_token)


# NO PRICE

def lp_state_from_lp_balances(lp_token: LpToken) -> LpState:
    if lp_token.asset1_id == 0 or lp_token.asset2_id == 0:
        balances = get_address_assets_with_algo(lp_token.address)
    else:
        balances = get_address_assets(lp_token.address)

    asset1_reserve_micros = balances[lp_token.asset1_id]
    asset2_reserve_micros = balances[lp_token.asset2_id]
    lp_token_reserve_micros = balances[lp_token.id]

    lp_token_total_supply_micros = get_asset(lp_token.id).total_supply_micros
    issued_lp_tokens_micros = lp_token_total_supply_micros - lp_token_reserve_micros

    return LpState(
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


def update_from_lp_balances(lp_state: LpState) -> LpState:
    if lp_state.asset1_id == 0 or lp_state.asset2_id == 0:
        balances = get_address_assets_with_algo(lp_state.address)
    else:
        balances = get_address_assets(lp_state.address)

    lp_state.asset1_reserve_micros = balances[lp_state.asset1_id]
    lp_state.asset2_reserve_micros = balances[lp_state.asset2_id]
    lp_state.lp_token_reserve_micros = balances[lp_state.token_id]

    lp_token_total_supply_micros = get_asset(lp_state.token_id).total_supply_micros
    lp_state.total_tokens_micros = lp_token_total_supply_micros - lp_state.lp_token_reserve_micros

    lp_state.last_updated_round = get_current_round()

    lp_state = db.lp_states.update(lp_state)
    return lp_state


def update_all_lp_states() -> list[LpState]:
    lp_states = db.lp_states.get_all()
    logger.debug(f'Updating {len(lp_states)} LP states...')

    updated_lp_states = []
    for lp_state in lp_states:
        try:
            updated_lp_state = update_from_lp_balances(lp_state)
            updated_lp_states.append(updated_lp_state)
        except Exception as e:
            logger.error(f'Error updating LP state {lp_state.id}: {e}', exc_info=True)

    logger.debug(f'Updated {len(updated_lp_states)} LP states')
    return updated_lp_states


def create_lp_states() -> list[LpState]:
    farming_pools = db.farming_pools.get_all()
    new_lp_states = []
    for farming_pool in farming_pools:
        if db.lp_states.exists(token_id=farming_pool.stake_token.id):
            continue

        lp_token = get_lp_token_info_by_id(farming_pool.stake_token.id)
        lp_state = lp_state_from_lp_balances(lp_token)
        db.lp_states.create(lp_state)
        new_lp_states.append(lp_state)

    return new_lp_states


async def update_lp_states_loop() -> None:
    logger.info('LOOP Updating LP states...')

    while True:
        try:
            updated_lp_states = update_all_lp_states()
            logger.info(f'LOOP Updated {len(updated_lp_states)} LP states')
        except Exception as e:
            logger.error(f'Error updating LP states: {e}', exc_info=True)

        await asyncio.sleep(30)
