import asyncio
import logging
from datetime import UTC, datetime

from aiocache import cached

from env import settings
from flex import db
from flex.blockchain.info import get_address_asset_snapshot
from flex.data.assets import get_asset_total_supply, get_full_asset
from flex.data.lp_tokens import get_lp_token_by_id, lp_token_from_tinyman_pool
from flex.db.lp_projection import (
    LpProjectionPersistenceError,
    MongoLpProjectionRepository,
)
from flex.db.model.blockchain import LpToken
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.domain.lp_projection import lp_round_end_order
from flex.domain.pricing import (
    base_units_to_decimal,
    calculate_lp_token_price_from_issued_supply,
    decimal_to_legacy_float,
)
from flex.meta_error import MetaError
from flex.providers.tinyman import fetch_algo_tinyman_pool_by_asset_id
from flex.providers.vestige import vestige_full_asset_price
from flex.util import build_key_str

logger = logging.getLogger(__name__)


async def get_price_algo(asset_id) -> float:
    # TODO: fix DB caching
    # asset_db_price = db.asset_prices.get_one(id=asset_id)
    # if asset_db_price is not None:
    #     price_algo = asset_db_price.price_algo
    # else:
    #     price_algo = (await vestige_full_asset_price(asset_id)).algo
    asset_price = await vestige_full_asset_price(asset_id)
    return asset_price.algo


async def recalculate_lp_state_price_algo_with_micros(lp_state: LpState) -> LpState:
    # Capture this before external reads. A slower, older calculation must not
    # overwrite a newer quote for the same balance cursor.
    lp_state.derived_observed_at = datetime.now(UTC)
    asset1, asset2, lp_token = await asyncio.gather(
        get_full_asset(lp_state.asset1_id),
        get_full_asset(lp_state.asset2_id),
        get_full_asset(lp_state.token_id),
    )
    asset1_reserve = base_units_to_decimal(
        lp_state.asset1_reserve_micros,
        decimals=asset1.decimals,
        field="asset1_reserve_micros",
    )
    asset2_reserve = base_units_to_decimal(
        lp_state.asset2_reserve_micros,
        decimals=asset2.decimals,
        field="asset2_reserve_micros",
    )
    issued_tokens = base_units_to_decimal(
        lp_state.total_tokens_micros,
        decimals=lp_token.decimals,
        field="issued_lp_supply_micros",
    )
    lp_state.asset1_reserve = decimal_to_legacy_float(
        asset1_reserve,
        field="asset1_reserve",
    )
    lp_state.asset2_reserve = decimal_to_legacy_float(
        asset2_reserve,
        field="asset2_reserve",
    )
    lp_state.total_tokens = decimal_to_legacy_float(
        issued_tokens,
        field="issued_tokens",
    )

    if lp_state.total_tokens_micros == 0:
        lp_state.token_price_algo = 0
        return lp_state

    asset1_price_algo = await get_price_algo(lp_state.asset1_id)
    exact_price = calculate_lp_token_price_from_issued_supply(
        asset1_price_algo=asset1_price_algo,
        asset1_reserve_micros=lp_state.asset1_reserve_micros,
        asset1_decimals=asset1.decimals,
        issued_lp_supply_micros=lp_state.total_tokens_micros,
        lp_token_decimals=lp_token.decimals,
    )
    lp_state.token_price_algo = decimal_to_legacy_float(
        exact_price,
        field="token_price_algo",
    )
    return lp_state


async def create_lp_state_by_lp_token_id(lp_token_id: int) -> LpState:
    lp_token = await get_lp_token_by_id(lp_token_id)
    if lp_token is None:
        raise MetaError(f"LP token not found for ID {lp_token_id}")

    return await create_lp_state_by_lp_token(lp_token)


