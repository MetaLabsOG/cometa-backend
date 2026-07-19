import asyncio
import logging
from dataclasses import dataclass

from aiocache import cached

from blockchain.node import get_current_round as _sync_get_current_round
from flex.blockchain.base import algod_client, indexer_client
from flex.db.model.blockchain import TOTAL_SUPPLY_SOURCE_INDEXER, Asset
from flex.domain.algorand import require_algorand_uint64

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AssetBalanceSnapshot:
    balances: dict[int, int]
    observed_round: int


ALGO_ASSET = Asset(
    id=0,
    decimals=6,
    name="Algorand",
    unit_name="ALGO",
    creator="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ",
    reserve="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ",
    total_supply=10_000_000_000,
    total_supply_micros=10_000_000_000_000_000,
    total_supply_source=TOTAL_SUPPLY_SOURCE_INDEXER,
)


async def _run_sync(func, *args):
    """Run a sync function in executor to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


async def fetch_asset(asset_id: int) -> Asset:
    if asset_id == 0:
        return ALGO_ASSET

    data = await _run_sync(indexer_client.asset_info, asset_id)
    params = data["asset"]["params"]
    return Asset(
        id=asset_id,
        decimals=params["decimals"],
        name=params.get("name", ""),
        unit_name=params.get("unit-name", ""),
        creator=params.get("creator", ""),
        reserve=params.get("reserve", ""),
        total_supply=0,
        total_supply_micros=params["total"],
        total_supply_source=TOTAL_SUPPLY_SOURCE_INDEXER,
    )


async def get_address_assets(address: str) -> dict:
    return (await get_address_asset_snapshot(address, include_algo=False)).balances


async def get_address_assets_with_algo(address: str) -> dict:
    return (await get_address_asset_snapshot(address, include_algo=True)).balances


async def get_address_asset_snapshot(
    address: str,
    *,
    include_algo: bool,
) -> AssetBalanceSnapshot:
    """Read balances and their authoritative Indexer round in one response."""

    data = await _run_sync(indexer_client.account_info, address)
    account_data = data.get("account")
    if not isinstance(account_data, dict):
        raise RuntimeError("Indexer account snapshot has no account object")
    raw_assets = account_data.get("assets")
    if not isinstance(raw_assets, list):
        raise RuntimeError("Indexer account snapshot has no asset holdings")

    asset_balances: dict[int, int] = {}
    for raw_holding in raw_assets:
        if not isinstance(raw_holding, dict):
            raise RuntimeError("Indexer account snapshot contains a malformed asset holding")
        try:
            asset_id = require_algorand_uint64(
                raw_holding.get("asset-id"),
                "Indexer asset-id",
                positive=True,
            )
            amount = require_algorand_uint64(
                raw_holding.get("amount"),
                "Indexer asset amount",
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if asset_id in asset_balances:
            raise RuntimeError(f"Indexer account snapshot repeats asset {asset_id}")
        asset_balances[asset_id] = amount

    if include_algo:
        try:
            asset_balances[0] = require_algorand_uint64(
                account_data.get("amount"),
                "Indexer ALGO amount",
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
    try:
        observed_round = require_algorand_uint64(
            data.get("current-round"),
            "Indexer current-round",
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    return AssetBalanceSnapshot(
        balances=asset_balances,
        observed_round=observed_round,
    )


@cached(ttl=10, namespace="node", key="current_round")
async def get_current_round():
    """Async wrapper around the sync get_current_round (single implementation, shared cache)."""
    return await _run_sync(_sync_get_current_round)


async def get_app_address(app_id: int) -> str:
    data = await _run_sync(lambda: indexer_client.application_logs(application_id=app_id, limit=10))
    log_data = data["log-data"]

    txid = log_data[0]["txid"]
    data = await _run_sync(lambda: indexer_client.transaction(txid=txid))

    return data["transaction"]["inner-txns"][0]["sender"]


async def get_address_app_ids(address: str) -> list[int]:
    data = await _run_sync(lambda: indexer_client.account_info(address=address))
    return [app_state["id"] for app_state in data["account"]["apps-local-state"]]


def is_opted_in(address: str, asa_id: int) -> bool:
    account_info = algod_client.account_info(address)
    for account in account_info.get("assets", []):
        if account["asset-id"] == asa_id:
            return True
    return False
