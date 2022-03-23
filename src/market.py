import typing

from src.collections import get_collection
from src.indexer import get_asset_creator
from src.marketplaces import algoxnft, randgallery, algogems
from src.util import pretty


def get_floor_price(asset_id: int) -> int:
    creator = get_asset_creator(asset_id)
    collection = get_collection(creator)
    result = None
    for address in collection.addresses:
        floor_price = min(algoxnft.get_floor_price(address),
                          algogems.get_floor_price(address),
                          randgallery.get_floor_price(address))
        if result is None or result > floor_price:
            result = floor_price

    return result


if __name__ == '__main__':
    # print(pretty(randgallery.get_sales('MNGOLDXO723TDRM6527G7OZ2N7JLNGCIH6U2R4MOCPPLONE3ZATOBN7OQM')))
    # print(pretty(algogems.get_sales('METAGTX4BELE3WVMF5GUOYZMCDYFMDEKBWBP6VLDF6AKTNFWJSGKUFDAYU')))
    print(get_floor_price(486657711))
