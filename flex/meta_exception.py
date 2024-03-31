from dataclasses import dataclass
from enum import Enum

from dataclasses_json import dataclass_json


class ErrorCode(str, Enum):
    BATTLE_ALREADY_STARTED = 'BATTLE_ALREADY_STARTED'
    ALREADY_IN_A_BATTLE = 'ALREADY_IN_A_BATTLE'
    NOT_IN_A_BATTLE = 'NOT_IN_A_BATTLE'

    TX_NOT_FOUND = 'TX_NOT_FOUND'
    INVALID_TX = 'INVALID_TX'
    TX_ALREADY_RECORDED = 'TX_ALREADY_RECORDED'

    BET_AMOUNT_TOO_BIG = 'BET_AMOUNT_TOO_BIG'

    REWARD_ALREADY_PAID = 'REWARD_ALREADY_PAID'

    UNKNOWN = 'UNKNOWN'


@dataclass_json
@dataclass
class MetaError(Exception):
    code: ErrorCode = ErrorCode.UNKNOWN
    message: str | None = None
