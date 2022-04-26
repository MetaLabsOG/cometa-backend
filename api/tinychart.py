import requests

BASE_URL = 'https://free-api.vestige.fi'


# TODO: cache value
def get_algo_price() -> float:
    url = f'{BASE_URL}/currency/USD/price'
    data = requests.get(url).json()
    return data['price']
