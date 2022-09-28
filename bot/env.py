from datetime import timedelta
from functools import cached_property

from pydantic import BaseSettings

# TODO: compute for each pool/user
BEST_COMPOUNDING_DELAY = timedelta(minutes=5)

MONITOR_LOG_DELAY = timedelta(seconds=10)
AIRTABLE_UPDATE_DELAY_SECONDS = 30

FEEDBACK_COMMAND = 'feedback'
SUPPORT_COMMAND = 'support'
MESSAGE_ALL_COMMAND = 'message_all'


class Settings(BaseSettings):
    telegram_api_token: str
    discord_api_token: str

    mongodb_host: str
    mongodb_port: int

    airtable_api_key: str
    airtable_base_id: str

    feedback_chat_id: int
    support_chat_id: int

    remind_again_delay_minutes: int

    logs_dir: str

    class Config:
        env_file = 'bot/.env'
        arbitrary_types_allowed = True

    @property
    def remind_again_delay(self):
        return timedelta(minutes=self.remind_again_delay_minutes)


settings = Settings()
