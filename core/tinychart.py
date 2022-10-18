import logging
from dataclasses import dataclass

import requests
from cachetools import cached, TTLCache

from blockchain.assets import MICROALGOS_IN_ALGO
from env import settings

BASE_URL = 'https://free-api.vestige.fi'

logger = logging.getLogger(__name__)


@dataclass
class Price:
    usd: float
    microalgo: int

    def multiply(self, mul: float) -> 'Price':
        return Price(self.usd * mul, int(self.microalgo * mul))


@cached(cache=TTLCache(maxsize=1, ttl=settings.algo_price_ttl))
def get_algo_price() -> float:
    # https://free-api.vestige.fi/asset/773632446/price
    url = f'{BASE_URL}/currency/USD/price'
    data = requests.get(url).json()
    return data['price']


@cached(cache=TTLCache(maxsize=1024, ttl=settings.asset_prices_ttl))
def get_asset_price(asset_id: int) -> float:
    if asset_id == 0:
        return get_algo_price()
    url = f'{BASE_URL}/asset/{asset_id}/price'
    logger.debug(f'Getting price for asset {asset_id} from {url}')
    data = requests.get(url).json()
    logger.debug(f'Response: {data}')
    return data['USD']


def get_asset_price_full(asset_id: int) -> Price:
    asset_usd_price = get_asset_price(asset_id)
    algo_price = get_algo_price()
    return Price(asset_usd_price, int(asset_usd_price / algo_price * MICROALGOS_IN_ALGO))
