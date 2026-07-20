import json
import logging
import urllib.request
from dataclasses import dataclass

from algosdk.v2client.algod import AlgodClient
from cachetools import TTLCache, cached
from tinyman.assets import Asset
from tinyman.v2.client import TinymanV2Client, TinymanV2MainnetClient, TinymanV2TestnetClient

from blockchain.node import init_algod_client
from env import settings

ASSETS_PATH = "https://asa-list.tinyman.org/assets.json"

logger = logging.getLogger(__name__)


def tinyman_from_algod(algod_client: AlgodClient, address: str | None = None) -> TinymanV2Client:
    """Build a read-only Tinyman client for the configured Algorand network."""

    if settings.is_mainnet():
        return TinymanV2MainnetClient(algod_client=algod_client, user_address=address)
    return TinymanV2TestnetClient(algod_client=algod_client, user_address=address)


def init_tinyman_client(address: str | None = None) -> TinymanV2Client:
    return tinyman_from_algod(init_algod_client(), address)


def get_amount(micros: int, asset: Asset) -> float:
    return micros / (10**asset.decimals)


@dataclass(frozen=True)
class PoolInfo:
    name: str
    asset1_reserve: float
    asset2_reserve: float
    total_lp_tokens: float


def get_pool_info(client: TinymanV2Client, asset1_id: int, asset2_id: int) -> PoolInfo:
    asset1 = client.fetch_asset(asset1_id)
    asset2 = client.fetch_asset(asset2_id)
    pool = client.fetch_pool(asset1, asset2)

    logger.debug("Found Tinyman pool for assets %s and %s", asset1_id, asset2_id)

    if pool.asset_1_reserves is None or pool.asset_2_reserves is None or pool.issued_pool_tokens is None:
        raise ValueError(f"Tinyman pool for assets {asset1_id} and {asset2_id} is empty")

    asset1_reserve = get_amount(pool.asset_1_reserves, pool.asset_1)
    asset2_reserve = get_amount(pool.asset_2_reserves, pool.asset_2)
    total_lp_tokens = get_amount(pool.issued_pool_tokens, pool.pool_token_asset)

    # Tinyman orders pool assets by ID rather than by the caller's argument order.
    if asset1_id < asset2_id:
        asset1_reserve, asset2_reserve = asset2_reserve, asset1_reserve

    return PoolInfo(
        name=pool.pool_token_asset.name,
        asset1_reserve=asset1_reserve,
        asset2_reserve=asset2_reserve,
        total_lp_tokens=total_lp_tokens,
    )


@cached(cache=TTLCache(maxsize=1, ttl=settings.asset_prices_ttl))
def get_all_assets() -> dict[str, dict]:
    with urllib.request.urlopen(ASSETS_PATH, timeout=30) as response:
        payload = json.loads(response.read().decode())
    if not isinstance(payload, dict):
        raise ValueError("Tinyman asset registry must be a JSON object")
    return payload


def get_asset_info(asset_id: int) -> dict | None:
    return get_all_assets().get(str(asset_id))
