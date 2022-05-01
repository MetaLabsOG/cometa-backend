# from api.metapunks import META_ADDRESSES
from marketplaces import Collection

# TODO: use db
# metapunks_collection = Collection('Metapunks', META_ADDRESSES)
# all_collections = [metapunks_collection]
all_collections = []


def get_collection(creator: str) -> Collection:
    for collection in all_collections:
        if creator in collection.addresses:
            return collection
    return Collection('Unknown', [creator])
