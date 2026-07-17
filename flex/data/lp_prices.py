import asyncio
import logging
from datetime import timedelta
from decimal import Decimal

from aiocache import cached
from algosdk.error import AlgodHTTPError

from blockchain.node import get_current_round
from core.db.contracts import get_contracts_by_type
from core.util import parse_bignum
from env import settings
from flex import db
from flex.blockchain.base import algod_client
from flex.blockchain.info import _run_sync
from flex.data.asset_prices import _upsert_asset_price
from flex.data.assets import get_asset_details
from flex.db.model.priced import AssetPrice
from flex.domain.pricing import (
    PriceQuote,
    PriceSource,
    PriceUnavailableError,
    PricingError,
)
from flex.domain.pricing import (
    calculate_lp_token_price_algo as calculate_lp_token_price_algo_exact,
)
from flex.providers import price_router

logger = logging.getLogger(__name__)

LP_CONCURRENCY = 2
LP_REQUEST_DELAY = 1.0  # seconds between algod calls per slot


class LpTokenRegistryError(RuntimeError):
    """The LP registry cannot safely distinguish derived from external prices."""


def _extract_stake_token_id(contract) -> int | None:
    """Extract stake token ID from contract metadata or cache."""
    meta = contract.metadata or {}
    stid = meta.get("stake_token_id")
    if stid is not None:
        return int(stid)

    cache = meta.get("cache", {})
    initial = cache.get("initial", {})
    raw = initial.get("stakeToken") or initial.get("token")
    if raw is None:
        return None
    if isinstance(raw, dict) and raw.get("type") == "BigNumber" and "hex" in raw:
        return int(raw["hex"], 16)
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _get_active_stake_token_ids() -> set[int]:
    """Return stake token IDs for farm contracts where rewards are still active.

    Only includes contracts where endBlock >= current_round (reward period not expired).
    Ended farms have static LP reserves — their prices don't need frequent updates.
    """
    contracts = get_contracts_by_type("farm")
    current_round = get_current_round()
    active_ids = set()
    total = 0

    for c in contracts:
        stid = _extract_stake_token_id(c)
        if not stid:
            continue
        total += 1

        meta = c.metadata or {}
        cache = meta.get("cache")
        if not cache:
            continue  # no cache = can't determine endBlock, skip

        try:
            end_block = parse_bignum(cache.get("initial", {}).get("endBlock"))
            if end_block >= current_round:
                active_ids.add(stid)
        except (ValueError, TypeError):
            continue

    logger.info(f"Active LP tokens: {len(active_ids)}/{total} farm contracts")
    return active_ids


