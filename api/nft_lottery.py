import logging
import math
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import uuid4

from algosdk.v2client import indexer
from dataclasses_json import dataclass_json
from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure

import flex
from api.swaps import SwapInfo
from api.wallet import send_nft
from blockchain.nfts import get_nft_info
from blockchain.node import init_algod_client
from core.db.db_manager import DbManager
from core.db.mongodb import get_db_collection
from env import settings
from flex.blockchain.base import cometa_public_key

MIN_DRAW_INTERVAL = 60 * 60 * 24  # 24 hours
LOTTERY_DRAW_ID_INDEX_NAME = "id_nonempty_unique"
LOTTERY_DRAW_ID_FILTER = {
    "id": {
        "$type": "string",
        "$gt": "",
    }
}
LEGACY_LOTTERY_DRAW_ID_FILTER = {"id": {"$type": "string"}}


class LotteryType(StrEnum):
    SWAP = "swap"
    STAKING = "staking"

    def __str__(self):
        return self.value


class LotteryPayoutStatus(StrEnum):
    PENDING = "pending"
    PREPARED = "prepared"
    CONFIRMED = "confirmed"
    UNRESOLVED = "unresolved"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class StakingEntitlementStatus(StrEnum):
    RESERVED = "reserved"
    PREPARED = "prepared"
    MATERIALIZED = "materialized"
    CONFIRMED = "confirmed"
    NO_PRIZE = "no_prize"
    UNRESOLVED = "unresolved"


@dataclass_json
@dataclass
class NftLottery:
    name: str
    asset_id: int
    min_amount: int
    probability: float
    available_nfts: list[int]
    win_title: str = "You have won a prize NFT!"
    max_amount: int | None = None
    type: str | None = None
    only_for_buy: bool | None = None
    pool_id: int | None = None

    def is_eligible(self, entity_id: int, amount: float) -> bool:
        return (
            (entity_id == self.asset_id or entity_id == self.pool_id)
            and amount >= self.min_amount
            and (self.max_amount is None or amount <= self.max_amount)
        )


@dataclass_json
@dataclass
class LotteryDraw:
    wallet: str
    prize: int | None
    timestamp: float | None = None
    lottery_name: str | None = None
    claimed: bool = False
    created_date: datetime | None = None
    send_error: str | None = None
    id: str | None = None
    payout_operation_id: str | None = None
    payout_txid: str | None = None
    confirmed_round: int | None = None
    payout_status: str | None = None
    entitlement_id: str | None = None
    entitlement_generation: int | None = None

    def __post_init__(self):
        if self.timestamp:
            self.created_date = datetime.fromtimestamp(self.timestamp, tz=UTC)


@dataclass_json
@dataclass
class LotteryParticipant:
    address: str
    pool_id: int
    last_draw_block: int


nft_lotteries = DbManager[NftLottery](settings.db_name, "nft_lotteries", "name", NftLottery)
lottery_draws = DbManager[LotteryDraw](settings.db_name, "lottery_draws", "id", LotteryDraw)
lottery_participants = DbManager[LotteryParticipant](
    settings.db_name, "lottery_participants", "address", LotteryParticipant
)
lottery_entitlements = get_db_collection(
    settings.db_name,
    "lottery_entitlements",
)

algod_client = init_algod_client()
indexer_client = indexer.IndexerClient(
    indexer_token=settings.algod_token, indexer_address=settings.algo_indexer_address
)

logger = logging.getLogger(__name__)


def _is_lottery_draw_id_index(
    index: dict[str, Any],
    *,
    partial_filter: dict[str, Any],
) -> bool:
    return (
        list(index.get("key", [])) == [("id", ASCENDING)]
        and index.get("unique") is True
        and index.get("partialFilterExpression") == partial_filter
    )


