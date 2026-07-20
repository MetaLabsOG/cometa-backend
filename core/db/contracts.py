from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from cachetools import TTLCache, cached
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from core.db.model import ContractInfo
from core.db.mongodb import get_db_collection
from env import settings

collection = get_db_collection(settings.db_name, "contract")

_contracts_cache = TTLCache(maxsize=16, ttl=settings.contracts_cache_ttl)


class ContractIdentityConflictError(ValueError):
    """A contract ID is already bound to another declared identity."""


@dataclass(frozen=True)
class ContractWriteResult:
    contract: ContractInfo
    created: bool


def _contract_identity(contract: ContractInfo) -> tuple[str, str]:
    contract_type = getattr(contract.type, "value", contract.type)
    return str(contract_type), contract.version.removeprefix("^")


def ensure_contract_id_index(
    *,
    target_collection: Collection | None = None,
) -> None:
    """Fail closed on duplicate contract IDs, then enforce uniqueness."""

    target = target_collection if target_collection is not None else collection
    duplicate = next(
        iter(
            target.aggregate(
                [
                    {"$group": {"_id": "$id", "count": {"$sum": 1}}},
                    {"$match": {"count": {"$gt": 1}}},
                    {"$limit": 1},
                ],
                allowDiskUse=True,
            )
        ),
        None,
    )
    if duplicate is not None:
        raise RuntimeError(
            f"contract contains duplicate immutable ID {duplicate['_id']!r}; reconcile it before registration"
        )
    target.create_index("id", unique=True, name="contract_id_unique")


def get_or_create_contract(
    contract: ContractInfo,
    *,
    target_collection: Collection | None = None,
) -> ContractWriteResult:
    """Persist one canonical contract and recover safely from concurrent retries."""

    target = target_collection if target_collection is not None else collection
    try:
        result = target.update_one(
            {"id": contract.id},
            {"$setOnInsert": contract.to_dict()},
            upsert=True,
        )
        created = result.upserted_id is not None
    except DuplicateKeyError:
        # A competing upsert won after this request evaluated its selector.
        created = False

    stored_document = target.find_one({"id": contract.id})
    if stored_document is None:
        raise RuntimeError(f"contract {contract.id} disappeared after atomic upsert")

    stored = ContractInfo.from_dict(stored_document)
    if _contract_identity(stored) != _contract_identity(contract):
        raise ContractIdentityConflictError(
            f"contract {contract.id} is already registered with a different type or version"
        )
    return ContractWriteResult(contract=stored, created=created)


def update_contract(id: int, description: Optional[str] = None, metadata: Optional[dict] = None) -> bool:
    upd_dict = {}
    if description is not None:
        upd_dict["description"] = description
    if metadata is not None:
        upd_dict["metadata"] = metadata

    if len(upd_dict) > 0:
        res = collection.update_one({"id": id}, {"$set": upd_dict})
        return res.acknowledged
    else:
        return False


def update_contract_with(contract_id: int, **kwargs) -> bool:
    if len(kwargs) > 0:
        res = collection.update_one({"id": contract_id}, {"$set": kwargs})
        return res.acknowledged
    else:
        return False


def get_contracts(args: dict) -> list[ContractInfo]:
    return list(map(ContractInfo.from_dict, collection.find(args)))


def get_all_pool_contracts() -> list[ContractInfo]:
    return get_contracts({"type": {"$in": ["farm", "distribution"]}})


@cached(cache=_contracts_cache)
def get_contracts_by_type(type: Optional[str]) -> list[ContractInfo]:
    if type is None:
        return get_contracts({"type": {"$in": ["distribution", "farm"]}})
    return get_contracts({"type": type})


def get_active_contracts(type: str) -> list[ContractInfo]:
    """Contracts that haven't ended (or have no end_date)."""
    cutoff_ts = (datetime.now() - timedelta(days=settings.old_pool_end_date_days_ago)).timestamp()
    all_contracts = get_contracts_by_type(type)
    result = []
    for c in all_contracts:
        if c.end_date is None or c.id in settings.always_return_pool_ids:
            result.append(c)
            continue
        end_ts = c.end_date.timestamp() if isinstance(c.end_date, datetime) else float(c.end_date)
        if end_ts > cutoff_ts:
            result.append(c)
    return result


def invalidate_contracts_cache():
    _contracts_cache.clear()


def get_contract(contract_id: int) -> Optional[ContractInfo]:
    res = collection.find_one({"id": contract_id})
    return ContractInfo.from_dict(res) if res else res


def remove_contract(contract_id: int) -> int:
    res = collection.delete_many({"id": contract_id})
    return res.deleted_count


def remove_contracts(type: str) -> int:
    res = collection.delete_many({"type": type})
    return res.deleted_count
