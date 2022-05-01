import time
from dataclasses import dataclass
from typing import List, Optional

from dataclasses_json import dataclass_json
from pymongo import MongoClient

from env import settings

client = MongoClient(port=settings.mongodb_port)
db = client[settings.algo_network].contract


@dataclass_json
@dataclass
class ContractInfo:
    type: str
    id: int
    version: str
    deployed_timestamp: float  # TODO: make datetime (have serialization problem with that right now)
    description: Optional[str] = None


def add_contract(type: str, id: int, version: str, description: Optional[str]) -> str:
    cur_time = time.time()
    contract = ContractInfo(type, id, version, cur_time, description)
    res = db.insert_one(contract.to_dict())
    return str(res.inserted_id)


def get_contracts(type: str) -> List[ContractInfo]:
    return list(map(ContractInfo.from_dict, db.find({'type': type})))


def get_contract(contract_id: int) -> Optional[ContractInfo]:
    res = db.find_one({'id': contract_id})
    return ContractInfo.from_dict(res) if res else res


def remove_contract(contract_id: int) -> int:
    res = db.delete_many({'id': contract_id})
    return res.deleted_count


def remove_contracts(type: str) -> int:
    res = db.delete_many({'type': type})
    return res.deleted_count


if __name__ == '__main__':
    pass
    # contract = ContractInfo('fomo', 12369, '1.0', datetime.timestamp())
    # print(add_contract(contract))
    # print(get_contract(12369))
    # print(get_contract(123))
    # print(get_contracts('fomo'))
    # print(list(get_contracts('fomo')))

