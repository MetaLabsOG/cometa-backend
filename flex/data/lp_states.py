from dataclasses import dataclass

from cachetools import cached, TTLCache
from dataclasses_json import dataclass_json

from flex.blockchain.info import get_address_assets, get_address_assets_with_algo, get_asset_total_supply, \
    get_current_round
from flex.data.assets import get_asset
from flex.data.lp_tokens import get_lp_token_info_by_id
from flex.data.tinyman import get_tinyman_pool_info
from flex.data.vestige import DexProvider, get_asset_price
from flex.db.model.blockchain import LpToken


@dataclass_json
@dataclass
class LpStateInfo:
    id: int
    token_id: int
    asset1_id: int
    asset2_id: int
    dex_provider: str
    address: str

    asset1_reserve_micros: int
    asset2_reserve_micros: int
    issued_tokens_micros: int

    last_updated_round: int

    swap_fee_apr: float | None = None


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


def lp_state_from_lp_balances(lp_token: LpToken) -> LpStateInfo:
    if lp_token.asset1_id == 0 or lp_token.asset2_id == 0:
        balances = get_address_assets_with_algo(lp_token.address)
    else:
        balances = get_address_assets(lp_token.address)

    asset1_reserve_micros = balances[lp_token.asset1_id]
    asset2_reserve_micros = balances[lp_token.asset2_id]
    lp_token_reserve_micros = balances[lp_token.id]

    lp_token_total_supply_micros = get_asset_total_supply(lp_token.id)
    issued_lp_tokens_micros = lp_token_total_supply_micros - lp_token_reserve_micros

    return LpStateInfo(
        id=lp_token.pool_id,
        token_id=lp_token.id,
        asset1_id=lp_token.asset1_id,
        asset2_id=lp_token.asset2_id,
        dex_provider=lp_token.dex_provider,
        address=lp_token.address,
        asset1_reserve_micros=asset1_reserve_micros,
        asset2_reserve_micros=asset2_reserve_micros,
        issued_tokens_micros=issued_lp_tokens_micros,
        last_updated_round=get_current_round(),
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
        issued_tokens=lp_state.issued_tokens_micros
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
