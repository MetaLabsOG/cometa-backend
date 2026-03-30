import asyncio
import logging

from aiocache import cached

from core.db.contracts import get_contracts_by_type
from flex.blockchain.base import algod_client
from flex.blockchain.info import _run_sync
from flex.data.assets import micros_to_amount, get_asset_details
from flex.data.asset_prices import _upsert_asset_price
from flex import db
from flex.db.model.priced import AssetPrice
from flex.providers.vestige import vestige_full_asset_price, get_algo_price_usd

logger = logging.getLogger(__name__)


@cached(ttl=300, namespace='lp_token_defs')
async def get_lp_token_definitions() -> list[dict]:
    """Build LP token registry from active farm contract metadata.

    Returns list of dicts with lp_token_id, asset1_id, asset2_id, dex.
    """
    contracts = get_contracts_by_type('farm')
    lp_defs = []
    for c in contracts:
        meta = c.metadata or {}
        stake_token_id = meta.get('stake_token_id')
        if stake_token_id is None:
            cache = meta.get('cache', {})
            initial = cache.get('initial', {})
            raw = initial.get('stakeToken')
            if isinstance(raw, dict) and raw.get('type') == 'BigNumber' and 'hex' in raw:
                stake_token_id = int(raw['hex'], 16)
            elif raw is not None:
                stake_token_id = int(raw)

        asset1_id = meta.get('asset1_id')
        dex = meta.get('dex')
        if stake_token_id and asset1_id and dex:
            lp_defs.append({
                'lp_token_id': int(stake_token_id),
                'asset1_id': int(asset1_id),
                'asset2_id': int(meta.get('asset2_id', 0)),
                'dex': dex,
            })

    seen = set()
    unique = []
    for d in lp_defs:
        if d['lp_token_id'] not in seen:
            seen.add(d['lp_token_id'])
            unique.append(d)
    return unique


async def calculate_lp_token_price_algo(lp_def: dict) -> float | None:
    """Calculate LP token price from on-chain reserves and asset1 price.

    Formula: asset1_price_algo * asset1_reserve * 2 / circulating_lp_supply
    Returns price of 1 whole LP token in ALGO, or None on failure.
    """
    lp_token_id = lp_def['lp_token_id']
    asset1_id = lp_def['asset1_id']

    # 1. Get LP token info (creator = pool address, total supply)
    asset_info = await _run_sync(algod_client.asset_info, lp_token_id)
    pool_address = asset_info['params']['creator']
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

    # 5. Get asset1 price in ALGO (prefer DB, fall back to Vestige)
    asset1_price_record = db.asset_prices.get_one(id=asset1_id)
    if asset1_price_record is not None and asset1_price_record.price_algo > 0:
        asset1_price_algo = asset1_price_record.price_algo
    else:
        asset1_price_algo = (await vestige_full_asset_price(asset1_id)).algo

    if asset1_price_algo <= 0:
        logger.warning(f'LP {lp_token_id}: asset1 {asset1_id} has zero price')
        return None

    # 6. LP price = asset1_price * asset1_reserve * 2 / circulating_supply
    return asset1_price_algo * asset1_reserve * 2 / circulating_supply


async def update_lp_token_prices(current_round: int) -> None:
    """Calculate and persist LP token prices into asset_prices collection.

    Called by the background worker after regular asset price updates.
    """
    lp_defs = await get_lp_token_definitions()
    if not lp_defs:
        return

    algo_price_usd = await get_algo_price_usd()
    lp_updated = 0

    for lp_def in lp_defs:
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
                lp_updated += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f'Failed LP price for token {lp_def["lp_token_id"]}: {e}')

    logger.info(f'LP token prices: {lp_updated}/{len(lp_defs)} updated')
