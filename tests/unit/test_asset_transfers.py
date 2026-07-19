from dataclasses import replace
from datetime import UTC, datetime

import pytest

from flex.application.asset_transfers import (
    AssetTransferConflictError,
    AssetTransferError,
    AssetTransferExpiredError,
    AssetTransferPendingError,
    AssetTransferRequest,
    AssetTransferService,
    ConfirmedAssetTransfer,
    InvalidAssetTransferError,
    PreparedAssetTransfer,
    TransferStatus,
)
from flex.db.model.transfers import AssetTransferIntent


class InMemoryIntentRepository:
    def __init__(self) -> None:
        self.intents: dict[str, AssetTransferIntent] = {}

    def get(self, operation_id: str) -> AssetTransferIntent | None:
        return self.intents.get(operation_id)

    def reserve(self, intent: AssetTransferIntent) -> AssetTransferIntent:
        return self.intents.setdefault(intent.id, intent)

    def record_attempt(self, operation_id: str, txid: str) -> AssetTransferIntent:
        intent = self._intent(operation_id, txid)
        intent.attempt_count += 1
        return intent

    def mark_submitted(self, operation_id: str, txid: str) -> AssetTransferIntent:
        intent = self._intent(operation_id, txid)
        intent.status = TransferStatus.SUBMITTED
        return intent

    def mark_confirmed(
        self,
        operation_id: str,
        txid: str,
        confirmed_round: int,
    ) -> AssetTransferIntent:
        intent = self._intent(operation_id, txid)
        intent.status = TransferStatus.CONFIRMED
        intent.confirmed_round = confirmed_round
        return intent

    def record_error(
        self,
        operation_id: str,
        txid: str,
        error: str,
    ) -> AssetTransferIntent:
        intent = self._intent(operation_id, txid)
        intent.last_error = error
        return intent

    def _intent(self, operation_id: str, txid: str) -> AssetTransferIntent:
        intent = self.intents[operation_id]
        assert intent.txid == txid
        return intent


class ConfirmOnUpdateRepository(InMemoryIntentRepository):
    def __init__(self, update_name: str) -> None:
        super().__init__()
        self.update_name = update_name

    def _confirm(self, intent: AssetTransferIntent, update_name: str) -> AssetTransferIntent:
        if self.update_name == update_name:
            intent.status = TransferStatus.CONFIRMED
            intent.confirmed_round = 777
        return intent

    def record_attempt(self, operation_id: str, txid: str) -> AssetTransferIntent:
        return self._confirm(
            super().record_attempt(operation_id, txid),
            "record_attempt",
        )

    def mark_submitted(self, operation_id: str, txid: str) -> AssetTransferIntent:
        return self._confirm(
            super().mark_submitted(operation_id, txid),
            "mark_submitted",
        )

    def record_error(
        self,
        operation_id: str,
        txid: str,
        error: str,
    ) -> AssetTransferIntent:
        return self._confirm(
            super().record_error(operation_id, txid, error),
            "record_error",
        )


class ReconcileReloadRepository(InMemoryIntentRepository):
    def __init__(self, reloaded: AssetTransferIntent | None) -> None:
        super().__init__()
        self.reloaded = reloaded
        self.get_count = 0

    def get(self, operation_id: str) -> AssetTransferIntent | None:
        self.get_count += 1
        if self.get_count == 1:
            return super().get(operation_id)
        return self.reloaded


class FakeTransferGateway:
    def __init__(self) -> None:
        self.prepare_count = 0
        self.broadcasted: list[str] = []
        self.current = 100
        self.confirmed_round = 101
        self.lookup_round: int | None = None
        self.broadcast_error: Exception | None = None
        self.wait_error: Exception | None = None
        self.returned_txid: str | None = None

    def prepare(self, request: AssetTransferRequest) -> PreparedAssetTransfer:
        self.prepare_count += 1
        return PreparedAssetTransfer(
            signed_transaction=f"signed-{request.operation_id}",
            txid=f"txid-{request.operation_id}",
            first_valid_round=100,
            last_valid_round=1_100,
        )

    def broadcast(
        self,
        prepared: PreparedAssetTransfer,
        request: AssetTransferRequest,
    ) -> str:
        self.broadcasted.append(prepared.signed_transaction)
        if self.broadcast_error is not None:
            raise self.broadcast_error
        if self.returned_txid is not None:
            return self.returned_txid
        return prepared.signed_transaction.replace("signed-", "txid-")

    def wait_for_confirmation(self, txid: str) -> int:
        if self.wait_error is not None:
            raise self.wait_error
        return self.confirmed_round

    def lookup_confirmed_round(self, txid: str) -> int | None:
        return self.lookup_round

    def lookup_confirmed_transfer(self, txid: str) -> ConfirmedAssetTransfer | None:
        if self.lookup_round is None:
            return None
        return ConfirmedAssetTransfer(
            txid=txid,
            sender="SENDER",
            receiver="ADDRESS",
            asset_id=42,
            amount_micros=1_000,
            confirmed_round=self.lookup_round,
        )

    def current_round(self) -> int:
        return self.current


