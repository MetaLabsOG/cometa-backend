from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity
from flex.db.util import get_uuid


@dataclass_json
@dataclass
class TxInfo:
    id: str
    confirmed_round: int


@dataclass_json
@dataclass
class PoolTransaction(BaseEntity['PoolTransaction']):
    # TODO: remove one of the fields
    pool_id: int
    pool_address: str
    user_address: str
    asa_id: int
    delta_amount_micros: int
    confirmed_round: int

    id: str
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def to_info(self) -> TxInfo:
        return TxInfo(id=self.id, confirmed_round=self.confirmed_round)


@dataclass_json
@dataclass
class LpToken(BaseEntity['LpToken']):
    asset1_id: int
    asset2_id: int
    dex_provider: str
    address: str
    pool_id: int

    id: int
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)


@dataclass_json
@dataclass
class AssetInfo:
    name: str
    decimals: int
    unit_name: str
    id: int

    @cached_property
    def amount_multiplier(self) -> int:
        return 10 ** self.decimals

    def amount_to_micros(self, amount: float) -> int:
        return int(amount * self.amount_multiplier)

    def micros_to_amount(self, micros: int) -> float:
        return micros / self.amount_multiplier


@dataclass_json
@dataclass
class Asset(BaseEntity['Asset']):
    name: str
    decimals: int
    unit_name: str
    creator_address: str
    total_supply: float
    id: int

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    @cached_property
    def total_supply_micros(self) -> int:
        return self.amount_to_micros(self.total_supply)

    @cached_property
    def amount_multiplier(self) -> int:
        return 10 ** self.decimals

    def amount_to_micros(self, amount: float) -> int:
        return int(amount * self.amount_multiplier)

    def micros_to_amount(self, micros: int) -> float:
        return micros / self.amount_multiplier

    def to_info(self) -> AssetInfo:
        return AssetInfo(
            name=self.name,
            decimals=self.decimals,
            unit_name=self.unit_name,
            id=self.id
        )


@dataclass_json
@dataclass
class SyncState(BaseEntity['SyncState']):
    last_round: int | None = None

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)


@dataclass_json
@dataclass
class SyncBlock(BaseEntity['SyncBlock']):
    round: int
    timestamp: int
    pool_tx_ids: list[str] = field(default_factory=list)

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
