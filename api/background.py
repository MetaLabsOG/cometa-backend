import asyncio
import logging
import multiprocessing

from contextlib import contextmanager

from blockchain.node import get_current_round
from core.cometa import calculate_tvl_for_type, get_pool_state
from core.db.cometa_users import cometa_users, update_user_pools
from core.db.contracts import get_contracts_by_type, update_contract, get_contracts
from core.db.new_pools import new_pools, NewPoolInfo
from core.decorators import safe_async_method, repeat_every
from core.db.model import PoolStatus, PoolInfo, PoolType
from core.db.pools import pools_db
from core.util import strip_version
from core.js_interop import calljs
from api.stats import save_snapshot
from env import settings

spawn = multiprocessing.get_context('spawn')
logger = logging.getLogger(__name__)


@safe_async_method
async def update_contracts_cache(type: str) -> None:
    contracts = get_contracts_by_type(type)
    if len(contracts) > 0:
        ids_and_versions = [{ 'id': info.id, 'version': strip_version(info.version) } for info in contracts]
        existing_metadatas = { info.id: info.metadata for info in contracts }
        states = await calljs("fetchContractsGlobalViews", contractType=type, idVersions=ids_and_versions)

        for s_id, state in states.items():
            id = int(s_id)
            old_metadata = existing_metadatas[id]
            if old_metadata is None:
                old_metadata = {}

            new_metadata = {**old_metadata, "cache": state}
            update_contract(id, metadata=new_metadata)
    
        logger.info(f'Updated state cache for contracts: {type}')


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

    all_contracts = get_contracts({'type': {'$in': ['farm', 'distribution']}})
    current_block = get_current_round()
    pools = pools_db.get_all()
    current_pools = {p.id: p.status for p in pools}
    for contract in all_contracts:
        try:
            pool_state = get_pool_state(contract)
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
                old_status = current_pools[pool_info.id]
                if old_status == PoolStatus.UPCOMING and pool_status == PoolStatus.LIVE:
                    new_pools.create(NewPoolInfo(pool_info.id, pool_info.name, pool_info.type))
            else:
                pools_db.create(pool_info)
                if pool_status == PoolStatus.LIVE:
                    new_pools.create(NewPoolInfo(pool_info.id, pool_info.name, pool_info.type))

        except Exception as e:
            logger.error(f'Failed to get info for pool {contract.description}')
            logger.exception(e, exc_info=True)

    logger.info(f'Updated {len(all_contracts)} pools info')


@safe_async_method
async def update_all_user_pools():
    logger.info('Updating user pools...')
    users = cometa_users.get_all()
    user_updates = list(map(update_user_pools, users))
    await asyncio.gather(*user_updates)
    logger.info(f'Updated pools for {len(users)} users')


@repeat_every(settings.contracts_cache_ttl)
async def update_contracts_worker():
    logger.info('Updating contract caches...')
    await update_contracts_cache('farm')
    await update_contracts_cache('distribution')

    # TODO: to use it on testnet we need to stop calculate prices with vestige
    if settings.is_mainnet():
        await update_pools_info()
        await update_all_user_pools()
        await record_contracts_stats()


# TODO: graceful shutdown here (with signal handling?)
def run_background():
    async def tasks():
        await asyncio.gather(
            update_contracts_worker(),
        )

    logger.info('Started background tasks')
    asyncio.run(tasks())


# Runs in a separate process to use a separate asyncio loop from uvicorn,
# since reusing the uvicorn's one is hacky and sad
@contextmanager
def start_bg_tasks():
    proc = spawn.Process(target=run_background)
    proc.start()
    logger.info(f'STARTED BG TASKS: {proc}')
    print('STARTED BORIS GREBENSCHEKOV')
    try:
        yield proc
    finally:
        proc.terminate()
        proc.join()

