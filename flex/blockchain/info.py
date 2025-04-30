from aiocache import cached
from algosdk.error import AlgodHTTPError
import logging

from flex.blockchain.base import indexer_client, algod_client
from flex.db.model.blockchain import Asset, AssetInfo

# TODO: make it better somehow I don't know I'm tired as issue bro
ALGO_ASSET = Asset(
    id=0,
    decimals=6,
    name='Algorand',
    unit_name='ALGO',
    creator='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ',
    reserve='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ',
    total_supply=10_000_000_000
)


async def fetch_asset(asset_id: int) -> Asset:
    if asset_id == 0:
        return ALGO_ASSET

    data = indexer_client.asset_info(asset_id)
    params = data['asset']['params']
    asset_info = AssetInfo(
        id=asset_id,
        decimals=params['decimals'],
        name=params['name'],
        unit_name=params['unit-name']
    )
    return Asset(
        id=asset_id,
        decimals=asset_info.decimals,
        name=asset_info.name,
        unit_name=asset_info.unit_name,
        creator=params['creator'],
        reserve=params['reserve'],
        total_supply=asset_info.micros_to_amount(params['total'])
    )


async def get_address_assets(address: str) -> dict:
    data = indexer_client.lookup_account_assets(address=address)
    return {asset['asset-id']: asset['amount'] for asset in data['assets']}


async def get_address_assets_with_algo(address: str) -> dict:
    data = indexer_client.account_info(address)
    asset_balances = {asset['asset-id']: asset['amount'] for asset in data['account']['assets']}
    asset_balances[0] = data['account']['amount']
    return asset_balances


@cached(ttl=10, namespace='node', key='current_round')
async def get_current_round():
    try:
        data = algod_client.status()
        current_round = data['last-round']
        # Store for fallback
        get_current_round._last_known_round = current_round
        return current_round
    except AlgodHTTPError as e:
        logging.error(f"Failed to get current round from Algod: {e}")
        fallback = getattr(get_current_round, '_last_known_round', 0)
        logging.warning(f"Using fallback round: {fallback}")
        return fallback
    except Exception as e:
        logging.error(f"Unexpected error getting current round: {e}", exc_info=True)
        return getattr(get_current_round, '_last_known_round', 0)


async def get_app_address(app_id: int) -> str:
    data = indexer_client.application_logs(application_id=app_id, limit=10)
    log_data = data['log-data']

    txid = log_data[0]['txid']
    data = indexer_client.transaction(txid=txid)

    return data['transaction']['inner-txns'][0]['sender']


async def get_address_app_ids(address: str) -> list[int]:
    data = indexer_client.account_info(address=address)
    return [app_state['id'] for app_state in data['account']['apps-local-state']]


def is_opted_in(address: str, asa_id: int) -> bool:
    account_info = algod_client.account_info(address)
    for account in account_info.get('assets', []):
        if account['asset-id'] == asa_id:
            return True
    return False
