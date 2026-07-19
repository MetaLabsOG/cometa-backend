from dataclasses import replace

import pytest
from algosdk import account, encoding, transaction

from flex.application.asset_transfers import (
    AssetTransferRequest,
    InvalidAssetTransferError,
)
from flex.blockchain.asset_transfers import AlgorandAssetTransferGateway


class FakeAlgod:
    def __init__(
        self,
        *,
        min_fee: object = 1_000,
        genesis_id: str = "mainnet-v1.0",
        genesis_hash: str = "wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=",
    ) -> None:
        self.sent: list[transaction.SignedTransaction] = []
        self.min_fee = min_fee
        self.genesis_id = genesis_id
        self.genesis_hash = genesis_hash

    def suggested_params(self) -> transaction.SuggestedParams:
        return transaction.SuggestedParams(
            fee=99_999,
            first=100,
            last=1_100,
            gh=self.genesis_hash,
            gen=self.genesis_id,
            flat_fee=False,
            min_fee=self.min_fee,
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
        network="mainnet",
        max_fee_microalgos=1_000,
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
    assert decoded.transaction.fee == 1_000
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
        network="mainnet",
        max_fee_microalgos=1_000,
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
        network="mainnet",
        max_fee_microalgos=1_000,
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


@pytest.mark.parametrize("min_fee", [None, True, -1, 0, 1, 999, 1_001])
def test_gateway_rejects_an_invalid_or_excessive_network_fee(
    min_fee: object,
) -> None:
    private_key, sender = account.generate_account()
    _, receiver = account.generate_account()
    algod = FakeAlgod(min_fee=min_fee)
    gateway = AlgorandAssetTransferGateway(
        algod=algod,  # type: ignore[arg-type]
        indexer=FakeIndexer(sender=sender, receiver=receiver),  # type: ignore[arg-type]
        sender=sender,
        private_key=private_key,
        network="mainnet",
        max_fee_microalgos=1_000,
    )

    with pytest.raises(InvalidAssetTransferError, match="fee"):
        gateway.prepare(
            AssetTransferRequest(
                operation_id="lottery:fee-policy",
                receiver=receiver,
                asset_id=7,
                amount_micros=1,
            )
        )

    assert algod.sent == []


def test_gateway_rejects_wrong_network_parameters_before_signing() -> None:
    private_key, sender = account.generate_account()
    _, receiver = account.generate_account()
    algod = FakeAlgod(
        genesis_id="testnet-v1.0",
        genesis_hash="SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
    )
    gateway = AlgorandAssetTransferGateway(
        algod=algod,  # type: ignore[arg-type]
        indexer=FakeIndexer(sender=sender, receiver=receiver),  # type: ignore[arg-type]
        sender=sender,
        private_key=private_key,
        network="mainnet",
        max_fee_microalgos=1_000,
    )

    with pytest.raises(InvalidAssetTransferError, match="configured network"):
        gateway.prepare(
            AssetTransferRequest(
                operation_id="lottery:wrong-network",
                receiver=receiver,
                asset_id=7,
                amount_micros=1,
            )
        )


def test_gateway_rejects_a_persisted_fee_above_policy_before_network_io() -> None:
    private_key, sender = account.generate_account()
    _, receiver = account.generate_account()
    algod = FakeAlgod()
    gateway = AlgorandAssetTransferGateway(
        algod=algod,  # type: ignore[arg-type]
        indexer=FakeIndexer(sender=sender, receiver=receiver),  # type: ignore[arg-type]
        sender=sender,
        private_key=private_key,
        network="mainnet",
        max_fee_microalgos=1_000,
    )
    request = AssetTransferRequest(
        operation_id="lottery:persisted-fee",
        receiver=receiver,
        asset_id=7,
        amount_micros=1,
    )
    prepared = gateway.prepare(request)
    decoded = encoding.msgpack_decode(prepared.signed_transaction)
    decoded.transaction.fee = 2_000
    resigned = decoded.transaction.sign(private_key)
    tampered = replace(
        prepared,
        signed_transaction=encoding.msgpack_encode(resigned),
        txid=decoded.transaction.get_txid(),
    )

    with pytest.raises(InvalidAssetTransferError, match="fee"):
        gateway.broadcast(tampered, request)

    assert algod.sent == []
