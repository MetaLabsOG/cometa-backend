from cachetools import cached, TTLCache

from env import settings
from flex import db
from flex.blockchain import BLOCKS_IN_A_YEAR
from flex.data.pools import get_pool_info_by_id
from flex.db.model.pool_states import UserState, PoolState
from flex.db.model.pools import PoolType
from flex.data.tinyman import get_tinyman_pool_info
from flex.data.vestige import get_asset_price_usd, get_algo_price_usd
from flex.db.model.priced import UserCost, PoolStateCost, UserPoolCost


@cached(cache=TTLCache(maxsize=1024, ttl=settings.asset_prices_ttl))
def get_lp_price_usd(asset1_id: int, asset2_id: int) -> float | None:
    tinyman_pool = get_tinyman_pool_info(asset1_id, asset2_id)
    if tinyman_pool.lp_tokens_amount == 0:
        return None

    asset1_price = get_asset_price_usd(asset1_id)
    asset2_price = get_asset_price_usd(asset2_id)
    total_cost = asset1_price * tinyman_pool.asset1_reserve + asset2_price * tinyman_pool.asset2_reserve
    lp_token_price = total_cost / tinyman_pool.lp_tokens_amount
    return lp_token_price


def calculate_lp_token_price_usd(lp_token_id: int) -> float:
    lp_token = db.lp_tokens.get_one(id=lp_token_id)
    if lp_token is None:
        raise ValueError(f'LP token {lp_token_id} not recorded in DB')
    return get_lp_price_usd(lp_token.asset1_id, lp_token.asset2_id)


def calculate_pool_state_cost(pool_state: PoolState) -> PoolStateCost:
    if pool_state.type == PoolType.FARMING:
        stake_token_price = calculate_lp_token_price_usd(pool_state.stake_token.id)
    else:
        stake_token_price = get_asset_price_usd(pool_state.stake_token.id)
    pool_info = get_pool_info_by_id(pool_state.pool_id)
    reward_token_price_usd = get_asset_price_usd(pool_info.reward_token.id)

    staked_usd = stake_token_price * pool_state.total_staked

    rewards_usd = pool_info.reward_amount * reward_token_price_usd
    algo_rewards_usd = pool_info.algo_reward_amount * get_algo_price_usd()
    total_rewards_usd = rewards_usd + algo_rewards_usd
    current_apr = total_rewards_usd / staked_usd * 100 * BLOCKS_IN_A_YEAR / pool_info.length_blocks if staked_usd > 0 else 0

    return PoolStateCost(
        info=pool_state,
        staked_usd=staked_usd,
        current_apr=current_apr
    )


def calculate_user_pool_state_cost(user_state: UserState) -> UserCost:
    user_cost = UserCost(address=user_state.address)
    for user_pool_state in user_state.pool_by_address.values():
        pool_info = get_pool_info_by_id(user_pool_state.pool_id)
        if pool_info.type == PoolType.FARMING:
            stake_token_price = calculate_lp_token_price_usd(pool_info.stake_token.id)
        else:
            stake_token_price = get_asset_price_usd(pool_info.stake_token.id)
        staked_usd = stake_token_price * user_pool_state.staked_amount
        user_cost.total_staked_usd += staked_usd
        user_cost.pools_by_id[pool_info.id] = UserPoolCost(
            pool_info=pool_info,
            staked_usd=staked_usd
        )
    return user_cost