async def create_lp_state_by_lp_token(lp_token: LpToken) -> LpState:
    # TODO: remove after test
    if lp_token.asset1_id == 0:
        raise MetaError(f"ALGO LP token asset1 ID = 0, not id2: {lp_token}")

    if lp_token.asset2_id == 0:
        snapshot = await get_address_asset_snapshot(
            lp_token.address,
            include_algo=True,
        )
    else:
        snapshot = await get_address_asset_snapshot(
            lp_token.address,
            include_algo=False,
        )
    balances = snapshot.balances

    asset1_reserve_micros = balances[lp_token.asset1_id]
    asset2_reserve_micros = balances[lp_token.asset2_id]
    lp_token_reserve_micros = balances[lp_token.id]

    # TODO: add field total_supply_micros to LP token
    lp_token_total_supply_micros = await get_asset_total_supply(lp_token.id)
    issued_lp_tokens_micros = lp_token_total_supply_micros - lp_token_reserve_micros

    current_round = snapshot.observed_round
    lp_state = LpState(
        id=lp_token.pool_id,
        token_id=lp_token.id,
        asset1_id=lp_token.asset1_id,
        asset2_id=lp_token.asset2_id,
        dex_provider=lp_token.dex_provider,
        address=lp_token.address,
        asset1_reserve_micros=asset1_reserve_micros,
        asset2_reserve_micros=asset2_reserve_micros,
        total_tokens_micros=issued_lp_tokens_micros,
        asset1_reserve=0,
        asset2_reserve=0,
        total_tokens=0,
        token_price_algo=0,
        last_updated_round=current_round,
        last_event_order=lp_round_end_order(current_round),
        is_algo_pool=lp_token.asset2_id == 0,
    )
    lp_state = await recalculate_lp_state_price_algo_with_micros(lp_state)
    if lp_state.is_algo_pool:
        logger.info(f"Created new LP state for ALGO pool, asa_id={lp_token.asset1_id}:\n{lp_state.pretty_str()}")

    persisted = db.lp_states.get_or_create(lp_state)
    immutable_fields = (
        persisted.id,
        persisted.token_id,
        persisted.asset1_id,
        persisted.asset2_id,
        persisted.dex_provider,
        persisted.address,
    )
    requested_fields = (
        lp_state.id,
        lp_state.token_id,
        lp_state.asset1_id,
        lp_state.asset2_id,
        lp_state.dex_provider,
        lp_state.address,
    )
    if immutable_fields != requested_fields:
        raise MetaError(f"LP token ID {lp_token.id} is already mapped to different pool metadata")
    return persisted


async def update_lp_state(lp_state: LpState) -> LpState:
    if lp_state.asset1_id == 0 or lp_state.asset2_id == 0:
        # TODO: take values from DB sync
        snapshot = await get_address_asset_snapshot(
            lp_state.address,
            include_algo=True,
        )
    else:
        snapshot = await get_address_asset_snapshot(
            lp_state.address,
            include_algo=False,
        )
    balances = snapshot.balances

    lp_state.asset1_reserve_micros = balances[lp_state.asset1_id]
    lp_state.asset2_reserve_micros = balances[lp_state.asset2_id]

    lp_token_reserve_micros = balances[lp_state.token_id]
    lp_token_total_supply_micros = await get_asset_total_supply(lp_state.token_id)
    lp_state.total_tokens_micros = lp_token_total_supply_micros - lp_token_reserve_micros

    lp_state = await recalculate_lp_state_price_algo_with_micros(lp_state)
    current_round = snapshot.observed_round
    repository = MongoLpProjectionRepository(
        states=db.lp_states.mongodb_collection,
        events=db.lp_transactions.mongodb_collection,
    )
    return await asyncio.to_thread(
        repository.replace_snapshot,
        lp_state,
        observed_round=current_round,
    )


async def create_lp_states_from_all_pools() -> list[LpState]:
    farming_pools = db.farming_pools.get_all()
    new_lp_states = []
    failures: list[Exception] = []
    for farming_pool in farming_pools:
        try:
            if db.lp_states.exists(token_id=farming_pool.stake_token.id):
                continue

            lp_state = await create_lp_state_by_lp_token_id(farming_pool.stake_token.id)
            new_lp_states.append(lp_state)
        except Exception as e:
            failures.append(e)
            logger.error(f"Failed to create LP state: {e}\n{farming_pool.pretty_str()}", exc_info=True)

    if failures:
        raise LpProjectionPersistenceError(
            f"failed to create {len(failures)} LP state(s) during cutover"
        ) from failures[0]
    return new_lp_states


def _preflight_lp_transactions(
    transactions: list[LpTransaction],
    *,
    expected_round: int,
) -> list[LpTransaction]:
    """Validate and canonicalize a complete block batch before any writes."""

    canonical_by_id: dict[str, LpTransaction] = {}
    for transaction in transactions:
        if transaction.confirmed_round != expected_round:
            raise LpProjectionPersistenceError(
                f"LP event {transaction.id!r} belongs to round {transaction.confirmed_round}, expected {expected_round}"
            )
        if transaction.event_order is None:
            raise LpProjectionPersistenceError(f"LP event {transaction.id!r} has no deterministic order")

        existing = canonical_by_id.get(transaction.id)
        if existing is None:
            canonical_by_id[transaction.id] = transaction
            continue
        if (
            existing.pool_address,
            existing.user_address,
            existing.asa_id,
            existing.delta_amount_micros,
            existing.confirmed_round,
            existing.event_position,
            existing.event_order,
        ) != (
            transaction.pool_address,
            transaction.user_address,
            transaction.asa_id,
            transaction.delta_amount_micros,
            transaction.confirmed_round,
            transaction.event_position,
            transaction.event_order,
        ):
            raise LpProjectionPersistenceError(f"LP event ID {transaction.id!r} has conflicting data in one block")

    return sorted(
        canonical_by_id.values(),
        key=lambda item: item.event_order or "",
    )


