import asyncio
import multiprocessing

from contextlib import contextmanager
from api.contract_manager import get_contracts, update_contract
from api.js_interop import calljs

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
        existing_metadatas = { info.id: info.metadata for info in contracts }
        states = await calljs("fetchContractsGlobalViews", contractType=type, ids=list(existing_metadatas.keys()))

        for s_id, state in states.items():
            id = int(s_id)
            old_metadata = existing_metadatas[id]
            if old_metadata is None:
                old_metadata = {}

            new_metadata = {**old_metadata, "cache": state}
            update_contract(id, None, new_metadata) 
    
        print(f'updated state cache for contracts: {type}')

@repeat_every(60) # once in a minute
async def update_contracts_worker():
    print('updating contract caches...')
    await update_contracts_cache('farm')
    await update_contracts_cache('distribution')
    await update_contracts_cache('crowdsale')

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