def _duplicate_lottery_draw_ids() -> list[dict[str, Any]]:
    return list(
        lottery_draws.collection.aggregate(
            [
                {"$match": LOTTERY_DRAW_ID_FILTER},
                {
                    "$group": {
                        "_id": "$id",
                        "count": {"$sum": 1},
                        "document_ids": {"$push": "$_id"},
                    }
                },
                {"$match": {"count": {"$gt": 1}}},
                {"$limit": 10},
            ],
            allowDiskUse=True,
        )
    )


def ensure_lottery_indexes() -> None:
    """Upgrade the draw identity index without a uniqueness gap or data loss."""

    collection = lottery_draws.collection
    indexes = collection.index_information()
    desired_index = indexes.get(LOTTERY_DRAW_ID_INDEX_NAME)
    legacy_index = indexes.get("id_unique")

    if desired_index is not None and not _is_lottery_draw_id_index(
        desired_index,
        partial_filter=LOTTERY_DRAW_ID_FILTER,
    ):
        raise RuntimeError(
            f"lottery_draws index {LOTTERY_DRAW_ID_INDEX_NAME!r} has unexpected options; "
            "inspect it manually before startup"
        )

    if legacy_index is not None and not (
        _is_lottery_draw_id_index(
            legacy_index,
            partial_filter=LEGACY_LOTTERY_DRAW_ID_FILTER,
        )
        or _is_lottery_draw_id_index(
            legacy_index,
            partial_filter=LOTTERY_DRAW_ID_FILTER,
        )
    ):
        raise RuntimeError("lottery_draws index 'id_unique' has unexpected options; inspect it manually before startup")

    if desired_index is None and not (
        legacy_index is not None
        and _is_lottery_draw_id_index(
            legacy_index,
            partial_filter=LOTTERY_DRAW_ID_FILTER,
        )
    ):
        duplicate_groups = _duplicate_lottery_draw_ids()
        if duplicate_groups:
            raise RuntimeError(
                "lottery_draws contains duplicate non-empty draw IDs; "
                f"preserved {len(duplicate_groups)} duplicate group(s) for explicit reconciliation"
            )
        try:
            collection.create_index(
                "id",
                unique=True,
                name=LOTTERY_DRAW_ID_INDEX_NAME,
                partialFilterExpression=LOTTERY_DRAW_ID_FILTER,
            )
        except DuplicateKeyError as exc:
            raise RuntimeError(
                "lottery_draws uniqueness changed while building its index; "
                "all conflicting records were preserved for explicit reconciliation"
            ) from exc
        except OperationFailure as exc:
            if exc.code != 11000:
                raise
            raise RuntimeError(
                "lottery_draws uniqueness changed while building its index; "
                "all conflicting records were preserved for explicit reconciliation"
            ) from exc
        desired_index = collection.index_information().get(LOTTERY_DRAW_ID_INDEX_NAME)
        if desired_index is None or not _is_lottery_draw_id_index(
            desired_index,
            partial_filter=LOTTERY_DRAW_ID_FILTER,
        ):
            raise RuntimeError("lottery_draws unique draw ID index was not installed")

    if legacy_index is not None and _is_lottery_draw_id_index(
        legacy_index,
        partial_filter=LEGACY_LOTTERY_DRAW_ID_FILTER,
    ):
        # The replacement already protects every non-empty ID. Dropping the
        # narrower legacy definition now cannot introduce a uniqueness gap.
        try:
            collection.drop_index("id_unique")
        except OperationFailure as exc:
            if exc.code != 27:
                raise
        else:
            logger.info("Upgraded lottery_draws.id unique index without modifying draw records")
        replacement = collection.index_information().get(LOTTERY_DRAW_ID_INDEX_NAME)
        if replacement is None or not _is_lottery_draw_id_index(
            replacement,
            partial_filter=LOTTERY_DRAW_ID_FILTER,
        ):
            raise RuntimeError("lottery_draws replacement identity index disappeared during the legacy index upgrade")


def _create_draw(
    *,
    lottery_name: str,
    prize: int | None,
    wallet: str,
    timestamp: float,
) -> LotteryDraw:
    ensure_lottery_indexes()
    return lottery_draws.create(
        LotteryDraw(
            id=uuid4().hex,
            lottery_name=lottery_name,
            prize=prize,
            wallet=wallet,
            timestamp=timestamp,
            payout_status=LotteryPayoutStatus.PENDING,
        )
    )


