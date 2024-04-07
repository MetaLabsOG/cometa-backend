from cachetools import cached, TTLCache

from env import settings
from flex.blockchain.base import indexer_client, algod_client
from flex.db.model.blockchain import Asset

# TODO: make it better somehow I don't know I'm tired as issue bro
ALGO_ASSET_INFO = Asset(
    id=0,
    decimals=6,
    name='Algorand',
    unit_name='ALGO',
    # total_supply_micros=10000000000 * 1000000,  # 10B,
    # creator_address=None
)


def fetch_asset_info(asset_id: int) -> Asset:
    if asset_id == 0:
        return ALGO_ASSET_INFO

    data = indexer_client.asset_info(asset_id)
    params = data['asset']['params']
    return Asset(
        id=asset_id,
        decimals=params['decimals'],
        name=params['name'],
        unit_name=params['unit-name'],
        # total_supply_micros=params['total'],
        # creator_address=params['creator']
    )


def get_asset_total_supply(asset_id: int) -> int:
    if asset_id == 0:
        return 10000000000 * 1000000
    data = indexer_client.asset_info(asset_id)
    return data['asset']['params']['total']


def get_address_assets(address: str) -> dict:
    data = indexer_client.lookup_account_assets(address=address)
    return {asset['asset-id']: asset['amount'] for asset in data['assets']}


def get_address_assets_with_algo(address: str) -> dict:
    data = indexer_client.account_info(address)
    asset_balances = {asset['asset-id']: asset['amount'] for asset in data['account']['assets']}
    asset_balances[0] = data['account']['amount']
    return asset_balances


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


def is_opted_in(address: str, asa_id: int) -> bool:
    account_info = algod_client.account_info(address)
    for account in account_info.get('assets', []):
        if account['asset-id'] == asa_id:
            return True
    return False
