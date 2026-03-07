import asyncio
import logging

from algosdk.v2client import indexer
from cachetools import cached, LRUCache

from env import settings

BASE_URL = settings.algo_indexer_address
logger = logging.getLogger(__name__)

indexer_client = indexer.IndexerClient(
    indexer_token=settings.algod_token,
    indexer_address=settings.algo_indexer_address,
    headers={
        'User-Agent': 'py-algorand-sdk',
        'x-algo-api-token': settings.algod_token
    }
)

# TODO: INFO NOT FULL, handle get_asset(0) better
ALGO_ASSET_INFO = {
    'created-at-round': 3317341,
    'deleted': False,
    'index': 0,
    'params': {
        'creator': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ',
        'total': 1000000000000000000000000000,
        'decimals': 6,
        'default-frozen': False,
        'unit-name': 'ALGO',
        'name': 'Algorand',
        'url': 'https://algorand.foundation/'
    }
}


@cached(cache=LRUCache(maxsize=2048))
def get_asset(asset_id: int):
    if asset_id == 0:
        return ALGO_ASSET_INFO
    logger.debug(f'Fetching asset {asset_id} info')
    data = indexer_client.asset_info(asset_id)
    return data['asset']


def get_account_assets(address: str) -> dict:
    data = indexer_client.account_info(address)
    assets = data['account']['assets']
    assets.append({
        'asset-id': 0,
        'amount': data['account']['amount'],
        'deleted': False,
        'is-frozen': False,
        'opted-in-at-round': 0
    })
    return assets


CONST_APP_STATE_BYTES = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'


def get_address_app_ids(address: str, only_active: bool = False) -> list[int]:
    logger.debug(f'Fetching app ids for {address}')
    data = indexer_client.account_info(address)
    account = data.get('account')
    if account is None:
        raise Exception(f'Account {address} not found: {data}')
    if not data['account'].get('apps-local-state'):
        return []

    app_ids = []
    for app in data['account']['apps-local-state']:
        if only_active:
            key_value = app.get('key-value')
            if key_value is None or len(key_value) == 0:
                continue
            bytes_str = key_value[0]['value']['bytes']
            if bytes_str == CONST_APP_STATE_BYTES:
                continue
        app_ids.append(app['id'])

    return app_ids


async def get_address_app_ids_async(address: str, only_active: bool = False) -> list[int]:
    """Non-blocking version of get_address_app_ids for use in async handlers."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_address_app_ids, address, only_active)


def get_asset_creator(asset_id: int) -> str:
    asset = get_asset(asset_id)
    return asset['params']['creator']


def get_asset_owner(asset_id: int) -> str:
    data = indexer_client.asset_balances(asset_id=asset_id)
    balances = data['balances']
    for balance in balances:
        if balance['amount'] == 1:
            return balance['address']
    raise Exception(f'Asset {asset_id} has all zero balances')


def get_asset_ids_by_creator(address):
    asset_ids = []
    data = {}
    params = {}

    indexer_client.search_assets(creator=address)
    for i in range(100):
        if data and data['next-token']:
            params = {'next': data['next-token']}
        data = indexer_client.search_assets(creator=address, **params)
        for asset in data['assets']:
            asset_ids.append(asset['index'])
        if not data.get('next-token', None):
            break

    return asset_ids
