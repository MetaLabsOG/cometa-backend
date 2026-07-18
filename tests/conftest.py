"""Hermetic test settings loaded before application modules are imported."""

import os

from algosdk import account, mnemonic

_private_key, _ = account.generate_account()
_test_mnemonic = mnemonic.from_private_key(_private_key)

_TEST_ENV = {
    "ALGO_NETWORK": "testnet",
    "ALGO_MNEMONIC": _test_mnemonic,
    "ALGOD_ADDRESS": "http://127.0.0.1:4001",
    "ALGOD_TOKEN": "test-token",
    "ALGO_INDEXER_ADDRESS": "http://127.0.0.1:8980",
    "SERVER_PORT": "8000",
    "WORKERS_NUM": "1",
    "API_PASSWORD": "test-password",
    "MONGODB_HOST": "127.0.0.1",
    "MONGODB_PORT": "27017",
    "REDIS_HOST": "127.0.0.1",
    "REDIS_PORT": "6379",
    "TELEGRAM_BOT_API_TOKEN": "123456:test-token",
    "TELEGRAM_CHANNEL_ID": "0",
    "TELEGRAM_API_TOKEN": "123456:test-token",
    "DISCORD_API_TOKEN": "test-token",
    "AIRTABLE_API_KEY": "test-token",
    "AIRTABLE_BASE_ID": "test-base",
    "FEEDBACK_CHAT_ID": "0",
    "SUPPORT_CHAT_ID": "0",
    "REMIND_AGAIN_DELAY_MINUTES": "60",
    "USER_POOLS_CACHE_TTL_SECONDS": "300",
    "LOGS_DIR": "/tmp",
    "TELEGRAM_ADMIN_IDS": "[]",
    "FARM_CREATION_FEE": "0",
    "FARM_FLAT_ALGO_CREATION_FEE": "0",
    "SYNC_NEW_POOLS": "false",
    "UPDATE_CONTRACT_CACHES": "false",
    "BACKGROUND_ASSET_PRICES_UPDATE": "false",
}

for _name, _value in _TEST_ENV.items():
    os.environ[_name] = _value
