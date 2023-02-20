from typing import List

import requests

from blockchain.assets import MICROALGOS_IN_ALGO
from .marketplace import Marketplace, Sale


# {
#     "assetId": 358535631,
#     "sellerAddress": "P6J2VWA74BDEMKQR3TBX33TPDPT7NIRG2RZE3VBIWFMPYVXKCNBHCJIDZ4",
#     "timestamp": 1643051869000,
#     "price": 2669.69,
#     "version": "legacy"
# }
class RandGallery(Marketplace):
    def get_sales(self, creator: str) -> List[Sale]:
        # TODO: fix, use correct randgallery api
        return []
        url = f'https://www.randswap.com/v1/listings/creator/{creator}'
        sales = requests.get(url).json()
        return [Sale(
            sale['assetId'],
            int(sale['price'] * MICROALGOS_IN_ALGO),
            sale['sellerAddress']
        ) for sale in sales]
