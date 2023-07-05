import logging

from algosdk import mnemonic, account
from algosdk.future.transaction import AssetTransferTxn, wait_for_confirmation

from blockchain.node import init_algod_client
from env import settings

cometa_private_key = mnemonic.to_private_key(settings.cometa_rekey_mnemonic)
cometa_rekey_private_key = mnemonic.to_private_key(settings.cometa_rekey_mnemonic)
cometa_public_key = account.address_from_private_key(cometa_private_key)

algod = init_algod_client()
logger = logging.getLogger(__name__)


def send_nft(address: str, nft_id: int, amount: int = 1) -> None:
    logger.info(f'Sending {amount} NFT {nft_id} to {address}')
    params = algod.suggested_params()
    txn = AssetTransferTxn(
        sender=cometa_public_key,
        sp=params,
        receiver=address,
        amt=amount,
        index=nft_id)
    stxn = txn.sign(cometa_rekey_private_key)

    txid = algod.send_transaction(stxn)
    wait_for_confirmation(algod, txid)
    logger.info(f'Sent {amount} NFT {nft_id} to {address} with tx {txid}')
