from dataclasses import dataclass

from dataclasses_json import dataclass_json

from core.db.db_manager import DbManager


@dataclass_json
@dataclass
class SwapInfo:
    txid: str
    wallet: str
    asset1_id: int
    asset2_id: int
    asset1_amount: int
    asset2_amount: int


swaps = DbManager('swaps', 'txid', SwapInfo)


def get_swap_by_id(txid: str) -> SwapInfo:
    return swaps.get_by_primary_key(txid)


def validate_swap(swap: SwapInfo) -> None:
    # TODO: check algoindexer for swap OR THROW
    pass


def record_swap(swap: SwapInfo) -> SwapInfo:
    validate_swap(swap)
    return swaps.create(swap)
