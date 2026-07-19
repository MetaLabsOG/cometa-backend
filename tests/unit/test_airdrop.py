import asyncio
from types import SimpleNamespace

import pytest
from algosdk import account

from flex.application.asset_transfers import (
    AssetTransferPendingError,
    AssetTransferReceipt,
    AssetTransferRequest,
    ConfirmedAssetTransfer,
)
from flex.db.model.airdrop import AirdropManifest
from flex.db.model.blockchain import AssetInfo
from flex.db.model.priced import AirdropReward
from flex.tools import airdrop


class FakeRewardCollection:
    def __init__(self, rewards: list[AirdropReward] | None = None) -> None:
        self.documents = [reward.to_dict() for reward in rewards or []]
        self.indexes: list[tuple[tuple, dict]] = []

    def aggregate(self, *args, **kwargs):
        return []

    def create_index(self, *args, **kwargs) -> None:
        self.indexes.append((args, kwargs))

    def find_one_and_update(self, query, update, **kwargs):
        document = next(
            (
                document
                for document in self.documents
                if all(document.get(field) == value for field, value in query.items())
            ),
            None,
        )
        if document is None and "$setOnInsert" in update:
            document = dict(update["$setOnInsert"])
            self.documents.append(document)
        if document is not None and "$set" in update:
            document.update(update["$set"])
        return dict(document) if document is not None else None


class FakeRewardManager:
    def __init__(self, rewards: list[AirdropReward] | None = None) -> None:
        self.mongodb_collection = FakeRewardCollection(rewards)

    def get_many(self, **query):
        matches = []
        for document in self.mongodb_collection.documents:
            reward = AirdropReward.from_dict(document)
            if all(getattr(reward, field) == value for field, value in query.items()):
                matches.append(reward)
        return matches


class FakeManifestCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}
        self.complete_before_partial = False

    def create_index(self, *args, **kwargs) -> None:
        return None

    def aggregate(self, *args, **kwargs):
        return []

    def find_one(self, query, projection=None):
        document = self.documents.get(query["id"])
        return dict(document) if document is not None else None

    def find_one_and_update(self, query, update, **kwargs):
        manifest_id = query["id"]
        self.documents.setdefault(manifest_id, dict(update["$setOnInsert"]))
        return dict(self.documents[manifest_id])

    def update_one(self, query, update):
        document = self.documents.get(query["id"])
        expected_status = query.get("status")
        if (
            document is not None
            and self.complete_before_partial
            and isinstance(expected_status, dict)
            and expected_status.get("$ne") == "complete"
        ):
            document["status"] = "complete"
        if document is None or (
            isinstance(expected_status, dict)
            and "$ne" in expected_status
            and document.get("status") == expected_status["$ne"]
        ):
            return SimpleNamespace(matched_count=0)
        document.update(update["$set"])
        return SimpleNamespace(matched_count=1)


class FakeTransferService:
    def __init__(
        self,
        *,
        fail_address: str | None = None,
        legacy_transfer: ConfirmedAssetTransfer | None = None,
    ) -> None:
        self.validated = []
        self.executed = []
        self.fail_address = fail_address
        self.legacy_transfer = legacy_transfer

    def validate(self, request) -> None:
        self.validated.append(request)

    def execute(self, request) -> AssetTransferReceipt:
        self.executed.append(request)
        if request.receiver == self.fail_address:
            raise AssetTransferPendingError(request.operation_id, f"tx-{request.receiver}")
        return AssetTransferReceipt(
            operation_id=request.operation_id,
            txid=f"tx-{request.receiver}",
            confirmed_round=123,
            already_confirmed=False,
        )

    def lookup_confirmed_transfer(self, txid: str) -> ConfirmedAssetTransfer | None:
        return self.legacy_transfer


def _addresses(count: int) -> list[str]:
    return [account.generate_account()[1] for _ in range(count)]


def _asset() -> AssetInfo:
    return AssetInfo(
        name="Test Asset",
        decimals=6,
        unit_name="TEST",
        id=42,
    )


