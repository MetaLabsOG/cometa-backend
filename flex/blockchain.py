from dataclasses import dataclass
from datetime import timedelta
from functools import cached_property

from algosdk import mnemonic, account
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from cachetools import cached, TTLCache
from dataclasses_json import dataclass_json

from env import settings


BLOCKS_IN_A_YEAR = int(timedelta(days=365).total_seconds() / settings.block_time)


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

cometa_private_key = mnemonic.to_private_key(settings.algo_mnemonic)
cometa_public_key = account.address_from_private_key(cometa_private_key)


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


# TODO: make it better somehow I don't know I'm tired as fuck bro
ALGO_ASSET_INFO = AssetInfo(
    id=0,
    decimals=6,
    name='Algorand',
    unit_name='ALGO'
)


@cached(cache=TTLCache(maxsize=65536, ttl=timedelta(hours=24).total_seconds()))
def get_asset_info(asset_id: int) -> AssetInfo:
    if asset_id == 0:
        return ALGO_ASSET_INFO

    data = indexer_client.asset_info(asset_id)
    params = data['asset']['params']
    return AssetInfo(
        id=asset_id,
        decimals=params['decimals'],
        name=params['name'],
        unit_name=params['unit-name']
    )


@cached(cache=TTLCache(maxsize=1, ttl=settings.block_time))
def get_current_round():
    data = algod_client.status()
    return data['last-round']


def get_app_address(app_id: int) -> str:
    data = indexer_client.application_logs(application_id=app_id, limit=10)
    log_data = data['log-data']

    txid = log_data[0]['txid']
    data = indexer_client.transaction(txid=txid)

    return data['transaction']['inner-txns'][0]['sender']


def asset_amount_to_micros(asset_id: int, amount: float) -> int:
    return get_asset_info(asset_id).amount_to_micros(amount)


def asset_micros_to_amount(asset_id: int, micros: int) -> float:
    return get_asset_info(asset_id).micros_to_amount(micros)


def is_opted_in(address: str, asa_id: int) -> bool:
    account_info = algod_client.account_info(address)
    for account in account_info.get('assets', []):
        if account['asset-id'] == asa_id:
            return True
    return False
