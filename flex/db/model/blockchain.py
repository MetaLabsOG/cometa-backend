from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from functools import cached_property
from typing import ClassVar

from dataclasses_json import config, dataclass_json

from flex.db.bson import (
    decode_bson_uint64,
    decode_optional_bson_uint64,
    encode_bson_integer,
    encode_optional_bson_uint64,
)
from flex.db.classes.base_entity import BaseEntity
from flex.db.classes.bson_uint64 import BsonUint64StorageMixin

UINT64_MAX = (1 << 64) - 1


class _MissingTotalSupply(int):
    """Typed sentinel that cannot be confused with an explicit integer."""


_MISSING_TOTAL_SUPPLY = _MissingTotalSupply(-1)


def _decode_total_supply(value: object) -> int:
    if isinstance(value, _MissingTotalSupply):
        return value
    return int(value)


def _validate_uint64(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if not 0 <= value <= UINT64_MAX:
        raise ValueError(f"{field_name} must be between 0 and {UINT64_MAX}")
    return value


@dataclass_json
@dataclass
class TxInfo:
    id: str
    confirmed_round: int


@dataclass_json
@dataclass
class PoolTransaction(BaseEntity["PoolTransaction"]):
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
class LpToken(
    BsonUint64StorageMixin,
    BaseEntity["LpToken"],
):
    BSON_UINT64_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "id",
            "asset1_id",
            "asset2_id",
            "pool_id",
        }
    )

    id: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    asset1_id: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    asset2_id: int = field(  # asset1_id > asset2_id
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    dex_provider: str
    address: str
    pool_id: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def to_info(self) -> LpTokenInfo:
        return LpTokenInfo(
            id=self.id,
            asset1_id=self.asset1_id,
            asset2_id=self.asset2_id,
            dex_provider=self.dex_provider,
            address=self.address,
            pool_id=self.pool_id,
        )


class AssetBase(ABC):
    id: int
    name: str
    decimals: int
    unit_name: str

    @cached_property
    def amount_multiplier(self) -> int:
        return 10**self.decimals

    def amount_to_micros(self, amount: Decimal | float | int | str) -> int:
        """Convert a display amount without introducing binary-float error."""
        return int(Decimal(str(amount)) * self.amount_multiplier)

    def micros_to_decimal(self, micros: int) -> Decimal:
        """Return an exact display-unit value for an on-chain base-unit amount."""
        return Decimal(micros) / self.amount_multiplier

    def micros_to_amount(self, micros: int) -> float:
        """Compatibility conversion for API models that still expose floats."""
        return float(self.micros_to_decimal(micros))


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
    logo_url: str


@dataclass_json
@dataclass
class Asset(
    BsonUint64StorageMixin,
    BaseEntity["Asset"],
    AssetBase,
):
    BSON_UINT64_FIELDS: ClassVar[frozenset[str]] = frozenset({"id"})

    id: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    name: str
    decimals: int
    unit_name: str
    creator: str
    reserve: str
    total_supply: float

    logo_url: str | None = None
    # ASA amounts occupy the full uint64 range, which does not fit BSON int64.
    # Keep an int in memory and serialize it as a decimal string in MongoDB.
    total_supply_micros: int = field(
        default=_MISSING_TOTAL_SUPPLY,
        metadata=config(encoder=str, decoder=_decode_total_supply),
    )

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if isinstance(self.total_supply_micros, _MissingTotalSupply):
            # Documents written before the canonical field was introduced only
            # contain display units. This is necessarily best-effort because a
            # historical float may already have lost precision.
            self.total_supply_micros = self.amount_to_micros(self.total_supply)

        self.total_supply_micros = _validate_uint64(
            self.total_supply_micros,
            field_name="total_supply_micros",
        )
        # The persisted base-unit amount is authoritative. Keep the old float
        # field as a presentation-only compatibility value.
        self.total_supply = self.micros_to_amount(self.total_supply_micros)

    @property
    def total_supply_base_units(self) -> int:
        """Canonical on-chain supply; alias clarifies the historical name."""
        return self.total_supply_micros

    def to_info(self) -> AssetInfo:
        return AssetInfo(name=self.name, decimals=self.decimals, unit_name=self.unit_name, id=self.id)

    def to_details(self) -> AssetDetails:
        return AssetDetails(
            id=self.id,
            name=self.name,
            unit_name=self.unit_name,
            decimals=self.decimals,
            creator=self.creator,
            reserve=self.reserve,
            logo_url=self.logo_url,
            total_supply=self.total_supply,
        )


@dataclass_json
@dataclass
class SyncState(
    BsonUint64StorageMixin,
    BaseEntity["SyncState"],
):
    BSON_UINT64_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "last_round",
            "claimed_round",
        }
    )

    id: str = "main"
    last_round: int | None = field(
        default=None,
        metadata=config(
            encoder=encode_optional_bson_uint64,
            decoder=decode_optional_bson_uint64,
        ),
    )
    claimed_round: int | None = field(
        default=None,
        metadata=config(
            encoder=encode_optional_bson_uint64,
            decoder=decode_optional_bson_uint64,
        ),
    )
    lease_owner: str | None = None
    lease_until: datetime | None = None
    last_error: str | None = None

    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def rounds_since_updated(self, current_round: int) -> int | None:
        return current_round - self.last_round if self.last_round is not None else None


@dataclass_json
@dataclass
class SyncBlock(
    BsonUint64StorageMixin,
    BaseEntity["SyncBlock"],
):
    BSON_UINT64_FIELDS: ClassVar[frozenset[str]] = frozenset({"round"})

    round: int = field(
        metadata=config(
            encoder=encode_bson_integer,
            decoder=decode_bson_uint64,
        )
    )
    timestamp: int

    id: str | None = None
    created: datetime = field(default_factory=datetime.now)
    updated: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = f"round:{self.round}"
