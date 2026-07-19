"""Operational airdrop tool with exact allocation and replay-safe transfers."""

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from algosdk import encoding
from pymongo import ReturnDocument

from flex import db
from flex.application.asset_transfers import (
    MAX_ALGORAND_UINT,
    AssetTransferReceipt,
    AssetTransferRequest,
    AssetTransferService,
)
from flex.application.transfer_runtime import get_asset_transfer_service
from flex.blockchain.base import cometa_public_key
from flex.blockchain.info import get_current_round
from flex.db.model.airdrop import AirdropManifest
from flex.db.model.blockchain import AssetInfo
from flex.db.model.priced import AirdropReward
from flex.domain.allocation import ShareInput, allocate_proportionally
from flex.txns import TxInfo

logger = logging.getLogger(__name__)


class AirdropError(RuntimeError):
    """Base class for invalid or incomplete airdrop execution."""


class AirdropConflictError(AirdropError):
    """Raised when an airdrop ID is reused with different transfer details."""


@dataclass(frozen=True, slots=True)
class AirdropFailure:
    address: str
    error_type: str
    txid: str | None = None


class AirdropIncompleteError(AirdropError):
    """Raised after all recipients were attempted and at least one is unresolved."""

    def __init__(
        self,
        failures: Sequence[AirdropFailure],
        confirmed_transactions: Sequence[TxInfo],
    ) -> None:
        super().__init__(f"airdrop incomplete: {len(failures)} recipient(s) unresolved; rerun with the same airdrop_id")
        self.failures = tuple(failures)
        self.confirmed_transactions = tuple(confirmed_transactions)


def _operation_id(airdrop_id: str, address: str) -> str:
    return f"airdrop:{airdrop_id}:{address}"


def _select_note(operation_id: str, notes: Sequence[str]) -> str:
    digest = sha256(operation_id.encode()).digest()
    index = int.from_bytes(digest[:8], "big") % len(notes)
    return notes[index]


def _validate_airdrop(
    *,
    airdrop_id: str,
    addresses: Sequence[str],
    notes: Sequence[str],
    amounts: Mapping[str, int],
) -> None:
    if not isinstance(airdrop_id, str) or not airdrop_id.strip():
        raise AirdropError("airdrop_id must be a non-empty string")
    if isinstance(notes, (str, bytes)) or not notes:
        raise AirdropError("notes must not be empty")
    if any(not isinstance(note, str) or len(note.encode()) > 1_000 for note in notes):
        raise AirdropError("each note must be a string within Algorand's 1000-byte limit")
    invalid_addresses = [address for address in addresses if not encoding.is_valid_address(address)]
    if invalid_addresses:
        raise AirdropError(f"airdrop contains {len(invalid_addresses)} invalid Algorand address(es)")
    zero_allocations = [address for address, amount in amounts.items() if amount == 0]
    if zero_allocations:
        raise AirdropError(
            f"airdrop budget is too small: {len(zero_allocations)} recipient(s) would receive zero base units"
        )


def _assert_reward_matches(
    reward: AirdropReward,
    *,
    asset_id: int,
    amount_micros: int,
) -> None:
    if (reward.asa_id_int, reward.amount_micros_int) != (asset_id, amount_micros):
        raise AirdropConflictError(
            f"existing reward {reward.airdrop_id!r}/{reward.address} has different transfer details"
        )


def _get_existing_reward(
    *,
    airdrop_id: str,
    address: str,
) -> AirdropReward | None:
    rewards = db.airdrop_rewards.get_many(
        address=address,
        airdrop_id=airdrop_id,
    )
    if len(rewards) > 1:
        raise AirdropError(
            f"multiple legacy rewards exist for {airdrop_id!r}/{address}; manual reconciliation required"
        )
    return rewards[0] if rewards else None


