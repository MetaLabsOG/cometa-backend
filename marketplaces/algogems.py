from typing import List

import requests

from blockchain.assets import MICROALGOS_IN_ALGO
from .marketplace import Sale, Marketplace


# {
#     "asa_id": 484970203,
#     "price": 420,
#     "seller_account": "F27OIWBY5VXUTK6I2I3EX5FSRSEKI43RR66FYBDLLQ6SPE6H3MZ677CXKA",
#     "type": "sale"
# }
class AlgoGems(Marketplace):
    def get_sales(self, creator: str) -> List[Sale]:
        # TODO: fix Algogems rate limiting
        return []
        url = f'https://algogems.io/api/nftexplorer/sales?address={creator}'
        sales = requests.get(url).json()['metadata']
        return [Sale(
            sale['asa_id'],
            int(sale['price'] * MICROALGOS_IN_ALGO),
            sale['seller_account']
        ) for sale in sales]
