import logging
from dataclasses import dataclass
from enum import Enum

import requests
from cachetools import cached, TTLCache

from env import settings
from flex.db.model.blockchain import LpToken
from flex.meta_error import MetaError

BASE_URL = 'https://free-api.vestige.fi'


logger = logging.getLogger(__name__)


class DexProvider(str, Enum):
    HUMBLE = 'H2'
    PACT = 'PT'
    TINYMAN = 'T2'
    TINYMAN_V2 = 'T3'
    ANY = 'ANY'


DEX_PROVIDER_BY_NAME = {
    'humble': DexProvider.HUMBLE,
    'pact': DexProvider.PACT,
    'tinyman': DexProvider.TINYMAN_V2,
    'tinymanold': DexProvider.TINYMAN,
}

DEX_PROVIDERS = list(DEX_PROVIDER_BY_NAME.values())


def is_valid_dex_provider(dex_provider: str) -> bool:
    return dex_provider in DEX_PROVIDERS


def get_dex_tag_by_name(name: str) -> str:
    return DEX_PROVIDER_BY_NAME.get(name.lower()) or name


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
def get_full_asset_price(asset_id: int) -> Price:
    return get_full_asset_price_not_cached(asset_id)


def get_full_asset_price_not_cached(asset_id: int) -> Price:
    if asset_id == 0:
        return Price(algo=1, usd=get_algo_price_usd())

    url = f'{BASE_URL}/asset/{asset_id}/price'
    response = requests.get(url)
    data = response.json()

    if 'USD' not in data:
        raise MetaError(f'Failed request {url}: code = {response.status_code}')
    return Price(algo=data['price'], usd=data['USD'])


def fetch_lp_token(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    ref_id = asset2_id if asset1_id == 0 else asset1_id
    url = f'{BASE_URL}/pools/{dex_provider}?assets=%5B{ref_id}%5D'
    response = requests.get(url)
    data = response.json()
    for token_data in data:
        if token_data['token_id'] == lp_token_id:
            address = token_data['address']
            return LpToken(
                id=lp_token_id,
                pool_id=token_data['id'],
                asset1_id=asset1_id,
                asset2_id=asset2_id,
                dex_provider=dex_provider,
                address=address,
            )
