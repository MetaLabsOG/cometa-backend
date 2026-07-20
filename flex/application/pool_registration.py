import logging
from datetime import UTC, datetime

from blockchain.node import get_current_round
from blockchain.util import date_from_block
from core.db.model import ContractInfo
from core.util import parse_bignum
from flex import db
from flex.blockchain.info import get_app_address
from flex.data.assets import get_asset_info
from flex.db.model.pools import CometaPool, FarmingPool, StakingPool

logger = logging.getLogger(__name__)


class PoolIdentityConflictError(ValueError):
    """A pool ID is already bound to incompatible immutable metadata."""


def _is_farming_contract(contract: ContractInfo) -> bool:
    return contract.type == "farm" and "dex" in (contract.metadata or {})


def ensure_pool_identity_slot(contract: ContractInfo) -> None:
    """Reject an ID already present in the opposite pool collection."""

    opposite = db.staking_pools if _is_farming_contract(contract) else db.farming_pools
    if opposite.exists(id=contract.id):
        raise PoolIdentityConflictError(f"pool {contract.id} is already registered as the opposite pool type")


def _pool_identity(pool: CometaPool) -> tuple[object, ...]:
    common = (
        type(pool),
        pool.id,
        pool.address,
        pool.stake_token.id,
        pool.reward_token.id,
        pool.reward_amount_micros,
        pool.algo_reward_amount_micros,
        pool.begin_block,
        pool.end_block,
        pool.lock_length_blocks,
    )
    if isinstance(pool, FarmingPool):
        return (
            *common,
            pool.first_token.id,
            pool.second_token.id,
            pool.dex_name,
        )
    return common


def _validate_persisted_pool(candidate: CometaPool, stored: CometaPool) -> CometaPool:
    if _pool_identity(candidate) != _pool_identity(stored):
        raise PoolIdentityConflictError(f"pool {candidate.id} has incompatible persisted identity fields")
    return stored


async def staking_pool_from_contract_info(contract_info: ContractInfo, distribution: bool = False) -> StakingPool:
    # Distribution contracts historically used the same token for stake and
    # reward; existing on-chain contracts retain that compatibility rule.
    if distribution:
        stake_token_id = contract_info.metadata.get("stake_token_id")
        if stake_token_id is None:
            stake_token_id = parse_bignum(contract_info.metadata["cache"]["initial"]["token"])
        stake_token_id = int(stake_token_id)

        reward_token_id = contract_info.metadata.get("reward_token_id")
        if reward_token_id is None:
            reward_token_id = parse_bignum(contract_info.metadata["cache"]["initial"]["token"])
        reward_token_id = int(reward_token_id)
    else:
        stake_token_id = contract_info.metadata.get("stake_token_id")
        if stake_token_id is None:
            stake_token_id = parse_bignum(contract_info.metadata["cache"]["initial"]["stakeToken"])
        stake_token_id = int(stake_token_id)

        reward_token_id = contract_info.metadata.get("reward_token_id")
        if reward_token_id is None:
            reward_token_id = parse_bignum(contract_info.metadata["cache"]["initial"]["rewardToken"])
        reward_token_id = int(reward_token_id)

    reward_amount_micros = parse_bignum(contract_info.metadata["cache"]["initial"]["totalRewardAmount"])
    algo_reward_amount_micros = parse_bignum(contract_info.metadata["cache"]["initial"]["totalAlgoRewardAmount"])

    begin_block = contract_info.metadata["begin_block"]
    end_block = contract_info.metadata["end_block"]
    begin_date = contract_info.begin_date
    end_date = contract_info.end_date

    if begin_date is None:
        start_time = datetime.now(UTC).replace(tzinfo=None)
        current_block = get_current_round()
        begin_date = date_from_block(begin_block, current_block, start_time)
        end_date = date_from_block(end_block, current_block, start_time)

    return StakingPool(
        id=contract_info.id,
        description=contract_info.description,
        address=(await get_app_address(contract_info.id)),
        stake_token=await get_asset_info(stake_token_id),
        reward_token=await get_asset_info(reward_token_id),
        reward_amount_micros=reward_amount_micros,
        algo_reward_amount_micros=algo_reward_amount_micros,
        begin_block=begin_block,
        end_block=end_block,
        lock_length_blocks=contract_info.metadata["lock_length_blocks"],
        deploy_date=datetime.fromtimestamp(contract_info.deployed_timestamp, UTC).replace(tzinfo=None),
        begin_date=begin_date,
        end_date=end_date,
    )