def _install_fake_db(
    monkeypatch,
    rewards: list[AirdropReward] | None = None,
) -> tuple[FakeRewardManager, FakeManifestCollection]:
    reward_manager = FakeRewardManager(rewards)
    manifest_collection = FakeManifestCollection()
    monkeypatch.setattr(
        airdrop,
        "db",
        SimpleNamespace(
            airdrop_rewards=reward_manager,
            airdrop_manifests=SimpleNamespace(
                mongodb_collection=manifest_collection,
            ),
        ),
    )

    async def current_round() -> int:
        return 100

    monkeypatch.setattr(airdrop, "get_current_round", current_round)
    return reward_manager, manifest_collection


def _seed_manifest(
    manifests: FakeManifestCollection,
    *,
    airdrop_id: str,
    amounts: dict[str, int],
    note: str = "hello",
) -> None:
    requests = {
        address: AssetTransferRequest(
            operation_id=f"airdrop:{airdrop_id}:{address}",
            receiver=address,
            asset_id=42,
            amount_micros=amount_micros,
            note=note,
        )
        for address, amount_micros in amounts.items()
    }
    total_amount_micros = sum(amounts.values())
    manifests.documents[airdrop_id] = AirdropManifest(
        id=airdrop_id,
        asset_id=42,
        total_amount_micros=str(total_amount_micros),
        recipient_count=len(requests),
        manifest_hash=airdrop._manifest_hash(
            airdrop_id=airdrop_id,
            asset_id=42,
            total_amount_micros=total_amount_micros,
            requests=requests,
        ),
    ).to_dict()


def test_airdrop_allocates_the_exact_budget_and_persists_every_receipt(monkeypatch) -> None:
    rewards, manifests = _install_fake_db(monkeypatch)
    addresses = _addresses(3)
    service = FakeTransferService()

    transactions = asyncio.run(
        airdrop.send_airdrop(
            asset_info=_asset(),
            total_amount_micros=10,
            address_shares=dict.fromkeys(reversed(addresses), 1),
            notes=["one", "two"],
            airdrop_id="summer-2026",
            transfer_service=service,  # type: ignore[arg-type]
        )
    )

    assert len(service.validated) == 3
    assert len(service.executed) == 3
    assert sum(request.amount_micros for request in service.executed) == 10
    assert sorted(request.amount_micros for request in service.executed) == [3, 3, 4]
    assert len(transactions) == 3
    assert len(rewards.mongodb_collection.documents) == 3
    assert manifests.documents["summer-2026"]["status"] == "complete"


@pytest.mark.parametrize("stale_status", ["prepared", "partial"])
def test_complete_airdrop_manifest_cannot_regress(monkeypatch, stale_status: str) -> None:
    _, manifests = _install_fake_db(monkeypatch)
    manifests.documents["summer-2026"] = {"id": "summer-2026", "status": "complete"}

    airdrop._mark_manifest_status("summer-2026", stale_status)

    assert manifests.documents["summer-2026"]["status"] == "complete"


def test_airdrop_configuration_conflict_aborts_before_any_broadcast(monkeypatch) -> None:
    address, other_address = _addresses(2)
    existing = AirdropReward(
        airdrop_id="summer-2026",
        address=other_address,
        asa_id=42,
        amount_micros=999,
        txid="legacy-txid",
    )
    _, manifests = _install_fake_db(monkeypatch, [existing])
    _seed_manifest(
        manifests,
        airdrop_id="summer-2026",
        amounts={address: 5, other_address: 5},
    )
    service = FakeTransferService()

    with pytest.raises(airdrop.AirdropConflictError):
        asyncio.run(
            airdrop.send_airdrop(
                asset_info=_asset(),
                total_amount_micros=10,
                address_shares={address: 1, other_address: 1},
                notes=["hello"],
                airdrop_id="summer-2026",
                transfer_service=service,  # type: ignore[arg-type]
            )
        )

    assert service.executed == []
    assert manifests.documents["summer-2026"]["status"] == "prepared"


