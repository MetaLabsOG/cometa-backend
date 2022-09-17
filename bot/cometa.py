import logging
import time
from dataclasses import dataclass
from typing import Optional, List

import schedule
from pyairtable import Base

from api.stats import get_pool_state, PoolState
from blockchain.assets import MICROALGOS_IN_ALGO
from blockchain.indexer import get_asset
from blockchain.node import get_current_round
from bot.db import events, users
from bot.db.events import get_event
from bot.db.model import EventType
from bot.env import settings, AIRTABLE_UPDATE_DELAY_SECONDS
from core.contract_manager import get_contracts
from core.js_interop import calljs
from core.tinychart import get_asset_price, get_algo_price
from core.util import strip_version, parse_bignum, blocks_to_seconds

logger = logging.getLogger(__name__)

base = Base(settings.airtable_api_key, settings.airtable_base_id)
airtable = base.get_table('farm')


@dataclass
class UserPool:
    pool_id: int
    name: str
    staked_usd: float
    reward_usd: float
    lock_timestamp: int
    ended_duration: Optional[float]


async def get_local_states(type: str, address: str) -> dict:
    contracts = get_contracts({'type': type})
    if not contracts:
        return {}
    ids_and_versions = [{'id': info.id, 'version': strip_version(info.version)} for info in contracts]
    local_states = await calljs("fetchContractsLocalViews",
                                contractType=type,
                                idVersions=ids_and_versions,
                                walletAddress=address)
    return local_states


# ffs
BIG_NUM = 1000000000000000000


def recalculate_reward(pool: PoolState, current_block: int, staked: int, reward: int,
                       reward_per_token_paid: int) -> int:
    if pool.last_update_block >= current_block or pool.total_staked == 0 or staked == 0:
        return reward

    last_block_with_rewards = min(current_block, pool.end_block)
    reward_blocks_passed = last_block_with_rewards - pool.last_update_block
    reward_per_token_stored_new = pool.reward_per_token_stored + \
                                  reward_blocks_passed * pool.reward_per_block * BIG_NUM // pool.total_staked
    reward_to_pay_now = staked * (reward_per_token_stored_new - reward_per_token_paid) // BIG_NUM
    return reward + reward_to_pay_now


async def get_user_pools(address: str) -> List[UserPool]:
    local_states = await get_local_states('farm', address) | await get_local_states('distribution', address)
    all_contracts = get_contracts({'type': {'$in': ['farm', 'distribution']}})
    contract_by_id = {str(c.id): c for c in all_contracts}
    pools = []
    for pool_id, state in local_states.items():
        try:
            reward = parse_bignum(state['reward'])
            staked = parse_bignum(state['staked'])

            # user doesn't have interest in such pools
            if reward == 0 and staked == 0:
                continue

            lock_timestamp = parse_bignum(state['lockTimestamp'])

            contract = contract_by_id[str(pool_id)]
            pool_state = get_pool_state(contract)

            current_block = get_current_round()
            ended_duration = None
            if current_block > pool_state.end_block:
                ended_duration = blocks_to_seconds(pool_state.end_block, current_block)

            staked_usd = pool_state.total_cost_usd * staked / pool_state.total_staked

            logger.debug(contract.description)
            logger.debug(contract.id)

            logger.debug(f'reward = {reward}')
            reward_per_token_paid = parse_bignum(state['rewardPerTokenPaid'])
            reward = recalculate_reward(pool_state, current_block, staked, reward, reward_per_token_paid)
            logger.debug(f'new_reward = {reward}')

            reward_asset = get_asset(pool_state.reward_token_id)
            logger.debug(f'reward_token = {pool_state.reward_token_id}')

            reward_tokens = reward / (10 ** reward_asset['params']['decimals'])
            logger.debug(f'reward_tokens = {reward_tokens}')

            reward_price = get_asset_price(pool_state.reward_token_id)
            reward_usd = reward_tokens * reward_price
            logger.debug(f'reward_usd = {reward_usd}')

            reward_usd += reward * pool_state.total_algo_rewards // \
                          pool_state.total_rewards * get_algo_price() / MICROALGOS_IN_ALGO
            logger.debug(f'reward_usd_with_algo = {reward_usd}\n')

            pools.append(UserPool(
                pool_id,
                contract.description,
                staked_usd,
                reward_usd,
                lock_timestamp,
                ended_duration
            ))
        except Exception as e:
            logger.error(f'Failed to get info for pool {pool_id}')
            logger.exception(e, exc_info=True)

    return pools


def get_last_event_time() -> Optional[int]:
    all_events = events.get_events({})
    if not all_events:
        return 0
    return all_events[-1].timestamp


# last_processed_entry_time = get_last_event_time()


def get_last_updates():
    all_entries = airtable.all(sort=['timestamp'])
    return list(filter(lambda e: e['fields']['timestamp'] > last_processed_entry_time, all_entries))


# TODO: make a field with type event in the table
def get_event_type(details) -> Optional[str]:
    msg = details['message']
    text = msg[1:-1]
    for t in EventType:
        if text == t:
            return t
    return None


def process_update(e):
    global last_processed_entry_time

    try:
        if get_event({'_id': e['id']}) is not None:
            return

        info = e['fields']
        t = info.get('timestamp')
        _type = get_event_type(info)

        # TODO: pool_name is not enough to differ pools (also locks to consider)
        event = events.add_event(
            _id=e['id'],
            type=_type,
            pool_name=info.get('lp_token_name'),
            address=info.get('address'),
            timestamp=t / 1000,  # millis
            token_id=info.get('lp_token_id'),
            reward_token_id=info.get('reward_token_id'),
            amount=info.get('amount')
        )

        # TODO: fix - for now 1 user == 1 address
        user = users.get_user_by_address(event.address)
        if user is not None:
            # app_context.bot.send_message(text=f'Hey looks like you... {_type}', chat_id=user.telegram_id)
            print(f'Hey looks like you... {_type}\n{user.algo_address}\ntg_id={user.telegram_id}')
            users.update_user_event(user, event)

        last_processed_entry_time = max(t, last_processed_entry_time)

    except Exception as e:
        # TODO: use logging
        print(e)
        return


def process_updates():
    print('Updating events!')
    last_events = get_last_updates()
    for e in last_events:
        process_update(e)
    print(f'Got {len(last_events)} new events!')


def updater_thread():
    schedule.every(AIRTABLE_UPDATE_DELAY_SECONDS).seconds.do(process_updates)

    while True:
        schedule.run_pending()
        time.sleep(AIRTABLE_UPDATE_DELAY_SECONDS)


def schedule_airtable_updates():
    # TODO: use executor
    # daemon = Thread(target=updater_thread, args=(), daemon=True, name='Updater')
    # daemon.start()
    pass


if __name__ == '__main__':
    process_updates()
