from dataclasses import dataclass

import pactsdk

from env import settings
from flex.blockchain.base import algod_client

pact = pactsdk.PactClient(algod_client, network=settings.algo_network)


@dataclass
class PactPoolInfo:
    lp_token_id: int
    asset1_id: int
    asset2_id: int
    app_id: int
    address: str


def get_pact_pool_info(asset1_id: int, asset2_id: int, lp_token_id: int) -> PactPoolInfo | None:
    asset1 = pact.fetch_asset(asset1_id)
    asset2 = pact.fetch_asset(asset2_id)

    pools = pact.fetch_pools_by_assets(asset1, asset2)
    pool = None
    for p in pools:
        if p.liquidity_asset.index == lp_token_id:
            pool = p
            break
    if pool is None:
        return None

    return PactPoolInfo(
        lp_token_id=pool.liquidity_asset.index,
        asset1_id=asset1_id,
        asset2_id=asset2_id,
        app_id=pool.app_id,
        address=pool.get_escrow_address(),
    )
