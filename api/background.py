import asyncio
import logging
import multiprocessing
from contextlib import contextmanager
from datetime import datetime
from time import sleep
import random

from api.notifications import notify_telegram_chat
from api.stats import save_snapshot
from blockchain.node import get_current_round
from core.cometa import calculate_tvl_for_type, get_pool_state
from core.db.cometa_users import cometa_users, update_user_pools
from core.db.contracts import get_contracts_by_type, update_contract, get_all_pool_contracts
from core.db.model import PoolStatus, PoolInfo, PoolType
from core.db.pools import pools_db
from core.decorators import safe_async_method, repeat_every
from core.js_interop import calljs
from core.util import strip_version, parse_bignum
from env import settings
from flex import db
from flex.migrations import migrate_background
from flex.providers.vestige import get_asset_price_usd_not_cached
from flex.sync_pools import sync_pools_loop
from flex.data.asset_prices import create_and_update_asset_prices, get_asset_price_not_cached

spawn = multiprocessing.get_context('spawn')
logger = logging.getLogger(__name__)


@safe_async_method
async def update_contracts_cache(type: str) -> None:
    start_time = datetime.now()

    all_contracts = get_contracts_by_type(type)
    contracts = []
    skipped = 0

    try:
        for contract in all_contracts:
            if contract.metadata is None or contract.metadata.get('cache') is None:
                contracts.append(contract)
            else:
                end_block = parse_bignum(contract.metadata['cache']['initial']['endBlock'])
                staked_microtokens = parse_bignum(contract.metadata['cache']['global']['totalStaked'])
                if end_block < get_current_round() and staked_microtokens <= 1:
                    skipped += 1
                    continue
                contracts.append(contract)
    except Exception as e:
        logger.error(f'Failed to filter contracts: {e}', exc_info=True)
        contracts = all_contracts


    existing_metadatas = { info.id: info.metadata for info in contracts }
    ids_and_versions = [{ 'id': info.id, 'version': strip_version(info.version) } for info in contracts]

    chunk_size = settings.update_contracts_chunk_size
    start_index = 0

    while start_index < len(ids_and_versions):
        states = await calljs("fetchContractsGlobalViews", contractType=type,
                              idVersions=ids_and_versions[start_index:start_index + chunk_size])

        for s_id, state in states.items():
            id = int(s_id)
            old_metadata = existing_metadatas[id]
            if old_metadata is None:
                old_metadata = {}

            new_metadata = {**old_metadata, "cache": state}
            update_contract(id, metadata=new_metadata)

        start_index += chunk_size
        await asyncio.sleep(1)

    time_delta = datetime.now() - start_time
    logger.info(f'Updated state cache for {len(all_contracts)} contracts: {type} ({skipped} skipped) in {time_delta.total_seconds()}s')


@safe_async_method
async def record_contracts_stats() -> None:
    logger.info('Making snapshot of contracts TVL...')
    farm_tvl = calculate_tvl_for_type(PoolType.FARM)
    distribution_tvl = calculate_tvl_for_type(PoolType.DISTRIBUTION)
    staking_tvl = calculate_tvl_for_type(PoolType.STAKING)
    save_snapshot(farm_tvl, distribution_tvl, staking_tvl)


@safe_async_method
async def update_pools_info() -> None:
    logger.info('Updating pools info...')
    start_time = datetime.now()

    all_contracts = get_all_pool_contracts()
    current_block = get_current_round()

    pools = pools_db.get_all()
    current_pools = {p.id: p.status for p in pools}

    OLD_BLOCK_THRESHOLD = 2000000  # ~90 days
    skipped = 0
    for contract in all_contracts:
        try:
            end_block = parse_bignum(contract.metadata['cache']['initial']['endBlock'])
            if end_block + OLD_BLOCK_THRESHOLD < current_block:
                skipped += 1
                continue
            # TODO: not to get rate-limit
            sleep(1)
            pool_state = get_pool_state(contract, settings.is_mainnet())
            pool_status = PoolStatus.from_current_block(current_block, pool_state.start_block, pool_state.end_block)

            pool_info = PoolInfo(
                type=pool_state.type,
                name=contract.description,
                id=contract.id,
                stake_token_id=pool_state.stake_token_id,
                staked=pool_state.total_staked,
                staked_usd=pool_state.total_staked_usd,
                reward_token_id=pool_state.reward_token_id,
                additional_algo_rewards=pool_state.total_algo_rewards > 0,
                current_apr=pool_state.current_apr,
                additional_info=pool_state.additional_info,
                status=pool_status,
                lock_length_blocks=pool_state.lock_length_blocks,
                last_updated=pool_state.last_updated
            )

            if pool_info.id in current_pools:
                pools_db.update(pool_info)
            else:
                pools_db.create(pool_info)

        except Exception as e:
            logger.error(f'Failed to get info for pool {contract.description}: {e}', exc_info=True)

    time_delta = datetime.now() - start_time
    logger.info(f'Updated {len(all_contracts)} pools info ({skipped} skipped) in {time_delta.total_seconds()}s')


