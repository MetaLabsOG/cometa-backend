import requests


# {
#     "asa_id": 484970203,
#     "price": 420,
#     "seller_account": "F27OIWBY5VXUTK6I2I3EX5FSRSEKI43RR66FYBDLLQ6SPE6H3MZ677CXKA",
#     "type": "sale"
# }
def get_sales(creator: str):
    url = f'https://algogems.io/api/nftexplorer/sales?address={creator}'
    return requests.get(url).json()['metadata']


def get_floor_price(creator: str):
    sales = get_sales(creator)
    return min(s['price'] for s in sales)

