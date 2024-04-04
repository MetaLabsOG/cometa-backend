import logging
from datetime import datetime

from blockchain.node import get_current_round
from blockchain.util import date_from_block
from core.db.contracts import get_contracts_by_type
from core.db.model import ContractInfo
from core.util import parse_bignum
from flex import db
from flex.blockchain import get_asset_info, get_app_address
from flex.db.model.pools import StakingPool, FarmingPool

logger = logging.getLogger(__name__)


def staking_pool_from_contract_info(contract_info: ContractInfo, distribution: bool = False) -> StakingPool:
    # FIXME: I DON'T FUCKING CARE, IT WORKS
    if distribution:
        stake_token_id = contract_info.metadata.get('stake_token_id')
        if stake_token_id is None:
            stake_token_id = parse_bignum(contract_info.metadata['cache']['initial']['token'])
        stake_token_id = int(stake_token_id)

        reward_token_id = contract_info.metadata.get('reward_token_id')
        if reward_token_id is None:
            reward_token_id = parse_bignum(contract_info.metadata['cache']['initial']['token'])
        reward_token_id = int(reward_token_id)
    else:
        stake_token_id = contract_info.metadata.get('stake_token_id')
        if stake_token_id is None:
            stake_token_id = parse_bignum(contract_info.metadata['cache']['initial']['stakeToken'])
        stake_token_id = int(stake_token_id)

        reward_token_id = contract_info.metadata.get('reward_token_id')
        if reward_token_id is None:
            reward_token_id = parse_bignum(contract_info.metadata['cache']['initial']['rewardToken'])
        reward_token_id = int(reward_token_id)

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
        address=get_app_address(contract_info.id),

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
    # TODO: migrations could be so beautiful and elegant
    first_token_id = contract_info.metadata.get('asset1_id')
    if first_token_id is None:
        first_token_id = contract_info.metadata['asset_1_id']
    second_token_id = contract_info.metadata.get('asset2_id')
    if second_token_id is None:
        second_token_id = contract_info.metadata['asset_2_id']
    first_token_id = int(first_token_id)
    second_token_id = int(second_token_id)

    lp_token_id = contract_info.metadata.get('stake_token_id')
    if lp_token_id is None:
        lp_token_id = parse_bignum(contract_info.metadata['cache']['initial']['stakeToken'])
    lp_token_id = int(lp_token_id)

    reward_token_id = contract_info.metadata.get('reward_token_id')
    if reward_token_id is None:
        reward_token_id = parse_bignum(contract_info.metadata['cache']['initial']['rewardToken'])
    reward_token_id = int(reward_token_id)

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

    lp_token_info = get_asset_info(lp_token_id)

    # TODO: check what is here, maybe remove
    # if not db.lp_tokens.exists(id=lp_token_id):
    #     db.lp_tokens.create(LpToken(
    #         id=lp_token_id,
    #         asset1_id=first_token_id,
    #         asset2_id=second_token_id,
    #         name=lp_token_info.name,
    #         dex=contract_info.metadata['dex']
    #     ))

    return FarmingPool(
        id=contract_info.id,
        dex_name=contract_info.metadata['dex'],
        description=contract_info.description,
        address=get_app_address(contract_info.id),

        first_token=get_asset_info(first_token_id),
        second_token=get_asset_info(second_token_id),
        stake_token=lp_token_info,
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


async def all_contracts_to_pools() -> tuple[list[StakingPool], list[FarmingPool]]:
    staking_pools = []
    farming_pools = []

    distribution_contracts = get_contracts_by_type('distribution')
    logger.info(f'Migrating {len(distribution_contracts)} distribution contracts to Pools DB\n')
    failed_contract_ids = []
    for contract in distribution_contracts:
        try:
            logger.debug(f'Processing distr contract {contract.id}')

            if db.staking_pools.exists(id=contract.id):
                logger.info(f'Staking pool {contract.id} already exists in DB')
                continue

            staking_pool = staking_pool_from_contract_info(contract, distribution=True)
            db.staking_pools.create(staking_pool)
            staking_pools.append(staking_pool)
        except Exception as e:
            logger.error(f'Failed to process contract {contract.id}: {e}\n{contract}\n', exc_info=True)
            failed_contract_ids.append(contract.id)

    farm_contracts = get_contracts_by_type('farm')
    logger.info(f'Migrating {len(farm_contracts)} farm contracts to Pools DB\n')
    for contract in farm_contracts:
        try:
            logger.debug(f'Processing farm contract {contract.id}')

            if 'dex' in contract.metadata:
                # ancient system: 'farm' can be staking A -> B. Do not bother refactoring if lol
                if db.farming_pools.exists(id=contract.id):
                    logger.info(f'Farming pool {contract.id} already exists in DB')
                    continue

                farming_pool = farming_pool_from_contract_info(contract)
                db.farming_pools.create(farming_pool)
                farming_pools.append(farming_pool)
            else:
                if db.staking_pools.exists(id=contract.id):
                    logger.info(f'Staking pool {contract.id} already exists in DB')
                    continue

                staking_pool = staking_pool_from_contract_info(contract)
                db.staking_pools.create(staking_pool)
                staking_pools.append(staking_pool)
        except Exception as e:
            logger.error(f'Failed to process contract {contract.id}: {e}\n{contract}\n', exc_info=True)
            failed_contract_ids.append(contract.id)

    logger.info(f'\n\nFailed to process contracts: {failed_contract_ids}\n\n')
    return staking_pools, farming_pools
