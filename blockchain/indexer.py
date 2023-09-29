import logging

import requests
from algosdk.v2client import indexer
from cachetools import cached, LRUCache

from env import settings

BASE_URL = settings.algo_indexer_address
logger = logging.getLogger(__name__)


# TODO: use SDK
@cached(cache=LRUCache(maxsize=2048))
def get_asset(asset_id: int):
    url = f'{BASE_URL}/v2/assets/{asset_id}'
    logger.debug(f'Fetching asset {asset_id} from {url}')
    return requests.get(url).json()['asset']


def get_account_assets(address: str) -> dict:
    url = f'{BASE_URL}/v2/accounts/{address}'
    data = requests.get(url).json()
    assets = data['account']['assets']
    assets.append({
        'asset-id': 0,
        'amount': data['account']['amount'],
        'deleted': False,
        'is-frozen': False,
        'opted-in-at-round': 0
    })
    return assets


def get_address_app_ids(address: str) -> list[int]:
    url = f'{BASE_URL}/v2/accounts/{address}'
    data = requests.get(url).json()
    logger.debug(f'Fetching app ids for {address} from {url}')
    account = data.get('account')
    if account is None:
        raise Exception(f'Account {address} not found: {data}')
    if not data['account'].get('apps-local-state'):
        return []
    return [app['id'] for app in data['account']['apps-local-state']]


def get_asset_creator(asset_id: int) -> str:
    asset = get_asset(asset_id)
    return asset['params']['creator']


def get_asset_owner(asset_id: int) -> str:
    url = f'{BASE_URL}/v2/assets/{asset_id}/balances'
    data = requests.get(url).json()
    balances = data['balances']
    for balance in balances:
        if balance['amount'] == 1:
            return balance['address']
    raise Exception(f'Asset {asset_id} has all zero balances')


def get_asset_ids_by_creator(address):
    URL = f'{BASE_URL}/v2/assets?creator={address}'
    asset_ids = []
    data = {}
    PARAMS = {}

    for i in range(100):
        if data and data['next-token']:
            PARAMS = {'next': data['next-token']}
        r = requests.get(url=URL, params=PARAMS)
        data = r.json()
        for asset in data['assets']:
            asset_ids.append(asset['index'])
        if not data.get('next-token', None):
            break

    return asset_ids

