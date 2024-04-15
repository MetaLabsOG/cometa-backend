import logging
from dataclasses import dataclass
from enum import Enum

import requests
from cachetools import cached, TTLCache

from env import settings
from flex.meta_error import MetaError

BASE_URL = 'https://free-api.vestige.fi'


logger = logging.getLogger(__name__)


class DexProvider(str, Enum):
    HUMBLE = 'H2'
    PACT = 'PT'
    TINYMAN = 'T2'
    TINYMAN_V2 = 'T3'


@dataclass
class Price:
    algo: float
    usd: float


@cached(cache=TTLCache(ttl=settings.algo_price_ttl, maxsize=1))
def get_algo_price_usd() -> float:
    url = f'{BASE_URL}/currency/USD/price'
    data = requests.get(url).json()
    return data['price']


@cached(cache=TTLCache(maxsize=1024, ttl=settings.asset_prices_ttl))
def get_asset_price_usd(asset_id: int) -> float:
    return get_asset_price_usd_not_cached(asset_id)


def get_asset_price_usd_not_cached(asset_id: int) -> float:
    if asset_id == 0:
        return get_algo_price_usd()

    url = f'{BASE_URL}/asset/{asset_id}/price'
    response = requests.get(url)
    data = response.json()

    if 'USD' not in data:
        raise MetaError(f'Failed request {url}: code = {response.status_code}')
    return data['USD']


@cached(cache=TTLCache(maxsize=1024, ttl=settings.asset_prices_ttl))
def get_asset_price(asset_id: int) -> Price:
    return get_asset_price_not_cached(asset_id)


def get_asset_price_not_cached(asset_id: int) -> Price:
    if asset_id == 0:
        return Price(algo=1, usd=get_algo_price_usd())

    url = f'{BASE_URL}/asset/{asset_id}/price'
    response = requests.get(url)
    data = response.json()

    if 'USD' not in data:
        raise MetaError(f'Failed request {url}: code = {response.status_code}')
    return Price(algo=data['price'], usd=data['USD'])
