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

    asset1_reserve: float
    asset2_reserve: float
    issued_tokens: float

    token_price_algo: float
    token_price_usd: float

    last_updated_round: int
    swap_fee_apr: float | None = None
    seconds_since_update: int | None = None


@dataclass_json
@dataclass
class LpState(BaseEntity['LpState']):
    id: int
    token_id: int
    asset1_id: int  # asset1_id > asset2_id
    asset2_id: int
    dex_provider: str
    address: str

    last_updated_round: int
    # TODO: could not fit into MongoDB ??? (64 bits)
    asset1_reserve_micros: int
    asset2_reserve_micros: int
    total_tokens_micros: int  # TODO: change name to issued_tokens_micros

    asset1_reserve: float
    asset2_reserve: float
    total_tokens: float
    token_price_algo: float

    is_algo_pool: bool = False

    swap_fee_apr: float | None = None
    updated: datetime = field(default_factory=datetime.now)
    created: datetime = field(default_factory=datetime.now)

    @classmethod
    def primary_key_name(cls) -> str:
        return 'token_id'

    def to_info(self, algo_price_usd: float, current_time: datetime | None = None) -> LpStateInfo:
        current_time = current_time or datetime.now()
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
            asset1_reserve=self.asset1_reserve,
            asset2_reserve=self.asset2_reserve,
            issued_tokens=self.total_tokens,
            token_price_algo=self.token_price_algo,
            token_price_usd=self.token_price_algo * algo_price_usd,
            last_updated_round=self.last_updated_round,
            swap_fee_apr=self.swap_fee_apr,
            seconds_since_update=int((current_time - self.updated).total_seconds())
        )


@dataclass_json
@dataclass
class LpTransaction(BaseEntity['LpTransaction']):
    id: str
    pool_address: int
    user_address: str
    asa_id: int
    delta_amount_micros: int
    confirmed_round: int

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