def _request(**changes: object) -> AssetTransferRequest:
    values = {
        "operation_id": "airdrop:summer:ADDRESS",
        "receiver": "ADDRESS",
        "asset_id": 42,
        "amount_micros": 1_000,
        "note": "thank you",
    }
    values.update(changes)
    return AssetTransferRequest(**values)  # type: ignore[arg-type]


def _intent(**changes: object) -> AssetTransferIntent:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    values = {
        "id": "airdrop:summer:ADDRESS",
        "receiver": "ADDRESS",
        "asset_id": "42",
        "amount_micros": "1000",
        "note": "thank you",
        "signed_transaction": "persisted-signed-transaction",
        "txid": "persisted-txid",
        "first_valid_round": 1,
        "last_valid_round": 1_000,
        "status": TransferStatus.SUBMITTED,
        "created": timestamp,
        "updated": timestamp,
    }
    values.update(changes)
    return AssetTransferIntent(**values)  # type: ignore[arg-type]


def test_retry_rebroadcasts_the_same_persisted_signed_transaction() -> None:
    repository = InMemoryIntentRepository()
    gateway = FakeTransferGateway()
    gateway.wait_error = TimeoutError("confirmation timeout")
    service = AssetTransferService(repository, gateway)

    with pytest.raises(AssetTransferPendingError):
        service.execute(_request())

    persisted = repository.intents["airdrop:summer:ADDRESS"]
    assert persisted.txid == "txid-airdrop:summer:ADDRESS"
    assert persisted.signed_transaction == "signed-airdrop:summer:ADDRESS"

    gateway.wait_error = None
    receipt = service.execute(_request())

    assert receipt.txid == persisted.txid
    assert gateway.prepare_count == 1
    assert gateway.broadcasted == [
        "signed-airdrop:summer:ADDRESS",
        "signed-airdrop:summer:ADDRESS",
    ]
    assert persisted.attempt_count == 2


def test_ambiguous_broadcast_is_resolved_by_confirmation() -> None:
    repository = InMemoryIntentRepository()
    gateway = FakeTransferGateway()
    gateway.broadcast_error = TimeoutError("connection dropped after submit")
    service = AssetTransferService(repository, gateway)

    receipt = service.execute(_request())

    assert receipt.confirmed_round == 101
    assert repository.intents[receipt.operation_id].status == TransferStatus.CONFIRMED


def test_confirmed_retry_does_not_contact_the_gateway() -> None:
    repository = InMemoryIntentRepository()
    confirmed = _intent(
        status=TransferStatus.CONFIRMED,
        confirmed_round=500,
    )
    repository.intents[confirmed.id] = confirmed
    gateway = FakeTransferGateway()
    service = AssetTransferService(repository, gateway)

    receipt = service.execute(_request())

    assert receipt.already_confirmed is True
    assert receipt.confirmed_round == 500
    assert gateway.prepare_count == 0
    assert gateway.broadcasted == []


def test_concurrent_confirmation_before_broadcast_returns_terminal_receipt() -> None:
    repository = ConfirmOnUpdateRepository("record_attempt")
    existing = _intent()
    repository.intents[existing.id] = existing
    gateway = FakeTransferGateway()
    service = AssetTransferService(repository, gateway)

    receipt = service.execute(_request())

    assert receipt.already_confirmed is True
    assert receipt.confirmed_round == 777
    assert gateway.broadcasted == []


@pytest.mark.parametrize("update_name", ["mark_submitted", "record_error"])
def test_concurrent_confirmation_after_broadcast_is_not_reported_pending(
    update_name: str,
) -> None:
    repository = ConfirmOnUpdateRepository(update_name)
    existing = _intent()
    repository.intents[existing.id] = existing
    gateway = FakeTransferGateway()
    if update_name == "record_error":
        gateway.wait_error = TimeoutError("another worker confirmed")
    else:
        gateway.returned_txid = existing.txid
    service = AssetTransferService(repository, gateway)

    receipt = service.execute(_request())

    assert receipt.already_confirmed is True
    assert receipt.confirmed_round == 777
    assert gateway.broadcasted == ["persisted-signed-transaction"]


def test_idempotency_key_cannot_be_reused_for_another_amount() -> None:
    repository = InMemoryIntentRepository()
    existing = _intent()
    repository.intents[existing.id] = existing
    gateway = FakeTransferGateway()
    service = AssetTransferService(repository, gateway)

    with pytest.raises(AssetTransferConflictError):
        service.execute(_request(amount_micros=1_001))

    assert gateway.broadcasted == []


