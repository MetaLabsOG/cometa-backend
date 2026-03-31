import asyncio
import logging

from aiocache import cached

from blockchain.node import get_current_round
from core.db.contracts import get_contracts_by_type
from core.util import parse_bignum
from flex.blockchain.base import algod_client
from flex.blockchain.info import _run_sync
from flex.data.assets import micros_to_amount, get_asset_details
from flex.data.asset_prices import _upsert_asset_price
from flex import db
from flex.db.model.priced import AssetPrice
from flex.providers import price_router

logger = logging.getLogger(__name__)

LP_CONCURRENCY = 2
LP_REQUEST_DELAY = 1.0  # seconds between algod calls per slot


def _extract_stake_token_id(contract) -> int | None:
    """Extract stake token ID from contract metadata or cache."""
    meta = contract.metadata or {}
    stid = meta.get('stake_token_id')
    if stid is not None:
        return int(stid)

    cache = meta.get('cache', {})
    initial = cache.get('initial', {})
    raw = initial.get('stakeToken') or initial.get('token')
    if raw is None:
        return None
    if isinstance(raw, dict) and raw.get('type') == 'BigNumber' and 'hex' in raw:
        return int(raw['hex'], 16)
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _get_active_stake_token_ids() -> set[int]:
    """Return stake token IDs for farm contracts that are still active or have stake.

    A contract is active if:
    - endBlock >= current_round (rewards not expired), OR
    - totalStaked > 1 (users still have tokens staked)

    Mirrors the filter in update_contracts_cache() (api/background.py).
    """
    contracts = get_contracts_by_type('farm')
    current_round = get_current_round()
    active_ids = set()
    total = 0

    for c in contracts:
        stid = _extract_stake_token_id(c)
        if not stid:
            continue
        total += 1

        meta = c.metadata or {}
        cache = meta.get('cache')
        if not cache:
            active_ids.add(stid)  # no cache = can't determine, assume active
            continue

        try:
            end_block = parse_bignum(cache.get('initial', {}).get('endBlock'))
            total_staked = parse_bignum(cache.get('global', {}).get('totalStaked'))
            if end_block >= current_round or total_staked > 1:
                active_ids.add(stid)
        except (ValueError, TypeError):
            active_ids.add(stid)  # parse error = assume active

    logger.info(f'Active LP tokens: {len(active_ids)}/{total} farm contracts')
    return active_ids


@cached(ttl=300, namespace='lp_token_defs')
async def get_lp_token_definitions() -> list[dict]:
    """Build LP token registry from DB sources (no algod calls).

    Sources (in priority order):
    1. lp_tokens collection (has verified asset1_id, asset2_id, dex_provider)
    2. farming_pools collection (has first_token, second_token, dex_name)
    3. Contract metadata (asset1_id, dex fields)

    Returns list of dicts with lp_token_id, asset1_id, asset2_id, dex.
    """
    contracts = get_contracts_by_type('farm')

    # Collect all stake token IDs from farm contracts
    stake_token_ids = set()
    for c in contracts:
        stid = _extract_stake_token_id(c)
        if stid:
            stake_token_ids.add(stid)

    if not stake_token_ids:
        logger.warning('No stake tokens found in farm contracts')
        return []

    lp_defs_by_id: dict[int, dict] = {}
    from_lp_tokens = 0
    from_farming_pools = 0
    from_metadata = 0

    # Source 1: lp_tokens collection (best quality — has verified pool data)
    try:
        lp_tokens_list = db.lp_tokens.get_many_by_query(
            {'id': {'$in': list(stake_token_ids)}}
        )
        for lt in lp_tokens_list:
            lp_defs_by_id[lt.id] = {
                'lp_token_id': lt.id,
                'asset1_id': lt.asset1_id,
                'asset2_id': lt.asset2_id,
                'dex': lt.dex_provider,
            }
            from_lp_tokens += 1
    except Exception as e:
        logger.error(f'Failed to query lp_tokens: {e}')

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
                'lp_token_id': stid,
                'asset1_id': asset1_id,
                'asset2_id': asset2_id,
                'dex': fp.dex_name,
            }
            from_farming_pools += 1
    except Exception as e:
        logger.error(f'Failed to query farming_pools: {e}')

    # Source 3: contract metadata
    for c in contracts:
        meta = c.metadata or {}
        stid = _extract_stake_token_id(c)
        if not stid or stid in lp_defs_by_id:
            continue
        asset1_id = meta.get('asset1_id')
        dex = meta.get('dex')
        if asset1_id is not None and dex:
            lp_defs_by_id[stid] = {
                'lp_token_id': stid,
                'asset1_id': int(asset1_id),
                'asset2_id': int(meta.get('asset2_id', 0)),
                'dex': dex,
            }
            from_metadata += 1

    result = list(lp_defs_by_id.values())
    logger.info(
        f'LP token definitions: {len(result)}/{len(stake_token_ids)} '
        f'(lp_tokens={from_lp_tokens}, farming_pools={from_farming_pools}, '
        f'metadata={from_metadata}, '
        f'unresolved={len(stake_token_ids) - len(result)})'
    )
    return result