@cached(ttl=300, namespace="lp_token_defs")
async def get_lp_token_definitions() -> list[dict]:
    """Build LP token registry from DB sources (no algod calls).

    Sources (in priority order):
    1. lp_tokens collection (has verified asset1_id, asset2_id, dex_provider)
    2. farming_pools collection (has first_token, second_token, dex_name)
    3. Contract metadata (asset1_id, dex fields)

    Returns list of dicts with lp_token_id, asset1_id, asset2_id, dex.
    """
    contracts = get_contracts_by_type("farm")

    # Collect all stake token IDs from farm contracts
    stake_token_ids = set()
    expected_lp_token_ids = set()
    for c in contracts:
        stid = _extract_stake_token_id(c)
        if stid:
            stake_token_ids.add(stid)
            meta = c.metadata or {}
            if "asset1_id" in meta or "asset_1_id" in meta:
                expected_lp_token_ids.add(stid)

    if not stake_token_ids:
        logger.warning("No stake tokens found in farm contracts")
        return []

    lp_defs_by_id: dict[int, dict] = {}
    from_lp_tokens = 0
    from_farming_pools = 0
    from_metadata = 0

    # Source 1: lp_tokens collection (best quality — has verified pool data)
    try:
        lp_tokens_list = db.lp_tokens.get_many_by_query({"id": {"$in": list(stake_token_ids)}})
        for lt in lp_tokens_list:
            lp_defs_by_id[lt.id] = {
                "lp_token_id": lt.id,
                "asset1_id": lt.asset1_id,
                "asset2_id": lt.asset2_id,
                "dex": lt.dex_provider,
            }
            from_lp_tokens += 1
    except Exception as exc:
        raise LpTokenRegistryError("failed to query lp_tokens") from exc

    # Source 2: farming_pools collection
    try:
        farming_pools_list = db.farming_pools.get_all()
        for fp in farming_pools_list:
            stid = fp.stake_token.id
            if stid not in stake_token_ids or stid in lp_defs_by_id:
                continue
            asset1_id = fp.first_token.id
            asset2_id = fp.second_token.id
            # Normalize: non-ALGO token as asset1 (matches lp_tokens convention)
            if asset1_id == 0:
                asset1_id, asset2_id = asset2_id, asset1_id
            lp_defs_by_id[stid] = {
                "lp_token_id": stid,
                "asset1_id": asset1_id,
                "asset2_id": asset2_id,
                "dex": fp.dex_name,
            }
            from_farming_pools += 1
    except Exception as exc:
        raise LpTokenRegistryError("failed to query farming_pools") from exc

    # Source 3: contract metadata
    for c in contracts:
        meta = c.metadata or {}
        stid = _extract_stake_token_id(c)
        if not stid or stid in lp_defs_by_id:
            continue
        asset1_id = meta.get("asset1_id", meta.get("asset_1_id"))
        asset2_id = meta.get("asset2_id", meta.get("asset_2_id", 0))
        dex = meta.get("dex") or meta.get("dex_provider")
        if asset1_id is not None and dex:
            lp_defs_by_id[stid] = {
                "lp_token_id": stid,
                "asset1_id": int(asset1_id),
                "asset2_id": int(asset2_id),
                "dex": dex,
            }
            from_metadata += 1

    unresolved_lp_ids = expected_lp_token_ids - lp_defs_by_id.keys()
    if unresolved_lp_ids:
        raise LpTokenRegistryError(
            f"LP registry is incomplete for token ids {sorted(unresolved_lp_ids)}",
        )

    result = list(lp_defs_by_id.values())
    logger.info(
        f"LP token definitions: {len(result)}/{len(stake_token_ids)} "
        f"(lp_tokens={from_lp_tokens}, farming_pools={from_farming_pools}, "
        f"metadata={from_metadata}, "
        f"unresolved={len(stake_token_ids) - len(result)})"
    )
    return result


def _get_pool_address(asset_info: dict) -> str:
    """Get the pool address for an LP token.

    Tinyman V2 stores the pool address in 'reserve' (creator is the factory).
    Other DEXes use 'creator' as the pool address directly.
    """
    params = asset_info["params"]
    reserve = params.get("reserve")
    creator = params["creator"]
    if reserve and reserve != creator:
        return reserve
    return creator


async def calculate_lp_token_price_algo(lp_def: dict) -> Decimal:
    """Calculate LP token price from on-chain reserves and asset1 price.

    Formula: asset1_price_algo * asset1_reserve * 2 / circulating_lp_supply
    The entire calculation stays in Decimal until the persistence boundary.
    """
    price_algo, _ = await _calculate_lp_token_price_algo_with_quote(lp_def)
    return price_algo


async def _calculate_lp_token_price_algo_with_quote(
    lp_def: dict,
) -> tuple[Decimal, PriceQuote]:
    """Calculate an LP price and retain the source asset observation."""

    lp_token_id = lp_def["lp_token_id"]
    asset1_id = lp_def["asset1_id"]

    # 1. Get LP token info (pool address + total supply)
    asset_info = await _run_sync(algod_client.asset_info, lp_token_id)
    pool_address = _get_pool_address(asset_info)
    total_supply_micros = asset_info["params"]["total"]

    # 2. Get pool account balances
    account_info = await _run_sync(algod_client.account_info, pool_address)

    asset_balances = {}
    for asset in account_info.get("assets", []):
        asset_balances[asset["asset-id"]] = asset["amount"]
    # ALGO balance (needed when asset1 or asset2 is ALGO)
    asset_balances[0] = account_info.get("amount", 0)

    asset1_reserve_micros = asset_balances.get(asset1_id, 0)
    pool_lp_balance_micros = asset_balances.get(lp_token_id, 0)

    asset1_details = await get_asset_details(asset1_id)
    asset1_quote = await price_router.get_asset_price_quote(asset1_id)

    return (
        calculate_lp_token_price_algo_exact(
            asset1_price_algo=asset1_quote.algo,
            asset1_reserve_micros=asset1_reserve_micros,
            asset1_decimals=asset1_details.decimals,
            total_lp_supply_micros=total_supply_micros,
            pool_lp_balance_micros=pool_lp_balance_micros,
            lp_token_decimals=asset_info["params"]["decimals"],
        ),
        asset1_quote,
    )


