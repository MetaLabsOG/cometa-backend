import asyncio
import multiprocessing

from contextlib import contextmanager
from core.contract_manager import get_contracts, update_contract
from core.util import strip_version
from core.js_interop import calljs
from api.stats import calculate_tvl_for_type, save_snapshot

spawn = multiprocessing.get_context('spawn')


# Decorators (for convenience)

def safe_async_method(fn):
    async def wrapper(*args, **kwargs):
        try:
            await fn(*args, **kwargs)
        except Exception as e:
            print(f'Error in `{fn.__name__}(*{args}, **{kwargs})`: ', e)
    return wrapper


def repeat_every(seconds: int):
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            while True:
                await fn(*args, **kwargs)
                await asyncio.sleep(seconds)
        return wrapper
    return decorator


# Task logic

@safe_async_method
async def update_contracts_cache(type: str) -> None:
    contracts = get_contracts(type)
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
    
        print(f'updated state cache for contracts: {type}')


@safe_async_method
async def record_contracts_stats() -> None:
    farm_tvl = calculate_tvl_for_type('farm')
    distribution_tvl = calculate_tvl_for_type('distribution')
    save_snapshot(farm_tvl, distribution_tvl)


@repeat_every(60)  # once in a minute
async def update_contracts_worker():
    print('updating contract caches...')
    await update_contracts_cache('farm')
    await update_contracts_cache('distribution')
    await update_contracts_cache('crowdsale')

    await record_contracts_stats()


# TODO: graceful shutdown here (with signal handling?)
def run_background():
    async def tasks():
        await asyncio.gather(
            update_contracts_worker(),
        )

    asyncio.run(tasks())


# Runs in a separate process to use a separate asyncio loop from uvicorn,
# since reusing the uvicorn's one is hacky and sad
@contextmanager
def start_bg_tasks():
    proc = spawn.Process(target=run_background)
    proc.start()
    print("STARTED BG TASKS", proc)
    try:
        yield proc
    finally:
        proc.terminate()
        proc.join()