async def update_lp_states_with_transactions(
    transactions: list[LpTransaction],
    *,
    expected_round: int,
) -> list[LpState]:
    if not transactions:
        return []

    transactions = _preflight_lp_transactions(
        transactions,
        expected_round=expected_round,
    )
    repository = MongoLpProjectionRepository(
        states=db.lp_states.mongodb_collection,
        events=db.lp_transactions.mongodb_collection,
    )
    changed_addresses: set[str] = set()
    applied_event_count = 0
    for transaction in transactions:
        outcome = await asyncio.to_thread(
            repository.project,
            transaction,
        )
        if outcome.requires_derived_refresh:
            changed_addresses.add(transaction.pool_address)
        if outcome.changed_balances:
            applied_event_count += 1

    updated_states: list[LpState] = []
    for pool_address in sorted(changed_addresses):
        for _ in range(2):
            state = await asyncio.to_thread(repository.get_state, pool_address)
            expected_cursor = state.last_event_order
            if expected_cursor is None:
                raise LpProjectionPersistenceError(f"LP state {state.token_id} has no event cursor")
            state = await recalculate_lp_state_price_algo_with_micros(state)
            updated = await asyncio.to_thread(
                repository.update_derived_fields,
                state,
                expected_cursor=expected_cursor,
            )
            if updated is not None:
                updated_states.append(updated)
                break
        else:
            raise LpProjectionPersistenceError(f"LP state {pool_address} kept changing during price persistence")

    logger.info(
        "Updated %s LP states with %s new transaction(s)",
        len(updated_states),
        applied_event_count,
    )
    return updated_states


async def update_all_lp_states_linear() -> list[LpState]:
    lp_states = db.lp_states.get_all()
    logger.debug(f"Updating {len(lp_states)} LP states...")

    updated_lp_states = []
    failures: list[Exception] = []
    for lp_state in lp_states:
        try:
            updated_lp_state = await update_lp_state(lp_state)
            updated_lp_states.append(updated_lp_state)
        except Exception as e:
            failures.append(e)
            logger.error(f"Error updating state of LP {lp_state.id}: {e}", exc_info=True)

    if failures:
        raise LpProjectionPersistenceError(
            f"failed to snapshot {len(failures)} LP state(s); sync checkpoint was not advanced"
        ) from failures[0]
    logger.debug(f"Updated {len(updated_lp_states)} LP states")
    return updated_lp_states


@cached(ttl=settings.lp_token_prices_ttl, namespace="lp_state_by_id", key_builder=build_key_str)
async def get_lp_state_by_lp_token_id(lp_token_id: int) -> LpState:
    lp_state = db.lp_states.get_one(token_id=lp_token_id)
    if lp_state is None:
        lp_state = await create_lp_state_by_lp_token_id(lp_token_id)
    # TODO: add setting: do update or not
    # elif (await get_current_round()) - lp_state.last_updated_round > settings.lp_state_ttl_rounds:
    #     lp_state = await update_lp_state(lp_state)
    return lp_state


@cached(ttl=60, namespace="lp_state_by_address", key_builder=build_key_str)
async def get_lp_state_by_address(address: str) -> LpState:
    return db.lp_states.get_one(address=address)


@cached(ttl=120, namespace="tinyman_lp_state", key_builder=build_key_str)
async def get_tinyman_pool_lp_state_by_asset_id(asset_id: int) -> LpState | None:
    tiny_lp_state = db.lp_states.get_one(asset1_id=asset_id, asset2_id=0)
    if tiny_lp_state is not None:
        return tiny_lp_state

    tinyman_pool = await fetch_algo_tinyman_pool_by_asset_id(asset_id)
    if tinyman_pool is None or tinyman_pool.lp_token_id is None:
        logger.debug(f"Tinyman pool for asset {asset_id} not found")
        return None

    lp_token = db.lp_tokens.get_by_primary_key(tinyman_pool.lp_token_id, throw_ex=False)
    if lp_token is None:
        lp_token = await lp_token_from_tinyman_pool(tinyman_pool)
        db.lp_tokens.create(lp_token)

    return await create_lp_state_by_lp_token(lp_token)
