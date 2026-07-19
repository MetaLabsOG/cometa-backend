"""Persistence model for immutable airdrop batch manifests."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from dataclasses_json import dataclass_json

from flex.db.classes.base_entity import BaseEntity


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass_json
@dataclass
class AirdropManifest(BaseEntity["AirdropManifest"]):
    id: str
    asset_id: str
    total_amount_micros: str
    recipient_count: int
    manifest_hash: str
    status: str = "prepared"

    created: datetime = field(default_factory=_utc_now)
    updated: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.asset_id = str(self.asset_id)
        self.total_amount_micros = str(self.total_amount_micros)

    @property
    def asset_id_int(self) -> int:
        return int(self.asset_id)
