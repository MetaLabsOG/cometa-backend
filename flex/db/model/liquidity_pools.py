from dataclasses import dataclass, field
from datetime import datetime

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity


@dataclass_json
@dataclass
class LpState(BaseEntity['LpState']):
    token_id: int
    asset1_id: int
    asset2_id: int
    dex_provider: str
    address: str

    asset1_reserve_micros: int
    asset2_reserve_micros: int
    total_tokens_micros: int

    last_updated_round: int

    id: int
    swap_fee_apr: float | None = None

    updated: datetime = field(default_factory=datetime.now)
    created: datetime = field(default_factory=datetime.now)


@dataclass_json
@dataclass
class LpTransaction(BaseEntity['LpTransaction']):
    pool_address: int
    user_address: str
    asa_id: int
    delta_amount_micros: int
    confirmed_round: int

    id: str
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
