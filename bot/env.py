from datetime import timedelta

from pydantic_settings import BaseSettings, SettingsConfigDict

FEEDBACK_COMMAND = "feedback"
SUPPORT_COMMAND = "support"
MESSAGE_ALL_COMMAND = "message_all"


class Settings(BaseSettings):
    telegram_api_token: str
    discord_api_token: str

    notify_users: bool = False

    mongodb_host: str
    mongodb_port: int

    airtable_api_key: str
    airtable_base_id: str

    feedback_chat_id: int
    support_chat_id: int

    remind_again_delay_minutes: int
    user_pools_cache_ttl_seconds: int = 300

    logs_dir: str
    logging_level: str = "INFO"

    telegram_admin_ids: list[int]

    db_name: str = "COMETA_BOT"

    model_config = SettingsConfigDict(env_file="bot/.env", env_file_encoding="utf-8")

    @property
    def remind_again_delay(self):
        return timedelta(minutes=self.remind_again_delay_minutes)


bot_settings = Settings()
