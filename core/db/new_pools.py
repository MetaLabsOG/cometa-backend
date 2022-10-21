from dataclasses import dataclass

from dataclasses_json import dataclass_json

from core.db.db_manager import DbManager
from env import settings


@dataclass_json
@dataclass
class NewPoolInfo:
    id: int
    name: str
    type: str


new_pools = DbManager[NewPoolInfo](settings.db_name, 'new_pools', 'id', NewPoolInfo)
