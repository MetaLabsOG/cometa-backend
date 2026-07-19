"""Algorand adapter for preparing and submitting persisted asset transfers."""

import base64
import hmac
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from algosdk import account, encoding, transaction
from algosdk.error import AlgodHTTPError
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient

from flex.application.asset_transfers import (
    AssetTransferRequest,
    ConfirmedAssetTransfer,
    InvalidAssetTransferError,
    PreparedAssetTransfer,
)

TX_WAIT_ROUNDS = 4
LEASE_DOMAIN = b"cometa-asset-transfer:v1:"


@dataclass(slots=True)
class AlgorandAssetTransferGateway:
    algod: AlgodClient
    indexer: IndexerClient
    sender: str
    private_key: str
    wait_rounds: int = TX_WAIT_ROUNDS

    def prepare(self, request: AssetTransferRequest) -> PreparedAssetTransfer:
        if not encoding.is_valid_address(request.receiver):
            raise InvalidAssetTransferError("receiver is not a valid Algorand address")

        params = self.algod.suggested_params()
        unsigned_transaction = transaction.AssetTransferTxn(
            sender=self.sender,
            sp=params,
            receiver=request.receiver,
            amt=request.amount_micros,
            index=request.asset_id,
            note=request.note.encode() if request.note is not None else None,
            lease=sha256(LEASE_DOMAIN + request.operation_id.encode()).digest(),
        )
        signed_transaction = unsigned_transaction.sign(self.private_key)
        return PreparedAssetTransfer(
            signed_transaction=encoding.msgpack_encode(signed_transaction),
            txid=unsigned_transaction.get_txid(),
            first_valid_round=unsigned_transaction.first_valid_round,
            last_valid_round=unsigned_transaction.last_valid_round,
        )

    def broadcast(
        self,
        prepared: PreparedAssetTransfer,
        request: AssetTransferRequest,
    ) -> str:
        decoded = encoding.msgpack_decode(prepared.signed_transaction)
        if not isinstance(decoded, transaction.SignedTransaction):
            raise InvalidAssetTransferError("persisted payload is not a signed transaction")
        self._validate_persisted_transaction(decoded, prepared, request)
        return self.algod.send_transaction(decoded)

    def _validate_persisted_transaction(
        self,
        signed: transaction.SignedTransaction,
        prepared: PreparedAssetTransfer,
        request: AssetTransferRequest,
    ) -> None:
        txn = signed.transaction
        expected_note = request.note.encode() if request.note is not None else None
        expected_lease = sha256(LEASE_DOMAIN + request.operation_id.encode()).digest()
        expected_authorizer = account.address_from_private_key(self.private_key)
        expected_signer = None if expected_authorizer == self.sender else expected_authorizer

        expected_fields = (
            self.sender,
            request.receiver,
            request.asset_id,
            request.amount_micros,
            expected_note,
            expected_lease,
            prepared.first_valid_round,
            prepared.last_valid_round,
            None,
            None,
            None,
            None,
        )
        observed_fields = (
            txn.sender,
            getattr(txn, "receiver", None),
            getattr(txn, "index", None),
            getattr(txn, "amount", None),
            txn.note,
            txn.lease,
            txn.first_valid_round,
            txn.last_valid_round,
            getattr(txn, "close_assets_to", None),
            getattr(txn, "revocation_target", None),
            txn.group,
            txn.rekey_to,
        )
        if not isinstance(txn, transaction.AssetTransferTxn) or observed_fields != expected_fields:
            raise InvalidAssetTransferError("persisted transaction fields do not match the transfer intent")
        if txn.get_txid() != prepared.txid:
            raise InvalidAssetTransferError("persisted transaction ID does not match the transfer intent")
        if signed.authorizing_address != expected_signer:
            raise InvalidAssetTransferError("persisted transaction has an unexpected authorizing address")

        expected_signature = base64.b64encode(txn.raw_sign(self.private_key)).decode()
        if not isinstance(signed.signature, str) or not hmac.compare_digest(
            signed.signature,
            expected_signature,
        ):
            raise InvalidAssetTransferError("persisted transaction signature is invalid")

    def wait_for_confirmation(self, txid: str) -> int:
        response = transaction.wait_for_confirmation(
            self.algod,
            txid,
            self.wait_rounds,
        )
        return self._confirmed_round(response)

    def lookup_confirmed_round(self, txid: str) -> int | None:
        try:
            pending = self.algod.pending_transaction_info(txid)
        except AlgodHTTPError as exc:
            if exc.code != 404:
                raise
        else:
            confirmed_round = self._optional_confirmed_round(pending)
            if confirmed_round is not None:
                return confirmed_round

        # The indexer is the durable lookup path after algod's pending window.
        observed = self.lookup_confirmed_transfer(txid)
        return observed.confirmed_round if observed is not None else None

    def lookup_confirmed_transfer(self, txid: str) -> ConfirmedAssetTransfer | None:
        response = self.indexer.transaction(txid)
        transaction_info = response.get("transaction")
        if not isinstance(transaction_info, dict):
            raise RuntimeError("Algorand indexer response has no transaction")
        confirmed_round = self._optional_confirmed_round(transaction_info)
        if confirmed_round is None:
            return None

        sender = transaction_info.get("sender")
        asset_transfer = transaction_info.get("asset-transfer-transaction")
        if not isinstance(sender, str) or not encoding.is_valid_address(sender):
            raise RuntimeError("Algorand indexer response has an invalid sender")
        if not isinstance(asset_transfer, dict):
            raise RuntimeError("Algorand transaction is not an asset transfer")

        receiver = asset_transfer.get("receiver")
        asset_id = asset_transfer.get("asset-id")
        amount_micros = asset_transfer.get("amount")
        if not isinstance(receiver, str) or not encoding.is_valid_address(receiver):
            raise RuntimeError("Algorand indexer response has an invalid receiver")
        if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id <= 0:
            raise RuntimeError("Algorand indexer response has an invalid asset ID")
        if isinstance(amount_micros, bool) or not isinstance(amount_micros, int) or amount_micros <= 0:
            raise RuntimeError("Algorand indexer response has an invalid transfer amount")

        return ConfirmedAssetTransfer(
            txid=txid,
            sender=sender,
            receiver=receiver,
            asset_id=asset_id,
            amount_micros=amount_micros,
            confirmed_round=confirmed_round,
        )

    def current_round(self) -> int:
        status = self.algod.status()
        current_round = status.get("last-round")
        if isinstance(current_round, bool) or not isinstance(current_round, int) or current_round < 0:
            raise RuntimeError("Algorand node returned an invalid current round")
        return current_round

    @staticmethod
    def _confirmed_round(response: dict[str, Any]) -> int:
        confirmed_round = AlgorandAssetTransferGateway._optional_confirmed_round(response)
        if confirmed_round is None:
            raise RuntimeError("Algorand confirmation response has no confirmed round")
        return confirmed_round

    @staticmethod
    def _optional_confirmed_round(response: dict[str, Any]) -> int | None:
        confirmed_round = response.get("confirmed-round")
        if confirmed_round is None or confirmed_round == 0:
            return None
        if isinstance(confirmed_round, bool) or not isinstance(confirmed_round, int) or confirmed_round < 0:
            raise RuntimeError("Algorand response contains an invalid confirmed round")
        return confirmed_round
