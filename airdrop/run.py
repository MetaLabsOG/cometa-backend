from blockchain.indexer import get_asset_ids_by_creator
from env import META_ADDRESSES


def get_metapunk_ids():
    res = []
    for address in META_ADDRESSES:
        asset_ids = get_asset_ids_by_creator(address)
        res = res + asset_ids
    return res


