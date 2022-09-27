import asyncio
import logging
import multiprocessing

from contextlib import contextmanager

from core.cometa import calculate_tvl_for_type
from core.contract_manager import get_contracts_by_type, update_contract
from core.decorators import safe_async_method, repeat_every
from core.util import strip_version
from core.js_interop import calljs
from api.stats import save_snapshot

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
    
        logger.info(f'updated state cache for contracts: {type}')


@safe_async_method
async def record_contracts_stats() -> None:
    farm_tvl = calculate_tvl_for_type('farm')
    distribution_tvl = calculate_tvl_for_type('distribution')
    save_snapshot(farm_tvl, distribution_tvl)


@repeat_every(60)  # once in a minute
async def update_contracts_worker():
    logger.info('updating contract caches...')
    await update_contracts_cache('farm')
    await update_contracts_cache('distribution')

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
    logger.info("STARTED BG TASKS", proc)
    print('STARTED BORIS GREBENSCHEKOV')
    try:
        yield proc
    finally:
        proc.terminate()
        proc.join()

