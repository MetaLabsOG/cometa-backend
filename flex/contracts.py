import logging
from datetime import datetime

from blockchain.node import get_current_round
from blockchain.util import date_from_block
from core.db.contracts import get_contracts_by_type
from core.db.model import ContractInfo
from core.util import parse_bignum
from flex import db
from flex.blockchain import get_asset_info
from flex.db.model import StakingPool, FarmingPool


logger = logging.getLogger(__name__)


def staking_pool_from_contract_info(contract_info: ContractInfo) -> StakingPool:
    stake_token_id = int(contract_info.metadata['stake_token_id'])
    reward_token_id = int(contract_info.metadata['reward_token_id'])
    reward_amount_micros = parse_bignum(contract_info.metadata['cache']['initial']['totalRewardAmount'])
    algo_reward_amount_micros = parse_bignum(contract_info.metadata['cache']['initial']['totalAlgoRewardAmount'])

    begin_block = contract_info.metadata['begin_block']
    end_block = contract_info.metadata['end_block']
    begin_date = contract_info.begin_date
    end_date = contract_info.end_date

    if begin_date is None:
        start_time = datetime.now()
        current_block = get_current_round()
        begin_date = date_from_block(begin_block, current_block, start_time)
        end_date = date_from_block(end_block, current_block, start_time)

    return StakingPool(
        id=contract_info.id,
        description=contract_info.description,

        stake_token=get_asset_info(stake_token_id),
        reward_token=get_asset_info(reward_token_id),

        reward_amount_micros=reward_amount_micros,
        algo_reward_amount_micros=algo_reward_amount_micros,

        begin_block=begin_block,
        end_block=end_block,
        lock_length_blocks=contract_info.metadata['lock_length_blocks'],

        deploy_date=datetime.fromtimestamp(contract_info.deployed_timestamp),
        begin_date=begin_date,
        end_date=end_date,
    )


def farming_pool_from_contract_info(contract_info: ContractInfo) -> FarmingPool:
    first_token_id = int(contract_info.metadata['asset1_id'])
    second_token_id = int(contract_info.metadata['asset2_id'])
    lp_token_id = int(contract_info.metadata['stake_token_id'])
    reward_token_id = int(contract_info.metadata['reward_token_id'])
    reward_amount_micros = parse_bignum(contract_info.metadata['cache']['initial']['totalRewardAmount'])
    algo_reward_amount_micros = parse_bignum(contract_info.metadata['cache']['initial']['totalAlgoRewardAmount'])

    begin_block = contract_info.metadata['begin_block']
    end_block = contract_info.metadata['end_block']

    begin_date = contract_info.begin_date
    end_date = contract_info.end_date
    if begin_date is None:
        start_time = datetime.now()
        current_block = get_current_round()
        begin_date = date_from_block(begin_block, current_block, start_time)
        end_date = date_from_block(end_block, current_block, start_time)

    return FarmingPool(
        id=contract_info.id,
        dex_name=contract_info.metadata['dex'],
        description=contract_info.description,

        first_token=get_asset_info(first_token_id),
        second_token=get_asset_info(second_token_id),
        lp_token=get_asset_info(lp_token_id),
        reward_token=get_asset_info(reward_token_id),

        reward_amount_micros=reward_amount_micros,
        algo_reward_amount_micros=algo_reward_amount_micros,

        begin_block=begin_block,
        end_block=end_block,
        lock_length_blocks=contract_info.metadata['lock_length_blocks'],

        deploy_date=datetime.fromtimestamp(contract_info.deployed_timestamp),
        begin_date=begin_date,
        end_date=end_date,
    )


def all_contracts_to_pools() -> tuple[list[StakingPool], list[FarmingPool]]:
    staking_pools = []
    farming_pools = []

    distribution_contracts = get_contracts_by_type('distribution')
    logger.info(f'Migrating {len(distribution_contracts)} distribution contracts to Pools DB\n')
    for contract in distribution_contracts:
        if db.staking_pools.exists(id=contract.id):
            logger.info(f'Staking pool {contract.id} already exists in DB')
            continue

        staking_pool = staking_pool_from_contract_info(contract)
        db.staking_pools.create(staking_pool)
        staking_pools.append(staking_pool)

    farm_contracts = get_contracts_by_type('farm')
    logger.info(f'Migrating {len(farm_contracts)} farm contracts to Pools DB\n')
    for contract in farm_contracts:
        if 'dex' in contract.metadata:
            # ancient system: 'farm' can be staking A -> B. Do not bother refactoring if lol
            if db.farming_pools.exists(id=contract.id):
                logger.info(f'Farming pool {contract.id} already exists in DB')
                continue

            farming_pool = farming_pool_from_contract_info(contract)
            db.farming_pools.create(farming_pool)
            farming_pools.append(farming_pool)
        else:
            if db.staking_pools.exists(pool_id=contract.id):
                logger.info(f'Staking pool {contract.id} already exists in DB')
                continue

            staking_pool = staking_pool_from_contract_info(contract)
            db.staking_pools.create(staking_pool)
            staking_pools.append(staking_pool)

    return staking_pools, farming_pools
