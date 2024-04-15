import pactsdk

from env import settings
from flex.blockchain.base import algod_client

pact = pactsdk.PactClient(algod_client, network=settings.algo_network)


def get_pact_pool_info(asset1_id: int, asset2_id: int) -> dict:
    asset1 = pact.fetch_asset(asset1_id)
    asset2 = pact.fetch_asset(asset2_id)

    pool = pact.fetch_pools_by_assets(asset1, asset2)[0]

    return {
        "total_liquidity": pool.state.total_liquidity,
        "total_primary": pool.state.total_primary,
        "total_secondary": pool.state.total_secondary
    }
