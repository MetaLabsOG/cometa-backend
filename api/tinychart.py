import requests
from cachetools import cached, TTLCache

from env import settings

BASE_URL = 'https://free-api.vestige.fi'


@cached(cache=TTLCache(maxsize=1, ttl=settings.algo_price_ttl))
def get_algo_price() -> float:
    url = f'{BASE_URL}/currency/USD/price'
    data = requests.get(url).json()
    return data['price']
