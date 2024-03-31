import logging

from algosdk.v2client import indexer

from core.db.contracts import get_contract
from core.new import db
from core.new.blockchain import asset_micros_to_amount
from core.new.db.model import PoolState, PoolTransaction
from env import settings


# class TransactionTypeName:
ASSET_TRANSFER_TX = 'asset-transfer-transaction'
APPLICATION_CALL_TX = 'application-transaction'
PAYMENT_TX = 'payment-transaction'


indexer_client = indexer.IndexerClient(indexer_token=settings.algod_token, indexer_address=settings.algo_indexer_address)
logger = logging.getLogger(__name__)


def get_pool_address(pool_id: int) -> str | None:
    data = indexer_client.application_logs(application_id=pool_id, limit=10)
    log_data = data.get('log-data')
    if log_data is None or len(log_data) == 0:
        return None

    txid = log_data[0]['txid']
    data = indexer_client.transaction(txid=txid)
    transaction = data.get('transaction')
    if transaction is None:
        return None

    return transaction['inner-txns'][0]['sender']


def pool_transaction_from_asset_transfer_tx_dict(pool_id: int, txid: str, tx: dict) -> PoolTransaction:
    return PoolTransaction(
        id=txid,
        pool_id=pool_id,
        user_address=tx['sender'],
        asa_id=tx[ASSET_TRANSFER_TX]['asset-id'],
        delta_amount_micros=tx[ASSET_TRANSFER_TX]['amount'],
        confirmed_round=tx['confirmed-round']
    )


def pool_fetch_new_transactions_by_id(
        pool_id: int,
        after_txid: str | None = None,
        pool_address: str | None = None,
        new_first: bool = False
) -> list[PoolTransaction]:
    logger.debug(f'Fetching new transactions for pool {pool_id}')

    if pool_address is None:
        pool_address = get_pool_address(pool_id)
        if pool_address is None:
            pass  # TODO: think

    new_transactions = []
    next_token = None

    while True:
        data = indexer_client.search_transactions_by_address(
            address=pool_address,
            next_page=next_token
        )
        txns = data['transactions']
        logger.debug(f'Pool {pool_id}: new {len(txns)} txns')

        for tx in txns:
            txid = tx['id']
            if txid == after_txid:
                # all the next (previous) txns was already processed
                break

            if ASSET_TRANSFER_TX in tx:
                pool_tx = pool_transaction_from_asset_transfer_tx_dict(pool_id, txid, tx)
                new_transactions.append(pool_tx)

            elif APPLICATION_CALL_TX in tx:
                inner_txns = tx['inner-txns']

                is_claim = False
                for inner_tx in inner_txns:
                    if PAYMENT_TX in inner_tx:
                        is_claim = True
                if is_claim:
                    # TODO: save claim tx as well
                    continue

                for inner_tx in inner_txns:
                    if ASSET_TRANSFER_TX in inner_tx:
                        pool_tx = pool_transaction_from_asset_transfer_tx_dict(pool_id, txid, inner_tx)
                        # TODO: use pooL_type withdraw/stake
                        pool_tx.delta_amount_micros = -pool_tx.delta_amount_micros
                        new_transactions.append(pool_tx)

        if 'next-token' in data:
            next_token = data['next-token']
        else:
            break

    logger.debug(f'Pool {pool_id}: fetched {len(new_transactions)} new txns')
    if not new_first:
        # txns are in reverse order in indexer response
        new_transactions.reverse()

    return new_transactions


def pool_fetch_new_transactions(pool: PoolState, new_first: bool = False) -> list[PoolTransaction]:
    return pool_fetch_new_transactions_by_id(pool.pool_id, pool.last_tx_id, pool.address, new_first)


def update_pool_state(pool_id: int) -> PoolState:
    logger.debug(f'Updating pool state {pool_id}')

    pool_state = db.pool_states.get_one(pool_id=pool_id)
    if pool_state is None:
        pool_address = get_pool_address(pool_id)
        if pool_address is None:
            pass  # TODO: think

        contract_info = get_contract(pool_id)
        if contract_info is None:
            pass  # TODO: ...

        pool_state = PoolState(
            pool_id=pool_id,
            stake_token_id=contract_info.metadata['stake_token_id'],
            address=pool_address
        )
        logger.debug(f'Created new pool state:\n{pool_state.pretty_str()}')

    new_transactions = pool_fetch_new_transactions(pool_state)
    if len(new_transactions) > 0:
        db.pool_transactions.create_many(new_transactions)
        logger.debug(f'Pool {pool_id}: saved {len(new_transactions)} new txns')

        for tx in new_transactions:
            pool_state.staked_amount_micros += tx.delta_amount_micros
            pool_state.staked_amount += asset_micros_to_amount(pool_state.stake_token_id, tx.delta_amount_micros)
            pool_state.last_tx = tx.to_info()

    return pool_state
