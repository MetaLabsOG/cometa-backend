from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict

from dataclasses_json import dataclass_json

from bot.env import bot_settings
from core.db.model import UserPool


@dataclass_json
@dataclass
class CometaUser:
    algo_address: str
    # discord_id: int
    telegram_id: int
    last_reminded: int = 0
    pools: Dict[int, UserPool] = field(default_factory=dict)

    @property
    def no_remind_for(self) -> timedelta:
        remind_time = datetime.utcfromtimestamp(self.last_reminded)
        return datetime.utcnow() - remind_time

    def should_remind(self) -> bool:
        return self.no_remind_for > bot_settings.remind_again_delay

    def is_admin(self) -> bool:
        return self.telegram_id in bot_settings.telegram_admin_ids