def _get_pool_address(asset_info: dict) -> str:
    """Get the pool address for an LP token.

    Tinyman V2 stores the pool address in 'reserve' (creator is the factory).
    Other DEXes use 'creator' as the pool address directly.
    """
    params = asset_info['params']
    reserve = params.get('reserve')
    creator = params['creator']
    if reserve and reserve != creator:
        return reserve
    return creator


async def calculate_lp_token_price_algo(lp_def: dict) -> float | None:
    """Calculate LP token price from on-chain reserves and asset1 price.

    Formula: asset1_price_algo * asset1_reserve * 2 / circulating_lp_supply
    Returns price of 1 whole LP token in ALGO, or None on failure.
    """
    lp_token_id = lp_def['lp_token_id']
    asset1_id = lp_def['asset1_id']

    # 1. Get LP token info (pool address + total supply)
    asset_info = await _run_sync(algod_client.asset_info, lp_token_id)
    pool_address = _get_pool_address(asset_info)
    total_supply_micros = asset_info['params']['total']

    # 2. Get pool account balances
    account_info = await _run_sync(algod_client.account_info, pool_address)

    asset_balances = {}
    for asset in account_info.get('assets', []):
        asset_balances[asset['asset-id']] = asset['amount']
    # ALGO balance (needed when asset1 or asset2 is ALGO)
    asset_balances[0] = account_info.get('amount', 0)

    asset1_reserve_micros = asset_balances.get(asset1_id, 0)
    pool_lp_balance_micros = asset_balances.get(lp_token_id, 0)

    # 3. Circulating supply = total - pool's own balance
    circulating_micros = total_supply_micros - pool_lp_balance_micros

    # 4. Convert to whole units
    asset1_reserve = await micros_to_amount(asset1_id, asset1_reserve_micros)
    circulating_supply = await micros_to_amount(lp_token_id, circulating_micros)

    if circulating_supply <= 0 or asset1_reserve <= 0:
        logger.warning(f'LP {lp_token_id}: invalid reserves (asset1={asset1_reserve}, circ={circulating_supply})')
        return None

    # 5. Get asset1 price in ALGO via price_router (DB → Vestige → Tinyman)
    try:
        asset1_price = await price_router.get_asset_price(asset1_id)
        asset1_price_algo = asset1_price.algo
    except Exception as e:
        logger.warning(f'LP {lp_token_id}: failed to get price for asset1 {asset1_id}: {e}')
        return None

    if asset1_price_algo <= 0:
        logger.warning(f'LP {lp_token_id}: asset1 {asset1_id} has zero price')
        return None

    # 6. LP price = asset1_price * asset1_reserve * 2 / circulating_supply
    return asset1_price_algo * asset1_reserve * 2 / circulating_supply


async def _update_single_lp(lp_def: dict, algo_price_usd: float, current_round: int) -> bool:
    """Calculate and persist a single LP token price. Returns True on success."""
    try:
        price_algo = await calculate_lp_token_price_algo(lp_def)
        if price_algo is not None and price_algo > 0:
            asset_details = await get_asset_details(lp_def['lp_token_id'])
            ap = AssetPrice(
                id=lp_def['lp_token_id'],
                name=asset_details.name,
                price_algo=price_algo,
                price_usd=price_algo * algo_price_usd,
                last_update_round=current_round,
            )
            _upsert_asset_price(ap)
            return True
    except Exception as e:
        logger.warning(f'Failed LP price for token {lp_def["lp_token_id"]}: {e}')
    return False


_last_lp_update_round: int = 0


async def update_lp_token_prices(current_round: int) -> None:
    """Calculate and persist LP token prices for active farm contracts only.

    Skips if fewer than lp_prices_update_interval seconds have elapsed.
    Only prices LP tokens from farms that are still active or have stake,
    dramatically reducing algod calls (from ~160 to ~10-20 tokens).
    """
    global _last_lp_update_round
    from env import settings as _settings
    min_round_gap = int(_settings.lp_prices_update_interval / _settings.block_time)
    if _last_lp_update_round and (current_round - _last_lp_update_round) < min_round_gap:
        return

    lp_defs = await get_lp_token_definitions()
    if not lp_defs:
        return

    # Only price LP tokens from active farms (endBlock not passed or still has stake)
    active_ids = _get_active_stake_token_ids()
    active_defs = [d for d in lp_defs if d['lp_token_id'] in active_ids]
    logger.info(f'LP pricing: {len(active_defs)} active out of {len(lp_defs)} total definitions')

    if not active_defs:
        _last_lp_update_round = current_round
        return

    try:
        algo_price_usd = await price_router.get_algo_price_usd()
    except Exception as e:
        logger.error(f'All ALGO price providers failed, skipping LP update: {e}')
        return

    semaphore = asyncio.Semaphore(LP_CONCURRENCY)

    async def _bounded(lp_def: dict) -> bool:
        async with semaphore:
            result = await _update_single_lp(lp_def, algo_price_usd, current_round)
            await asyncio.sleep(LP_REQUEST_DELAY)
            return result

    results = await asyncio.gather(*[_bounded(d) for d in active_defs])
    lp_updated = sum(1 for r in results if r)
    _last_lp_update_round = current_round

    logger.info(f'LP token prices: {lp_updated}/{len(active_defs)} updated')
