import logging

import requests
from cachetools import cached, TTLCache

from env import settings
from flex.blockchain import get_current_round, get_address_assets, get_asset_info
from flex.db.model.blockchain import LpToken
from flex.meta_error import MetaError

BASE_URL = 'https://free-api.vestige.fi'


logger = logging.getLogger(__name__)


class DexProvider:
    HUMBLE = 'H2'
    PACT = 'PT'
    TINYMAN = 'T2'
    TINYMAN_V2 = 'T3'


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
    logger.debug(f'Request {url} got response: {data}')

    if 'USD' not in data:
        raise MetaError(f'Failed request {url}: code = {response.status_code}')
    return data['USD']


def get_lp_token_not_cached(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    url = f'{BASE_URL}/pools/{dex_provider}?assets=%5B{asset1_id}%5D'
    response = requests.get(url)
    data = response.json()
    for token_data in data:
        if token_data['token_id'] == lp_token_id:
            price_algo = token_data['price']
            address = token_data['address']
            address_balances = get_address_assets(address)

            asset1_reserve = None
            for asset in address_balances:
                if asset.asa_id == asset1_id:
                    asset1_reserve = asset.amount_micros
            asset2_reserve = None
            for asset in address_balances:
                if asset.asa_id == asset2_id:
                    asset2_reserve = asset.amount_micros

            asset1 = get_asset_info(asset1_id)
            asset2 = get_asset_info(asset2_id)

            return LpToken(
                id=lp_token_id,
                app_id=token_data['application_id'],
                asset1_id=asset1_id,
                asset2_id=asset2_id,
                dex_provider=dex_provider,
                address=address,
                asset1_reserve=asset1.micros_to_amount(asset1_reserve),
                asset2_reserve=asset2.micros_to_amount(asset2_reserve),
                price_usd=price_algo * get_algo_price_usd(),
                last_updated_round=get_current_round()
            )
