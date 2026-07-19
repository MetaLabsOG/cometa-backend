import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.database import Database

from flex.application.asset_transfers import (
    AssetTransferService,
    TransferStatus,
)
from flex.db.asset_transfer_intents import (
    MongoAssetTransferIntentRepository,
    TransferIntentPersistenceError,
)
from flex.db.model.transfers import AssetTransferIntent
from flex.tools import airdrop

pytestmark = pytest.mark.integration


@pytest.fixture
def mongo_database() -> Database:
    uri = os.getenv("MONGODB_TEST_URI")
    if not uri:
        pytest.skip("MONGODB_TEST_URI is not configured")

    client = MongoClient(
        uri,
        serverSelectionTimeoutMS=2_000,
        tz_aware=True,
    )
    client.admin.command("ping")
    database_name = f"cometa_transfer_races_{uuid4().hex}"
    database = client[database_name]
    try:
        yield database
    finally:
        client.drop_database(database_name)
        client.close()


def _intent() -> AssetTransferIntent:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    return AssetTransferIntent(
        id="airdrop:summer:address",
        receiver="address",
        asset_id="42",
        amount_micros="1000",
        note="hello",
        signed_transaction="signed",
        txid="txid",
        first_valid_round=100,
        last_valid_round=1_100,
        status=TransferStatus.PREPARED,
        created=timestamp,
        updated=timestamp,
    )


def _repository(
    database: Database,
) -> MongoAssetTransferIntentRepository:
    repository = MongoAssetTransferIntentRepository(
        database["asset_transfer_intents"],
    )
    repository.ensure_indexes()
    repository.reserve(_intent())
    return repository


@pytest.mark.parametrize(
    "nonterminal_update",
    ["record_attempt", "mark_submitted", "record_error"],
)
def test_confirmation_wins_real_mongo_race_against_nonterminal_update(
    mongo_database: Database,
    nonterminal_update: str,
) -> None:
    repository = _repository(mongo_database)
    intent = _intent()
    barrier = Barrier(2)

    def confirm() -> AssetTransferIntent:
        barrier.wait(timeout=5)
        return repository.mark_confirmed(intent.id, intent.txid, 777)

    def update_nonterminal() -> AssetTransferIntent:
        barrier.wait(timeout=5)
        if nonterminal_update == "record_attempt":
            return repository.record_attempt(intent.id, intent.txid)
        if nonterminal_update == "mark_submitted":
            return repository.mark_submitted(intent.id, intent.txid)
        return repository.record_error(intent.id, intent.txid, "late failure")

    with ThreadPoolExecutor(max_workers=2) as executor:
        confirmation = executor.submit(confirm)
        nonterminal = executor.submit(update_nonterminal)
        confirmation.result(timeout=5)
        nonterminal.result(timeout=5)

    confirmed = repository.get(intent.id)
    assert confirmed is not None
    assert confirmed.status == TransferStatus.CONFIRMED
    assert confirmed.confirmed_round == 777
    assert confirmed.confirmed_at is not None
    assert confirmed.last_error is None

    original_confirmed_at = confirmed.confirmed_at
    repository.record_error(intent.id, intent.txid, "must not overwrite terminal evidence")
    persisted = repository.get(intent.id)
    assert persisted is not None
    assert persisted.status == TransferStatus.CONFIRMED
    assert persisted.confirmed_round == 777
    assert persisted.confirmed_at == original_confirmed_at
    assert persisted.last_error is None


def test_conflicting_real_mongo_confirmations_preserve_one_terminal_result(
    mongo_database: Database,
) -> None:
    repository = _repository(mongo_database)
    intent = _intent()
    barrier = Barrier(2)

    def confirm(round_number: int) -> tuple[str, int]:
        barrier.wait(timeout=5)
        try:
            result = repository.mark_confirmed(
                intent.id,
                intent.txid,
                round_number,
            )
        except TransferIntentPersistenceError:
            return "conflict", round_number
        return "confirmed", result.confirmed_round or 0

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(confirm, round_number) for round_number in (777, 778)]
        results = [future.result(timeout=5) for future in futures]

    assert sorted(status for status, _ in results) == ["confirmed", "conflict"]
    persisted = repository.get(intent.id)
    assert persisted is not None
    assert persisted.status == TransferStatus.CONFIRMED
    assert persisted.confirmed_round in {777, 778}
    assert persisted.confirmed_at is not None

    confirmed_at = persisted.confirmed_at
    repeated = repository.mark_confirmed(
        intent.id,
        intent.txid,
        persisted.confirmed_round,
    )
    assert repeated.confirmed_at == confirmed_at

    conflicting_round = 778 if persisted.confirmed_round == 777 else 777
    with pytest.raises(TransferIntentPersistenceError, match="already confirmed"):
        repository.mark_confirmed(
            intent.id,
            intent.txid,
            conflicting_round,
        )
    unchanged = repository.get(intent.id)
    assert unchanged is not None
    assert unchanged.confirmed_round == persisted.confirmed_round
    assert unchanged.confirmed_at == confirmed_at


class _ConfirmDuringLookupGateway:
    def __init__(
        self,
        repository: MongoAssetTransferIntentRepository,
        intent: AssetTransferIntent,
    ) -> None:
        self.repository = repository
        self.intent = intent

    def lookup_confirmed_round(self, txid: str) -> int | None:
        assert txid == self.intent.txid
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(
                self.repository.mark_confirmed,
                self.intent.id,
                txid,
                779,
            ).result(timeout=5)
        return None

    @staticmethod
    def current_round() -> int:
        return 200


def test_reconcile_reloads_real_mongo_terminal_state_before_nonterminal_result(
    mongo_database: Database,
) -> None:
    repository = _repository(mongo_database)
    intent = _intent()
    service = AssetTransferService(
        repository=repository,
        gateway=_ConfirmDuringLookupGateway(repository, intent),  # type: ignore[arg-type]
    )

    result = service.reconcile(intent.id)

    assert result.status == TransferStatus.CONFIRMED
    assert result.txid == intent.txid
    assert result.confirmed_round == 779


def test_complete_airdrop_manifest_wins_real_mongo_partial_status_race(
    mongo_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = mongo_database["airdrop_manifests"]
    collection.insert_one({"id": "summer-2026", "status": "prepared"})
    monkeypatch.setattr(
        airdrop,
        "db",
        SimpleNamespace(
            airdrop_manifests=SimpleNamespace(
                mongodb_collection=collection,
            ),
        ),
    )
    barrier = Barrier(2)

    def mark(status: str) -> str:
        barrier.wait(timeout=5)
        return airdrop._mark_manifest_status("summer-2026", status)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(mark, status) for status in ("complete", "partial")]
        results = [future.result(timeout=5) for future in futures]

    persisted = collection.find_one({"id": "summer-2026"})
    assert persisted is not None
    assert persisted["status"] == "complete"
    assert results[0] == "complete"
    assert results[1] in {"partial", "complete"}
