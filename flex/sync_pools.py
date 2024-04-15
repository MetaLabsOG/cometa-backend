import asyncio
import logging
from datetime import timedelta

from cachetools import cached, LRUCache

from env import settings
from flex import db
from flex.blockchain.base import indexer_client
from flex.blockchain.info import get_current_round
from flex.data.lp_states import update_all_lp_states_linear, update_lp_states_with_transactions, create_lp_states
from flex.data.pool_state import update_pool_states_with_transactions, update_all_pool_states_linear, \
    get_or_create_pool_state, update_pool_state, update_user_state
from flex.data.transactions import ASSET_TRANSFER_TX, APPLICATION_CALL_TX, PAYMENT_TX
from flex.db.model.blockchain import PoolTransaction, SyncState, SyncBlock
from flex.db.model.liquidity_pools import LpState, LpTransaction
from flex.db.model.pool_states import PoolState, UserState

logger = logging.getLogger(__name__)


def find_transfer_transactions(txns: list[dict]) -> list[dict]:
    transfer_transactions = []
    for tx in txns:
        if ASSET_TRANSFER_TX in tx:
            # Stake
            transfer_transactions.append(tx)

        elif APPLICATION_CALL_TX in tx:
            inner_txns = tx.get('inner-txns')
            if inner_txns is None:
                continue

            is_claim = False
            for inner_tx in inner_txns:
                if PAYMENT_TX in inner_tx:
                    is_claim = True
            if is_claim:
                # TODO: save claim tx as well
                continue

            for inner_tx in inner_txns:
                if ASSET_TRANSFER_TX in inner_tx:
                    # Withdraw
                    inner_tx['id'] = tx['id']
                    transfer_transactions.append(inner_tx)
    return transfer_transactions


@cached(cache=LRUCache(maxsize=1024))
def get_pool_state_by_address(address: str) -> PoolState:
    return db.pool_states.get_one(address=address)


def process_lp_transactions(transactions: list[dict]) -> list[LpTransaction]:
    lp_transactions = []
    for tx in transactions:
        txid = tx['id']
        sender = tx['sender']
        asa_id = tx[ASSET_TRANSFER_TX]['asset-id']
        receiver = tx[ASSET_TRANSFER_TX]['receiver']
        amount = tx[ASSET_TRANSFER_TX]['amount']
        confirmed_round = tx['confirmed-round']

        lp_state_send = db.lp_states.get_one(address=sender)
        if lp_state_send is not None:
            lp_tx = LpTransaction(
                id=txid,
                pool_address=sender,
                user_address=receiver,
                asa_id=asa_id,
                delta_amount_micros=-amount,
                confirmed_round=confirmed_round,
            )
            lp_transactions.append(lp_tx)

        # TODO: optimize, maybe return with txns
        lp_state_receive = db.lp_states.get_one(address=receiver)
        if lp_state_receive is not None:
            lp_tx = LpTransaction(
                id=txid,
                pool_address=receiver,
                user_address=sender,
                asa_id=asa_id,
                delta_amount_micros=amount,
                confirmed_round=confirmed_round,
            )
            lp_transactions.append(lp_tx)

    return lp_transactions


def process_pool_transactions(txns: list[dict]) -> list[PoolTransaction]:
    pool_transactions = []
    for tx in txns:
        txid = tx['id']
        sender = tx['sender']
        tx_asa_id = tx[ASSET_TRANSFER_TX]['asset-id']
        receiver = tx[ASSET_TRANSFER_TX]['receiver']
        amount = tx[ASSET_TRANSFER_TX]['amount']
        confirmed_round = tx['confirmed-round']

        # TODO: optimize lookup locally
        withdraw_pool = get_pool_state_by_address(address=sender)
        if withdraw_pool is not None:
            if withdraw_pool.stake_token.id == tx_asa_id:
                pool_tx = PoolTransaction(
                    id=txid,
                    pool_id=withdraw_pool.pool_id,
                    user_address=receiver,
                    pool_address=withdraw_pool.address,
                    asa_id=tx_asa_id,
                    delta_amount_micros=-amount,
                    confirmed_round=confirmed_round
                )
                pool_transactions.append(pool_tx)

        stake_pool = get_pool_state_by_address(address=receiver)
        if stake_pool is not None:
            if stake_pool.stake_token.id == tx_asa_id:
                pool_tx = PoolTransaction(
                    id=txid,
                    pool_id=stake_pool.pool_id,
                    user_address=sender,
                    pool_address=stake_pool.address,
                    asa_id=tx_asa_id,
                    delta_amount_micros=amount,
                    confirmed_round=confirmed_round
                )
                pool_transactions.append(pool_tx)

    return pool_transactions


