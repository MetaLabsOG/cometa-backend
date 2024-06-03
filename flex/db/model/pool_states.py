from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity
from flex.db.model.blockchain import TxInfo, AssetInfo
from flex.db.model.pools import PoolType
from flex.db.util import get_uuid
from flex.util import format_timedelta


@dataclass_json
@dataclass
class PoolStateInfo:
    pool_id: int
    type: PoolType
    token_id: int
    token_name: str
    address: str

    total_staked_micros: int
    total_staked: float
    since_update: timedelta
    updated_round: int | None = None

    staked_micros_by_address: dict[str, int] = field(default_factory=dict)


@dataclass_json
@dataclass
class PoolState(BaseEntity['PoolState']):
    pool_id: int
    type: PoolType
    stake_token: AssetInfo
    address: str

    staked_micros_by_address: dict[str, int] = field(default_factory=dict)
    total_staked_micros: int = 0
    last_tx: TxInfo | None = None

    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    @property
    def last_tx_id(self) -> str | None:
        if self.last_tx is None:
            return None
        return self.last_tx.id

    @property
    def last_tx_round(self) -> int | None:
        if self.last_tx is None:
            return None
        return self.last_tx.confirmed_round

    @property
    def total_staked(self) -> float:
        return self.stake_token.micros_to_amount(self.total_staked_micros)

    def to_info(self, now: datetime| None = None) -> PoolStateInfo:
        now = now or datetime.now()
        return PoolStateInfo(
            pool_id=self.pool_id,
            type=self.type,
            token_id=self.stake_token.id,
            token_name=self.stake_token.name,
            address=self.address,
            total_staked_micros=self.total_staked_micros,
            total_staked=self.total_staked,
            updated_round=self.last_tx_round,
            since_update=now - self.updated,
            staked_micros_by_address=self.staked_micros_by_address
        )


@dataclass_json
@dataclass
class UserPoolStateInfo:
    pool_id: int
    stake_token_id: int
    stake_token_name: str
    staked_amount_micros: int
    staked_amount: float
    updated_round: int | None = None


@dataclass_json
@dataclass
class UserPoolState:
    pool_id: int
    stake_token: AssetInfo
    staked_amount_micros: int = 0
    last_tx: TxInfo | None = None

    @property
    def staked_amount(self):
        return self.stake_token.micros_to_amount(self.staked_amount_micros)

    def to_info(self) -> UserPoolStateInfo:
        return UserPoolStateInfo(
            pool_id=self.pool_id,
            stake_token_id=self.stake_token.id,
            stake_token_name=self.stake_token.name,
            staked_amount_micros=self.staked_amount_micros,
            staked_amount=self.staked_amount,
            updated_round=self.last_tx.confirmed_round if self.last_tx else None,
        )


@dataclass_json
@dataclass
class UserStateInfo:
    address: str
    pools: dict[int, UserPoolStateInfo] = field(default_factory=dict)
    updated_round: int | None = None
    since_update: str | None = None


@dataclass_json
@dataclass
class UserState(BaseEntity['UserState']):
    address: str
    pool_by_address: dict[str, UserPoolState] = field(default_factory=dict)
    last_tx: TxInfo | None = None
    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def to_info(self, now: datetime | None = None) -> UserStateInfo:
        now = now or datetime.now()
        return UserStateInfo(
            address=self.address,
            pools={pool.pool_id: pool.to_info() for pool in self.pool_by_address.values()},
            updated_round=self.last_tx.confirmed_round if self.last_tx else None,
            since_update=format_timedelta(now - self.updated)
        )
