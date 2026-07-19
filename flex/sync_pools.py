import asyncio
import logging
import random
from uuid import uuid4

from aiocache import cached as cached_async

from env import settings
from flex import db
from flex.blockchain.base import indexer_client
from flex.blockchain.info import get_current_round
from flex.data.asset_prices import create_and_update_asset_prices
from flex.data.assets import load_all_assets_data
from flex.data.lp_states import (
    create_lp_states_from_all_pools,
    update_all_lp_states_linear,
    update_lp_states_with_transactions,
)
from flex.data.pool_state import (
    get_or_create_pool_state,
    update_pool_state,
    update_pool_states_with_transactions,
)
from flex.data.tinyman_lps import update_tinyman_algo_asset_price
from flex.db.model.blockchain import PoolTransaction, SyncBlock, SyncState
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.db.model.pool_states import PoolState, UserState
from flex.db.model.priced import AssetPrice
from flex.db.sync_coordinator import (
    MongoSyncCoordinator,
    SyncCoordinatorError,
)
from flex.domain.lp_projection import lp_cursor_complete_through
from flex.domain.pricing import PricingError
from flex.domain.transactions import (
    ASSET_TRANSFER_TX,
    PAYMENT_TX,
    flatten_asset_transfers,
    flatten_transfer_payments,
    projection_event_id,
)
from flex.providers.price_router import get_algo_price_quote
from flex.sync_state import get_sync_state, is_sync_delayed
from flex.util import build_key_str

logger = logging.getLogger(__name__)


def get_all_lp_state_addresses() -> set[str]:
    return set(lp_state.address for lp_state in db.lp_states.get_all())


def find_transfer_payment_transactions(txns: list[dict]) -> list[dict]:
    return flatten_transfer_payments(txns)


def find_transfer_transactions(txns: list[dict]) -> list[dict]:
    return flatten_asset_transfers(txns)


@cached_async(ttl=30, namespace="pool_state", key_builder=build_key_str)
async def get_pool_state_by_address(address: str) -> PoolState:
    return db.pool_states.get_one(address=address)


async def process_lp_transactions(transactions: list[dict]) -> list[LpTransaction]:
    all_lp_addresses = get_all_lp_state_addresses()

    lp_transactions = []
    for event_position, tx in enumerate(transactions):
        txid = tx["id"]
        sender = tx["sender"]
        confirmed_round = tx["confirmed-round"]

        if ASSET_TRANSFER_TX in tx:
            transfer = tx[ASSET_TRANSFER_TX]
            receiver = transfer["receiver"]
            affected_addresses = {
                sender,
                receiver,
                transfer.get("sender"),
                transfer.get("close-to"),
            }
            if not (affected_addresses & all_lp_addresses):
                continue
            if any(field in transfer for field in ("sender", "close-to", "close-amount")):
                raise ValueError(f"LP projection does not support clawback/close semantics: {txid}")
            asa_id = transfer["asset-id"]
            amount = transfer["amount"]
        elif PAYMENT_TX in tx:
            payment = tx[PAYMENT_TX]
            receiver = payment["receiver"]
            affected_addresses = {
                sender,
                receiver,
                payment.get("close-remainder-to"),
            }
            if not (affected_addresses & all_lp_addresses):
                continue
            if any(field in payment for field in ("close-remainder-to", "close-amount")):
                raise ValueError(f"LP projection does not support payment close semantics: {txid}")
            asa_id = 0
            amount = payment["amount"]
        else:
            raise ValueError(f"Invalid transaction type: {tx}")

        if sender == receiver and sender in all_lp_addresses:
            # A self-transfer has zero net effect on the pool. Emitting both
            # legs would create the same scoped event ID twice and make a
            # deduplicating projector persist only one side.
            continue

        if sender in all_lp_addresses:
            lp_tx = LpTransaction(
                id=projection_event_id(txid, sender),
                pool_address=sender,
                user_address=receiver,
                asa_id=asa_id,
                delta_amount_micros=-amount,
                confirmed_round=confirmed_round,
                event_position=event_position,
            )
            lp_transactions.append(lp_tx)

        if receiver in all_lp_addresses:
            lp_tx = LpTransaction(
                id=projection_event_id(txid, receiver),
                pool_address=receiver,
                user_address=sender,
                asa_id=asa_id,
                delta_amount_micros=amount,
                confirmed_round=confirmed_round,
                event_position=event_position,
            )
            lp_transactions.append(lp_tx)

    return lp_transactions


