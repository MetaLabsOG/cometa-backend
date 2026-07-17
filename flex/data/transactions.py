import asyncio
import logging

from flex.blockchain.base import indexer_client
from flex.blockchain.info import get_app_address
from flex.db.model.blockchain import PoolTransaction
from flex.db.model.pool_states import PoolState
from flex.domain.transactions import (
    APPLICATION_CALL_TX,
    ASSET_TRANSFER_TX,
    event_id_aliases,
    flatten_asset_transfers,
)
from flex.meta_error import MetaError

logger = logging.getLogger(__name__)


async def pool_fetch_new_transactions_by_id(
    pool_id: int, asset_id: int, last_tx_id: str | None = None, pool_address: str | None = None, new_first: bool = False
) -> list[PoolTransaction]:
    logger.debug(
        f"Fetching new transactions for pool {pool_id}: after {last_tx_id}, pool_address {pool_address}, new_first {new_first}"
    )

    if pool_address is None:
        pool_address = await get_app_address(pool_id)
        if pool_address is None:
            raise MetaError(f"Pool {pool_id} address not found")

    new_transactions = []
    next_token = None
    last_root_tx_id = event_id_aliases(last_tx_id)[-1] if last_tx_id is not None else None

    still_new = True

    loop = asyncio.get_running_loop()

    while still_new:
        data = await loop.run_in_executor(
            None,
            lambda nt=next_token: indexer_client.search_transactions_by_address(address=pool_address, next_page=nt),
        )
        txns = data["transactions"]
        logger.debug(f"Pool {pool_id}: processing {len(txns)} txns...")

        for tx in txns:
            txid = tx["id"]
            if txid == last_root_tx_id:
                logger.debug(f"Pool {pool_id}: last tx {txid} reached")
                still_new = False
                break

            if ASSET_TRANSFER_TX in tx:
                # Stake
                tx_asa_id = int(tx[ASSET_TRANSFER_TX]["asset-id"])
                if asset_id != tx_asa_id:
                    continue
                tx_amount = tx[ASSET_TRANSFER_TX]["amount"]
                if tx_amount == 0:
                    continue
                pool_tx = PoolTransaction(
                    id=txid,
                    pool_id=pool_id,
                    user_address=tx["sender"],
                    pool_address=pool_address,
                    asa_id=tx_asa_id,
                    delta_amount_micros=tx_amount,
                    confirmed_round=tx["confirmed-round"],
                )
                new_transactions.append(pool_tx)

            elif APPLICATION_CALL_TX in tx:
                for inner_tx in flatten_asset_transfers([tx]):
                    tx_asa_id = int(inner_tx[ASSET_TRANSFER_TX]["asset-id"])
                    if asset_id != tx_asa_id:
                        continue
                    tx_amount = inner_tx[ASSET_TRANSFER_TX]["amount"]
                    if tx_amount == 0:
                        continue
                    pool_tx = PoolTransaction(
                        id=inner_tx["id"],
                        pool_id=pool_id,
                        user_address=inner_tx[ASSET_TRANSFER_TX]["receiver"],
                        pool_address=pool_address,
                        asa_id=tx_asa_id,
                        delta_amount_micros=-tx_amount,
                        confirmed_round=inner_tx["confirmed-round"],
                    )
                    new_transactions.append(pool_tx)

        if "next-token" in data:
            next_token = data["next-token"]
        else:
            break

    logger.debug(f"Pool {pool_id}: in total {len(new_transactions)} user action txns")

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
        new_first=new_first,
    )
