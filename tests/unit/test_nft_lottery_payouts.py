from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pymongo.errors import OperationFailure

from flex.application.asset_transfers import AssetTransferReceipt


def _matches(document: dict, query: dict) -> bool:
    for field, expected in query.items():
        if field == "$or":
            if not any(_matches(document, branch) for branch in expected):
                return False
            continue
        if isinstance(expected, dict):
            if "$exists" in expected:
                if (field in document) is not expected["$exists"]:
                    return False
                continue
            if "$ne" in expected:
                if document.get(field) == expected["$ne"]:
                    return False
                continue
            if "$in" in expected:
                if document.get(field) not in expected["$in"]:
                    return False
                continue
            if "$eq" in expected:
                if document.get(field) != expected["$eq"]:
                    return False
                continue
        if document.get(field) != expected:
            return False
    return True


class FakeLotteryCollection:
    def __init__(
        self,
        documents: list[dict],
        *,
        index_information: dict[str, dict] | None = None,
    ) -> None:
        self.documents = documents
        self.indexes: list[tuple[tuple, dict]] = []
        self.dropped_indexes: list[str] = []
        self.index_events: list[tuple[str, str]] = []
        self.find_one_and_update_calls: list[tuple[dict, dict]] = []
        self._index_information = deepcopy(
            index_information
            or {
                "_id_": {
                    "key": [("_id", 1)],
                }
            }
        )

    def aggregate(self, pipeline, **kwargs):
        del kwargs
        matching_ids: dict[str, list[object]] = {}
        for document in self.documents:
            draw_id = document.get("id")
            if isinstance(draw_id, str) and draw_id:
                matching_ids.setdefault(draw_id, []).append(document.get("_id"))
        return [
            {
                "_id": draw_id,
                "count": len(document_ids),
                "document_ids": document_ids,
            }
            for draw_id, document_ids in matching_ids.items()
            if len(document_ids) > 1
        ][: pipeline[-1].get("$limit", 10)]

    def index_information(self):
        return deepcopy(self._index_information)

    def create_index(self, *args, **kwargs) -> str:
        self.indexes.append((args, kwargs))
        index_name = kwargs["name"]
        self._index_information[index_name] = {
            "key": [(args[0], 1)],
            "unique": kwargs.get("unique", False),
            "partialFilterExpression": deepcopy(kwargs.get("partialFilterExpression")),
        }
        self.index_events.append(("create", index_name))
        return index_name

    def drop_index(self, name: str) -> None:
        self.dropped_indexes.append(name)
        self._index_information.pop(name)
        self.index_events.append(("drop", name))

    def find(self, query):
        return [deepcopy(document) for document in self.documents if _matches(document, query)]

    def find_one(self, query):
        document = next((item for item in self.documents if _matches(item, query)), None)
        return deepcopy(document) if document is not None else None

    def find_one_and_update(self, query, update, **kwargs):
        self.find_one_and_update_calls.append((deepcopy(query), deepcopy(update)))
        document = next((item for item in self.documents if _matches(item, query)), None)
        if document is None:
            return None
        document.update(update.get("$set", {}))
        return deepcopy(document)

    def update_one(self, query, update):
        document = next((item for item in self.documents if _matches(item, query)), None)
        if document is not None:
            document.update(update.get("$set", {}))
        matched_count = int(document is not None)
        return SimpleNamespace(
            matched_count=matched_count,
            modified_count=matched_count,
        )


class ClaimBeforePrepareCollection(FakeLotteryCollection):
    def update_one(self, query, update):
        if "payout_operation_id" in query:
            self.documents[0].update(
                {
                    "claimed": True,
                    "payout_operation_id": "nft:manual-reconciliation",
                    "payout_txid": "manual-chain-tx",
                    "payout_status": "confirmed",
                }
            )
        return super().update_one(query, update)


class ConcurrentLegacyDropCollection(FakeLotteryCollection):
    def drop_index(self, name: str) -> None:
        self._index_information.pop(name, None)
        self.index_events.append(("concurrent_drop", name))
        raise OperationFailure("index not found", code=27)


