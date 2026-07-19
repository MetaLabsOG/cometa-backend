import pytest
from algosdk import account, encoding, transaction

from flex.application.asset_transfers import (
    AssetTransferRequest,
    InvalidAssetTransferError,
)
from flex.blockchain.asset_transfers import AlgorandAssetTransferGateway


class FakeAlgod:
    def __init__(self) -> None:
        self.sent: list[transaction.SignedTransaction] = []

    def suggested_params(self) -> transaction.SuggestedParams:
        return transaction.SuggestedParams(
            fee=1_000,
            first=100,
            last=1_100,
            gh=b"0" * 32,
            flat_fee=True,
        )

    def send_transaction(self, signed: transaction.SignedTransaction) -> str:
        self.sent.append(signed)
        return signed.transaction.get_txid()

    def status(self) -> dict[str, int]:
        return {"last-round": 100}


class FakeIndexer:
    def __init__(self, *, sender: str, receiver: str) -> None:
        self.sender = sender
        self.receiver = receiver

    def transaction(self, txid: str) -> dict:
        return {
            "transaction": {
                "confirmed-round": 123,
                "sender": self.sender,
                "asset-transfer-transaction": {
                    "receiver": self.receiver,
                    "asset-id": 42,
                    "amount": 1_000,
                },
            }
        }


def test_gateway_prepares_a_replay_safe_signed_transaction() -> None:
    private_key, sender = account.generate_account()
    _, receiver = account.generate_account()
    algod = FakeAlgod()
    gateway = AlgorandAssetTransferGateway(
        algod=algod,  # type: ignore[arg-type]
        indexer=FakeIndexer(sender=sender, receiver=receiver),  # type: ignore[arg-type]
        sender=sender,
        private_key=private_key,
    )
    request = AssetTransferRequest(
        operation_id="airdrop:summer:recipient",
        receiver=receiver,
        asset_id=42,
        amount_micros=1_000,
        note="hello",
    )

    prepared = gateway.prepare(request)
    decoded = encoding.msgpack_decode(prepared.signed_transaction)

    assert isinstance(decoded, transaction.SignedTransaction)
    assert decoded.transaction.get_txid() == prepared.txid
    assert decoded.transaction.receiver == receiver
    assert decoded.transaction.index == 42
    assert decoded.transaction.amount == 1_000
    assert decoded.transaction.note == b"hello"
    assert len(decoded.transaction.lease) == 32
    assert prepared.first_valid_round == 100
    assert prepared.last_valid_round == 1_100

    returned_txid = gateway.broadcast(prepared, request)

    assert returned_txid == prepared.txid
    assert len(algod.sent) == 1

    observed = gateway.lookup_confirmed_transfer(prepared.txid)

    assert observed is not None
    assert observed.sender == sender
    assert observed.receiver == receiver
    assert observed.asset_id == 42
    assert observed.amount_micros == 1_000
    assert observed.confirmed_round == 123


def test_operation_id_deterministically_selects_the_lease() -> None:
    private_key, sender = account.generate_account()
    _, receiver = account.generate_account()
    gateway = AlgorandAssetTransferGateway(
        algod=FakeAlgod(),  # type: ignore[arg-type]
        indexer=FakeIndexer(sender=sender, receiver=receiver),  # type: ignore[arg-type]
        sender=sender,
        private_key=private_key,
    )
    request = AssetTransferRequest(
        operation_id="lottery:draw:42",
        receiver=receiver,
        asset_id=7,
        amount_micros=1,
    )

    first = encoding.msgpack_decode(gateway.prepare(request).signed_transaction)
    second = encoding.msgpack_decode(gateway.prepare(request).signed_transaction)

    assert first.transaction.lease == second.transaction.lease
    assert first.transaction.get_txid() == second.transaction.get_txid()


def test_gateway_rejects_a_swapped_signed_payload_before_network_io() -> None:
    private_key, sender = account.generate_account()
    _, receiver = account.generate_account()
    _, other_receiver = account.generate_account()
    algod = FakeAlgod()
    gateway = AlgorandAssetTransferGateway(
        algod=algod,  # type: ignore[arg-type]
        indexer=FakeIndexer(sender=sender, receiver=receiver),  # type: ignore[arg-type]
        sender=sender,
        private_key=private_key,
    )
    expected = AssetTransferRequest(
        operation_id="airdrop:summer:recipient",
        receiver=receiver,
        asset_id=42,
        amount_micros=1_000,
        note="hello",
    )
    swapped = gateway.prepare(
        AssetTransferRequest(
            operation_id=expected.operation_id,
            receiver=other_receiver,
            asset_id=42,
            amount_micros=1_000,
            note="hello",
        )
    )

    with pytest.raises(InvalidAssetTransferError, match="do not match"):
        gateway.broadcast(swapped, expected)

    assert algod.sent == []
