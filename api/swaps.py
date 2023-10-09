from dataclasses import dataclass
from typing import Union

from dataclasses_json import dataclass_json

from core.db.db_manager import DbManager
from env import settings


@dataclass_json
@dataclass
class SwapInfo:
    txids: list[str]
    wallet: str
    asset1_id: int
    asset2_id: int
    asset1_amount: Union[int, float]
    asset2_amount: Union[int, float]


swaps = DbManager(settings.db_name, 'swaps', '_id', SwapInfo)


def validate_swap(swap: SwapInfo) -> None:
    # TODO: check algoindexer for swap OR THROW
    pass


def record_swap(swap: SwapInfo) -> SwapInfo:
    validate_swap(swap)
    return swaps.create(swap)
