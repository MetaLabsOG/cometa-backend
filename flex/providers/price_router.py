"""Price routing with fallback chain: DB cache → Vestige → Tinyman Analytics → CoinGecko.

Single entry point for all price lookups. Handles provider failures gracefully.
"""

import logging

import httpx

from flex import db
from flex.providers.vestige import Price

logger = logging.getLogger(__name__)

_http_client: httpx.AsyncClient | None = None

TINYMAN_ANALYTICS_BASE = 'https://mainnet.analytics.tinyman.org/api/v1'
COINGECKO_ALGO_URL = 'https://api.coingecko.com/api/v3/simple/price?ids=algorand&vs_currencies=usd'


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


async def _algo_price_from_coingecko() -> float:
    """Fetch ALGO/USD price from CoinGecko free API."""
    client = _get_client()
    response = await client.get(COINGECKO_ALGO_URL)
    response.raise_for_status()
    data = response.json()
    return data['algorand']['usd']


async def _algo_price_from_tinyman() -> float:
    """Fetch ALGO price from Tinyman Analytics (asset 0)."""
    client = _get_client()
    url = f'{TINYMAN_ANALYTICS_BASE}/assets/0/'
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()
    return float(data['price_in_usd'])


async def _asset_price_from_tinyman(asset_id: int) -> Price:
    """Fetch asset price from Tinyman Analytics."""
    client = _get_client()
    url = f'{TINYMAN_ANALYTICS_BASE}/assets/{asset_id}/'
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()
    price_algo = float(data.get('price_in_algo', 0))
    price_usd = float(data.get('price_in_usd', 0))
    return Price(algo=price_algo, usd=price_usd)


async def get_algo_price_usd() -> float:
    """Get ALGO/USD price with fallback chain: Vestige → Tinyman → CoinGecko → DB."""
    from flex.providers.vestige import get_algo_price_usd as vestige_algo_price

    # 1. Vestige (primary, has its own cache)
    try:
        return await vestige_algo_price()
    except Exception as e:
        logger.warning(f'Vestige ALGO price failed: {e}')

    # 2. Tinyman Analytics
    try:
        price = await _algo_price_from_tinyman()
        if price > 0:
            logger.info(f'ALGO price from Tinyman: ${price}')
            return price
    except Exception as e:
        logger.warning(f'Tinyman ALGO price failed: {e}')

    # 3. CoinGecko
    try:
        price = await _algo_price_from_coingecko()
        if price > 0:
            logger.info(f'ALGO price from CoinGecko: ${price}')
            return price
    except Exception as e:
        logger.warning(f'CoinGecko ALGO price failed: {e}')

    # 4. Last resort: most recent ALGO price from DB (asset_id=0)
    algo_record = db.asset_prices.get_one(id=0)
    if algo_record is not None and algo_record.price_usd > 0:
        logger.warning(f'Using stale ALGO price from DB: ${algo_record.price_usd}')
        return algo_record.price_usd

    raise RuntimeError('All ALGO price providers failed and no DB fallback available')


async def get_asset_price(asset_id: int) -> Price:
    """Get asset price with fallback chain: DB → Vestige → Tinyman Analytics.

    Returns Price(algo, usd). Raises RuntimeError if all providers fail.
    """
    if asset_id == 0:
        algo_usd = await get_algo_price_usd()
        return Price(algo=1.0, usd=algo_usd)

    # 1. DB cache (freshest)
    record = db.asset_prices.get_one(id=asset_id)
    if record is not None and record.price_algo > 0:
        return Price(algo=record.price_algo, usd=record.price_usd)

    # 2. Vestige
    from flex.providers.vestige import vestige_full_asset_price
    try:
        return await vestige_full_asset_price(asset_id)
    except Exception as e:
        logger.warning(f'Vestige price failed for asset {asset_id}: {e}')

    # 3. Tinyman Analytics
    try:
        price = await _asset_price_from_tinyman(asset_id)
        if price.algo > 0 or price.usd > 0:
            logger.info(f'Asset {asset_id} price from Tinyman: algo={price.algo}, usd={price.usd}')
            return price
    except Exception as e:
        logger.warning(f'Tinyman price failed for asset {asset_id}: {e}')

    raise RuntimeError(f'All price providers failed for asset {asset_id}')
