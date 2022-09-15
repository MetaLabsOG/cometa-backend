import time
from dataclasses import dataclass
from typing import List, Optional

from dataclasses_json import dataclass_json

from core import mongodb

contracts = mongodb.database.contract


@dataclass_json
@dataclass
class ContractInfo:
    type: str
    id: int
    version: str
    deployed_timestamp: float
    description: Optional[str] = None
    metadata: Optional[dict] = None


def add_contract(type: str, id: int, version: str, description: Optional[str], metadata: Optional[dict]) -> str:
    cur_time = time.time()
    contract = ContractInfo(type, id, version, cur_time, description, metadata)
    res = contracts.insert_one(contract.to_dict())
    return str(res.inserted_id)


def update_contract(id: int, description: Optional[str] = None, metadata: Optional[dict] = None) -> bool:
    upd_dict = {}
    if description is not None:
        upd_dict['description'] = description
    if metadata is not None:
        upd_dict['metadata'] = metadata
    
    if len(upd_dict) > 0:
        res = contracts.update_one({'id': id}, {'$set': upd_dict})
        return res.acknowledged
    else:
        return False


def get_contracts(args: dict) -> List[ContractInfo]:
    return list(map(ContractInfo.from_dict, contracts.find(args)))


def get_contracts_by_type(type: str) -> List[ContractInfo]:
    return get_contracts({'type': type})


def get_contract(contract_id: int) -> Optional[ContractInfo]:
    res = contracts.find_one({'id': contract_id})
    return ContractInfo.from_dict(res) if res else res


def remove_contract(contract_id: int) -> int:
    res = contracts.delete_many({'id': contract_id})
    return res.deleted_count


def remove_contracts(type: str) -> int:
    res = contracts.delete_many({'type': type})
    return res.deleted_count
