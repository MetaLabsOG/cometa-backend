import json
import logging
from collections import defaultdict
from typing import Optional

from algosdk.v2client import indexer

from blockchain.node import get_current_round
from core.new import db
from core.new.db.model import PoolState, PoolTransaction
from core.new.meta_exception import MetaError
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


def pool_transaction_from_asset_transfer_tx_dict(pool_id: str, txid: str, tx: dict) -> PoolTransaction:
    return PoolTransaction(
        id=txid,
        pool_id=pool_id,
        user_address=tx['sender'],
        asa_id=tx[ASSET_TRANSFER_TX]['asset-id'],
        delta_amount_micros=tx[ASSET_TRANSFER_TX]['amount'],
        confirmed_round=tx['confirmed-round']
    )


def fetch_new_transactions(pool: PoolState) -> list[PoolTransaction]:
    new_transactions = []
    next_token = None

    while True:
        data = indexer_client.search_transactions_by_address(
            address=pool.address,
            next_page=next_token
        )
        txns = data['transactions']
        logger.debug(f'Pool {pool.id}: new {len(txns)} txns')

        for tx in txns:
            txid = tx['id']
            if txid == pool.last_txid:
                # all the next (previous) txns was already processed
                break

            if ASSET_TRANSFER_TX in tx:
                pool_tx = pool_transaction_from_asset_transfer_tx_dict(pool.id, txid, tx)
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
                        pool_tx = pool_transaction_from_asset_transfer_tx_dict(pool.id, txid, inner_tx)
                        # TODO: use pooL_type withdraw/stake
                        pool_tx.delta_amount_micros = -pool_tx.delta_amount_micros
                        new_transactions.append(pool_tx)

        if 'next-token' in data:
            next_token = data['next-token']
        else:
            break

    return new_transactions


def update_pool_state(pool_id: int) -> PoolState:
    pool_state = db.pool_states.get_by_primary_key(pool_id, throw_ex=False)
    if pool_state is None:
        pool_address = get_pool_address(pool_id)
        if pool_address is None:
            pass  # TODO: think

        pool_state = PoolState(
            id=pool_id,
            stake_token_id=0,  # TODO: set correct value
            address=pool_address
        )
    new_transactions = fetch_new_transactions(pool_state)
    new_transactions.reverse()
    for tx in new_transactions:
        pool_state.staked_amount_micros += tx.delta_amount_micros
        pool_state.last_txid = tx.id
        pool_state.last_updated_round = tx.confirmed_round
    return pool_state


def get_pool_snapshot(pool_id: int, max_round: Optional[int] = None):
    pool_address = get_pool_address(pool_id)
    if pool_address is None:
        pool_address = get_pool_address(pool_id)
    if pool_address is None:
        raise MetaError(message=f'Pool {pool_id} not found, bro.')
    print(f'Pool wallet: {pool_address}')

    if max_round is None:
        max_round = get_current_round()

    next_token = None
    all_txns = []
    balances = defaultdict(lambda: 0)

    while True:
        data = indexer_client.search_transactions_by_address(address=pool_address,
                                                             next_page=next_token)
        txns = data['transactions']
        print(f'New txns, cnt = {len(txns)}')

        for tx in txns:
            if ASSET_TRANSFER_TX in tx:
                if max_round is not None and tx['confirmed-round'] > max_round:
                    continue

                sender = tx['sender']
                amount = tx[ASSET_TRANSFER_TX]['amount']
                if sender == watch_address:
                    print(f'{balances[sender]} + {amount} = {balances[sender] + amount}')
                balances[sender] += amount
            elif APPLICATION_CALL_TX in tx:
                inner_txns = tx['inner-txns']
                is_claim = False
                for inner_tx in inner_txns:
                    if PAYMENT_TX in inner_tx:
                        is_claim = True
                if is_claim:
                    continue
                for inner_tx in inner_txns:
                    if ASSET_TRANSFER_TX in inner_tx:
                        if inner_tx['confirmed-round'] > max_round:
                            continue

                        receiver = inner_tx[ASSET_TRANSFER_TX]['receiver']
                        amount = inner_tx[ASSET_TRANSFER_TX]['amount']
                        if receiver == watch_address:
                            print(f'{balances[receiver]} - {amount} = {balances[receiver] - amount}')
                        balances[receiver] -= amount

        print(f'{len(txns)} txns processed!')
        print(f'Currently {len(balances)} balances')
        print()

        all_txns.extend(txns)
        if 'next-token' in data:
            next_token = data['next-token']
        else:
            break

    res_filename = f'pool_{pool_id}_round_{max_round}.json'
    with open(res_filename, 'w') as write_file:
        json.dump(balances, write_file, indent=4, sort_keys=True)

    print(f'{len(all_txns)} processed!')
    print(f'{len(balances)} wallets are written to "{res_filename}"!')

    total_microtokens = 0
    for k, v in balances.items():
        total_microtokens += v

    print(f'In total {total_microtokens} microtokens')

    return balances
