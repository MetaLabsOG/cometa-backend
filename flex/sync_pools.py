import asyncio
import logging
import random
from uuid import uuid4

from aiocache import cached as cached_async

from env import settings
from flex import db
from flex.blockchain.base import indexer_client
from flex.blockchain.info import get_current_round
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
from flex.db.model.blockchain import PoolTransaction, SyncBlock, SyncState
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.db.model.pool_states import PoolState, UserState
from flex.db.sync_coordinator import (
    MongoSyncCoordinator,
    SyncCoordinatorError,
)
from flex.domain.algorand import require_algorand_uint64
from flex.domain.lp_projection import (
    lp_cursor_complete_through,
)
from flex.domain.transactions import (
    ASSET_TRANSFER_TX,
    PAYMENT_TX,
    flatten_asset_transfers,
    flatten_transfer_payments,
    projection_event_id,
)
from flex.sync_state import get_sync_state, is_sync_delayed
from flex.util import build_key_str

logger = logging.getLogger(__name__)


def get_lp_tracked_assets_by_address() -> dict[str, frozenset[int]]:
    return {
        lp_state.address: frozenset(
            {
                0,
                lp_state.asset1_id,
                lp_state.asset2_id,
                lp_state.token_id,
            }
        )
        for lp_state in db.lp_states.get_all()
    }


def find_transfer_payment_transactions(txns: list[dict]) -> list[dict]:
    return flatten_transfer_payments(txns)


def find_transfer_transactions(txns: list[dict]) -> list[dict]:
    return flatten_asset_transfers(txns)


@cached_async(ttl=30, namespace="pool_state", key_builder=build_key_str)
async def get_pool_state_by_address(address: str) -> PoolState:
    return db.pool_states.get_one(address=address)


def _transaction_fee(tx: dict, *, txid: str) -> int:
    try:
        return require_algorand_uint64(
            tx.get("fee"),
            "LP transaction fee",
        )
    except ValueError as exc:
        raise ValueError(f"{exc}: {txid}") from exc


async def process_lp_transactions(transactions: list[dict]) -> list[LpTransaction]:
    tracked_assets_by_address = get_lp_tracked_assets_by_address()
    all_lp_addresses = tracked_assets_by_address.keys()

    lp_transactions = []
    for event_position, tx in enumerate(transactions):
        txid = tx["id"]
        sender = tx["sender"]
        confirmed_round = require_algorand_uint64(
            tx.get("confirmed-round"),
            "LP transaction confirmed-round",
        )

        if ASSET_TRANSFER_TX in tx:
            transfer = tx[ASSET_TRANSFER_TX]
            receiver = transfer["receiver"]
            asa_id = require_algorand_uint64(
                transfer.get("asset-id"),
                "LP transaction asset-id",
                positive=True,
            )
            amount = require_algorand_uint64(
                transfer.get("amount"),
                "LP transaction amount",
            )
            affected_addresses = {
                sender,
                receiver,
                transfer.get("sender"),
                transfer.get("close-to"),
            }
            if not (affected_addresses & all_lp_addresses):
                continue
            if any(field in transfer for field in ("sender", "close-to", "close-amount")):
                tracked_affected_pool = any(
                    address in tracked_assets_by_address and asa_id in tracked_assets_by_address[address]
                    for address in affected_addresses
                    if address is not None
                )
                if tracked_affected_pool:
                    raise ValueError(f"LP projection does not support clawback/close semantics: {txid}")
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
            amount = require_algorand_uint64(
                payment.get("amount"),
                "LP transaction amount",
            )
        else:
            raise ValueError(f"Invalid transaction type: {tx}")

        fee = _transaction_fee(tx, txid=txid)
        sender_assets = tracked_assets_by_address.get(sender)
        receiver_assets = tracked_assets_by_address.get(receiver)
        sender_tracks_asset = sender_assets is not None and asa_id in sender_assets
        receiver_tracks_asset = receiver_assets is not None and asa_id in receiver_assets
        is_pool_self_transfer = sender == receiver and sender_tracks_asset
        if is_pool_self_transfer:
            # A self-transfer has zero net effect on the pool. Emitting both
            # legs would create the same scoped event ID twice and make a
            # deduplicating projector persist only one side. Its network fee
            # is still a real ALGO debit and is projected separately below.
            pass

        elif sender_tracks_asset:
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

        if not is_pool_self_transfer and receiver_tracks_asset:
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

        if sender_assets is not None and fee:
            lp_transactions.append(
                LpTransaction(
                    id=projection_event_id(f"{txid}#fee", sender),
                    pool_address=sender,
                    user_address=sender,
                    asa_id=0,
                    delta_amount_micros=-fee,
                    confirmed_round=confirmed_round,
                    event_position=event_position,
                )
            )

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


async def update_pools(txns: list[dict]) -> list[PoolState]:
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


async def reconcile_sync_checkpoint(sync_state: SyncState, current_round: int) -> SyncState:
    logger.info("Reconciling LP snapshots before event sync")
    logger.info(
        f"Last sync round = {sync_state.last_round}, sync lag = {sync_state.rounds_since_updated(current_round)} rounds.\n"
    )

    _ = await load_all_assets_data()
    if settings.sync_staking_pools:
        raise RuntimeError(
            "legacy staking-pool projection is disabled until full Algorand group validation is implemented"
        )

    current_round = await get_current_round()
    logger.info("Starting event sync from reconciled round %s", current_round)
    if settings.sync_liquidity_pools:
        logger.info("\n\nSyncing LP states from authoritative account snapshots.\n")
        _ = await create_lp_states_from_all_pools()
        snapshotted_states = await update_all_lp_states_linear()
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
    logger.info("Snapshot reconciliation complete through round %s", checkpoint_round)

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
        sync_state = await reconcile_sync_checkpoint(sync_state, current_round)
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
    return db.user_states.get_one(address=user_address)
