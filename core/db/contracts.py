import time
from typing import Optional

from cachetools import cached, TTLCache

from core.db.model import ContractInfo
from core.db.mongodb import get_db_collection
from env import settings

collection = get_db_collection(settings.db_name, 'contract')

_contracts_cache = TTLCache(maxsize=16, ttl=settings.contracts_cache_ttl)


def add_contract(type: str, id: int, version: str, description: str, metadata: Optional[dict]) -> str:
    cur_time = time.time()
    contract = ContractInfo(type, id, version, cur_time, description, metadata)
    res = collection.insert_one(contract.to_dict())
    return str(res.inserted_id)


def insert_contract(contract: ContractInfo) -> str:
    res = collection.insert_one(contract.to_dict())
    return str(res.inserted_id)


def update_contract(id: int, description: Optional[str] = None, metadata: Optional[dict] = None) -> bool:
    upd_dict = {}
    if description is not None:
        upd_dict['description'] = description
    if metadata is not None:
        upd_dict['metadata'] = metadata
    
    if len(upd_dict) > 0:
        res = collection.update_one({'id': id}, {'$set': upd_dict})
        return res.acknowledged
    else:
        return False


def update_contract_with(contract_id: int, **kwargs) -> bool:
    if len(kwargs) > 0:
        res = collection.update_one({'id': contract_id}, {'$set': kwargs})
        return res.acknowledged
    else:
        return False


def get_contracts(args: dict) -> list[ContractInfo]:
    return list(map(ContractInfo.from_dict, collection.find(args)))


def get_all_pool_contracts() -> list[ContractInfo]:
    return get_contracts({'type': {'$in': ['farm', 'distribution']}})


@cached(cache=_contracts_cache)
def get_contracts_by_type(type: Optional[str]) -> list[ContractInfo]:
    if type is None:
        return get_contracts({'type': {'$in': ['distribution', 'farm']}})
    return get_contracts({'type': type})


def invalidate_contracts_cache():
    _contracts_cache.clear()


def get_contract(contract_id: int) -> Optional[ContractInfo]:
    res = collection.find_one({'id': contract_id})
    return ContractInfo.from_dict(res) if res else res


def remove_contract(contract_id: int) -> int:
    res = collection.delete_many({'id': contract_id})
    return res.deleted_count


def remove_contracts(type: str) -> int:
    res = collection.delete_many({'type': type})
    return res.deleted_count
