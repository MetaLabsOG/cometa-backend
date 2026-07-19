from datetime import timedelta

from env import settings
from flex import db
from flex.blockchain.info import get_current_round
from flex.db.model.blockchain import SyncState


async def get_sync_state() -> SyncState:
    return db.sync_states.get_or_create(SyncState())


sync_max_delay = timedelta(seconds=settings.sync_behind_seconds_threshold)
sync_max_delay_rounds = int(sync_max_delay.total_seconds() / settings.block_time)


async def is_sync_delayed(current_round: int | None = None) -> bool:
    current_round = current_round or (await get_current_round())
    sync_state = await get_sync_state()
    rounds_behind = sync_state.rounds_since_updated(current_round)
    return rounds_behind is None or rounds_behind > sync_max_delay_rounds