def get_sync_state() -> SyncState:
    sync_state = db.sync_states.get_one()
    if sync_state is None:
        sync_state = db.sync_states.create(SyncState())
    return sync_state


SYNC_MAX_DELAY = timedelta(minutes=1)
SYNC_MAX_DELAY_ROUNDS = int(SYNC_MAX_DELAY.total_seconds() / settings.block_time)


def is_sync_delayed(current_round: int | None = None) -> bool:
    if current_round is None:
        current_round = get_current_round()
    sync_state = get_sync_state()
    return current_round - sync_state.last_round > SYNC_MAX_DELAY_ROUNDS


async def update_pools(txns: list[dict]) -> [PoolState]:
    pool_transactions = process_pool_transactions(txns)
    return await update_pool_states_with_transactions(pool_transactions)


async def update_lps(txns: list[dict]) -> list[LpState]:
    lp_transactions = process_lp_transactions(txns)
    return await update_lp_states_with_transactions(lp_transactions)


async def sync_pools_loop():
    current_round = get_current_round()

    logger.info(f'\n\nStart pools sync loop. Current round = {current_round}\n\n')

    sync_state = get_sync_state()
    sync_lag = current_round - sync_state.last_round if sync_state.last_round is not None else None

    if sync_state.last_round is None or sync_lag > settings.sync_lag_max_rounds:
        logger.info('\n\nSyncing ALL pool states in order first.')
        logger.info(f'Last sync round = {sync_state.last_round}, sync lag = {sync_lag} rounds.\n\n')

        await update_all_pool_states_linear()

        current_round = get_current_round()
        logger.info(f'\n\nAnother, shorter loop, starting from round {current_round}\n\n')
        await update_all_pool_states_linear()

        # TODO: async
        logger.info('\n\nSyncing ALL LP states linearly.\n\n')
        create_lp_states()
        update_all_lp_states_linear()

        sync_state.last_round = current_round
        db.sync_states.update(sync_state)
        logger.info(f'\n\nPools synced up to round {current_round}.\n\n')

    logger.info('\n\nStarting the main BLOCKCHAIN sync loop.\n\n')

    no_block_seconds = 0
    MAX_BLOCK_DELAY_SECONDS = 10
    while True:
        next_round = sync_state.last_round + 1

        try:
            block_dict = indexer_client.block_info(round_num=next_round)
        except Exception as e:
            no_block_seconds += 1
            if no_block_seconds > MAX_BLOCK_DELAY_SECONDS:
                logger.debug(f'No #{next_round} for {no_block_seconds} seconds: {e}')

            await asyncio.sleep(1)
            continue

        no_block_seconds = 0

        try:
            raw_transactions = block_dict['transactions']
            transfer_transactions = find_transfer_transactions(raw_transactions)
            logger.debug(f'Fetch #{next_round}: sync {len(raw_transactions)} txns')

            updated_pool_states = await update_pools(transfer_transactions)
            updated_lp_states = await update_lps(transfer_transactions)

            sync_state.last_round = next_round
            db.sync_states.update(sync_state)
            db.sync_blocks.create(
                SyncBlock(
                    round=next_round,
                    timestamp=block_dict['timestamp']
                )
            )

            logger.debug(f'#{next_round} sync OK! Saved {len(updated_pool_states) + len(updated_lp_states)} txns\n')
        except Exception as e:
            logger.error(f'Error processing round {next_round}: {e}', exc_info=True)
            continue


async def get_sync_pool_state_by_id(pool_id: int) -> PoolState:
    pool_state = await get_or_create_pool_state(pool_id)
    if is_sync_delayed():
        pool_state = await update_pool_state(pool_state)
    return pool_state


async def get_sync_user_state_by_address(user_address: str) -> UserState:
    user_state = db.user_states.get_one(address=user_address)
    if is_sync_delayed():
        user_state = await update_user_state(user_state)
    return user_state