def test_airdrop_reports_partial_failure_and_continues_safe_recipients(monkeypatch) -> None:
    rewards, manifests = _install_fake_db(monkeypatch)
    addresses = _addresses(3)
    service = FakeTransferService(fail_address=addresses[1])

    with pytest.raises(airdrop.AirdropIncompleteError) as error:
        asyncio.run(
            airdrop.send_airdrop(
                asset_info=_asset(),
                total_amount_micros=9,
                address_shares=dict.fromkeys(addresses, 1),
                notes=["hello"],
                airdrop_id="summer-2026",
                transfer_service=service,  # type: ignore[arg-type]
            )
        )

    assert len(service.executed) == 3
    assert error.value.failures == (
        airdrop.AirdropFailure(
            address=addresses[1],
            error_type="AssetTransferPendingError",
            txid=f"tx-{addresses[1]}",
        ),
    )
    assert len(error.value.confirmed_transactions) == 2
    assert len(rewards.mongodb_collection.documents) == 2
    assert manifests.documents["summer-2026"]["status"] == "partial"


def test_stale_airdrop_failure_observes_concurrent_terminal_completion(monkeypatch) -> None:
    rewards, manifests = _install_fake_db(monkeypatch)
    addresses = _addresses(2)
    service = FakeTransferService(fail_address=addresses[1])
    manifests.complete_before_partial = True

    transactions = asyncio.run(
        airdrop.send_airdrop(
            asset_info=_asset(),
            total_amount_micros=10,
            address_shares=dict.fromkeys(addresses, 1),
            notes=["hello"],
            airdrop_id="summer-2026",
            transfer_service=service,  # type: ignore[arg-type]
        )
    )

    assert len(transactions) == 1
    assert len(rewards.mongodb_collection.documents) == 1
    assert manifests.documents["summer-2026"]["status"] == "complete"


def test_airdrop_rejects_zero_allocations_before_execution(monkeypatch) -> None:
    _install_fake_db(monkeypatch)
    addresses = _addresses(2)
    service = FakeTransferService()

    with pytest.raises(airdrop.AirdropError, match="would receive zero"):
        asyncio.run(
            airdrop.send_airdrop(
                asset_info=_asset(),
                total_amount_micros=1,
                address_shares={addresses[0]: 1, addresses[1]: 1},
                notes=["hello"],
                airdrop_id="summer-2026",
                transfer_service=service,  # type: ignore[arg-type]
            )
        )

    assert service.executed == []


def test_airdrop_manifest_rejects_recipient_set_changes_after_partial_run(monkeypatch) -> None:
    _, manifests = _install_fake_db(monkeypatch)
    first, second, added = _addresses(3)
    first_service = FakeTransferService(fail_address=second)

    with pytest.raises(airdrop.AirdropIncompleteError):
        asyncio.run(
            airdrop.send_airdrop(
                asset_info=_asset(),
                total_amount_micros=10,
                address_shares={first: 1, second: 1},
                notes=["hello"],
                airdrop_id="immutable-batch",
                transfer_service=first_service,  # type: ignore[arg-type]
            )
        )

    assert manifests.documents["immutable-batch"]["status"] == "partial"
    changed_service = FakeTransferService()
    with pytest.raises(airdrop.AirdropConflictError, match="immutable manifest"):
        asyncio.run(
            airdrop.send_airdrop(
                asset_info=_asset(),
                total_amount_micros=15,
                address_shares={first: 1, second: 1, added: 1},
                notes=["hello"],
                airdrop_id="immutable-batch",
                transfer_service=changed_service,  # type: ignore[arg-type]
            )
        )

    assert changed_service.executed == []


