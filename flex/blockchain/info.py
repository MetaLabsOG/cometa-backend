import asyncio
import logging

from aiocache import cached

from blockchain.node import get_current_round as _sync_get_current_round
from flex.blockchain.base import indexer_client, algod_client
from flex.db.model.blockchain import Asset

logger = logging.getLogger(__name__)

ALGO_ASSET = Asset(
    id=0,
    decimals=6,
    name='Algorand',
    unit_name='ALGO',
    creator='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ',
    reserve='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ',
    total_supply=10_000_000_000
)


async def _run_sync(func, *args):
    """Run a sync function in executor to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


async def fetch_asset(asset_id: int) -> Asset:
    if asset_id == 0:
        return ALGO_ASSET

    data = await _run_sync(indexer_client.asset_info, asset_id)
    params = data['asset']['params']
    return Asset(
        id=asset_id,
        decimals=params['decimals'],
        name=params.get('name', ''),
        unit_name=params.get('unit-name', ''),
        creator=params.get('creator', ''),
        reserve=params.get('reserve', ''),
        total_supply=params['total'] / (10 ** params['decimals'])
    )


async def get_address_assets(address: str) -> dict:
    data = await _run_sync(lambda: indexer_client.lookup_account_assets(address=address))
    return {asset['asset-id']: asset['amount'] for asset in data['assets']}


async def get_address_assets_with_algo(address: str) -> dict:
    data = await _run_sync(indexer_client.account_info, address)
    asset_balances = {asset['asset-id']: asset['amount'] for asset in data['account']['assets']}
    asset_balances[0] = data['account']['amount']
    return asset_balances


@cached(ttl=10, namespace='node', key='current_round')
async def get_current_round():
    """Async wrapper around the sync get_current_round (single implementation, shared cache)."""
    return await _run_sync(_sync_get_current_round)


async def get_app_address(app_id: int) -> str:
    data = await _run_sync(lambda: indexer_client.application_logs(application_id=app_id, limit=10))
    log_data = data['log-data']

    txid = log_data[0]['txid']
    data = await _run_sync(lambda: indexer_client.transaction(txid=txid))

    return data['transaction']['inner-txns'][0]['sender']


async def get_address_app_ids(address: str) -> list[int]:
    data = await _run_sync(lambda: indexer_client.account_info(address=address))
    return [app_state['id'] for app_state in data['account']['apps-local-state']]


def is_opted_in(address: str, asa_id: int) -> bool:
    account_info = algod_client.account_info(address)
    for account in account_info.get('assets', []):
        if account['asset-id'] == asa_id:
            return True
    return False
