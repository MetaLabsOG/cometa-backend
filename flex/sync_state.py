from datetime import timedelta

from env import settings
from flex import db
from flex.blockchain.info import get_current_round
from flex.db.model.blockchain import SyncState


async def get_sync_state() -> SyncState:
    sync_state = db.sync_states.get_one()
    if sync_state is None:
        sync_state = db.sync_states.create(SyncState())
    return sync_state


sync_max_delay = timedelta(seconds=settings.sync_behind_seconds_threshold)
sync_max_delay_rounds = int(sync_max_delay.total_seconds() / settings.block_time)


async def is_sync_delayed(current_round: int | None = None) -> bool:
    current_round = current_round or (await get_current_round())
    sync_state = await get_sync_state()
    return sync_state.rounds_since_updated(current_round) > sync_max_delay_rounds
