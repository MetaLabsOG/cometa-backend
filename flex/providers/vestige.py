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

# HTTP status codes that indicate Vestige is unavailable (not a data error)
_UNAVAILABLE_STATUSES = {403, 429, 502, 503, 504}

logger = logging.getLogger(__name__)


class VestigeUnavailableError(Exception):
    """Raised when Vestige API is unreachable (403/429/5xx)."""
    pass


def _check_response(response: httpx.Response) -> None:
    """Raise VestigeUnavailableError for 403/429/5xx, raise_for_status for other errors."""
    if response.status_code in _UNAVAILABLE_STATUSES:
        raise VestigeUnavailableError(
            f'Vestige API returned {response.status_code}: {response.text[:200]}'
        )
    response.raise_for_status()

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
    _check_response(response)
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
    _check_response(response)
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
        _check_response(response_usd)
        _check_response(response_algo)
        data = response_usd.json()

        if not isinstance(data, list) or len(data) == 0:
            raise MetaError(f'No price data for asset {asset_id}. Response: {data}')

        price_usd = data[0]['price']

        data_algo = response_algo.json()
        price_algo = data_algo[0]['price'] if isinstance(data_algo, list) and len(data_algo) > 0 else 0

        return Price(algo=price_algo, usd=price_usd)
    except VestigeUnavailableError:
        raise
    except httpx.HTTPError as e:
        logger.error(f"Vestige API request failed for asset {asset_id}: {e}")
        raise MetaError(f'Failed to fetch price from Vestige API: {e}')
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid response from Vestige API for asset {asset_id}: {e}")
        raise MetaError(f'Invalid response from Vestige API: {e}')


@cached(ttl=settings.asset_prices_ttl, namespace='vestige_price', key_builder=build_key_str)
async def vestige_full_asset_price(asset_id: int) -> Price:
    return await vestige_full_asset_price_not_cached(asset_id)


async def _vestige_batch_chunk(chunk_ids: list[int]) -> dict[int, Price]:
    """Fetch prices for a chunk of assets from Vestige."""
    ids_str = ','.join(str(aid) for aid in chunk_ids)
    url_algo = f'{BASE_URL}/assets/price?asset_ids={ids_str}&denominating_asset_id=0'
    url_usd = f'{BASE_URL}/assets/price?asset_ids={ids_str}&denominating_asset_id={USDC_ASSET_ID}'

    client = _get_client()
    response_algo, response_usd = await asyncio.gather(
        client.get(url_algo),
        client.get(url_usd),
    )
    _check_response(response_algo)
    _check_response(response_usd)

    data_algo = response_algo.json()
    data_usd = response_usd.json()

    if not isinstance(data_algo, list) or not isinstance(data_usd, list):
        logger.error(f"Vestige batch: unexpected response format. algo={type(data_algo)}, usd={type(data_usd)}")
        return {}

    usd_by_id = {}
    for item in data_usd:
        aid = item.get('asset_id')
        if aid is not None:
            usd_by_id[aid] = item.get('price', 0)

    result = {}
    for item in data_algo:
        aid = item.get('asset_id')
        if aid is None:
            continue
        price_algo = item.get('price', 0)
        price_usd = usd_by_id.get(aid, 0)
        result[aid] = Price(algo=price_algo, usd=price_usd)

    return result


VESTIGE_BATCH_CHUNK_SIZE = 100


async def vestige_batch_prices(asset_ids: list[int]) -> dict[int, Price]:
    """Fetch prices for multiple assets using Vestige batch API (chunked)."""
    if not asset_ids:
        return {}

    result = {}
    for i in range(0, len(asset_ids), VESTIGE_BATCH_CHUNK_SIZE):
        chunk = asset_ids[i:i + VESTIGE_BATCH_CHUNK_SIZE]
        try:
            chunk_result = await _vestige_batch_chunk(chunk)
            result.update(chunk_result)
        except httpx.HTTPError as e:
            logger.error(f"Vestige batch chunk failed ({len(chunk)} assets): {e}")
        except Exception as e:
            logger.error(f"Vestige batch chunk error: {e}")

    logger.info(f'Vestige batch: fetched {len(result)} prices for {len(asset_ids)} requested assets')
    return result


async def fetch_lp_token(lp_token_id: int, asset1_id: int, asset2_id: int, dex_provider: str) -> LpToken:
    ref_id = asset2_id if asset1_id == 0 else asset1_id
    url = f'{BASE_URL}/pools?asset_1_id={ref_id}&limit=100'
    client = _get_client()
    response = await client.get(url)
    _check_response(response)
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