async def _update_single_lp(
    lp_def: dict,
    algo_quote: PriceQuote,
    current_round: int,
) -> bool:
    """Calculate and persist a single LP token price. Returns True on success."""
    try:
        price_algo, asset1_quote = await _calculate_lp_token_price_algo_with_quote(lp_def)
        quote = PriceQuote.from_raw(
            asset_id=lp_def["lp_token_id"],
            algo=price_algo,
            usd=price_algo * algo_quote.usd,
            source=PriceSource.DERIVED_LP,
            stale_after=timedelta(seconds=settings.lp_prices_update_interval),
            observed_round=current_round,
            observed_at=min(asset1_quote.observed_at, algo_quote.observed_at),
        )
        legacy_algo, legacy_usd = quote.to_legacy_floats()
        asset_details = await get_asset_details(quote.asset_id)
        asset_price = AssetPrice(
            id=quote.asset_id,
            name=asset_details.name,
            price_algo=legacy_algo,
            price_usd=legacy_usd,
            last_update_round=current_round,
            source=quote.source.value,
            observed_at=quote.observed_at,
        )
        _upsert_asset_price(asset_price)
        return True
    except (PriceUnavailableError, PricingError) as exc:
        logger.warning("Failed LP price for token %s: %s", lp_def["lp_token_id"], exc)
        return False
    except (AlgodHTTPError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Failed LP price for token %s: %s", lp_def["lp_token_id"], exc)
        return False


_last_lp_update_round: int = 0


async def update_lp_token_prices(current_round: int) -> None:
    """Calculate and persist LP token prices for active farm contracts only.

    Skips if fewer than lp_prices_update_interval seconds have elapsed.
    Only prices LP tokens from farms that are still active or have stake,
    dramatically reducing algod calls (from ~160 to ~10-20 tokens).
    """
    global _last_lp_update_round
    min_round_gap = int(settings.lp_prices_update_interval / settings.block_time)
    if _last_lp_update_round and (current_round - _last_lp_update_round) < min_round_gap:
        return

    lp_defs = await get_lp_token_definitions()
    if not lp_defs:
        return

    # Only price LP tokens from active farms (endBlock not passed or still has stake)
    active_ids = _get_active_stake_token_ids()
    active_defs = [d for d in lp_defs if d["lp_token_id"] in active_ids]
    logger.info(f"LP pricing: {len(active_defs)} active out of {len(lp_defs)} total definitions")

    if not active_defs:
        _last_lp_update_round = current_round
        return

    try:
        algo_quote = await price_router.get_algo_price_quote()
    except (PriceUnavailableError, PricingError) as exc:
        logger.error("All ALGO price providers failed, skipping LP update: %s", exc)
        return

    semaphore = asyncio.Semaphore(LP_CONCURRENCY)

    async def _bounded(lp_def: dict) -> bool:
        async with semaphore:
            result = await _update_single_lp(lp_def, algo_quote, current_round)
            await asyncio.sleep(LP_REQUEST_DELAY)
            return result

    results = await asyncio.gather(*[_bounded(d) for d in active_defs])
    lp_updated = sum(1 for r in results if r)
    _last_lp_update_round = current_round

    logger.info(f"LP token prices: {lp_updated}/{len(active_defs)} updated")
