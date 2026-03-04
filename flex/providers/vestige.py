import asyncio
import logging
from dataclasses import dataclass
from enum import Enum

import httpx
from aiocache import cached

from env import settings
from flex.db.model.blockchain import LpToken
from flex.meta_error import MetaError
from flex.util import build_key_str

BASE_URL = 'https://api.vestigelabs.org'
USDC_ASSET_ID = 31566704


logger = logging.getLogger(__name__)

_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


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


@cached(ttl=settings.algo_price_ttl, namespace='algo_price', key='algo_price')
async def get_algo_price_usd() -> float:
    url = f'{BASE_URL}/assets/price?asset_ids=0&denominating_asset_id={USDC_ASSET_ID}'
    client = _get_client()
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list) and len(data) > 0:
        return data[0]['price']
    raise MetaError(f'Failed to get ALGO price from Vestige API: {data}')


@cached(ttl=settings.asset_prices_ttl, namespace='vestige_asset_price', key_builder=build_key_str)
async def get_asset_price_usd(asset_id: int) -> float:
    return await get_asset_price_usd_not_cached(asset_id)


async def get_asset_price_usd_not_cached(asset_id: int) -> float:
    if asset_id == 0:
        return await get_algo_price_usd()

    url = f'{BASE_URL}/assets/price?asset_ids={asset_id}&denominating_asset_id={USDC_ASSET_ID}'
    client = _get_client()
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()

    if isinstance(data, list) and len(data) > 0:
        return data[0]['price']
    raise MetaError(f'Failed to get price for asset {asset_id} from Vestige API: {data}')


async def vestige_full_asset_price_not_cached(asset_id: int) -> Price:
    if asset_id == 0:
        algo_price_usd = await get_algo_price_usd()
        return Price(algo=1, usd=algo_price_usd)

    try:
        client = _get_client()
        url_usd = f'{BASE_URL}/assets/price?asset_ids={asset_id}&denominating_asset_id={USDC_ASSET_ID}'
        url_algo = f'{BASE_URL}/assets/price?asset_ids={asset_id}&denominating_asset_id=0'

        response_usd, response_algo = await asyncio.gather(
            client.get(url_usd),
            client.get(url_algo),
        )
        response_usd.raise_for_status()
        response_algo.raise_for_status()
        data = response_usd.json()

        if not isinstance(data, list) or len(data) == 0:
            raise MetaError(f'No price data for asset {asset_id}. Response: {data}')

        price_usd = data[0]['price']

        data_algo = response_algo.json()
        price_algo = data_algo[0]['price'] if isinstance(data_algo, list) and len(data_algo) > 0 else 0

        return Price(algo=price_algo, usd=price_usd)
    except httpx.HTTPError as e:
        logger.error(f"Vestige API request failed for asset {asset_id}: {e}")
        raise MetaError(f'Failed to fetch price from Vestige API: {e}')
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid response from Vestige API for asset {asset_id}: {e}")
        raise MetaError(f'Invalid response from Vestige API: {e}')


@cached(ttl=settings.asset_prices_ttl, namespace='full_asset', key_builder=build_key_str)
async def vestige_full_asset_price(asset_id: int) -> Price:
    return await vestige_full_asset_price_not_cached(asset_id)


async def fetch_lp_token(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    ref_id = asset2_id if asset1_id == 0 else asset1_id
    url = f'{BASE_URL}/pools?asset_1_id={ref_id}&limit=100'
    client = _get_client()
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()
    results = data.get('results', data) if isinstance(data, dict) else data
    for token_data in results:
        if token_data['token_id'] == lp_token_id:
            address = token_data['address']
            if asset1_id < asset2_id:
                asset1_id, asset2_id = asset2_id, asset1_id
            return LpToken(
                id=lp_token_id,
                pool_id=token_data['id'],
                asset1_id=asset1_id,
                asset2_id=asset2_id,
                dex_provider=dex_provider,
                address=address,
            )