async def farming_pool_from_contract_info(contract_info: ContractInfo) -> FarmingPool:
    # Legacy metadata used two field naming conventions.
    first_token_id = contract_info.metadata.get("asset1_id")
    if first_token_id is None:
        first_token_id = contract_info.metadata["asset_1_id"]
    second_token_id = contract_info.metadata.get("asset2_id")
    if second_token_id is None:
        second_token_id = contract_info.metadata["asset_2_id"]
    first_token_id = int(first_token_id)
    second_token_id = int(second_token_id)

    lp_token_id = contract_info.metadata.get("stake_token_id")
    if lp_token_id is None:
        lp_token_id = parse_bignum(contract_info.metadata["cache"]["initial"]["stakeToken"])
    lp_token_id = int(lp_token_id)

    reward_token_id = contract_info.metadata.get("reward_token_id")
    if reward_token_id is None:
        reward_token_id = parse_bignum(contract_info.metadata["cache"]["initial"]["rewardToken"])
    reward_token_id = int(reward_token_id)

    reward_amount_micros = parse_bignum(contract_info.metadata["cache"]["initial"]["totalRewardAmount"])
    algo_reward_amount_micros = parse_bignum(contract_info.metadata["cache"]["initial"]["totalAlgoRewardAmount"])

    begin_block = contract_info.metadata["begin_block"]
    end_block = contract_info.metadata["end_block"]

    begin_date = contract_info.begin_date
    end_date = contract_info.end_date
    if begin_date is None:
        start_time = datetime.now(UTC).replace(tzinfo=None)
        current_block = get_current_round()
        begin_date = date_from_block(begin_block, current_block, start_time)
        end_date = date_from_block(end_block, current_block, start_time)

    lp_token_info = await get_asset_info(lp_token_id)

    return FarmingPool(
        id=contract_info.id,
        dex_name=contract_info.metadata["dex"],
        description=contract_info.description,
        address=(await get_app_address(contract_info.id)),
        first_token=await get_asset_info(first_token_id),
        second_token=await get_asset_info(second_token_id),
        stake_token=lp_token_info,
        reward_token=await get_asset_info(reward_token_id),
        reward_amount_micros=reward_amount_micros,
        algo_reward_amount_micros=algo_reward_amount_micros,
        begin_block=begin_block,
        end_block=end_block,
        lock_length_blocks=contract_info.metadata["lock_length_blocks"],
        deploy_date=datetime.fromtimestamp(contract_info.deployed_timestamp, UTC).replace(tzinfo=None),
        begin_date=begin_date,
        end_date=end_date,
    )


async def create_pool_from_contract(contract: ContractInfo) -> CometaPool:
    logger.debug(f"Creating Pool from {contract.type} contract {contract.id}")
    ensure_pool_identity_slot(contract)

    if contract.type == "distribution":
        pool = await staking_pool_from_contract_info(contract, distribution=True)
        stored = db.staking_pools.get_or_create(pool)
        return _validate_persisted_pool(pool, stored)

    # contract.type == 'farm'

    if "dex" in contract.metadata:
        # Legacy farm contracts with DEX metadata represent LP staking.
        pool = await farming_pool_from_contract_info(contract)
        stored = db.farming_pools.get_or_create(pool)
        return _validate_persisted_pool(pool, stored)

    pool = await staking_pool_from_contract_info(contract)
    stored = db.staking_pools.get_or_create(pool)
    return _validate_persisted_pool(pool, stored)