def _staking_entitlement_id(lottery_name: str, wallet: str) -> str:
    identity = f"staking-lottery:{lottery_name}:{wallet}"
    return sha256(identity.encode()).hexdigest()


def _valid_draw_timestamp(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _seed_staking_entitlement(
    *,
    lottery_name: str,
    wallet: str,
    now: datetime,
) -> str:
    """Initialize the CAS guard from any pre-migration draw."""

    entitlement_id = _staking_entitlement_id(lottery_name, wallet)
    seed: dict[str, Any] = {
        "_id": entitlement_id,
        "lottery_name": lottery_name,
        "wallet": wallet,
        "generation": 0,
        "next_eligible_at": datetime.fromtimestamp(0, tz=UTC),
        "created": now,
        "updated": now,
    }
    latest = lottery_draws.collection.find_one(
        {
            "wallet": wallet,
            "lottery_name": lottery_name,
        },
        sort=[("timestamp", -1)],
    )
    outstanding = lottery_draws.collection.find_one(
        {
            "wallet": wallet,
            "lottery_name": lottery_name,
            "prize": {"$ne": None},
            "claimed": {"$in": [False, None]},
        },
        sort=[("timestamp", -1)],
    )
    active_document = outstanding or latest
    if active_document is not None:
        draw, _ = _backfill_draw_id(active_document)
        active_timestamp = _valid_draw_timestamp(draw.timestamp)
        latest_timestamp = _valid_draw_timestamp(latest.get("timestamp")) if latest is not None else active_timestamp
        if active_timestamp is None or latest_timestamp is None:
            draw_timestamp = now.timestamp()
            status = StakingEntitlementStatus.UNRESOLVED
            next_eligible_at = now + timedelta(seconds=MIN_DRAW_INTERVAL)
        else:
            draw_timestamp = active_timestamp
            status = (
                StakingEntitlementStatus.NO_PRIZE
                if draw.prize is None
                else (StakingEntitlementStatus.CONFIRMED if draw.claimed else StakingEntitlementStatus.UNRESOLVED)
            )
            try:
                next_eligible_at = datetime.fromtimestamp(
                    latest_timestamp,
                    tz=UTC,
                ) + timedelta(seconds=MIN_DRAW_INTERVAL)
            except (OverflowError, OSError, ValueError):
                draw_timestamp = now.timestamp()
                status = StakingEntitlementStatus.UNRESOLVED
                next_eligible_at = now + timedelta(seconds=MIN_DRAW_INTERVAL)
        seed["next_eligible_at"] = next_eligible_at
        seed["active"] = {
            "draw_id": draw.id,
            "draw_timestamp": draw_timestamp,
            "prize": draw.prize,
            "status": status,
        }

    try:
        lottery_entitlements.update_one(
            {"_id": entitlement_id},
            {"$setOnInsert": seed},
            upsert=True,
        )
    except DuplicateKeyError:
        # Another worker installed the same single-document guard.
        pass
    return entitlement_id


def _claim_staking_entitlement(
    *,
    lottery_name: str,
    wallet: str,
    now: datetime,
) -> dict[str, Any] | None:
    """Claim one rolling-window liability or recover its unfinished draw."""

    entitlement_id = _seed_staking_entitlement(
        lottery_name=lottery_name,
        wallet=wallet,
        now=now,
    )
    draw_id_value = uuid4().hex
    draw_timestamp = now.timestamp()
    claimed = lottery_entitlements.find_one_and_update(
        {
            "_id": entitlement_id,
            "next_eligible_at": {"$lte": now},
            "$or": [
                {"active": {"$exists": False}},
                {
                    "active.status": {
                        "$in": [
                            StakingEntitlementStatus.CONFIRMED,
                            StakingEntitlementStatus.NO_PRIZE,
                        ]
                    }
                },
            ],
        },
        {
            "$inc": {"generation": 1},
            "$set": {
                "next_eligible_at": now + timedelta(seconds=MIN_DRAW_INTERVAL),
                "active": {
                    "draw_id": draw_id_value,
                    "draw_timestamp": draw_timestamp,
                    "reserved_at": now,
                    "status": StakingEntitlementStatus.RESERVED,
                },
                "updated": now,
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if claimed is not None:
        return claimed

    current = lottery_entitlements.find_one({"_id": entitlement_id})
    if not isinstance(current, dict):
        raise RuntimeError("staking lottery entitlement disappeared")
    active = current.get("active")
    if isinstance(active, dict) and active.get("status") in {
        StakingEntitlementStatus.MATERIALIZED,
        StakingEntitlementStatus.UNRESOLVED,
    }:
        active_draw_id = active.get("draw_id")
        draw_document = (
            lottery_draws.collection.find_one({"id": active_draw_id}) if isinstance(active_draw_id, str) else None
        )
        if (
            isinstance(draw_document, dict)
            and draw_document.get("claimed") is True
            and draw_document.get("payout_status") == LotteryPayoutStatus.CONFIRMED
        ):
            repaired = lottery_entitlements.find_one_and_update(
                {
                    "_id": entitlement_id,
                    "generation": current["generation"],
                    "active.draw_id": active_draw_id,
                    "active.status": active["status"],
                },
                {
                    "$set": {
                        "active.status": StakingEntitlementStatus.CONFIRMED,
                        "updated": now,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            if repaired is not None:
                return _claim_staking_entitlement(
                    lottery_name=lottery_name,
                    wallet=wallet,
                    now=now,
                )
    if isinstance(active, dict) and active.get("status") in {
        StakingEntitlementStatus.RESERVED,
        StakingEntitlementStatus.PREPARED,
    }:
        # A crash or competing request may leave the one winning reservation
        # unfinished. Helping it cannot create a second business entitlement.
        return current
    return None


def _prepare_staking_prize(
    entitlement: dict[str, Any],
    lottery: NftLottery,
) -> dict[str, Any]:
    active = entitlement.get("active")
    if not isinstance(active, dict) or not isinstance(active.get("draw_id"), str):
        raise RuntimeError("staking lottery entitlement has no active draw")
    if active.get("status") == StakingEntitlementStatus.RESERVED:
        prize_id = draw_id(lottery)
        prepared = lottery_entitlements.find_one_and_update(
            {
                "_id": entitlement["_id"],
                "generation": entitlement["generation"],
                "active.draw_id": active["draw_id"],
                "active.status": StakingEntitlementStatus.RESERVED,
            },
            {
                "$set": {
                    "active.prize": prize_id,
                    "active.status": StakingEntitlementStatus.PREPARED,
                    "updated": datetime.now(UTC),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if prepared is not None:
            return prepared
        entitlement = lottery_entitlements.find_one({"_id": entitlement["_id"]})
        if not isinstance(entitlement, dict):
            raise RuntimeError("staking lottery entitlement disappeared during prize reservation")

    active = entitlement.get("active")
    if not isinstance(active, dict) or active.get("status") not in {
        StakingEntitlementStatus.PREPARED,
        StakingEntitlementStatus.MATERIALIZED,
        StakingEntitlementStatus.NO_PRIZE,
    }:
        raise RuntimeError("staking lottery prize reservation is not recoverable")
    return entitlement


def _materialize_staking_draw(
    entitlement: dict[str, Any],
    lottery: NftLottery,
    wallet: str,
) -> LotteryDraw:
    active = entitlement["active"]
    draw_id_value = active["draw_id"]
    draw_timestamp = active["draw_timestamp"]
    prize_id = active.get("prize")
    generation = entitlement["generation"]
    ensure_lottery_indexes()
    payload = LotteryDraw(
        id=draw_id_value,
        lottery_name=lottery.name,
        prize=prize_id,
        wallet=wallet,
        timestamp=draw_timestamp,
        payout_status=LotteryPayoutStatus.PENDING,
        entitlement_id=entitlement["_id"],
        entitlement_generation=generation,
    ).to_dict()
    try:
        document = lottery_draws.collection.find_one_and_update(
            {"id": draw_id_value},
            {"$setOnInsert": payload},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        document = lottery_draws.collection.find_one({"id": draw_id_value})
    if not isinstance(document, dict):
        raise RuntimeError("staking lottery draw could not be materialized")
    immutable = (
        document.get("id"),
        document.get("lottery_name"),
        document.get("wallet"),
        document.get("prize"),
        document.get("timestamp"),
        document.get("entitlement_id"),
        document.get("entitlement_generation"),
    )
    expected = (
        draw_id_value,
        lottery.name,
        wallet,
        prize_id,
        draw_timestamp,
        entitlement["_id"],
        generation,
    )
    if immutable != expected:
        raise RuntimeError("staking lottery draw ID belongs to different immutable data")

    status = StakingEntitlementStatus.NO_PRIZE if prize_id is None else StakingEntitlementStatus.MATERIALIZED
    updated = lottery_entitlements.update_one(
        {
            "_id": entitlement["_id"],
            "generation": generation,
            "active.draw_id": draw_id_value,
            "active.status": {
                "$in": [
                    StakingEntitlementStatus.PREPARED,
                    status,
                ]
            },
        },
        {
            "$set": {
                "active.status": status,
                "updated": datetime.now(UTC),
            }
        },
    )
    if updated.matched_count != 1:
        current = lottery_entitlements.find_one({"_id": entitlement["_id"]})
        current_active = current.get("active") if isinstance(current, dict) else None
        if not (
            isinstance(current_active, dict)
            and current_active.get("draw_id") == draw_id_value
            and current_active.get("status")
            in {
                status,
                StakingEntitlementStatus.CONFIRMED,
                StakingEntitlementStatus.UNRESOLVED,
            }
        ):
            raise RuntimeError("staking lottery entitlement changed during draw materialization")
    return LotteryDraw.from_dict(document)


def _get_or_create_staking_draw(
    lottery: NftLottery,
    wallet: str,
    *,
    now: datetime,
) -> LotteryDraw | None:
    entitlement = _claim_staking_entitlement(
        lottery_name=lottery.name,
        wallet=wallet,
        now=now,
    )
    if entitlement is None:
        return None
    prepared = _prepare_staking_prize(entitlement, lottery)
    return _materialize_staking_draw(prepared, lottery, wallet)


def _update_staking_entitlement_status(
    draw: LotteryDraw,
    status: StakingEntitlementStatus,
) -> None:
    if draw.entitlement_id is None or draw.entitlement_generation is None or draw.id is None:
        return
    selector: dict[str, Any] = {
        "_id": draw.entitlement_id,
        "generation": draw.entitlement_generation,
        "active.draw_id": draw.id,
    }
    if status != StakingEntitlementStatus.CONFIRMED:
        selector["active.status"] = {
            "$ne": StakingEntitlementStatus.CONFIRMED,
        }
    try:
        result = lottery_entitlements.update_one(
            selector,
            {
                "$set": {
                    "active.status": status,
                    "updated": datetime.now(UTC),
                }
            },
        )
    except Exception:
        logger.exception(
            "Could not update staking entitlement %s generation %s to %s; future draws remain fail-closed",
            draw.entitlement_id,
            draw.entitlement_generation,
            status,
        )
        return
    if result.matched_count != 1:
        current = lottery_entitlements.find_one(
            {
                "_id": draw.entitlement_id,
                "generation": draw.entitlement_generation,
                "active.draw_id": draw.id,
            }
        )
        current_active = current.get("active") if isinstance(current, dict) else None
        if isinstance(current_active, dict) and current_active.get("status") in {
            status,
            StakingEntitlementStatus.CONFIRMED,
        }:
            return
        logger.error(
            "Could not update staking entitlement %s generation %s to %s; future draws remain fail-closed",
            draw.entitlement_id,
            draw.entitlement_generation,
            status,
        )


def _backfill_draw_id(document: dict[str, Any]) -> tuple[LotteryDraw, Any]:
    document_id = document.get("_id")
    if document_id is None:
        raise RuntimeError("lottery draw is missing its MongoDB identity")

    for attempt in range(4):
        original_id = document.get("id")
        missing_draw_id = not isinstance(original_id, str) or not original_id
        draw_id_value = (
            f"legacy-{sha256(f'lottery-draw:{document_id}'.encode()).hexdigest()}" if missing_draw_id else original_id
        )
        original_status = document.get("payout_status")
        missing_payout_status = not isinstance(original_status, str) or not original_status
        claimed_value = document.get("claimed")
        missing_claimed = "claimed" not in document or claimed_value is None
        if claimed_value is not None and not isinstance(claimed_value, bool):
            raise RuntimeError("lottery draw has an invalid claimed state")
        if not missing_draw_id and not missing_payout_status and not missing_claimed:
            break
        if attempt == 3:
            raise RuntimeError("lottery draw kept changing during migration")

        expected_operation_id = f"nft:lottery:{draw_id_value}"
        payout_status = (
            LotteryPayoutStatus.CONFIRMED
            if claimed_value is True
            else (
                LotteryPayoutStatus.PREPARED
                if document.get("payout_operation_id") == expected_operation_id
                else LotteryPayoutStatus.RECONCILIATION_REQUIRED
            )
        )
        migration_query: dict[str, Any] = {"_id": document_id}
        for field_name in (
            "id",
            "payout_status",
            "claimed",
            "payout_operation_id",
        ):
            migration_query[field_name] = (
                {"$eq": document[field_name]} if field_name in document else {"$exists": False}
            )
        migrated = lottery_draws.collection.find_one_and_update(
            migration_query,
            {
                "$set": {
                    "id": draw_id_value,
                    "payout_status": payout_status,
                    **({"claimed": False} if missing_claimed else {}),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if migrated is not None:
            document = migrated
            break
        updated = lottery_draws.collection.find_one({"_id": document_id})
        if updated is None:
            raise RuntimeError("lottery draw disappeared during migration")
        document = updated

    draw = LotteryDraw.from_dict(document)
    if not isinstance(draw.id, str) or not draw.id or not draw.payout_status or not isinstance(draw.claimed, bool):
        raise RuntimeError("lottery draw migration did not persist its identity and payout state")
    return draw, document_id


def draw_id(lottery: NftLottery) -> int | None:
    if random.random() > lottery.probability:
        return None
    while True:
        if not lottery.available_nfts:
            return None
        # TODO: refactor to get balance once
        res = random.choice(lottery.available_nfts)
        data = indexer_client.lookup_account_assets(address=cometa_public_key, asset_id=res)
        assets = data.get("assets", [])
        if len(assets) > 0 and assets[0].get("amount", 0) > 0:
            # drawn nft persists in the wallet
            break
        logger.info(f"NFT {res} is not in the wallet, drawing again")
        lottery.available_nfts.remove(res)
        nft_lotteries.update(lottery)
    return res


@dataclass
class NftPrize:
    asa_id: int
    name: str
    image_url: str
    title: str


def get_nft_prize(lottery: NftLottery, asa_id: int | None) -> NftPrize | None:
    if asa_id is None:
        return None
    prize_info = get_nft_info(asa_id)

    PINATA_URL = "https://gateway.pinata.cloud/ipfs/"
    image_url = prize_info.image_url.replace("ipfs://", PINATA_URL)

    return NftPrize(asa_id=asa_id, name=prize_info.name, image_url=image_url, title=lottery.win_title)


def draw_prize(lottery: NftLottery, address: str) -> NftPrize | None:
    logger.debug(f"Drawing lottery {lottery.name} for {address}")
    prize_id = draw_id(lottery)
    _create_draw(
        lottery_name=lottery.name,
        prize=prize_id,
        wallet=address,
        timestamp=time.time(),
    )
    return get_nft_prize(lottery, prize_id)


def lottery_for_swap(swap: SwapInfo) -> NftPrize | None:
    lotteries = nft_lotteries.get_many({"type": LotteryType.SWAP})
    logger.debug(f"Swap lotteries cnt = {len(lotteries)}")

    prize = None
    for lottery in lotteries:
        if prize is None and lottery.is_eligible(swap.asset2_id, swap.asset2_amount):
            prize = draw_prize(lottery, swap.wallet)
        if prize is None and not lottery.only_for_buy and lottery.is_eligible(swap.asset1_id, swap.asset1_amount):
            prize = draw_prize(lottery, swap.wallet)

    return prize


async def lottery_for_staking(pool_id: int, address: str) -> NftPrize | None:
    lotteries = nft_lotteries.get_many({"type": LotteryType.STAKING, "pool_id": pool_id})
    if not lotteries:
        logger.info(f"No lotteries found for pools_id {pool_id}")
        return None
    logger.debug(f"Lotteries found for pools_id {pool_id}: {lotteries}")

    pool_state = flex.db.pool_states.get_one(pool_id=pool_id)
    if pool_state is None:
        logger.error(f"Pool state not found for pool {pool_id}")
        return None

    user_state = flex.db.user_states.get_one(address=address)
    if user_state is None:
        logger.error(f"User state not found for address {address}")
        return None

    address_stake_micros = user_state.pool_by_address.get(pool_state.address)
    if address_stake_micros is None:
        logger.info(f"No staking found for address {address} in pool {pool_id}")
        return None

    lottery = None
    for candidate in lotteries:
        if len(candidate.available_nfts) == 0:
            logger.warning(f"NFTS are OVER for lottery {candidate.name}")
            nft_lotteries.remove(candidate)
            logger.info(f"Lottery {candidate.name} removed")
            continue

        if address_stake_micros >= candidate.min_amount and (
            lottery is None or candidate.probability > lottery.probability
        ):
            lottery = candidate

    if lottery is None:
        logger.info(f"No lottery found for address {address} in pool {pool_id}")
        return None

    logger.info(f"Lottery {lottery.name} for pool {pool_id} and address {address} started")

    draw = _get_or_create_staking_draw(
        lottery,
        address,
        now=datetime.now(UTC),
    )
    if draw is None:
        logger.info(f"Lottery {lottery.name} for pool {pool_id} and address {address} already drawn recently")
        return None
    prize_id = draw.prize

    logger.info(f"The prize is {prize_id}")

    if prize_id is not None:
        prize_info = get_nft_prize(lottery, prize_id)
        logger.info(f"Prize info: {prize_info}")
        return prize_info

    return None


def send_all_prizes():
    logger.info("Sending all failed NFT prizes...")

    ensure_lottery_indexes()
    res = []
    sent_count = 0
    error_count = 0
    documents = list(
        lottery_draws.collection.find(
            {
                "claimed": {"$in": [False, None]},
                "prize": {"$ne": None},
            }
        )
    )
    for document in documents:
        try:
            draw, document_id = _backfill_draw_id(document)
        except Exception as exc:
            document_id = document.get("_id")
            info = {
                "wallet": document.get("wallet"),
                "prize": document.get("prize"),
                "lottery": document.get("lottery_name"),
                "error": f"lottery draw migration failed: {exc}",
            }
            if document_id is not None:
                lottery_draws.collection.update_one(
                    {"_id": document_id, "claimed": False},
                    {"$set": {"send_error": str(info["error"])[:500]}},
                )
            error_count += 1
            logger.exception("Skipped malformed lottery draw")
            res.append(info)
            continue
        if draw.claimed or draw.prize is None:
            continue
        info = {"wallet": draw.wallet, "prize": draw.prize, "lottery": draw.lottery_name}
        payable_statuses = (
            LotteryPayoutStatus.PENDING,
            LotteryPayoutStatus.PREPARED,
            LotteryPayoutStatus.UNRESOLVED,
        )
        if draw.payout_status not in payable_statuses:
            error = (
                "legacy lottery payout requires manual reconciliation"
                if draw.payout_status == LotteryPayoutStatus.RECONCILIATION_REQUIRED
                else f"lottery payout has non-payable status {draw.payout_status!r}"
            )
            info["error"] = error
            lottery_draws.collection.update_one(
                {
                    "_id": document_id,
                    "claimed": False,
                    "payout_status": draw.payout_status,
                },
                {"$set": {"send_error": error}},
            )
            error_count += 1
            logger.warning("Skipped non-payable NFT payout: %s", info)
            res.append(info)
            continue
        try:
            idempotency_key = f"lottery:{draw.id}"
            payout_operation_id = f"nft:{idempotency_key}"
            if draw.payout_operation_id not in (None, payout_operation_id):
                raise RuntimeError("lottery draw belongs to a different payout operation")
            prepared = lottery_draws.collection.update_one(
                {
                    "_id": document_id,
                    "claimed": False,
                    "payout_operation_id": {"$in": [None, payout_operation_id]},
                    "payout_status": {
                        "$in": list(payable_statuses),
                    },
                },
                {
                    "$set": {
                        "payout_operation_id": payout_operation_id,
                        "payout_status": LotteryPayoutStatus.PREPARED,
                        "send_error": None,
                    }
                },
            )
            if prepared.matched_count != 1:
                current = lottery_draws.collection.find_one({"_id": document_id})
                if current is not None and current.get("claimed") is True:
                    info["already_claimed"] = True
                    info["txid"] = current.get("payout_txid")
                    _update_staking_entitlement_status(
                        LotteryDraw.from_dict(current),
                        StakingEntitlementStatus.CONFIRMED,
                    )
                    logger.info("NFT payout completed by another worker: %s", info)
                    res.append(info)
                    continue
                raise RuntimeError("lottery draw changed before payout reservation")
            receipt = send_nft(
                draw.wallet,
                draw.prize,
                idempotency_key=idempotency_key,
            )
            info["txid"] = receipt.txid
            info["sent"] = datetime.now(UTC)
            claimed = lottery_draws.collection.find_one_and_update(
                {
                    "_id": document_id,
                    "claimed": False,
                    "payout_operation_id": receipt.operation_id,
                    "payout_status": {
                        "$ne": LotteryPayoutStatus.RECONCILIATION_REQUIRED,
                    },
                },
                {
                    "$set": {
                        "claimed": True,
                        "payout_operation_id": receipt.operation_id,
                        "payout_txid": receipt.txid,
                        "confirmed_round": receipt.confirmed_round,
                        "payout_status": LotteryPayoutStatus.CONFIRMED,
                        "send_error": None,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            if claimed is None:
                claimed = lottery_draws.collection.find_one({"_id": document_id})
                if claimed is None or not claimed.get("claimed") or claimed.get("payout_txid") != receipt.txid:
                    raise RuntimeError("lottery draw changed while recording its confirmed payout")
                info["already_claimed"] = True
            else:
                sent_count += 1
            _update_staking_entitlement_status(
                LotteryDraw.from_dict(claimed),
                StakingEntitlementStatus.CONFIRMED,
            )
        except Exception as e:
            info["error"] = str(e)
            _update_staking_entitlement_status(
                draw,
                StakingEntitlementStatus.UNRESOLVED,
            )
            lottery_draws.collection.update_one(
                {
                    "_id": document_id,
                    "claimed": False,
                    "payout_operation_id": payout_operation_id,
                    "payout_status": {"$ne": LotteryPayoutStatus.RECONCILIATION_REQUIRED},
                },
                {
                    "$set": {
                        "payout_status": LotteryPayoutStatus.UNRESOLVED,
                        "send_error": str(e)[:500],
                    }
                },
            )
            error_count += 1

        logger.info(f"Sent NFT: {info}")

        res.append(info)

    return {"sent_count": sent_count, "error_count": error_count, "results": res}
