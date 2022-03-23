import typing
from dataclasses import dataclass

from src.env import META_ADDRESSES


@dataclass
class Collection:
    name: str
    addresses: typing.List[str]


metapunks_collection = Collection('Metapunks', META_ADDRESSES)
all_collections = [metapunks_collection]


def get_collection(creator: str) -> Collection:
    for collection in all_collections:
        if creator in collection.addresses:
            return collection
    return Collection('Unknown', [creator])
