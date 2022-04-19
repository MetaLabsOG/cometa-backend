from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict

from pymongo import MongoClient

from api import market
from blockchain.indexer import get_asset_ids_by_creator, get_asset_owner
from env import META_ADDRESSES

db = MongoClient(port=27017)


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


@dataclass
class HolderInfo:
    address: str
    asa_ids: List[int]


def get_holders() -> List[Dict]:
    ids = get_unlisted_ids()
    holders = defaultdict(list)
    for asa_id in ids:
        address = get_asset_owner(asa_id)
        holders[address].append(asa_id)
    return [{
        'address': k,
        'asa_ids': v
    } for k, v in holders.items()]


def make_snapshot(snapshot_id: int):
    holders = get_holders()
    holders_db = db[f'test{snapshot_id}'].holders
    holders_db.insert_many(holders)


if __name__ == '__main__':
    print(make_snapshot(1))
