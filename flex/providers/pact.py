import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import cast

import httpx
from algosdk import error as algod_error
from algosdk.logic import get_application_address

from env import settings
from flex.blockchain.base import algod_client

logger = logging.getLogger(__name__)

_API_URLS = {
    "mainnet": "https://api.pact.fi",
    "testnet": "https://api.testnet.pact.fi",
}
_MAX_POOL_RESULTS = 100
_MAX_UINT64 = (1 << 64) - 1
_CONFIG_KEY = "Q09ORklH"
_LTID_KEY = "TFRJRA=="

_http_client: httpx.AsyncClient | None = None


class PactPayloadError(ValueError):
    """Pact or Algod returned a response with an unexpected shape."""


@dataclass(frozen=True)
class PactPoolInfo:
    lp_token_id: int
    asset1_id: int
    asset2_id: int
    app_id: int
    address: str


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


def _uint(value: object, *, name: str, allow_zero: bool = True) -> int:
    if isinstance(value, bool):
        raise PactPayloadError(f"{name} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        parsed = int(value)
    else:
        raise PactPayloadError(f"{name} must be an integer")
    if parsed < (0 if allow_zero else 1) or parsed > _MAX_UINT64:
        raise PactPayloadError(f"{name} is out of range")
    return parsed


def _nested_id(pool: dict[str, object], field: str) -> int:
    asset = pool.get(field)
    if not isinstance(asset, dict):
        raise PactPayloadError(f"{field} is missing")
    return _uint(asset.get("on_chain_id"), name=f"{field}.on_chain_id")


def _results(payload: object) -> list[object]:
    if not isinstance(payload, dict):
        raise PactPayloadError("Pact pools response has no results list")
    results = payload.get("results")
    if not isinstance(results, list):
        raise PactPayloadError("Pact pools response has no results list")
    if len(results) > _MAX_POOL_RESULTS:
        raise PactPayloadError("Pact pools response exceeded the requested limit")
    return cast(list[object], results)


def _pool_app_id(
    pool: object,
    *,
    primary_asset_id: int,
    secondary_asset_id: int,
    lp_token_id: int,
) -> int | None:
    if not isinstance(pool, dict):
        raise PactPayloadError("Pact pool entry must be an object")
    if _nested_id(pool, "primary_asset") != primary_asset_id:
        return None
    if _nested_id(pool, "secondary_asset") != secondary_asset_id:
        return None
    if _nested_id(pool, "pool_asset") != lp_token_id:
        return None
    return _uint(pool.get("on_chain_id"), name="pool.on_chain_id", allow_zero=False)


def _decode_config(value: object) -> tuple[int, int]:
    if not isinstance(value, dict) or value.get("type") != 1:
        raise PactPayloadError("CONFIG must be a byte slice")
    encoded = value.get("bytes")
    if not isinstance(encoded, str):
        raise PactPayloadError("CONFIG has no byte value")
    try:
        config = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise PactPayloadError("CONFIG is not valid base64") from exc
    if len(config) not in (24, 32):
        raise PactPayloadError("CONFIG has an unexpected length")
    return (
        int.from_bytes(config[:8], byteorder="big"),
        int.from_bytes(config[8:16], byteorder="big"),
    )


def _on_chain_pool_identity(app_info: object, *, app_id: int) -> tuple[int, int, int]:
    if not isinstance(app_info, dict):
        raise PactPayloadError("Algod application response must be an object")
    if _uint(app_info.get("id"), name="application.id", allow_zero=False) != app_id:
        raise PactPayloadError("Algod returned the wrong application")
    params = app_info.get("params")
    if not isinstance(params, dict) or not isinstance(params.get("global-state"), list):
        raise PactPayloadError("Algod application response has no global state")
    config: tuple[int, int] | None = None
    lp_token_id: int | None = None
    for item in params["global-state"]:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if key == _CONFIG_KEY:
            if config is not None:
                raise PactPayloadError("Algod application response has duplicate CONFIG")
            config = _decode_config(value)
        elif key == _LTID_KEY:
            if lp_token_id is not None:
                raise PactPayloadError("Algod application response has duplicate LTID")
            if not isinstance(value, dict) or value.get("type") != 2:
                raise PactPayloadError("LTID must be an unsigned integer")
            lp_token_id = _uint(value.get("uint"), name="LTID", allow_zero=False)

    if config is None:
        raise PactPayloadError("Algod application response has no CONFIG")
    if lp_token_id is None:
        raise PactPayloadError("Algod application response has no LTID")
    return config[0], config[1], lp_token_id


def _validate_lookup_ids(asset1_id: int, asset2_id: int, lp_token_id: int) -> None:
    for name, value, allow_zero in (
        ("asset1_id", asset1_id, True),
        ("asset2_id", asset2_id, True),
        ("lp_token_id", lp_token_id, False),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise PactPayloadError(f"{name} must be an integer")
        if value < (0 if allow_zero else 1) or value > _MAX_UINT64:
            raise PactPayloadError(f"{name} is out of range")


async def get_pact_pool_info(asset1_id: int, asset2_id: int, lp_token_id: int) -> PactPoolInfo | None:
    """Discover a Pact pool and confirm its LP token against on-chain state."""
    _validate_lookup_ids(asset1_id, asset2_id, lp_token_id)
    try:
        api_url = _API_URLS[settings.algo_network]
    except KeyError as exc:
        raise ValueError(f"Unsupported Pact network: {settings.algo_network}") from exc

    primary_asset_id, secondary_asset_id = sorted((asset1_id, asset2_id))
    try:
        response = await _get_client().get(
            f"{api_url}/api/pools",
            params={
                "primary_asset__on_chain_id": primary_asset_id,
                "secondary_asset__on_chain_id": secondary_asset_id,
                "limit": _MAX_POOL_RESULTS,
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise PactPayloadError("Pact pools response is not valid JSON") from exc

        for raw_pool in _results(payload):
            try:
                app_id = _pool_app_id(
                    raw_pool,
                    primary_asset_id=primary_asset_id,
                    secondary_asset_id=secondary_asset_id,
                    lp_token_id=lp_token_id,
                )
                if app_id is None:
                    continue
                app_info = await asyncio.to_thread(
                    algod_client.application_info,
                    app_id,
                    timeout=10,
                )
                on_chain_primary, on_chain_secondary, on_chain_lp = _on_chain_pool_identity(
                    app_info,
                    app_id=app_id,
                )
                if (on_chain_primary, on_chain_secondary, on_chain_lp) != (
                    primary_asset_id,
                    secondary_asset_id,
                    lp_token_id,
                ):
                    raise PactPayloadError("Pact API pool identity does not match on-chain CONFIG/LTID")
                return PactPoolInfo(
                    lp_token_id=lp_token_id,
                    asset1_id=asset1_id,
                    asset2_id=asset2_id,
                    app_id=app_id,
                    address=get_application_address(app_id),
                )
            except PactPayloadError as exc:
                logger.warning("Ignoring invalid Pact pool candidate: %s", exc)
    except (
        httpx.HTTPError,
        algod_error.AlgodHTTPError,
        algod_error.AlgodResponseError,
        OSError,
        PactPayloadError,
    ) as exc:
        logger.warning(
            "Pact pool lookup failed for assets %s/%s and LP %s: %s",
            asset1_id,
            asset2_id,
            lp_token_id,
            exc,
        )
    return None
