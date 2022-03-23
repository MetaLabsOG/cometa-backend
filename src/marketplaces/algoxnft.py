import requests


# {
#     "asset_id": 486657711,
#     "buy_it_now_listing_id": 7487,
#     "link": "https://algoxnft.com/buy-it-now-listing/7487",
#     "price": 4999000000,
#     "seller": "J22F6WZWRA5TEM7A5PYGMMEZVU3LC6JRI3AASMWAVZUU743I23OP3LS7TQ",
#     "type": "buy-it-now"
# }
def get_sales(creator: str):
    url = f'https://api.algoxnft.com/v1/nft-explorer/creator/{creator}'
    return requests.get(url).json()


def get_floor_price(creator: str) -> int:
    sales = get_sales(creator)
    return min(s['price'] for s in sales)
