import json

from api.pool_snapshot import get_pool_snapshot
from core.db.contracts import get_contracts_by_type
from core.util import parse_bignum


OUTAGE_ROUND = 36034104


def snapshot_all() -> dict:
    contracts = get_contracts_by_type(type=None)
    LATEST_BLOCK = 35264929 # 17.01.24 00:55
    MONTH_BLOCKS = 785454
    THRESHOLD_BLOCK = LATEST_BLOCK - MONTH_BLOCKS
    recent_pools = []
    for contract in contracts:
        cache = contract.metadata.get('cache')
        if cache is None:
            continue
        initial = cache.get('initial')
        if initial is None:
            continue
        end_block = parse_bignum(initial['endBlock'])
        if end_block > THRESHOLD_BLOCK:
            recent_pools.append(contract)

    user_pools = {}

    for pool in recent_pools:
        snapshot_dict = get_pool_snapshot(pool.id, max_round=OUTAGE_ROUND)
        with open(f'snapshots/{pool.id}.json', 'w') as f:
            json.dump(snapshot_dict, f, indent=4)

        for address, balance in snapshot_dict.items():
            if balance > 0:
                if address not in user_pools:
                    user_pools[address] = []
                user_pools[address].append(pool.id)

    with open('snapshots/user_pools.json', 'w') as f:
        json.dump(user_pools, f, indent=4)

    return user_pools
