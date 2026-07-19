"""Idempotent application service for outbound Algorand asset transfers."""

from dataclasses import dataclass
from typing import Protocol

from flex.db.model.transfers import AssetTransferIntent

MAX_ALGORAND_UINT = 2**64 - 1
MAX_NOTE_BYTES = 1_000
MAX_OPERATION_ID_BYTES = 200


class AssetTransferError(RuntimeError):
    """Base class for outbound transfer failures."""


class InvalidAssetTransferError(ValueError):
    """Raised before persistence when a transfer request is invalid."""


class AssetTransferConflictError(AssetTransferError):
    """Raised when an idempotency key is reused for a different transfer."""


class AssetTransferPendingError(AssetTransferError):
    """Raised when broadcast outcome is ambiguous and must be reconciled."""

    def __init__(self, operation_id: str, txid: str) -> None:
        super().__init__(f"transfer {operation_id!r} is unresolved; reconcile transaction {txid}")
        self.operation_id = operation_id
        self.txid = txid


class AssetTransferExpiredError(AssetTransferError):
    """Raised when an unconfirmed persisted transaction is no longer valid."""

    def __init__(self, operation_id: str, txid: str) -> None:
        super().__init__(
            f"transfer {operation_id!r} expired unconfirmed; verify transaction {txid} on-chain before replacement"
        )
        self.operation_id = operation_id
        self.txid = txid


class TransferStatus:
    PREPARED = "prepared"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class AssetTransferRequest:
    operation_id: str
    receiver: str
    asset_id: int
    amount_micros: int
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise InvalidAssetTransferError("operation_id must be a non-empty string")
        if len(self.operation_id.encode()) > MAX_OPERATION_ID_BYTES:
            raise InvalidAssetTransferError("operation_id is too long")
        if not isinstance(self.receiver, str) or not self.receiver.strip():
            raise InvalidAssetTransferError("receiver must be a non-empty string")
        if isinstance(self.asset_id, bool) or not isinstance(self.asset_id, int):
            raise InvalidAssetTransferError("asset_id must be an integer")
        if not 0 < self.asset_id <= MAX_ALGORAND_UINT:
            raise InvalidAssetTransferError("asset_id is outside the Algorand uint64 range")
        if isinstance(self.amount_micros, bool) or not isinstance(self.amount_micros, int):
            raise InvalidAssetTransferError("amount_micros must be an integer")
        if not 0 < self.amount_micros <= MAX_ALGORAND_UINT:
            raise InvalidAssetTransferError("amount_micros is outside the Algorand uint64 range")
        if self.note is not None:
            if not isinstance(self.note, str):
                raise InvalidAssetTransferError("note must be a string")
            if len(self.note.encode()) > MAX_NOTE_BYTES:
                raise InvalidAssetTransferError("note exceeds Algorand's 1000-byte limit")


@dataclass(frozen=True, slots=True)
class PreparedAssetTransfer:
    signed_transaction: str
    txid: str
    first_valid_round: int
    last_valid_round: int


@dataclass(frozen=True, slots=True)
class AssetTransferReceipt:
    operation_id: str
    txid: str
    confirmed_round: int
    already_confirmed: bool


@dataclass(frozen=True, slots=True)
class ConfirmedAssetTransfer:
    txid: str
    sender: str
    receiver: str
    asset_id: int
    amount_micros: int
    confirmed_round: int


@dataclass(frozen=True, slots=True)
class TransferReconciliation:
    operation_id: str
    txid: str
    status: str
    confirmed_round: int | None


class AssetTransferIntentRepository(Protocol):
    def get(self, operation_id: str) -> AssetTransferIntent | None: ...

    def reserve(self, intent: AssetTransferIntent) -> AssetTransferIntent: ...

    def record_attempt(self, operation_id: str, txid: str) -> AssetTransferIntent: ...

    def mark_submitted(self, operation_id: str, txid: str) -> AssetTransferIntent: ...

    def mark_confirmed(
        self,
        operation_id: str,
        txid: str,
        confirmed_round: int,
    ) -> AssetTransferIntent: ...

    def record_error(
        self,
        operation_id: str,
        txid: str,
        error: str,
    ) -> AssetTransferIntent: ...


class AssetTransferGateway(Protocol):
    def prepare(self, request: AssetTransferRequest) -> PreparedAssetTransfer: ...

    def broadcast(
        self,
        prepared: PreparedAssetTransfer,
        request: AssetTransferRequest,
    ) -> str: ...

    def wait_for_confirmation(self, txid: str) -> int: ...

    def lookup_confirmed_round(self, txid: str) -> int | None: ...

    def lookup_confirmed_transfer(self, txid: str) -> ConfirmedAssetTransfer | None: ...

    def current_round(self) -> int: ...


