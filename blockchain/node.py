import logging

from algosdk.error import AlgodHTTPError
from algosdk.v2client.algod import AlgodClient
from cachetools import TTLCache, cached

from env import settings

logger = logging.getLogger(__name__)


def init_algod_client() -> AlgodClient:
    return AlgodClient(
        settings.algod_token,
        settings.algod_address,
        headers={"User-Agent": "py-algorand-sdk", "x-algo-api-token": settings.algod_token},
    )


algod_client = init_algod_client()


@cached(cache=TTLCache(maxsize=1, ttl=settings.block_time))
def get_current_round():
    try:
        data = algod_client.status()
        current_round = data["last-round"]
        get_current_round._last_known_round = current_round
        return current_round
    except AlgodHTTPError as e:
        logger.error(f"Failed to get current round from Algod: {e}")
        fallback = getattr(get_current_round, "_last_known_round", 0)
        logger.warning(f"Using fallback round: {fallback}")
        return fallback
    except Exception as e:
        logger.error(f"Unexpected error getting current round: {e}", exc_info=True)
        return getattr(get_current_round, "_last_known_round", 0)