def _legacy_draw_id(document_id: str) -> str:
    return f"legacy-{sha256(f'lottery-draw:{document_id}'.encode()).hexdigest()}"


def _receipt(asset_id: int, idempotency_key: str) -> AssetTransferReceipt:
    return AssetTransferReceipt(
        operation_id=f"nft:{idempotency_key}",
        txid=f"tx-{asset_id}",
        confirmed_round=777,
        already_confirmed=False,
    )


def test_new_lottery_draw_starts_with_pending_payout(monkeypatch) -> None:
    from api import nft_lottery

    collection = FakeLotteryCollection([])
    manager = SimpleNamespace(
        collection=collection,
        create=lambda draw: draw,
    )
    monkeypatch.setattr(nft_lottery, "lottery_draws", manager)

    draw = nft_lottery._create_draw(
        lottery_name="summer",
        prize=101,
        wallet="WALLET-A",
        timestamp=1.0,
    )

    assert draw.id
    assert draw.payout_status == nft_lottery.LotteryPayoutStatus.PENDING
    assert collection.indexes == [
        (
            ("id",),
            {
                "unique": True,
                "name": nft_lottery.LOTTERY_DRAW_ID_INDEX_NAME,
                "partialFilterExpression": {
                    "id": {
                        "$type": "string",
                        "$gt": "",
                    }
                },
            },
        )
    ]


def test_lottery_index_upgrade_builds_replacement_before_dropping_legacy(
    monkeypatch,
) -> None:
    from api import nft_lottery

    documents = [
        {"_id": "legacy-a"},
        {"_id": "legacy-b", "id": ""},
        {"_id": "current", "id": "draw-current"},
    ]
    collection = FakeLotteryCollection(
        deepcopy(documents),
        index_information={
            "_id_": {"key": [("_id", 1)]},
            "id_unique": {
                "key": [("id", 1)],
                "unique": True,
                "partialFilterExpression": {"id": {"$type": "string"}},
            },
        },
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )

    nft_lottery.ensure_lottery_indexes()

    assert collection.documents == documents
    assert collection.index_events == [
        ("create", nft_lottery.LOTTERY_DRAW_ID_INDEX_NAME),
        ("drop", "id_unique"),
    ]
    replacement = collection.index_information()[nft_lottery.LOTTERY_DRAW_ID_INDEX_NAME]
    assert replacement["partialFilterExpression"] == nft_lottery.LOTTERY_DRAW_ID_FILTER


def test_lottery_index_upgrade_preserves_duplicate_evidence_and_fails_closed(
    monkeypatch,
) -> None:
    from api import nft_lottery

    documents = [
        {"_id": "mongo-a", "id": "duplicate"},
        {"_id": "mongo-b", "id": "duplicate"},
    ]
    collection = FakeLotteryCollection(deepcopy(documents))
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )

    with pytest.raises(RuntimeError, match="preserved 1 duplicate group"):
        nft_lottery.ensure_lottery_indexes()

    assert collection.documents == documents
    assert collection.indexes == []
    assert collection.dropped_indexes == []


def test_lottery_index_upgrade_converges_after_concurrent_legacy_drop(
    monkeypatch,
) -> None:
    from api import nft_lottery

    collection = ConcurrentLegacyDropCollection(
        [{"_id": "current", "id": "draw-current"}],
        index_information={
            "_id_": {"key": [("_id", 1)]},
            "id_unique": {
                "key": [("id", 1)],
                "unique": True,
                "partialFilterExpression": {"id": {"$type": "string"}},
            },
        },
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )

    nft_lottery.ensure_lottery_indexes()

    replacement = collection.index_information()[nft_lottery.LOTTERY_DRAW_ID_INDEX_NAME]
    assert replacement["partialFilterExpression"] == nft_lottery.LOTTERY_DRAW_ID_FILTER
    assert collection.index_events == [
        ("create", nft_lottery.LOTTERY_DRAW_ID_INDEX_NAME),
        ("concurrent_drop", "id_unique"),
    ]


