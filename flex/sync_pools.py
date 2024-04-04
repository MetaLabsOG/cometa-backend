import asyncio
import logging

from cachetools import cached, LRUCache

from flex import db
from flex.blockchain import get_current_round, indexer_client
from flex.data.pool_state import update_pools_with_transactions, update_all_pool_states_linear
from flex.data.transactions import ASSET_TRANSFER_TX, APPLICATION_CALL_TX, PAYMENT_TX
from flex.db.model import SyncState, PoolTransaction, SyncBlock, PoolState

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


def process_transactions(txns: list[dict]) -> list[PoolTransaction]:
    transfer_transactions = find_transfer_transactions(txns)
    pool_transactions = []
    for tx in transfer_transactions:
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


async def sync_pools_loop():
    logger.info('\n\nEnter the pools sync loop.\n\n')
    sync_state = get_sync_state()

    if sync_state.last_round is None:
        logger.info('\n\nSyncing pools for the first time.\n\n')
        await update_all_pool_states_linear()

        current_round = get_current_round()

        logger.info(f'\n\nAnother, shorter loop, starting from round {current_round}\n\n')
        await update_all_pool_states_linear()

        sync_state.last_round = current_round
        logger.info(f'\n\nPools synced up to round {current_round}.\n\n')

    while True:
        next_round = sync_state.last_round + 1

        try:
            block_dict = indexer_client.block_info(round_num=next_round)
        except Exception as e:
            logger.error(f'#{next_round} NOT HERE SORRY: {e}')
            await asyncio.sleep(1)
            continue

        try:
            raw_transactions = block_dict['transactions']
            logger.debug(f'Fetch #{next_round}: sync {len(raw_transactions)} txns')

            pool_transactions = process_transactions(raw_transactions)
            _ = await update_pools_with_transactions(pool_transactions)

            sync_state.last_round = next_round
            db.sync_states.update(sync_state)
            db.sync_blocks.create(
                SyncBlock(
                    round=next_round,
                    timestamp=block_dict['timestamp'],
                    pool_tx_ids=[tx.id for tx in pool_transactions],
                )
            )

            logger.debug(f'#{next_round} sync OK: {len(pool_transactions)} pool txns\n')
        except Exception as e:
            logger.error(f'Error processing round {next_round}: {e}', exc_info=True)
            continue
