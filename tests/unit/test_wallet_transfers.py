from api import wallet
from flex.application.asset_transfers import (
    AssetTransferReceipt,
    AssetTransferRequest,
)


def test_send_nft_requires_and_namespaces_a_stable_idempotency_key(monkeypatch) -> None:
    requests = []

    class FakeService:
        def execute(self, request):
            requests.append(request)
            return AssetTransferReceipt(
                operation_id=request.operation_id,
                txid="TXID",
                confirmed_round=123,
                already_confirmed=False,
            )

    monkeypatch.setattr(
        wallet,
        "get_asset_transfer_service",
        lambda: FakeService(),
    )

    receipt = wallet.send_nft(
        "RECEIVER",
        42,
        idempotency_key="lottery:draw-1",
    )

    assert receipt.txid == "TXID"
    assert requests == [
        AssetTransferRequest(
            operation_id="nft:lottery:draw-1",
            receiver="RECEIVER",
            asset_id=42,
            amount_micros=1,
            note=None,
        )
    ]