def test_legacy_unconfirmed_reward_is_not_treated_as_paid(monkeypatch) -> None:
    address = _addresses(1)[0]
    legacy_reward = AirdropReward(
        airdrop_id="legacy",
        address=address,
        asa_id=42,
        amount_micros=10,
        txid="legacy-txid",
    )
    _, manifests = _install_fake_db(monkeypatch, [legacy_reward])
    _seed_manifest(
        manifests,
        airdrop_id="legacy",
        amounts={address: 10},
    )
    service = FakeTransferService()

    with pytest.raises(airdrop.AirdropError, match="not confirmed"):
        asyncio.run(
            airdrop.send_airdrop(
                asset_info=_asset(),
                total_amount_micros=10,
                address_shares={address: 1},
                notes=["hello"],
                airdrop_id="legacy",
                transfer_service=service,  # type: ignore[arg-type]
            )
        )

    assert service.executed == []


def test_legacy_confirmed_reward_is_backfilled_and_skipped(monkeypatch) -> None:
    address = _addresses(1)[0]
    legacy_reward = AirdropReward(
        airdrop_id="legacy",
        address=address,
        asa_id=42,
        amount_micros=10,
        txid="legacy-txid",
    )
    rewards, manifests = _install_fake_db(monkeypatch, [legacy_reward])
    _seed_manifest(
        manifests,
        airdrop_id="legacy",
        amounts={address: 10},
    )
    service = FakeTransferService(
        legacy_transfer=ConfirmedAssetTransfer(
            txid="legacy-txid",
            sender=airdrop.cometa_public_key,
            receiver=address,
            asset_id=42,
            amount_micros=10,
            confirmed_round=456,
        )
    )

    transactions = asyncio.run(
        airdrop.send_airdrop(
            asset_info=_asset(),
            total_amount_micros=10,
            address_shares={address: 1},
            notes=["hello"],
            airdrop_id="legacy",
            transfer_service=service,  # type: ignore[arg-type]
        )
    )

    assert transactions == []
    assert service.executed == []
    assert rewards.mongodb_collection.documents[0]["confirmed_round"] == 456
    assert rewards.mongodb_collection.documents[0]["operation_id"] == f"airdrop:legacy:{address}"


def test_legacy_confirmation_metadata_does_not_bypass_on_chain_field_validation(monkeypatch) -> None:
    address, wrong_receiver = _addresses(2)
    legacy_reward = AirdropReward(
        airdrop_id="legacy",
        address=address,
        asa_id=42,
        amount_micros=10,
        txid="legacy-txid",
        confirmed_round=456,
    )
    _, manifests = _install_fake_db(monkeypatch, [legacy_reward])
    _seed_manifest(
        manifests,
        airdrop_id="legacy",
        amounts={address: 10},
    )
    service = FakeTransferService(
        legacy_transfer=ConfirmedAssetTransfer(
            txid="legacy-txid",
            sender=airdrop.cometa_public_key,
            receiver=wrong_receiver,
            asset_id=42,
            amount_micros=10,
            confirmed_round=456,
        )
    )

    with pytest.raises(airdrop.AirdropConflictError, match="does not match"):
        asyncio.run(
            airdrop.send_airdrop(
                asset_info=_asset(),
                total_amount_micros=10,
                address_shares={address: 1},
                notes=["hello"],
                airdrop_id="legacy",
                transfer_service=service,  # type: ignore[arg-type]
            )
        )

    assert service.executed == []


def test_legacy_campaign_cannot_expand_without_explicit_manifest_migration(monkeypatch) -> None:
    paid, new_recipient = _addresses(2)
    legacy_reward = AirdropReward(
        airdrop_id="legacy",
        address=paid,
        asa_id=42,
        amount_micros=10,
        txid="legacy-txid",
    )
    _install_fake_db(monkeypatch, [legacy_reward])
    service = FakeTransferService()

    with pytest.raises(airdrop.AirdropError, match="no immutable manifest"):
        asyncio.run(
            airdrop.send_airdrop(
                asset_info=_asset(),
                total_amount_micros=20,
                address_shares={paid: 1, new_recipient: 1},
                notes=["hello"],
                airdrop_id="legacy",
                transfer_service=service,  # type: ignore[arg-type]
            )
        )

    assert service.executed == []
