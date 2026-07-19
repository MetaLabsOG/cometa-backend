PYTHON_LINT_PATHS := \
	api/background.py api/nft_lottery.py api/wallet.py app.py blockchain/indexer.py bot/log.py env.py telegram_bot.py \
	core/circuit_breaker.py core/cometa.py core/decorators.py core/util.py \
	flex/__init__.py flex/api.py flex/application flex/blockchain/asset_transfers.py \
	flex/blockchain/contract_state.py flex/blockchain/info.py flex/data/asset_prices.py \
	flex/data/lp_prices.py flex/data/lp_states.py flex/data/pool_state.py \
	flex/data/tinyman_lps.py flex/data/transactions.py \
	flex/db/asset_transfer_intents.py flex/db/bson.py flex/db/classes/base_entity.py \
	flex/db/classes/bson_uint64.py flex/db/classes/collection_manager.py \
	flex/db/indexes.py flex/db/lp_projection.py \
	flex/db/sync_coordinator.py flex/db/model/airdrop.py flex/db/model/blockchain.py flex/db/model/liquidity_pools.py \
	flex/db/model/pools.py flex/db/model/priced.py flex/db/model/transfers.py flex/domain flex/providers/pact.py \
	flex/providers/price_router.py \
	flex/providers/vestige.py flex/sync_pools.py flex/sync_state.py \
	flex/migrations/fix_dex_providers.py \
	flex/tools/airdrop.py scripts/verify_algorand_credentials.py tests

PYTHON_MODERN_PATHS := \
	api/background.py api/nft_lottery.py api/wallet.py core/circuit_breaker.py flex/application \
	flex/blockchain/asset_transfers.py \
	flex/blockchain/contract_state.py flex/data/asset_prices.py flex/data/lp_prices.py \
	flex/db/asset_transfer_intents.py flex/db/bson.py flex/db/classes/bson_uint64.py \
	flex/db/lp_projection.py flex/db/sync_coordinator.py \
	flex/db/model/airdrop.py flex/db/model/priced.py flex/db/model/transfers.py \
	flex/domain flex/providers/pact.py flex/providers/price_router.py tests/unit tests/integration

PYTHON_FORMAT_PATHS := \
	api/background.py api/nft_lottery.py api/wallet.py app.py blockchain/indexer.py bot/log.py \
	core/circuit_breaker.py core/cometa.py core/util.py \
	flex/api.py flex/application flex/blockchain/asset_transfers.py flex/blockchain/contract_state.py flex/blockchain/info.py \
	flex/data/asset_prices.py flex/data/lp_prices.py \
	flex/data/lp_states.py flex/data/pool_state.py flex/data/tinyman_lps.py \
	flex/data/transactions.py flex/db/asset_transfer_intents.py flex/db/bson.py flex/db/classes/base_entity.py \
	flex/db/classes/bson_uint64.py flex/db/classes/collection_manager.py flex/db/indexes.py flex/db/lp_projection.py \
	flex/db/sync_coordinator.py flex/db/model/airdrop.py flex/db/model/blockchain.py \
	flex/db/model/liquidity_pools.py flex/db/model/pools.py flex/db/model/priced.py flex/db/model/transfers.py \
	flex/domain flex/providers/pact.py flex/providers/price_router.py \
	flex/providers/vestige.py flex/sync_pools.py flex/sync_state.py telegram_bot.py \
	flex/migrations/fix_dex_providers.py \
	flex/tools/airdrop.py tests/conftest.py tests/unit tests/integration

.PHONY: sync run run-api lint format format-check typecheck test quality

sync:
	pipenv verify
	pipenv sync --dev --python 3.12

run:
	pipenv run python app.py

run-api:
	pipenv run uvicorn app:app --reload --port 8000

lint:
	pipenv run ruff check $(PYTHON_LINT_PATHS)
	pipenv run ruff check --select ASYNC,C4,DTZ,RUF,UP $(PYTHON_MODERN_PATHS)

format:
	pipenv run ruff format $(PYTHON_FORMAT_PATHS)

format-check:
	pipenv run ruff format --check $(PYTHON_FORMAT_PATHS)

typecheck:
	pipenv run mypy

test:
	pipenv run pytest tests \
		--cov=core.circuit_breaker \
		--cov=core.decorators \
		--cov=flex.application.asset_transfers \
		--cov=flex.db.asset_transfer_intents \
		--cov=flex.db.lp_projection \
		--cov=flex.db.sync_coordinator \
		--cov=flex.db.classes.collection_manager \
		--cov=flex.blockchain.contract_state \
		--cov=flex.domain.allocation \
		--cov=flex.domain.lp_projection \
		--cov=flex.domain.pricing \
		--cov=flex.domain.transactions \
		--cov=flex.providers.pact \
		--cov-report=term-missing \
		--cov-fail-under=75

quality: lint format-check typecheck test
