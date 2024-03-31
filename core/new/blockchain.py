from dataclasses import dataclass
from functools import cached_property

from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from cachetools import cached, LRUCache
from dataclasses_json import dataclass_json

from env import settings

indexer_client: IndexerClient = IndexerClient(
    indexer_token=settings.algod_token,
    indexer_address=settings.algo_indexer_address
)

algod_client: AlgodClient = AlgodClient(
    settings.algod_token,
    settings.algod_address,
    headers={
        'User-Agent': 'py-algorand-sdk',
        'X-API-Key': settings.algod_token
    }
)


@dataclass_json
@dataclass
class AssetInfo:
    id: int
    decimals: int
    name: str
    unit_name: str

    @cached_property
    def amount_multiplier(self) -> int:
        return 10 ** self.decimals

    def amount_to_micros(self, amount: float) -> int:
        return int(amount * self.amount_multiplier)

    def micros_to_amount(self, micros: int) -> float:
        return micros / self.amount_multiplier


# TODO: update cache method (time-based better)
@cached(cache=LRUCache(maxsize=2048))
def get_asset_info(asset_id: int) -> AssetInfo:
    data = indexer_client.asset_info(asset_id)
    params = data['asset']['params']
    return AssetInfo(
        id=asset_id,
        decimals=params['decimals'],
        name=params['name'],
        unit_name=params['unit-name']
    )


def asset_amount_to_micros(asset_id: int, amount: float) -> int:
    return get_asset_info(asset_id).amount_to_micros(amount)


def asset_micros_to_amount(asset_id: int, micros: int) -> float:
    return get_asset_info(asset_id).micros_to_amount(micros)
