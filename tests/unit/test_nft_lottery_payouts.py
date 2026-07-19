from copy import deepcopy
from types import SimpleNamespace

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
        if document.get(field) != expected:
            return False
    return True


class FakeLotteryCollection:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents
        self.indexes: list[tuple[tuple, dict]] = []

    def create_index(self, *args, **kwargs) -> None:
        self.indexes.append((args, kwargs))

    def find(self, query):
        return [deepcopy(document) for document in self.documents if _matches(document, query)]

    def find_one(self, query):
        document = next((item for item in self.documents if _matches(item, query)), None)
        return deepcopy(document) if document is not None else None

    def find_one_and_update(self, query, update, **kwargs):
        document = next((item for item in self.documents if _matches(item, query)), None)
        if document is None:
            return None
        document.update(update.get("$set", {}))
        return deepcopy(document)

    def update_one(self, query, update):
        document = next((item for item in self.documents if _matches(item, query)), None)
        if document is not None:
            document.update(update.get("$set", {}))
        return SimpleNamespace(modified_count=int(document is not None))


def test_lottery_payouts_backfill_unique_draw_ids_and_claim_exact_documents(monkeypatch) -> None:
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
        operation_id = f"nft:{idempotency_key}"
        return AssetTransferReceipt(
            operation_id=operation_id,
            txid=f"tx-{asset_id}",
            confirmed_round=777,
            already_confirmed=False,
        )

    monkeypatch.setattr(nft_lottery, "send_nft", send_nft)

    result = nft_lottery.send_all_prizes()

    assert result["sent_count"] == 2
    assert result["error_count"] == 0
    assert len(calls) == 2
    assert len({call[2] for call in calls}) == 2
    assert [document["payout_txid"] for document in collection.documents] == [
        "tx-101",
        "tx-202",
    ]
    assert all(document["claimed"] for document in collection.documents)
    assert all(document["id"].startswith("legacy-") for document in collection.documents)

    first_calls = list(calls)
    retry = nft_lottery.send_all_prizes()

    assert retry["sent_count"] == 0
    assert calls == first_calls
