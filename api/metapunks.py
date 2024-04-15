from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List

from blockchain.indexer import get_asset_ids_by_creator, get_asset_owner

META_ADDRESSES = [
    'METAGTX4BELE3WVMF5GUOYZMCDYFMDEKBWBP6VLDF6AKTNFWJSGKUFDAYU',
    'METASWXOZB3CFFNWD6BDWU7CG5E42HNWFJZMM6IWR7MCT4P7NDW6755IMM',
    'METAGLOPQRWQFZVA5Q2CFSVXEBPGWW4AUHZTC6B2ZQ6UQW24PS5JAMLQSY',
    'METAEVEML4X7TXWHCBP4TKJDUZ7X2O7MSRECM57YA5TPFYSAI6J7WKCX3E', # Custom
    'METAUPN7HLU67ASI4YBYX3BWZEXNYL2CQWGCZES2DM7AGXAHUDZQ2LZMEY',  # Legendary
    'METAA3F2YB75XA4JADKKETAXH2YXLIDLZ4VWPT2CPUOJDDKQAIUGJIIGPA'  # YBG
]


def get_all_metapunk_ids() -> List[int]:
    res = []
    for address in META_ADDRESSES:
        asset_ids = get_asset_ids_by_creator(address)
        res = res + asset_ids
    return res


def get_listed_ids() -> List[int]:
    res = []
    for address in META_ADDRESSES:
        sales = nft_market.get_sales(address)
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


def get_holders() -> List[HolderInfo]:
    ids = get_unlisted_ids()
    print(f'Got {len(ids)} unlisted Metapunks!')
    holders = defaultdict(list)
    for i, asa_id in enumerate(ids[:100]):
        address = get_asset_owner(asa_id)
        holders[address].append(asa_id)
        if i % 10 == 0:
            print(f'#{i}')
    return [HolderInfo(k, v) for k, v in holders.items()]


def asset_owner(asset_id):
    return asset_id, get_asset_owner(asset_id)


def get_holders_async() -> dict:
    ids = get_unlisted_ids()
    print(f'Got {len(ids)} unlisted Metapunks!')
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = executor.map(asset_owner, ids)
    holders = {}
    for asa_id, address in results:
        if address not in holders:
            holders[address] = []
        holders[address].append(asa_id)
    return holders


def get_available() -> List[HolderInfo]:
    holders = get_holders()
    meta_holders = list(filter(lambda x: x.address in META_ADDRESSES, holders))
    return meta_holders


if __name__ == '__main__':
    available_punks = get_available()
    for i, punk in enumerate(available_punks):
        print(f'#{i}: {punk}')