@dataclass(slots=True)
class AssetTransferService:
    repository: AssetTransferIntentRepository
    gateway: AssetTransferGateway

    def validate(self, request: AssetTransferRequest) -> None:
        """Reject an idempotency-key conflict without touching the network."""

        intent = self.repository.get(request.operation_id)
        if intent is not None:
            self._assert_same_transfer(intent, request)

    def lookup_confirmed_round(self, txid: str) -> int | None:
        """Look up a legacy transaction without creating a new intent."""

        return self.gateway.lookup_confirmed_round(txid)

    def lookup_confirmed_transfer(self, txid: str) -> ConfirmedAssetTransfer | None:
        """Return authoritative on-chain fields for legacy reconciliation."""

        return self.gateway.lookup_confirmed_transfer(txid)

    def execute(self, request: AssetTransferRequest) -> AssetTransferReceipt:
        intent = self.repository.get(request.operation_id)
        if intent is None:
            prepared = self.gateway.prepare(request)
            intent = self.repository.reserve(
                AssetTransferIntent(
                    id=request.operation_id,
                    receiver=request.receiver,
                    asset_id=str(request.asset_id),
                    amount_micros=str(request.amount_micros),
                    note=request.note,
                    signed_transaction=prepared.signed_transaction,
                    txid=prepared.txid,
                    first_valid_round=prepared.first_valid_round,
                    last_valid_round=prepared.last_valid_round,
                    status=TransferStatus.PREPARED,
                )
            )

        self._assert_same_transfer(intent, request)
        if intent.status == TransferStatus.CONFIRMED:
            return self._confirmed_receipt(intent, already_confirmed=True)

        if self.gateway.current_round() > intent.last_valid_round:
            try:
                confirmed_round = self.gateway.lookup_confirmed_round(intent.txid)
            except Exception as exc:
                self.repository.record_error(
                    intent.id,
                    intent.txid,
                    f"expired transaction lookup unavailable after {type(exc).__name__}",
                )
                raise AssetTransferExpiredError(intent.id, intent.txid) from exc
            if confirmed_round is not None:
                intent = self.repository.mark_confirmed(
                    intent.id,
                    intent.txid,
                    confirmed_round,
                )
                return self._confirmed_receipt(intent, already_confirmed=True)

            self.repository.record_error(
                intent.id,
                intent.txid,
                "signed transaction expired before confirmation; manual reconciliation required",
            )
            raise AssetTransferExpiredError(intent.id, intent.txid)

        self.repository.record_attempt(intent.id, intent.txid)
        broadcast_error: Exception | None = None
        try:
            returned_txid = self.gateway.broadcast(
                PreparedAssetTransfer(
                    signed_transaction=intent.signed_transaction,
                    txid=intent.txid,
                    first_valid_round=intent.first_valid_round,
                    last_valid_round=intent.last_valid_round,
                ),
                request,
            )
            if returned_txid != intent.txid:
                raise AssetTransferError("Algorand node returned a different transaction ID")
            self.repository.mark_submitted(intent.id, intent.txid)
        except Exception as exc:
            # A transport failure can happen after the node accepted the
            # transaction. Confirmation of the persisted txid is authoritative.
            broadcast_error = exc

        try:
            confirmed_round = self.gateway.wait_for_confirmation(intent.txid)
        except Exception as exc:
            failure_kind = type(broadcast_error or exc).__name__
            self.repository.record_error(
                intent.id,
                intent.txid,
                f"confirmation unresolved after {failure_kind}",
            )
            raise AssetTransferPendingError(intent.id, intent.txid) from exc

        intent = self.repository.mark_confirmed(
            intent.id,
            intent.txid,
            confirmed_round,
        )
        return self._confirmed_receipt(intent, already_confirmed=False)

    def reconcile(self, operation_id: str) -> TransferReconciliation:
        intent = self.repository.get(operation_id)
        if intent is None:
            raise AssetTransferError(f"transfer {operation_id!r} does not exist")
        if intent.status == TransferStatus.CONFIRMED:
            receipt = self._confirmed_receipt(intent, already_confirmed=True)
            return TransferReconciliation(
                operation_id=receipt.operation_id,
                txid=receipt.txid,
                status=TransferStatus.CONFIRMED,
                confirmed_round=receipt.confirmed_round,
            )

        confirmed_round = self.gateway.lookup_confirmed_round(intent.txid)
        if confirmed_round is not None:
            confirmed = self.repository.mark_confirmed(
                intent.id,
                intent.txid,
                confirmed_round,
            )
            return TransferReconciliation(
                operation_id=confirmed.id,
                txid=confirmed.txid,
                status=TransferStatus.CONFIRMED,
                confirmed_round=confirmed.confirmed_round,
            )

        status = "expired_unconfirmed" if self.gateway.current_round() > intent.last_valid_round else intent.status
        return TransferReconciliation(
            operation_id=intent.id,
            txid=intent.txid,
            status=status,
            confirmed_round=None,
        )

    @staticmethod
    def _assert_same_transfer(
        intent: AssetTransferIntent,
        request: AssetTransferRequest,
    ) -> None:
        persisted = (
            intent.receiver,
            intent.asset_id_int,
            intent.amount_micros_int,
            intent.note,
        )
        requested = (
            request.receiver,
            request.asset_id,
            request.amount_micros,
            request.note,
        )
        if persisted != requested:
            raise AssetTransferConflictError(
                f"idempotency key {request.operation_id!r} already belongs to a different transfer"
            )

    @staticmethod
    def _confirmed_receipt(
        intent: AssetTransferIntent,
        *,
        already_confirmed: bool,
    ) -> AssetTransferReceipt:
        if intent.confirmed_round is None:
            raise AssetTransferError("confirmed transfer is missing confirmed_round")
        return AssetTransferReceipt(
            operation_id=intent.id,
            txid=intent.txid,
            confirmed_round=intent.confirmed_round,
            already_confirmed=already_confirmed,
        )
