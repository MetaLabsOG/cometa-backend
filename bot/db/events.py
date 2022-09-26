from typing import List, Optional

from bot.db.model import CometaEvent
from bot.db.mongo import get_collection

# TODO: remove events
collection = get_collection('events')


def add_event(
        _id: str,
        type: str,
        pool_name: str,
        address: str,
        timestamp: int,
        token_id: int,
        reward_token_id: Optional[int],
        amount: float) -> CometaEvent:
    event = CometaEvent(_id, type, pool_name, address, timestamp, token_id, reward_token_id, amount)
    collection.insert_one(event.to_dict())
    return event


def get_event(args: dict) -> Optional[CometaEvent]:
    event = collection.find_one(args)
    return CometaEvent.from_dict(event) if event is not None else None


def get_events(args: dict) -> List[CometaEvent]:
    events = collection.find(args).sort('timestamp', 1)
    return [CometaEvent.from_dict(e) for e in events]
