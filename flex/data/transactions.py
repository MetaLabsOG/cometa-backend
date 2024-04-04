import logging

from flex.blockchain import indexer_client, get_app_address
from flex.db.model.blockchain import PoolTransaction
from flex.db.model.pool_states import PoolState

# class TransactionTypeName:
ASSET_TRANSFER_TX = 'asset-transfer-transaction'
APPLICATION_CALL_TX = 'application-transaction'
PAYMENT_TX = 'payment-transaction'


logger = logging.getLogger(__name__)


async def pool_fetch_new_transactions_by_id(
        pool_id: int,
        asset_id: int,
        last_tx_id: str | None = None,
        pool_address: str | None = None,
        new_first: bool = False
) -> list[PoolTransaction]:
    logger.debug(f'Fetching new transactions for pool {pool_id}: after {last_tx_id}, pool_address {pool_address}, new_first {new_first}')

    if pool_address is None:
        pool_address = get_app_address(pool_id)
        if pool_address is None:
            pass  # TODO: think

    new_transactions = []
    next_token = None

    still_new = True

    while still_new:
        data = indexer_client.search_transactions_by_address(
            address=pool_address,
            next_page=next_token
        )
        txns = data['transactions']
        logger.debug(f'Pool {pool_id}: processing {len(txns)} txns...')

        for tx in txns:
            txid = tx['id']
            if txid == last_tx_id:
                logger.debug(f'Pool {pool_id}: last tx {txid} reached')
                still_new = False
                break

            if ASSET_TRANSFER_TX in tx:
                # Stake
                tx_asa_id = int(tx[ASSET_TRANSFER_TX]['asset-id'])
                if asset_id != tx_asa_id:
                    continue
                pool_tx = PoolTransaction(
                    id=txid,
                    pool_id=pool_id,
                    user_address=tx['sender'],
                    pool_address=pool_address,
                    asa_id=tx_asa_id,
                    delta_amount_micros=tx[ASSET_TRANSFER_TX]['amount'],
                    confirmed_round=tx['confirmed-round']
                )
                new_transactions.append(pool_tx)

            elif APPLICATION_CALL_TX in tx:
                inner_txns = tx['inner-txns']

                is_claim = False
                for inner_tx in inner_txns:
                    if PAYMENT_TX in inner_tx:
                        is_claim = True
                        if ASSET_TRANSFER_TX in inner_tx and inner_tx[ASSET_TRANSFER_TX]['asset-id'] == asset_id:
                            print(f'There are claim + transfer lol: {txid}\n')
                if is_claim:
                    # TODO: save claim tx as well
                    continue

                for inner_tx in inner_txns:
                    if ASSET_TRANSFER_TX in inner_tx:
                        # Withdraw
                        tx_asa_id = int(inner_tx[ASSET_TRANSFER_TX]['asset-id'])
                        if asset_id != tx_asa_id:
                            continue
                        pool_tx = PoolTransaction(
                            id=txid,
                            pool_id=pool_id,
                            user_address=inner_tx[ASSET_TRANSFER_TX]['receiver'],
                            pool_address=pool_address,
                            asa_id=tx_asa_id,
                            delta_amount_micros=-inner_tx[ASSET_TRANSFER_TX]['amount'],
                            confirmed_round=inner_tx['confirmed-round']
                        )
                        # TODO: use pooL_type withdraw/stake
                        new_transactions.append(pool_tx)

        if 'next-token' in data:
            next_token = data['next-token']
        else:
            break

    logger.debug(f'Pool {pool_id}: in total {len(new_transactions)} user action txns')

    if not new_first:
        # txns are in reverse order in indexer response
        new_transactions.reverse()

    return new_transactions


async def pool_fetch_new_transactions(pool: PoolState, new_first: bool = False) -> list[PoolTransaction]:
    return await pool_fetch_new_transactions_by_id(
        pool_id=pool.pool_id,
        asset_id=pool.stake_token.id,
        last_tx_id=pool.last_tx_id,
        pool_address=pool.address,
        new_first=new_first
    )