async def process_pool_transactions(txns: list[dict]) -> list[PoolTransaction]:
    pool_transactions = []
    for tx in txns:
        txid = tx["id"]
        sender = tx["sender"]
        tx_asa_id = tx[ASSET_TRANSFER_TX]["asset-id"]
        receiver = tx[ASSET_TRANSFER_TX]["receiver"]
        amount = tx[ASSET_TRANSFER_TX]["amount"]
        confirmed_round = tx["confirmed-round"]

        withdraw_pool = await get_pool_state_by_address(address=sender)
        if withdraw_pool is not None:
            if withdraw_pool.stake_token.id == tx_asa_id:
                pool_tx = PoolTransaction(
                    id=txid,
                    pool_id=withdraw_pool.pool_id,
                    user_address=receiver,
                    pool_address=withdraw_pool.address,
                    asa_id=tx_asa_id,
                    delta_amount_micros=-amount,
                    confirmed_round=confirmed_round,
                )
                pool_transactions.append(pool_tx)
                continue

        stake_pool = await get_pool_state_by_address(address=receiver)
        if stake_pool is not None:
            if stake_pool.stake_token.id == tx_asa_id:
                pool_tx = PoolTransaction(
                    id=txid,
                    pool_id=stake_pool.pool_id,
                    user_address=sender,
                    pool_address=stake_pool.address,
                    asa_id=tx_asa_id,
                    delta_amount_micros=amount,
                    confirmed_round=confirmed_round,
                )
                pool_transactions.append(pool_tx)

    return pool_transactions


async def update_pools(txns: list[dict]) -> [PoolState]:
    pool_transactions = await process_pool_transactions(txns)
    return await update_pool_states_with_transactions(pool_transactions)


async def update_lp_states(
    txns: list[dict],
    *,
    expected_round: int,
) -> list[LpState]:
    lp_transactions = await process_lp_transactions(txns)
    return await update_lp_states_with_transactions(
        lp_transactions,
        expected_round=expected_round,
    )


async def update_asset_prices(updated_lp_states: list[LpState]) -> list[AssetPrice]:
    if len(updated_lp_states) == 0:
        return []

    algo_quote = await get_algo_price_quote()
    updated_asset_prices = []
    for lp_state in updated_lp_states:
        if lp_state.is_algo_pool:
            try:
                updated_asset_price = await update_tinyman_algo_asset_price(
                    lp_state,
                    algo_quote,
                )
                updated_asset_prices.append(updated_asset_price)
            except PricingError as exc:
                logger.warning(
                    "Skipping invalid Tinyman LP state %s: %s",
                    lp_state.id,
                    exc,
                )

    if len(updated_asset_prices) > 0:
        logger.debug(f"Updated {len(updated_asset_prices)} asset prices.")
    return updated_asset_prices


def _snapshot_checkpoint_round(
    *,
    previous_round: int | None,
    node_round: int,
    lp_states: list[LpState],
) -> int:
    """Choose a checkpoint covered by every persisted LP snapshot."""

    checkpoint = min(
        [
            node_round,
            *(lp_cursor_complete_through(state.last_event_order) for state in lp_states),
        ],
    )
    if previous_round is not None and checkpoint < previous_round:
        raise SyncCoordinatorError(
            "Indexer snapshots lag behind the persisted sync checkpoint; "
            "wait for Indexer catch-up before resuming projection"
        )
    return checkpoint


async def catch_up_the_sync_manually(sync_state: SyncState, current_round: int) -> SyncState:
    logger.info("\n\nMANUAL roll rock and roll BABE.\n")
    logger.info(
        f"Last sync round = {sync_state.last_round}, sync lag = {sync_state.rounds_since_updated(current_round)} rounds.\n"
    )

    _ = await load_all_assets_data()
    if settings.sync_staking_pools:
        raise RuntimeError(
            "legacy staking-pool projection is disabled until full Algorand group validation is implemented"
        )

    current_round = await get_current_round()
    logger.info(f"\n\nAnother, shorter loop, starting from round {current_round}\n")
    if settings.sync_liquidity_pools:
        logger.info("\n\nSyncing LP states from authoritative account snapshots.\n")
        _ = await create_lp_states_from_all_pools()
        snapshotted_states = await update_all_lp_states_linear()
        _ = await create_and_update_asset_prices()
    else:
        snapshotted_states = []

    checkpoint_round = _snapshot_checkpoint_round(
        previous_round=sync_state.last_round,
        node_round=current_round,
        lp_states=snapshotted_states,
    )

    coordinator = MongoSyncCoordinator(
        db.sync_states.mongodb_collection,
    )
    sync_state = await asyncio.to_thread(
        coordinator.advance_snapshot,
        expected_last_round=sync_state.last_round,
        round_number=checkpoint_round,
    )
    logger.info(f"\n\nALL synced up to round {checkpoint_round}.\n")

    return sync_state


