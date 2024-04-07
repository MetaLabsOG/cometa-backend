from dataclasses import dataclass

from dataclasses_json import dataclass_json

from flex.blockchain.info import get_address_assets, get_address_assets_with_algo, get_asset_total_supply
from flex.data.assets import get_asset
from flex.data.tinyman import get_tinyman_pool_info
from flex.data.vestige import DexProvider
from flex.db.model.blockchain import LpToken


@dataclass_json
@dataclass
class LpState:
    id: int
    token_id: int
    asset1_id: int
    asset2_id: int
    dex_provider: str
    address: str

    asset1_reserve: float
    asset2_reserve: float
    issued_tokens: float
    swap_fee_apr: float | None = None


def lp_state_from_lp_balances(lp_token: LpToken) -> LpState:
    if lp_token.asset1_id == 0 or lp_token.asset2_id == 0:
        balances = get_address_assets_with_algo(lp_token.address)
    else:
        balances = get_address_assets(lp_token.address)

    asset1_reserve_micros = balances[lp_token.asset1_id]
    asset2_reserve_micros = balances[lp_token.asset2_id]
    lp_token_reserve_micros = balances[lp_token.id]

    asset2_info = get_asset(lp_token.asset2_id)
    asset1_info = get_asset(lp_token.asset1_id)
    lp_token_asset_info = get_asset(lp_token.id)

    lp_token_total_supply_micros = get_asset_total_supply(lp_token.id)
    issued_lp_tokens_micros = lp_token_total_supply_micros - lp_token_reserve_micros

    return LpState(
        id=lp_token.pool_id,
        token_id=lp_token.id,
        asset1_id=lp_token.asset1_id,
        asset2_id=lp_token.asset2_id,
        dex_provider=lp_token.dex_provider,
        address=lp_token.address,
        asset1_reserve=asset1_info.micros_to_amount(asset1_reserve_micros),
        asset2_reserve=asset2_info.micros_to_amount(asset2_reserve_micros),
        issued_tokens=lp_token_asset_info.micros_to_amount(issued_lp_tokens_micros)
    )


def fetch_lp_state_by_token(lp_token: LpToken) -> LpState:
    if lp_token.dex_provider == DexProvider.TINYMAN_V2:
        pool_info = get_tinyman_pool_info(lp_token.asset1_id, lp_token.asset2_id)
        return LpState(
            id=lp_token.pool_id,
            token_id=lp_token.id,
            asset1_id=lp_token.asset1_id,
            asset2_id=lp_token.asset2_id,
            dex_provider=lp_token.dex_provider,
            address=lp_token.address,
            asset1_reserve=pool_info.asset1_reserve,
            asset2_reserve=pool_info.asset2_reserve,
            total_tokens=pool_info.total_lp_tokens
        )

    return lp_state_from_lp_balances(lp_token)
