from dataclasses import dataclass, field
from datetime import datetime

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity


@dataclass_json
@dataclass
class LpStateInfo:
    id: int
    token_id: int
    asset1_id: int
    asset2_id: int
    dex_provider: str
    address: str

    asset1_reserve_micros: int
    asset2_reserve_micros: int
    issued_tokens_micros: int

    last_updated_round: int

    swap_fee_apr: float | None = None


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

    def to_info(self) -> LpStateInfo:
        return LpStateInfo(
            id=self.id,
            token_id=self.token_id,
            asset1_id=self.asset1_id,
            asset2_id=self.asset2_id,
            dex_provider=self.dex_provider,
            address=self.address,
            asset1_reserve_micros=self.asset1_reserve_micros,
            asset2_reserve_micros=self.asset2_reserve_micros,
            issued_tokens_micros=self.total_tokens_micros,
            last_updated_round=self.last_updated_round,
            swap_fee_apr=self.swap_fee_apr
        )


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
