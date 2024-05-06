import asyncio
import json

from flex import db
from flex.blockchain.base import indexer_client
from flex.sync_pools import find_transfer_transactions, process_pool_transactions

# 01.02 — 30.04

DATE_0_BLOCK = 35720000

DATE_1_BLOCK = 37530000
DATE_1_ALGO_PRICE = 0.251

DATE_2_BLOCK = 38496000


async def calculate_pool_tvl(pool_address: str) -> int:
    total_tvl = 0
    next_token = None
    while True:
        data = indexer_client.search_transactions_by_address(
            address=pool_address,
            next_page=next_token
        )
        txns = data['transactions']
        print(f'Pool {pool_address}: processing {len(txns)} txns...')

        raw_txns = find_transfer_transactions(txns)
        pool_txns = await process_pool_transactions(raw_txns)

        for pool_tx in pool_txns:
            if pool_tx.confirmed_round < DATE_2_BLOCK:
                total_tvl += pool_tx.delta_amount_micros

        if 'next-token' in data:
            next_token = data['next-token']
        else:
            break

    return total_tvl


async def get_user_transactions(pool_address: str, start_block: int, end_block: int, pool_id: int, ind: int | None = None) -> dict:
    print(f'#{ind}: {pool_address}')
    address_txns = {}
    next_token = None
    while True:
        data = indexer_client.search_transactions_by_address(
            address=pool_address,
            next_page=next_token,
            min_round=start_block,
            max_round=end_block
        )
        txns = data['transactions']
        print(f'Pool {pool_id}: processing {len(txns)} txns...')

        for tx in txns:
            confirmed_round = tx['confirmed-round']
            if confirmed_round < start_block or confirmed_round > end_block:
                continue
            txid = tx['id']
            sender = tx['sender']
            address_txns.setdefault(sender, []).append(txid)

        if 'next-token' in data:
            next_token = data['next-token']
        else:
            break

    print(f'#{ind}: {len(address_txns)} users')

    return {
        'txns': address_txns,
        'pool_id': pool_id
    }


async def get_all_user_transactions(start_block: int, end_block: int) -> dict[str, dict[str, list[str]]]:
    farm_pools = db.farming_pools.get_all()
    pool_id_address = {p.id: p.address for p in farm_pools}
    staking_pools = db.staking_pools.get_all()
    pool_id_address.update({p.id: p.address for p in staking_pools})
    print(f'Getting user txns from {len(pool_id_address)} pools...')

    user_txns_cors = []
    ind = 1
    for pool_id, pool_address in pool_id_address.items():
        user_pool_txns_co = get_user_transactions(pool_address, start_block, end_block, pool_id=pool_id, ind = ind)
        user_txns_cors.append(user_pool_txns_co)
        ind += 1

    user_pool_txns = await asyncio.gather(*user_txns_cors)
    user_txns_by_pool_id = {}
    for res in user_pool_txns:
        txns_dict = res['txns']
        pool_id = res['pool_id']
        for user, txns in txns_dict.items():
            user_txns_by_pool_id.setdefault(user, {})[pool_id] = len(txns)

    return user_txns_by_pool_id


async def fetch_and_record_user_txns() -> dict:
    user_txns = await get_all_user_transactions(DATE_0_BLOCK, DATE_1_BLOCK)
    with open(f'user_txns_{DATE_0_BLOCK}_{DATE_1_BLOCK}.json', 'w') as f:
        json.dump(user_txns, f)

    print(f'In total {len(user_txns)} users in the period {DATE_0_BLOCK} - {DATE_1_BLOCK}')
    return user_txns
