from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict

from dataclasses_json import dataclass_json
from pymongo import MongoClient

from api import market
from blockchain.indexer import get_asset_ids_by_creator, get_asset_owner
from blockchain.node import get_current_round
from env import META_ADDRESSES, DB_NAME, MONGO_PORT

db = MongoClient(port=MONGO_PORT)[DB_NAME]


def get_all_metapunk_ids() -> List[int]:
    res = []
    for address in META_ADDRESSES:
        asset_ids = get_asset_ids_by_creator(address)
        res = res + asset_ids
    return res


def get_listed_ids() -> List[int]:
    res = []
    for address in META_ADDRESSES:
        sales = market.get_sales(address)
        res = res + [s.asa_id for s in sales]
    return res


def get_unlisted_ids() -> List[int]:
    all_ids = get_all_metapunk_ids()
    listed_ids = get_listed_ids()
    return list(set(all_ids) - set(listed_ids))


@dataclass_json
@dataclass
class HolderInfo:
    address: str
    asa_ids: List[int]


def get_holders() -> List[HolderInfo]:
    ids = get_unlisted_ids()
    print(f'Got {len(ids)} unlisted Metapunks!')
    holders = defaultdict(list)
    for i, asa_id in enumerate(ids):
        address = get_asset_owner(asa_id)
        holders[address].append(asa_id)
        if i % 10 == 0:
            print(f'#{i}')
    return [HolderInfo(k, v) for k, v in holders.items()]


def make_snapshot(snapshot_id: int):
    if db.snapshots.find_one({'snapshot_id': snapshot_id}) is not None:
        print(f'Snapshot #{snapshot_id} is already done!')
        return

    current_round = get_current_round()
    start_time = datetime.now()

    print(f'Snapshot #{snapshot_id} in progress!')
    print(f'Current round = {current_round}')
    print(f'Time = {start_time}')

    holders = get_holders()
    nft_count = 0
    holders.sort(reverse=True, key=lambda h: len(h.asa_ids))
    print(f'{len(holders)} holders:')
    for h in holders:
        cur_cnt = len(h.asa_ids)
        print(f'{h.address}: {cur_cnt} Metapunks!')
        nft_count += cur_cnt

    end_time = datetime.now()
    db.snapshots.insert_one(
        {
            'snapshot_id': snapshot_id,
            'start_time': start_time,
            'end_time': end_time,
            'round': current_round,
            'nft_count': nft_count,
            'holders': [h.to_dict() for h in holders]
        }
    )

    print(f'Snapshot was made in {end_time - start_time}')


if __name__ == '__main__':
    make_snapshot(1)
    # print(db.snapshots.find_one({'snapshot_id': -1}))
