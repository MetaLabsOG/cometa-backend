import logging

from algosdk import mnemonic, account
from algosdk.future.transaction import AssetTransferTxn, wait_for_confirmation

from blockchain.node import init_algod_client
from env import settings

private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)

algod = init_algod_client()
logger = logging.getLogger(__name__)


def send_nft(address: str, nft_id: int, amount: int = 1) -> None:
    logger.info(f'Sending NFT {nft_id} to {address}')
    params = algod.suggested_params()
    txn = AssetTransferTxn(
        sender=public_key,
        sp=params,
        receiver=address,
        amt=amount,
        index=nft_id)
    stxn = txn.sign(private_key)

    txid = algod.send_transaction(stxn)
    wait_for_confirmation(algod, txid)
    logger.info(f'Sent NFT {nft_id} to {address} with tx {txid}')