def _manifest_hash(
    *,
    airdrop_id: str,
    asset_id: int,
    total_amount_micros: int,
    requests: Mapping[str, AssetTransferRequest],
) -> str:
    canonical = {
        "airdrop_id": airdrop_id,
        "asset_id": asset_id,
        "total_amount_micros": str(total_amount_micros),
        "recipients": [
            [
                address,
                str(requests[address].amount_micros),
                requests[address].note,
            ]
            for address in sorted(requests)
        ],
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return sha256(encoded).hexdigest()


def _reserve_manifest(
    manifest: AirdropManifest,
) -> AirdropManifest:
    collection = db.airdrop_manifests.mongodb_collection
    collection.create_index("id", unique=True, name="id_unique")
    document = collection.find_one_and_update(
        {"id": manifest.id},
        {"$setOnInsert": manifest.to_dict()},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise AirdropError(f"failed to reserve airdrop manifest {manifest.id!r}")
    payload = dict(document)
    payload.pop("_id", None)
    persisted = AirdropManifest.from_dict(payload)
    immutable_fields = (
        persisted.asset_id_int,
        persisted.total_amount_micros,
        persisted.recipient_count,
        persisted.manifest_hash,
    )
    requested_fields = (
        manifest.asset_id_int,
        manifest.total_amount_micros,
        manifest.recipient_count,
        manifest.manifest_hash,
    )
    if immutable_fields != requested_fields:
        raise AirdropConflictError(f"airdrop_id {manifest.id!r} is already reserved for a different immutable manifest")
    return persisted


def _has_manifest(airdrop_id: str) -> bool:
    return (
        db.airdrop_manifests.mongodb_collection.find_one(
            {"id": airdrop_id},
            projection={"_id": 1},
        )
        is not None
    )


def _mark_manifest_status(airdrop_id: str, status: str) -> None:
    db.airdrop_manifests.mongodb_collection.update_one(
        {"id": airdrop_id},
        {
            "$set": {
                "status": status,
                "updated": datetime.now(UTC),
            }
        },
    )


def _reconcile_existing_reward(
    reward: AirdropReward,
    *,
    operation_id: str,
    transfer_service: AssetTransferService,
) -> AirdropReward:
    if reward.operation_id not in (None, operation_id):
        raise AirdropConflictError(f"reward {reward.airdrop_id!r}/{reward.address} belongs to another operation")

    confirmed_round = reward.confirmed_round
    if reward.operation_id is None or confirmed_round is None:
        observed = transfer_service.lookup_confirmed_transfer(reward.txid)
        if observed is None:
            raise AirdropError(
                f"legacy reward {reward.airdrop_id!r}/{reward.address} is not confirmed; manual reconciliation required"
            )
        expected = (
            cometa_public_key,
            reward.address,
            reward.asa_id_int,
            reward.amount_micros_int,
        )
        actual = (
            observed.sender,
            observed.receiver,
            observed.asset_id,
            observed.amount_micros,
        )
        if actual != expected:
            raise AirdropConflictError(
                f"legacy transaction {reward.txid} does not match its stored sender/receiver/asset/amount"
            )
        confirmed_round = observed.confirmed_round

    collection = db.airdrop_rewards.mongodb_collection
    document = collection.find_one_and_update(
        {
            "airdrop_id": reward.airdrop_id,
            "address": reward.address,
            "txid": reward.txid,
        },
        {
            "$set": {
                "operation_id": operation_id,
                "confirmed_round": confirmed_round,
                "updated": datetime.now(UTC),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise AirdropError(f"failed to backfill legacy reward {reward.airdrop_id!r}/{reward.address}")
    payload = dict(document)
    payload.pop("_id", None)
    return AirdropReward.from_dict(payload)


def _persist_reward(
    reward: AirdropReward,
) -> AirdropReward:
    if reward.operation_id is None:
        raise AirdropError("operation_id is required for a persisted reward")
    collection = db.airdrop_rewards.mongodb_collection
    document = collection.find_one_and_update(
        {"operation_id": reward.operation_id},
        {"$setOnInsert": reward.to_dict()},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise AirdropError(f"failed to persist reward {reward.operation_id!r}")
    payload = dict(document)
    payload.pop("_id", None)
    persisted = AirdropReward.from_dict(payload)
    _assert_reward_matches(
        persisted,
        asset_id=reward.asa_id_int,
        amount_micros=reward.amount_micros_int,
    )
    if persisted.txid != reward.txid:
        raise AirdropConflictError(f"reward {reward.operation_id!r} points to another transaction")
    if persisted.confirmed_round != reward.confirmed_round:
        raise AirdropConflictError(f"reward {reward.operation_id!r} has a different confirmation round")
    return persisted


def _to_tx_info(
    *,
    receipt: AssetTransferReceipt,
    asset_id: int,
    amount_micros: int,
    address: str,
    note: str,
) -> TxInfo:
    return TxInfo(
        id=receipt.txid,
        amount=amount_micros,
        asa_id=asset_id,
        receiver=address,
        note=note,
        sender=cometa_public_key,
        confirmed_round=receipt.confirmed_round,
    )


def _write_manifest(
    directory: Path,
    *,
    asset_id: int,
    current_round: int,
    amounts: Mapping[str, int],
    transactions: Sequence[TxInfo],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    amounts_path = directory / f"airdrop_amounts_{asset_id}_{current_round}.json"
    transactions_path = directory / f"airdrop_txns_{asset_id}_{current_round}.json"
    amounts_path.write_text(
        json.dumps(amounts, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    transactions_path.write_text(
        json.dumps([transaction_info.to_dict() for transaction_info in transactions], indent=2) + "\n",
        encoding="utf-8",
    )


async def send_airdrop(
    asset_info: AssetInfo,
    total_amount_micros: int,
    address_shares: Mapping[str, ShareInput],
    notes: Sequence[str],
    airdrop_id: str,
    *,
    manifest_directory: Path | None = None,
    transfer_service: AssetTransferService | None = None,
) -> list[TxInfo]:
    """Execute or resume an airdrop without exceeding its integer budget."""

    current_round = await get_current_round()
    if total_amount_micros > MAX_ALGORAND_UINT:
        raise AirdropError("total_amount_micros exceeds Algorand's uint64 range")
    amounts = allocate_proportionally(total_amount_micros, address_shares)
    _validate_airdrop(
        airdrop_id=airdrop_id,
        addresses=list(address_shares),
        notes=notes,
        amounts=amounts,
    )
    service = transfer_service or get_asset_transfer_service()
    requests = {
        address: AssetTransferRequest(
            operation_id=_operation_id(airdrop_id, address),
            receiver=address,
            asset_id=asset_info.id,
            amount_micros=amount_micros,
            note=_select_note(_operation_id(airdrop_id, address), notes),
        )
        for address, amount_micros in amounts.items()
    }

    campaign_rewards = db.airdrop_rewards.get_many(airdrop_id=airdrop_id)
    if campaign_rewards and not _has_manifest(airdrop_id):
        raise AirdropError(
            f"legacy airdrop {airdrop_id!r} has rewards but no immutable manifest; reconcile and migrate it explicitly"
        )

    # Configuration conflicts must abort the entire batch before any new
    # transaction is broadcast.
    for address, request in requests.items():
        service.validate(request)
        existing_reward = _get_existing_reward(
            airdrop_id=airdrop_id,
            address=address,
        )
        if existing_reward is not None:
            _assert_reward_matches(
                existing_reward,
                asset_id=asset_info.id,
                amount_micros=amounts[address],
            )
            _reconcile_existing_reward(
                existing_reward,
                operation_id=request.operation_id,
                transfer_service=service,
            )

    _reserve_manifest(
        AirdropManifest(
            id=airdrop_id,
            asset_id=str(asset_info.id),
            total_amount_micros=str(total_amount_micros),
            recipient_count=len(requests),
            manifest_hash=_manifest_hash(
                airdrop_id=airdrop_id,
                asset_id=asset_info.id,
                total_amount_micros=total_amount_micros,
                requests=requests,
            ),
        )
    )

    logger.info(
        "Executing airdrop %s for asset %s at round %s: %s base units across %s recipients",
        airdrop_id,
        asset_info.id,
        current_round,
        total_amount_micros,
        len(amounts),
    )

    confirmed_transactions: list[TxInfo] = []
    failures: list[AirdropFailure] = []

    for position, (address, amount_micros) in enumerate(amounts.items(), start=1):
        request = requests[address]
        try:
            existing_reward = _get_existing_reward(
                airdrop_id=airdrop_id,
                address=address,
            )
            if existing_reward is not None:
                _assert_reward_matches(
                    existing_reward,
                    asset_id=asset_info.id,
                    amount_micros=amount_micros,
                )
                existing_reward = _reconcile_existing_reward(
                    existing_reward,
                    operation_id=request.operation_id,
                    transfer_service=service,
                )
                logger.info(
                    "Airdrop %s recipient %s/%s already confirmed as %s",
                    airdrop_id,
                    position,
                    len(amounts),
                    existing_reward.txid,
                )
                continue

            receipt = service.execute(
                request,
            )
            _persist_reward(
                AirdropReward(
                    airdrop_id=airdrop_id,
                    address=address,
                    asa_id=str(asset_info.id),
                    amount_micros=str(amount_micros),
                    txid=receipt.txid,
                    operation_id=request.operation_id,
                    confirmed_round=receipt.confirmed_round,
                )
            )
            if not receipt.already_confirmed:
                confirmed_transactions.append(
                    _to_tx_info(
                        receipt=receipt,
                        asset_id=asset_info.id,
                        amount_micros=amount_micros,
                        address=address,
                        note=request.note or "",
                    )
                )
        except Exception as exc:
            failures.append(
                AirdropFailure(
                    address=address,
                    error_type=type(exc).__name__,
                    txid=getattr(exc, "txid", None),
                )
            )
            logger.exception(
                "Airdrop %s recipient %s/%s is unresolved",
                airdrop_id,
                position,
                len(amounts),
            )

    if manifest_directory is not None:
        _write_manifest(
            manifest_directory,
            asset_id=asset_info.id,
            current_round=current_round,
            amounts=amounts,
            transactions=confirmed_transactions,
        )

    if failures:
        _mark_manifest_status(airdrop_id, "partial")
        raise AirdropIncompleteError(failures, confirmed_transactions)

    _mark_manifest_status(airdrop_id, "complete")
    logger.info(
        "Airdrop %s confirmed %s new transaction(s); allocated total remains exactly %s base units",
        airdrop_id,
        len(confirmed_transactions),
        sum(amounts.values()),
    )
    return confirmed_transactions
