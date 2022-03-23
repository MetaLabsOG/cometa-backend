import typing
import requests

from src.env import MICROALGOS_IN_ALGO


# {
#     "assetId": 358535631,
#     "sellerAddress": "P6J2VWA74BDEMKQR3TBX33TPDPT7NIRG2RZE3VBIWFMPYVXKCNBHCJIDZ4",
#     "timestamp": 1643051869000,
#     "price": 2669.69,
#     "version": "legacy"
# }
def get_sales(creator: str):
    url = f'https://www.randswap.com/v1/listings/creator/{creator}'
    return requests.get(url).json()


def get_floor_price(creator: str) -> int:
    sales = get_sales(creator)
    prices = (int(s['price'] * MICROALGOS_IN_ALGO) for s in sales)
    return min(prices, default=None)
