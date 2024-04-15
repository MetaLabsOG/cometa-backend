from dataclasses import dataclass, field
from datetime import datetime

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity
from flex.db.model.blockchain import TxInfo, AssetInfo
from flex.db.model.pools import PoolType
from flex.db.util import get_uuid


@dataclass_json
@dataclass
class PoolStateInfo:
    pool_id: int
    type: PoolType
    stake_token: AssetInfo
    address: str

    total_staked_micros: int
    total_staked: float
    staked_micros_by_address: dict[str, int] = field(default_factory=dict)
    last_tx: TxInfo | None = None


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
    def total_staked(self) -> float:
        return self.stake_token.micros_to_amount(self.total_staked_micros)

    def to_info(self) -> PoolStateInfo:
        return PoolStateInfo(
            pool_id=self.pool_id,
            type=self.type,
            stake_token=self.stake_token,
            address=self.address,
            staked_micros_by_address=self.staked_micros_by_address,
            total_staked_micros=self.total_staked_micros,
            total_staked=self.stake_token.micros_to_amount(self.total_staked_micros),
            last_tx=self.last_tx
        )


@dataclass_json
@dataclass
class UserPoolStateInfo:
    pool_id: int
    stake_token_id: int
    staked_amount_micros: int
    staked_amount: float
    last_tx: TxInfo | None = None


@dataclass_json
@dataclass
class UserStateInfo:
    address: str
    pool_by_address: dict[str, UserPoolStateInfo]
    last_tx: TxInfo | None = None


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
            staked_amount_micros=self.staked_amount_micros,
            staked_amount=self.staked_amount,
            last_tx=self.last_tx
        )


@dataclass_json
@dataclass
class UserState(BaseEntity['UserState']):
    address: str
    pool_by_address: dict[str, UserPoolState] = field(default_factory=dict)
    last_tx: TxInfo | None = None
    id: str = field(default_factory=get_uuid)
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def to_info(self) -> UserStateInfo:
        return UserStateInfo(
            address=self.address,
            pool_by_address={pool_address: pool_state.to_info() for pool_address, pool_state in self.pool_by_address.items()},
            last_tx=self.last_tx
        )
