import time
from dataclasses import dataclass
from threading import Thread
from typing import Optional, List

import schedule
from pyairtable import Base

from bot.db import events, users
from bot.db.events import get_event
from bot.db.model import EventType
from bot.env import settings, AIRTABLE_UPDATE_DELAY_SECONDS
from core.contract_manager import get_contracts
from core.js_interop import calljs
from core.util import strip_version

base = Base(settings.airtable_api_key, settings.airtable_base_id)
airtable = base.get_table('farm')


@dataclass
class CometaLocalState:
    pool_id: int
    staked: int
    current_reward: int
    lock_timestamp: int


def bignumber_to_int(number: dict) -> int:
    return int(number['hex'], 16)


def get_user_pools(address: str) -> List[CometaLocalState]:
    all_contracts = get_contracts({})
    if not all_contracts:
        return []

    ids_and_versions = [{'id': info.id, 'version': strip_version(info.version)} for info in all_contracts]
    states = await calljs("fetchContractsLocalViews",
                          contractType=type,
                          idVersions=ids_and_versions,
                          walletAddress=address)
    pools = []
    for pool_id, state in states.items():
        current_reward = bignumber_to_int(state['reward'])
        staked = bignumber_to_int(state['staked'])
        if current_reward == 0 and staked == 0:
            continue
        lock_timestamp = bignumber_to_int(state['lockTimestamp'])
        pools.append(CometaLocalState(pool_id, staked, current_reward, lock_timestamp))
    return pools


def get_last_event_time() -> Optional[int]:
    all_events = events.get_events({})
    if not all_events:
        return 0
    return all_events[-1].timestamp


last_processed_entry_time = get_last_event_time()


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
    daemon = Thread(target=updater_thread, args=(), daemon=True, name='Updater')
    daemon.start()


if __name__ == '__main__':
    process_updates()
