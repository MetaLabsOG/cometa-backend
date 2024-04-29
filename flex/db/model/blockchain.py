from abc import ABC
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
    id: str
    pool_id: int
    pool_address: str
    user_address: str
    asa_id: int
    delta_amount_micros: int
    confirmed_round: int

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def to_info(self) -> TxInfo:
        return TxInfo(id=self.id, confirmed_round=self.confirmed_round)


@dataclass_json
@dataclass
class LpTokenInfo:
    id: int
    asset1_id: int
    asset2_id: int
    dex_provider: str
    address: str
    pool_id: int


@dataclass_json
@dataclass
class LpToken(BaseEntity['LpToken']):
    id: int
    asset1_id: int
    asset2_id: int   # asset1_id > asset2_id
    dex_provider: str
    address: str
    pool_id: int

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def to_info(self) -> LpTokenInfo:
        return LpTokenInfo(
            id=self.id,
            asset1_id=self.asset1_id,
            asset2_id=self.asset2_id,
            dex_provider=self.dex_provider,
            address=self.address,
            pool_id=self.pool_id
        )


class AssetBase(ABC):
    id: int
    name: str
    decimals: int
    unit_name: str

    @cached_property
    def amount_multiplier(self) -> int:
        return 10 ** self.decimals

    def amount_to_micros(self, amount: float) -> int:
        return int(amount * self.amount_multiplier)

    def micros_to_amount(self, micros: int) -> float:
        return micros / self.amount_multiplier


@dataclass_json
@dataclass
class AssetInfo(AssetBase):
    name: str
    decimals: int
    unit_name: str
    id: int


@dataclass_json
@dataclass
class AssetDetails(AssetBase):
    id: int
    name: str
    unit_name: str
    decimals: int
    creator: str
    reserve: str
    total_supply: float
    logo_url: str | None = None


@dataclass_json
@dataclass
class Asset(BaseEntity['Asset'], AssetBase):
    id: int
    name: str
    decimals: int
    unit_name: str
    creator: str
    reserve: str
    total_supply: float

    logo_url: str | None = None

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    @cached_property
    def total_supply_micros(self) -> int:
        return self.amount_to_micros(self.total_supply)

    def to_info(self) -> AssetInfo:
        return AssetInfo(
            name=self.name,
            decimals=self.decimals,
            unit_name=self.unit_name,
            id=self.id
        )

    def to_details(self) -> AssetDetails:
        return AssetDetails(
            id=self.id,
            name=self.name,
            unit_name=self.unit_name,
            decimals=self.decimals,
            creator=self.creator,
            reserve=self.reserve,
            logo_url=self.logo_url,
            total_supply=self.total_supply
        )


@dataclass_json
@dataclass
class SyncState(BaseEntity['SyncState']):
    id: str = field(default_factory=get_uuid)
    last_round: int | None = None

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def rounds_since_updated(self, current_round: int) -> int | None:
        return current_round - self.last_round if self.last_round else None


@dataclass_json
@dataclass
class SyncBlock(BaseEntity['SyncBlock']):
    round: int
    timestamp: int

    # TODO: remove - migrate
    pool_tx_ids: list[str] | None = None

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)
