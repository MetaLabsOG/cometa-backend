import logging
from dataclasses import dataclass

import httpx
from cachetools import TTLCache, cached

from blockchain.assets import MICROALGOS_IN_ALGO
from env import settings

BASE_URL = "https://api.vestigelabs.org"
USDC_ASSET_ID = 31566704

logger = logging.getLogger(__name__)

_http_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


@dataclass
class Price:
    usd: float
    microalgo: int

    def multiply(self, mul: float) -> "Price":
        return Price(self.usd * mul, int(self.microalgo * mul))


@cached(cache=TTLCache(maxsize=1, ttl=settings.algo_price_ttl))
def get_algo_price() -> float:
    url = f"{BASE_URL}/assets/price?asset_ids=0&denominating_asset_id={USDC_ASSET_ID}"
    data = _get_client().get(url).json()
    if isinstance(data, list) and len(data) > 0:
        return data[0]["price"]
    logger.error(f"Failed to get ALGO price from Vestige: {data}")
    return 0.0


@cached(cache=TTLCache(maxsize=1024, ttl=settings.asset_prices_ttl))
def get_asset_price(asset_id: int) -> float:
    if asset_id == 0:
        return get_algo_price()
    url = f"{BASE_URL}/assets/price?asset_ids={asset_id}&denominating_asset_id={USDC_ASSET_ID}"
    logger.debug(f"Getting price for asset {asset_id} from {url}")
    data = _get_client().get(url).json()
    logger.debug(f"Response: {data}")
    if isinstance(data, list) and len(data) > 0:
        return data[0]["price"]
    logger.error(f"No price data for asset {asset_id}: {data}")
    return 0.0


def get_asset_price_full(asset_id: int) -> Price:
    asset_usd_price = get_asset_price(asset_id)
    algo_price = get_algo_price()
    return Price(asset_usd_price, int(asset_usd_price / algo_price * MICROALGOS_IN_ALGO) if algo_price > 0 else 0)