@safe_async_method
async def update_all_user_pools():
    logger.info('Updating user pools...')
    users = cometa_users.get_all()
    user_updates = []
    for user in users:
        user_updates.append(update_user_pools(user, settings.is_mainnet()))
    await asyncio.gather(*user_updates)
    logger.info(f'Updated pools for {len(users)} users')


@repeat_every(settings.contracts_cache_ttl)
async def update_contracts_worker():
    # TODO: not call the top-level method at all
    if settings.enable_js and settings.update_contract_caches:
        logger.info('Updating contract caches...')
        await update_contracts_cache('farm')
        await update_contracts_cache('distribution')
        logger.info('Contract caches updated.')


@repeat_every(settings.contracts_cache_ttl)
async def update_pools_info_worker():
    logger.info('Updating pools...')

    if settings.is_mainnet():
        await record_contracts_stats()

    logger.info('Pools info updated.')


@repeat_every(3)
async def notify_prices():
    logger.info('CHECKING PRICES...')
    degen_price = await get_asset_price_usd_not_cached(1813373577)
    if degen_price > 0.0185:
        await notify_telegram_chat(
            chat_id=-4262280851,
            text=f'DEGEN price: ${degen_price:.4f}'
        )


def sync_new_pools():
    if settings.sync_new_pools:
        logger.info('\n\nStarted SYNC process.\n')

        asyncio.run(sync_pools_loop())


@repeat_every(settings.asset_prices_update_interval)  # Use the configured interval for updates
@safe_async_method
async def update_asset_prices_background():
    """
    Background task that updates asset prices periodically.
    Uses rate limiting to avoid hitting Vestige API limits.
    """
    if not settings.background_asset_prices_update:
        logger.info('Background asset price updates are disabled')
        return
        
    logger.info('Starting background asset price update')
    
    # Get all assets that need price updates
    all_assets = db.assets.get_all()
    current_round = get_current_round()
    
    # Prioritize frequently requested assets
    prioritized_assets = list(settings.always_return_pool_ids)
    
    # Add all other assets
    for asset in all_assets:
        if asset.id not in prioritized_assets:
            prioritized_assets.append(asset.id)
    
    # Shuffle non-priority assets to distribute load and prevent always hitting 
    # the API for the same assets in the same order
    regular_assets = prioritized_assets[len(settings.always_return_pool_ids):]
    random.shuffle(regular_assets)
    prioritized_assets = prioritized_assets[:len(settings.always_return_pool_ids)] + regular_assets
    
    total_updated = 0
    batch_size = min(settings.asset_price_update_batch_size, len(prioritized_assets))
    
    # Process in small batches with delays between API calls
    for i in range(0, len(prioritized_assets), batch_size):
        batch = prioritized_assets[i:i+batch_size]
        for asset_id in batch:
            try:
                asset_price = db.asset_prices.get_one(id=asset_id)
                
                # Only update if price is stale or missing
                if asset_price is None or (current_round - asset_price.last_update_round > settings.asset_prices_ttl):
                    await get_asset_price_not_cached(asset_id)
                    total_updated += 1
                    
                    # Small delay between API calls to prevent rate limiting
                    await asyncio.sleep(settings.asset_price_api_call_delay)
                
            except Exception as e:
                logger.error(f'Error updating price for asset {asset_id}: {e}')
        
        # Larger delay between batches
        if i + batch_size < len(prioritized_assets):
            await asyncio.sleep(settings.asset_price_batch_delay)
    
    logger.info(f'Background asset price update completed. Updated {total_updated}/{len(prioritized_assets)} assets')


# TODO: graceful shutdown here (with signal handling?)
def run_background():
    async def tasks():
        await asyncio.gather(
            migrate_background(),
            update_contracts_worker(),
            update_asset_prices_background(),
            # update_pools_info_worker()
            # sync_new_pools(),
            # notify_prices()
        )

    logger.info('Started background tasks.')
    asyncio.run(tasks())


# Runs in a separate process to use a separate asyncio loop from uvicorn,
# since reusing the uvicorn's one is hacky and sad
@contextmanager
def start_bg_tasks():
    proc = spawn.Process(target=run_background)
    proc.start()
    logger.info(f'STARTED BG TASKS: {proc}')
    print('STARTED BORIS GREBENSCHEKOV PROTOCOL')
    try:
        yield proc
    finally:
        proc.terminate()
        proc.join()


@contextmanager
def start_sync_proc():
    proc = spawn.Process(target=sync_new_pools)
    proc.start()
    logger.info(f'STARTED sync proc: {proc}')
    try:
        yield proc
    finally:
        proc.terminate()
        proc.join()
