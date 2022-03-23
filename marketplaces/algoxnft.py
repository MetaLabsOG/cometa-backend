import requests

from typing import List
from .marketplace import Marketplace, Sale


# {
#     "asset_id": 486657711,
#     "buy_it_now_listing_id": 7487,
#     "link": "https://algoxnft.com/buy-it-now-listing/7487",
#     "price": 4999000000,
#     "seller": "J22F6WZWRA5TEM7A5PYGMMEZVU3LC6JRI3AASMWAVZUU743I23OP3LS7TQ",
#     "type": "buy-it-now"
# }
class AlgoXNft(Marketplace):
    def get_sales(self, creator: str) -> List[Sale]:
        url = f'https://api.algoxnft.com/v1/nft-explorer/creator/{creator}'
        sales = requests.get(url).json()
        return [Sale(
            sale['asset_id'],
            sale['price'],
            sale['seller']
        ) for sale in sales]
