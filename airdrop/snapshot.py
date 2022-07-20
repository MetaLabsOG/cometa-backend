from datetime import datetime

from pymongo import MongoClient

from api import metapunks
from blockchain.node import get_current_round
from env import settings

db = MongoClient(host=settings.mongodb_host, port=settings.mongodb_port)[settings.db_name]


def mock_snapshot(snapshot_id: str):
    db.snapshots.insert_one(
        {
            'snapshot_id': snapshot_id,
            'start_time': 420,
            'end_time': 420,
            'round': 420,
            'nft_count': 6,
            'holders': [
                {
                    'address': 'H74LG5REU6TVNFTXNTELPWDPBUFMX62J66VE2UCEY54NO626BFQ7G2RAI4',  # MY OWN opt-in
                    'asa_ids': ['420', '421', '423']
                },
                {
                    'address': 'METASWXOZB3CFFNWD6BDWU7CG5E42HNWFJZMM6IWR7MCT4P7NDW6755IMM',  # META 1 (!) no opt-in
                    'asa_ids': ['422']
                },
                {
                    'address': 'METAGTX4BELE3WVMF5GUOYZMCDYFMDEKBWBP6VLDF6AKTNFWJSGKUFDAYU',  # META 2 opt-in
                    'asa_ids': ['425', '424']
                }
            ]
        }
    )


def make_snapshot(snapshot_id: str):
    if db.snapshots.find_one({'snapshot_id': snapshot_id}) is not None:
        print(f'Snapshot #{snapshot_id} is already done!')
        return

    # mock_snapshot(snapshot_id)  # For testing.
    # return

    current_round = get_current_round()
    start_time = datetime.now()

    print(f'Snapshot #{snapshot_id} in progress!')
    print(f'Current round = {current_round}')
    print(f'Time = {start_time}')

    holders = metapunks.get_holders_async()
    nft_count = 0
    holders.sort(reverse=True, key=lambda h: len(h.asa_ids))
    print(f'{len(holders)} holders:')
    for h in holders:
        cur_cnt = len(h.asa_ids)
        print(f'{h.address}: {cur_cnt} Metapunks!')
        nft_count += cur_cnt

    end_time = datetime.now()
    db.snapshots.insert_one(
        {
            'snapshot_id': snapshot_id,
            'start_time': start_time,
            'end_time': end_time,
            'round': current_round,
            'nft_count': nft_count,
            'holders': [h.to_dict() for h in holders]
        }
    )

    print(f'Snapshot was made in {end_time - start_time}\n')


if __name__ == '__main__':
    make_snapshot('1')
