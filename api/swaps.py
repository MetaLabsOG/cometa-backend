from dataclasses import dataclass

from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class SwapInfo:
    txids: list[str]
    wallet: str
    asset1_id: int
    asset2_id: int
    asset1_amount: int | float
    asset2_amount: int | float
