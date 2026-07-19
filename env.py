import logging
import os
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    algo_network: str
    algo_mnemonic: str
    rekeyed_mnemonic: Optional[str] = None

    algod_address: str
    algod_token: str
    algo_indexer_address: str

    server_port: int
    workers_num: int
    api_password: str
    migrate: bool = False

    mongodb_host: str
    mongodb_port: int
    mongodb_username: Optional[str] = None
    mongodb_password: Optional[str] = None
    new_db_name: str = "cometa-updated"

    logging_level: str = "INFO"
    logging_format: str = "[%(asctime)s][%(levelname)s][%(filename)s] %(message)s"
    logging_date_format: str = "%I:%M:%S"

    return_all_user_pools: bool = False
    # List of pool IDs that should always be returned
    always_return_pool_ids: list[int] = [
        1705298492,
        1713659453,
        1846754940,
        1911323813,
        1911383471,
        3470204961,
        3470209137,
    ]
    return_all_cometa_pools_to_addresses: list[str] = []

    # Special addresses that should receive all pools
    special_addresses: list[str] = ["DLO6VI4XJJWZOYUHSEKP3MVQZXGEOKDJUTTL5NJIS7UMXAPETOYLX3KNVE", "native.algo"]

    # Beneficiary address for contract verification
    beneficiary_address: str = "METAFG5UBD74CKQFIIABWMMQXR45J7BAP3KV6BVR3V7LDPNAEKNEVLMBRE"

    # Uvicorn log level
    uvicorn_log_level: str = "info"

    background_user_pools_update: bool = False
    background_pools_update: bool = False
    background_asset_prices_update: bool = True  # Enable background update of asset prices
    # Legacy LP pricing uses raw pool-account balances, which can include
    # donations or protocol excess. Keep it off until each DEX has a verified
    # economic-reserve adapter.
    background_lp_prices_update: bool = False
    asset_price_update_batch_size: int = Field(default=10, gt=0)
    asset_price_api_call_delay: float = Field(default=1, ge=0)
    asset_price_batch_delay: float = Field(default=2.0, ge=0)

    sync_new_pools: bool = True
    sync_liquidity_pools: bool = False
    # Legacy stake projection does not yet validate complete application groups.
    # Keep it fail-closed until the authoritative event classifier lands.
    sync_staking_pools: bool = False
    update_contract_caches: bool = True
    update_contracts_chunk_size: int = Field(default=10, ge=1, le=100)

    telegram_bot_api_token: str
    telegram_channel_id: int
    discord_notify_webhook_url: Optional[str] = None

    block_time: float = 2.7
    old_pool_end_date_days_ago: int = 30
    sync_lag_max_rounds: int = 1000  # 1 hour
    sync_behind_seconds_threshold: int = 60
    sync_round_max_attempts: int = Field(default=5, ge=1, le=100)
    sync_retry_max_seconds: float = Field(default=30, gt=0, le=300)

    reset_and_resync_pool_states: bool = False

    contracts_cache_ttl: int = 120
    algo_price_ttl: int = 3
    asset_prices_ttl: int = Field(default=120, gt=0)  # 2 minutes.
    asset_prices_max_stale: int = Field(default=3600, gt=0)
    asset_prices_update_interval: int = 60  # Run the background update every 60 seconds
    lp_prices_update_interval: int = 300  # LP pricing via algod every 5 minutes
    lp_token_prices_ttl: int = 30
    total_tvl_ttl: int = 30

    lp_state_ttl_rounds: int = 10  # 30s

    farm_creation_fee: int
    farm_flat_algo_creation_fee: int

    # Accepted temporarily so existing deployments can roll forward before
    # removing obsolete integration keys from their .env files. These values
    # are intentionally unused.
    enable_js: bool = False
    reach_no_warn: bool = False
    reach_connector_mode: str = "ALGO"
    sync_humble_pools: int = 0
    redis_host: str = ""
    redis_port: int = 6379

    asset_default_logo_svg_url: str = (
        "https://app.cometa.farm/static/media/tokenPlaceholder.b822bbf7d312b67292cf97f3d22194ed.svg"
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def validate_price_freshness_windows(self) -> "Settings":
        if self.asset_prices_max_stale < self.asset_prices_ttl:
            raise ValueError("asset_prices_max_stale must be at least asset_prices_ttl")
        return self

    def is_mainnet(self):
        return self.algo_network == "mainnet"

    @property
    def db_name(self):
        return self.algo_network.upper()


settings = Settings()

DIR_PATH = os.path.dirname(os.path.realpath(__file__))

logger.info("Algo network: %s", settings.algo_network)
logger.info("Mongo endpoint: %s:%s", settings.mongodb_host, settings.mongodb_port)
logger.info("Always-return pool IDs: %s", settings.always_return_pool_ids)
logger.info("Return-all Cometa pool addresses: %s", settings.return_all_cometa_pools_to_addresses)
