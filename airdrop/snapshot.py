import json
from datetime import datetime

from pymongo import MongoClient

from api import metapunks
from blockchain.node import get_current_round
from env import settings

db = MongoClient(host=settings.mongodb_host, port=settings.mongodb_port)[settings.db_name]


def make_snapshot(snapshot_id: str):
    if db.snapshots.find_one({'snapshot_id': snapshot_id}) is not None:
        print(f'Snapshot #{snapshot_id} is already done!')
        return

    # mock_snapshot(snapshot_id)  # For testing.
    # return

    current_round = get_current_round()
    start_time = datetime.now().timestamp()

    print(f'Snapshot #{snapshot_id} in progress!')
    print(f'Current round = {current_round}')
    print(f'Time = {start_time}')

    holders = metapunks.get_holders_async()
    nft_count = 0
    print(f'{len(holders)} holders:')
    for address, asa_ids in holders.items():
        cur_cnt = len(asa_ids)
        print(f'{address}: {cur_cnt} Metapunks!')
        nft_count += cur_cnt

    end_time = datetime.now().timestamp()
    snapshot_dict = {
        'snapshot_id': snapshot_id,
        'start_time': start_time,
        'end_time': end_time,
        'round': current_round,
        'nft_count': nft_count,
        'holders': holders
    }
    # db.snapshots.insert_one(
    #     snapshot_dict
    # )

    with open(f'snapshot_{snapshot_id}.json', 'w') as f:
        f.write(str(snapshot_dict))
        json.dump(snapshot_dict, f, indent=4)

    print(f'Snapshot was made in {end_time - start_time}\n')

    # total_nfts = 0
    # for h in holders:
    #     hold = len(h.asa_ids)
    #     get = int(sqrt(hold))
    #     print(f'holding = {hold}, getting = {get}')
    #     total_nfts += get
    #
    # print(f'In total we need {total_nfts} NFTs!')


if __name__ == '__main__':
    make_snapshot('comeback_2')