async def sync_pools_loop():
    if settings.sync_staking_pools:
        raise RuntimeError(
            "legacy staking-pool projection is disabled until full Algorand group validation is implemented"
        )
    if not settings.sync_liquidity_pools:
        logger.warning(
            "Financial sync is disabled; set SYNC_LIQUIDITY_POOLS=true only after reviewing the snapshot cutover"
        )
        return

    current_round = await get_current_round()
    logger.info(f"\n\nEnter sync loop. Current round = {current_round}")
    sync_state = await get_sync_state()

    previous_round = sync_state.last_round
    try:
        sync_state = await catch_up_the_sync_manually(sync_state, current_round)
    except SyncCoordinatorError:
        # A competing worker may have completed the same authoritative cutover.
        refreshed = await get_sync_state()
        if refreshed.last_round == previous_round:
            raise
        sync_state = refreshed

    logger.info("\n\nMain BLOCKCHAIN sync loop!\n")

    coordinator = MongoSyncCoordinator(
        db.sync_states.mongodb_collection,
    )
    worker_id = uuid4().hex
    no_block_seconds = 0
    processing_attempts = 0
    MAX_BLOCK_DELAY_SECONDS = 10
    while True:
        next_round = sync_state.last_round + 1

        try:
            block_dict = await asyncio.to_thread(
                indexer_client.block_info,
                round_num=next_round,
            )
        except Exception as e:
            no_block_seconds += 1
            if no_block_seconds > MAX_BLOCK_DELAY_SECONDS:
                logger.debug(f"No #{next_round} for {no_block_seconds} seconds: {e}")

            await asyncio.sleep(1)
            continue

        no_block_seconds = 0

        claimed = await asyncio.to_thread(
            coordinator.claim_round,
            owner=worker_id,
            expected_last_round=sync_state.last_round,
            round_number=next_round,
        )
        if claimed is None:
            await asyncio.sleep(0.25)
            sync_state = await get_sync_state()
            continue

        try:
            raw_transactions = block_dict["transactions"]
            logger.debug(f"Fetch #{next_round}: sync {len(raw_transactions)} txns")

            if settings.sync_staking_pools:
                raise RuntimeError(
                    "legacy staking-pool projection is disabled until full Algorand group validation is implemented"
                )
            updated_pool_states: list[PoolState] = []
            updated_lp_states = (
                await update_lp_states(
                    find_transfer_payment_transactions(raw_transactions),
                    expected_round=next_round,
                )
                if settings.sync_liquidity_pools
                else []
            )
            _ = await update_asset_prices(updated_lp_states)

            sync_state = await asyncio.to_thread(
                coordinator.complete_round,
                owner=worker_id,
                expected_last_round=sync_state.last_round,
                round_number=next_round,
            )
            db.sync_blocks.get_or_create(
                SyncBlock(
                    round=next_round,
                    timestamp=block_dict["timestamp"],
                )
            )
            processing_attempts = 0

            logger.debug(f"#{next_round} sync OK! Saved {len(updated_pool_states) + len(updated_lp_states)} txns\n")
        except Exception as e:
            processing_attempts += 1
            await asyncio.to_thread(
                coordinator.release_after_error,
                owner=worker_id,
                round_number=next_round,
                error=f"{type(e).__name__}: {e}",
            )
            logger.error(f"Error processing round {next_round}: {e}", exc_info=True)
            if processing_attempts >= settings.sync_round_max_attempts:
                raise RuntimeError(f"round {next_round} failed {processing_attempts} consecutive times") from e
            delay_cap = min(
                2 ** (processing_attempts - 1),
                settings.sync_retry_max_seconds,
            )
            await asyncio.sleep(random.uniform(0, delay_cap))
            sync_state = await get_sync_state()
            continue


async def get_sync_pool_state_by_id(pool_id: int) -> PoolState:
    pool_state = await get_or_create_pool_state(pool_id)
    if await is_sync_delayed():
        pool_state = await update_pool_state(pool_state)
    return pool_state


async def get_sync_user_state_by_address(user_address: str) -> UserState:
    user_state = db.user_states.get_one(address=user_address)
    # TODO: uncomment
    # if is_sync_delayed():
    #     user_state = await update_user_state(user_state)
    return user_state
