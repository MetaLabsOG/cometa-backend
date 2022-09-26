from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional

from dataclasses_json import dataclass_json

from bot.env import BEST_COMPOUNDING_DELAY, settings


class EventType(str, Enum):
    STAKE = 'STAKE'
    CLAIM = 'CLAIM'
    COMPOUND = 'COMPOUND'
    WITHDRAW = 'WITHDRAW'


@dataclass_json
@dataclass
class CometaEvent:
    _id: str
    type: str
    pool_name: str
    address: str
    timestamp: int
    lp_asa_id: int
    reward_token_id: Optional[int]
    amount: float


@dataclass_json
@dataclass
class PoolInfo:
    name: str
    last_interacted: int  # timestamp

    @property
    def no_interact_for(self) -> timedelta:
        interact_time = datetime.utcfromtimestamp(self.last_interacted)
        return datetime.utcnow() - interact_time

    def should_remind(self) -> bool:
        return self.no_interact_for > BEST_COMPOUNDING_DELAY


@dataclass_json
@dataclass
class CometaUser:
    algo_address: str
    # discord_id: int
    telegram_id: int
    last_reminded: int = 0
    pools: Dict[str, PoolInfo] = field(default_factory=dict)

    @property
    def no_remind_for(self) -> timedelta:
        remind_time = datetime.utcfromtimestamp(self.last_reminded)
        return datetime.utcnow() - remind_time

    def should_remind(self) -> bool:
        return self.no_remind_for > settings.remind_again_delay