def test_legacy_lottery_payouts_require_reconciliation_and_never_send(monkeypatch) -> None:
    # Import after test collection helpers so module-level infrastructure stays
    # outside the behavioral assertion.
    from api import nft_lottery

    collection = FakeLotteryCollection(
        [
            {
                "_id": "draw-a",
                "wallet": "WALLET-A",
                "prize": 101,
                "timestamp": 1.0,
                "lottery_name": "summer",
                "claimed": False,
            },
            {
                "_id": "draw-b",
                "wallet": "WALLET-B",
                "prize": 202,
                "timestamp": 2.0,
                "lottery_name": "summer",
                "claimed": False,
                "payout_txid": "legacy-chain-tx",
            },
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )
    calls: list[tuple[str, int, str]] = []

    def send_nft(address: str, asset_id: int, *, idempotency_key: str):
        calls.append((address, asset_id, idempotency_key))
        return _receipt(asset_id, idempotency_key)

    monkeypatch.setattr(nft_lottery, "send_nft", send_nft)

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 0
    assert result["error_count"] == 2
    assert calls == []
    assert not any(document["claimed"] for document in collection.documents)
    assert all(document["id"].startswith("legacy-") for document in collection.documents)
    assert all(
        document["payout_status"] == nft_lottery.LotteryPayoutStatus.RECONCILIATION_REQUIRED
        for document in collection.documents
    )
    assert collection.documents[1]["payout_txid"] == "legacy-chain-tx"

    retry = nft_lottery.send_all_prizes()

    assert retry["sent_count"] == 0
    assert retry["error_count"] == 2
    assert calls == []


def test_existing_draw_without_payout_state_is_legacy_and_fails_closed(monkeypatch) -> None:
    from api import nft_lottery

    collection = FakeLotteryCollection(
        [
            {
                "_id": "mongo-a",
                "id": "pre-status-draw",
                "wallet": "WALLET-A",
                "prize": 101,
                "timestamp": 1.0,
                "lottery_name": "summer",
                "claimed": False,
            }
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )
    calls: list[tuple[str, int, str]] = []

    def send_nft(address: str, asset_id: int, *, idempotency_key: str):
        calls.append((address, asset_id, idempotency_key))
        return _receipt(asset_id, idempotency_key)

    monkeypatch.setattr(nft_lottery, "send_nft", send_nft)

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 0
    assert result["error_count"] == 1
    assert calls == []
    assert collection.documents[0]["payout_status"] == nft_lottery.LotteryPayoutStatus.RECONCILIATION_REQUIRED


def test_empty_legacy_identity_and_status_are_migrated_fail_closed(monkeypatch) -> None:
    from api import nft_lottery

    collection = FakeLotteryCollection(
        [
            {
                "_id": "mongo-a",
                "id": "",
                "wallet": "WALLET-A",
                "prize": 101,
                "timestamp": 1.0,
                "lottery_name": "summer",
                "claimed": False,
                "payout_status": "",
            }
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )
    monkeypatch.setattr(
        nft_lottery,
        "send_nft",
        lambda *args, **kwargs: pytest.fail("legacy draw must not broadcast"),
    )

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 0
    assert result["error_count"] == 1
    assert collection.documents[0]["id"].startswith("legacy-")
    assert collection.documents[0]["payout_status"] == nft_lottery.LotteryPayoutStatus.RECONCILIATION_REQUIRED


def test_missing_claimed_is_atomically_normalized_and_fails_closed(monkeypatch) -> None:
    from api import nft_lottery

    collection = FakeLotteryCollection(
        [
            {
                "_id": "mongo-a",
                "id": "draw-a",
                "wallet": "WALLET-A",
                "prize": 101,
                "timestamp": 1.0,
                "lottery_name": "summer",
                "payout_status": nft_lottery.LotteryPayoutStatus.PENDING,
            }
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )
    monkeypatch.setattr(
        nft_lottery,
        "send_nft",
        lambda *args, **kwargs: pytest.fail("uncertain legacy draw must not broadcast"),
    )

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 0
    assert result["error_count"] == 1
    assert collection.documents[0]["claimed"] is False
    assert collection.documents[0]["payout_status"] == nft_lottery.LotteryPayoutStatus.RECONCILIATION_REQUIRED
    migration_query, migration_update = collection.find_one_and_update_calls[0]
    assert migration_query["claimed"] == {"$exists": False}
    assert migration_update["$set"] == {
        "id": "draw-a",
        "claimed": False,
        "payout_status": nft_lottery.LotteryPayoutStatus.RECONCILIATION_REQUIRED,
    }


def test_null_claimed_with_exact_durable_operation_is_safe_to_resume(monkeypatch) -> None:
    from api import nft_lottery

    collection = FakeLotteryCollection(
        [
            {
                "_id": "mongo-a",
                "id": "draw-a",
                "wallet": "WALLET-A",
                "prize": 101,
                "timestamp": 1.0,
                "lottery_name": "summer",
                "claimed": None,
                "payout_operation_id": "nft:lottery:draw-a",
                "payout_status": nft_lottery.LotteryPayoutStatus.PENDING,
            }
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )
    calls: list[tuple[str, int, str]] = []

    def send_nft(address: str, asset_id: int, *, idempotency_key: str):
        calls.append((address, asset_id, idempotency_key))
        return _receipt(asset_id, idempotency_key)

    monkeypatch.setattr(nft_lottery, "send_nft", send_nft)

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 1
    assert result["error_count"] == 0
    assert calls == [("WALLET-A", 101, "lottery:draw-a")]
    assert collection.documents[0]["claimed"] is True
    assert collection.documents[0]["payout_status"] == nft_lottery.LotteryPayoutStatus.CONFIRMED
    migration_query, migration_update = collection.find_one_and_update_calls[0]
    assert migration_query["claimed"] == {"$eq": None}
    assert migration_update["$set"] == {
        "id": "draw-a",
        "claimed": False,
        "payout_status": nft_lottery.LotteryPayoutStatus.PREPARED,
    }


def test_malformed_legacy_draw_does_not_block_safe_payouts(monkeypatch) -> None:
    from api import nft_lottery

    collection = FakeLotteryCollection(
        [
            {
                "_id": "malformed",
                "prize": 101,
                "claimed": False,
            },
            {
                "_id": "mongo-b",
                "id": "draw-b",
                "wallet": "WALLET-B",
                "prize": 202,
                "timestamp": 2.0,
                "lottery_name": "summer",
                "claimed": False,
                "payout_status": nft_lottery.LotteryPayoutStatus.PENDING,
            },
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )
    calls: list[tuple[str, int, str]] = []

    def send_nft(address: str, asset_id: int, *, idempotency_key: str):
        calls.append((address, asset_id, idempotency_key))
        return _receipt(asset_id, idempotency_key)

    monkeypatch.setattr(nft_lottery, "send_nft", send_nft)

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 1
    assert result["error_count"] == 1
    assert calls == [("WALLET-B", 202, "lottery:draw-b")]
    assert "migration failed" in result["results"][0]["error"]
    assert collection.documents[1]["claimed"] is True


def test_legacy_lottery_payout_with_matching_operation_is_safe_to_resume(monkeypatch) -> None:
    from api import nft_lottery

    document_id = "draw-a"
    legacy_id = _legacy_draw_id(document_id)
    collection = FakeLotteryCollection(
        [
            {
                "_id": document_id,
                "wallet": "WALLET-A",
                "prize": 101,
                "timestamp": 1.0,
                "lottery_name": "summer",
                "claimed": False,
                "payout_operation_id": f"nft:lottery:{legacy_id}",
            }
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )
    calls: list[tuple[str, int, str]] = []

    def send_nft(address: str, asset_id: int, *, idempotency_key: str):
        calls.append((address, asset_id, idempotency_key))
        return _receipt(asset_id, idempotency_key)

    monkeypatch.setattr(nft_lottery, "send_nft", send_nft)

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 1
    assert result["error_count"] == 0
    assert calls == [("WALLET-A", 101, f"lottery:{legacy_id}")]
    assert collection.documents[0]["claimed"] is True
    assert collection.documents[0]["payout_status"] == nft_lottery.LotteryPayoutStatus.CONFIRMED


def test_failed_new_lottery_payout_becomes_unresolved(monkeypatch) -> None:
    from api import nft_lottery

    collection = FakeLotteryCollection(
        [
            {
                "_id": "mongo-a",
                "id": "draw-a",
                "wallet": "WALLET-A",
                "prize": 101,
                "timestamp": 1.0,
                "lottery_name": "summer",
                "claimed": False,
                "payout_status": nft_lottery.LotteryPayoutStatus.PENDING,
            }
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )

    def fail_send_nft(address: str, asset_id: int, *, idempotency_key: str):
        raise RuntimeError("indexer unavailable")

    monkeypatch.setattr(nft_lottery, "send_nft", fail_send_nft)

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 0
    assert result["error_count"] == 1
    assert collection.documents[0]["payout_operation_id"] == "nft:lottery:draw-a"
    assert collection.documents[0]["payout_status"] == nft_lottery.LotteryPayoutStatus.UNRESOLVED
    assert collection.documents[0]["send_error"] == "indexer unavailable"


def test_claim_won_before_reservation_never_broadcasts_again(monkeypatch) -> None:
    from api import nft_lottery

    collection = ClaimBeforePrepareCollection(
        [
            {
                "_id": "mongo-a",
                "id": "draw-a",
                "wallet": "WALLET-A",
                "prize": 101,
                "timestamp": 1.0,
                "lottery_name": "summer",
                "claimed": False,
                "payout_status": nft_lottery.LotteryPayoutStatus.PENDING,
            }
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )
    calls: list[tuple[str, int, str]] = []

    def send_nft(address: str, asset_id: int, *, idempotency_key: str):
        calls.append((address, asset_id, idempotency_key))
        return _receipt(asset_id, idempotency_key)

    monkeypatch.setattr(nft_lottery, "send_nft", send_nft)

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 0
    assert result["error_count"] == 0
    assert result["results"][0]["already_claimed"] is True
    assert result["results"][0]["txid"] == "manual-chain-tx"
    assert calls == []


def test_new_lottery_payouts_use_stable_ids_and_claim_exact_documents(monkeypatch) -> None:
    from api import nft_lottery

    collection = FakeLotteryCollection(
        [
            {
                "_id": "mongo-a",
                "id": "draw-a",
                "wallet": "WALLET-A",
                "prize": 101,
                "timestamp": 1.0,
                "lottery_name": "summer",
                "claimed": False,
                "payout_status": nft_lottery.LotteryPayoutStatus.PENDING,
            },
            {
                "_id": "mongo-b",
                "id": "draw-b",
                "wallet": "WALLET-B",
                "prize": 202,
                "timestamp": 2.0,
                "lottery_name": "summer",
                "claimed": False,
                "payout_status": nft_lottery.LotteryPayoutStatus.PENDING,
            },
        ]
    )
    monkeypatch.setattr(
        nft_lottery,
        "lottery_draws",
        SimpleNamespace(collection=collection),
    )
    calls: list[tuple[str, int, str]] = []

    def send_nft(address: str, asset_id: int, *, idempotency_key: str):
        calls.append((address, asset_id, idempotency_key))
        return _receipt(asset_id, idempotency_key)

    monkeypatch.setattr(nft_lottery, "send_nft", send_nft)

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 2
    assert result["error_count"] == 0
    assert calls == [
        ("WALLET-A", 101, "lottery:draw-a"),
        ("WALLET-B", 202, "lottery:draw-b"),
    ]
    assert [document["payout_txid"] for document in collection.documents] == [
        "tx-101",
        "tx-202",
    ]
    assert all(document["claimed"] for document in collection.documents)
    assert all(
        document["payout_status"] == nft_lottery.LotteryPayoutStatus.CONFIRMED for document in collection.documents
    )

    first_calls = list(calls)
    retry = nft_lottery.send_all_prizes()

    assert retry["sent_count"] == 0
    assert calls == first_calls
