"""Wallet-side asset transfer operations."""

import logging

from flex.application.asset_transfers import (
    AssetTransferReceipt,
    AssetTransferRequest,
)
from flex.application.transfer_runtime import get_asset_transfer_service

logger = logging.getLogger(__name__)


def send_nft(
    address: str,
    nft_id: int,
    amount: int = 1,
    *,
    idempotency_key: str,
) -> AssetTransferReceipt:
    """Send an NFT once for a stable business operation."""

    receipt = get_asset_transfer_service().execute(
        AssetTransferRequest(
            operation_id=f"nft:{idempotency_key}",
            receiver=address,
            asset_id=nft_id,
            amount_micros=amount,
        )
    )
    logger.info(
        "NFT transfer %s confirmed in round %s as %s",
        receipt.operation_id,
        receipt.confirmed_round,
        receipt.txid,
    )
    return receipt
