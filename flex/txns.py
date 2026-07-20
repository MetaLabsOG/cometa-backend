import logging
from dataclasses import dataclass
from enum import Enum

from algosdk import transaction
from dataclasses_json import dataclass_json

from flex.blockchain.base import algod_client, cometa_private_key, cometa_public_key
from flex.db.model.blockchain import AssetInfo
from flex.meta_error import MetaError
from flex.util import decode_b64

TX_WAIT_ROUNDS = 4


class TxType(str, Enum):
    PAYMENT = "payment"
    ASSET_TRANSFER = "asset-transfer"


@dataclass_json
@dataclass
class TxInfo:
    id: str
    sender: str
    receiver: str
    asa_id: int
    amount: int | None
    note: str | None = None
    confirmed_round: int | None = None


logger = logging.getLogger(__name__)


def get_tx_info_with_wait(txid: str, tx_type: TxType, timeout_rounds: int = TX_WAIT_ROUNDS) -> TxInfo:
    try:
        tx_response = transaction.wait_for_confirmation(algod_client, txid, timeout_rounds)
        tx_info = tx_response["txn"]["txn"]
    except Exception as exc:
        logger.error(f"Transaction with id = {txid} is not found: {exc}", exc_info=True)
        raise MetaError(f"Transaction with id = {txid} is not found: {exc}") from exc

    receiver = tx_info["rcv"] if tx_type == TxType.PAYMENT else tx_info["arcv"]
    amount = None if tx_type == TxType.PAYMENT else tx_info["aamt"]
    asa_id = 0 if tx_type == TxType.PAYMENT else tx_info["xaid"]

    return TxInfo(
        id=txid,
        sender=tx_info["snd"],
        receiver=receiver,
        amount=amount,
        asa_id=asa_id,
        note=decode_b64(tx_info.get("note")),
        confirmed_round=tx_response["confirmed-round"],
    )


def get_payment_info_with_wait(txid: str, wait_rounds: int = TX_WAIT_ROUNDS) -> TxInfo:
    return get_tx_info_with_wait(txid, TxType.PAYMENT, wait_rounds)


def get_transfer_info_with_wait(txid: str, wait_rounds: int = TX_WAIT_ROUNDS) -> TxInfo:
    return get_tx_info_with_wait(txid, TxType.ASSET_TRANSFER, wait_rounds)


def send_asset_micros(asset_info: AssetInfo, address: str, amount_micros: int, note: str | None = None) -> str:
    logger.debug(f"Sending {asset_info.micros_to_amount(amount_micros)} {asset_info.unit_name} to {address}!")

    params = algod_client.suggested_params()
    unsigned_txn = transaction.AssetTransferTxn(
        sender=cometa_public_key, sp=params, receiver=address, amt=amount_micros, index=asset_info.id, note=note
    )
    signed_txn = unsigned_txn.sign(cometa_private_key)
    txid = algod_client.send_transaction(signed_txn)

    return txid


def send_asset_micros_with_wait(
    asset_info: AssetInfo, address: str, amount_micros: int, note: str | None = None, wait_rounds: int = TX_WAIT_ROUNDS
) -> TxInfo:
    txid = send_asset_micros(asset_info, address, amount_micros, note)
    tx_info = get_transfer_info_with_wait(txid, wait_rounds=wait_rounds)
    logger.debug(
        f"Sent {asset_info.micros_to_amount(amount_micros)} {asset_info.unit_name} to {address} with txid: {txid}!"
    )
    return tx_info


def send_asset(asset_info: AssetInfo, address: str, amount: float, note: str | None = None) -> str:
    amount_micros = asset_info.amount_to_micros(amount)
    return send_asset_micros(asset_info, address, amount_micros, note)
