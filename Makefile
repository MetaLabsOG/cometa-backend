PYTHON_MODERN_PATHS := \
	api/background.py api/nft_lottery.py api/wallet.py core/circuit_breaker.py flex/application \
	flex/blockchain/asset_transfers.py \
	flex/blockchain/contract_state.py flex/data/asset_prices.py flex/data/lp_registry.py flex/data/lp_tokens.py \
	flex/db/asset_transfer_intents.py flex/db/bson.py flex/db/classes/bson_uint64.py \
	flex/db/lp_projection.py flex/db/sync_coordinator.py \
	flex/db/model/airdrop.py flex/db/model/priced.py flex/db/model/transfers.py \
	flex/domain flex/providers/pact.py flex/providers/price_router.py tests/unit tests/integration

.PHONY: sync run run-api lint format format-check typecheck test quality

sync:
	pipenv verify
	pipenv sync --dev --python 3.12

run:
	pipenv run python app.py

run-api:
	pipenv run uvicorn app:app --reload --port 8000

lint:
	pipenv run ruff check .
	pipenv run ruff check --select ASYNC,C4,DTZ,RUF,UP $(PYTHON_MODERN_PATHS)

format:
	pipenv run ruff format .

format-check:
	pipenv run ruff format --check .

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
