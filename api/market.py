from typing import List

from .collection_manager import get_collection
from blockchain.indexer import get_asset_creator
from marketplaces import AlgoGems, RandGallery, AlgoXNft, Marketplace, Sale

algogems = AlgoGems()
randgallery = RandGallery()
algoxnft = AlgoXNft()

marketplaces: List[Marketplace] = [algogems, randgallery, algoxnft]


# TODO: make market a class
def get_sales(creator: str) -> List[Sale]:
    sales = []
    for marketplace in marketplaces:
        sales += marketplace.get_sales(creator)
    return sales


def get_floor_price(asset_id: int) -> int:
    # TODO: catch exceptions GRACEFULLY
    creator = get_asset_creator(asset_id)
    collection = get_collection(creator)
    marketplace_floors = [m.get_collection_floor_price(collection) for m in marketplaces]
    return min(filter(None, marketplace_floors), default=None)


def test():
    # print(algogems.get_sales('METAGTX4BELE3WVMF5GUOYZMCDYFMDEKBWBP6VLDF6AKTNFWJSGKUFDAYU'))
    # print(randgallery.get_sales('MNGOLDXO723TDRM6527G7OZ2N7JLNGCIH6U2R4MOCPPLONE3ZATOBN7OQM'))
    # print(algoxnft.get_sales('METAGTX4BELE3WVMF5GUOYZMCDYFMDEKBWBP6VLDF6AKTNFWJSGKUFDAYU'))
    print(get_floor_price(326189642))