def test_expired_intent_reconciles_a_confirmed_transaction() -> None:
    repository = InMemoryIntentRepository()
    existing = _intent(last_valid_round=99)
    repository.intents[existing.id] = existing
    gateway = FakeTransferGateway()
    gateway.current = 100
    gateway.lookup_round = 88
    service = AssetTransferService(repository, gateway)

    receipt = service.execute(_request())

    assert receipt.already_confirmed is True
    assert receipt.confirmed_round == 88
    assert gateway.broadcasted == []


def test_expired_unconfirmed_intent_requires_manual_reconciliation() -> None:
    repository = InMemoryIntentRepository()
    existing = _intent(last_valid_round=99)
    repository.intents[existing.id] = existing
    gateway = FakeTransferGateway()
    gateway.current = 100
    service = AssetTransferService(repository, gateway)

    with pytest.raises(AssetTransferExpiredError):
        service.execute(_request())

    assert gateway.prepare_count == 0
    assert gateway.broadcasted == []
    assert "manual reconciliation" in existing.last_error


def test_reconcile_marks_an_observed_transaction_confirmed() -> None:
    repository = InMemoryIntentRepository()
    existing = _intent()
    repository.intents[existing.id] = existing
    gateway = FakeTransferGateway()
    gateway.lookup_round = 777
    service = AssetTransferService(repository, gateway)

    result = service.reconcile(existing.id)

    assert result.status == TransferStatus.CONFIRMED
    assert result.confirmed_round == 777


def test_reconcile_returns_confirmation_committed_during_chain_lookup() -> None:
    confirmed = _intent(
        status=TransferStatus.CONFIRMED,
        confirmed_round=778,
    )
    repository = ReconcileReloadRepository(confirmed)
    existing = _intent()
    repository.intents[existing.id] = existing
    gateway = FakeTransferGateway()
    service = AssetTransferService(repository, gateway)

    result = service.reconcile(existing.id)

    assert repository.get_count == 2
    assert result.status == TransferStatus.CONFIRMED
    assert result.txid == existing.txid
    assert result.confirmed_round == 778


def test_reconcile_fails_if_the_intent_disappears_during_chain_lookup() -> None:
    repository = ReconcileReloadRepository(None)
    existing = _intent()
    repository.intents[existing.id] = existing
    service = AssetTransferService(repository, FakeTransferGateway())

    with pytest.raises(AssetTransferError, match="disappeared during reconciliation"):
        service.reconcile(existing.id)


def test_reconcile_fails_if_the_persisted_transaction_changes() -> None:
    replacement = _intent(txid="replacement-txid")
    repository = ReconcileReloadRepository(replacement)
    existing = _intent()
    repository.intents[existing.id] = existing
    service = AssetTransferService(repository, FakeTransferGateway())

    with pytest.raises(AssetTransferConflictError, match="changed transaction"):
        service.reconcile(existing.id)


def test_reconcile_builds_nonterminal_result_from_reloaded_intent() -> None:
    reloaded = _intent(
        status=TransferStatus.PREPARED,
        last_valid_round=99,
    )
    repository = ReconcileReloadRepository(reloaded)
    existing = _intent(last_valid_round=1_000)
    repository.intents[existing.id] = existing
    gateway = FakeTransferGateway()
    gateway.current = 100
    service = AssetTransferService(repository, gateway)

    result = service.reconcile(existing.id)

    assert result.status == "expired_unconfirmed"
    assert result.confirmed_round is None


def test_full_algorand_uint64_values_are_persisted_without_bson_integers() -> None:
    repository = InMemoryIntentRepository()
    gateway = FakeTransferGateway()
    service = AssetTransferService(repository, gateway)

    request = _request(asset_id=2**64 - 1, amount_micros=2**64 - 1)
    service.execute(request)

    intent = repository.intents[request.operation_id]
    assert intent.asset_id == str(2**64 - 1)
    assert intent.amount_micros == str(2**64 - 1)
    assert intent.asset_id_int == 2**64 - 1
    assert intent.amount_micros_int == 2**64 - 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation_id", ""),
        ("operation_id", "x" * 201),
        ("receiver", ""),
        ("asset_id", True),
        ("asset_id", 0),
        ("asset_id", 2**64),
        ("amount_micros", True),
        ("amount_micros", 0),
        ("amount_micros", 2**64),
        ("note", "x" * 1_001),
    ],
)
def test_transfer_request_rejects_invalid_values(field: str, value: object) -> None:
    request = _request()

    with pytest.raises(InvalidAssetTransferError):
        replace(request, **{field: value})
