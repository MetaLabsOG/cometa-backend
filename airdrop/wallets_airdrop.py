import json

from airdrop.airdrop import tinyman_client, send_tokens
from blockchain.assets import META_ASA_ID

JSON_FILENAME = 'snapshots/outage_opted_in.json'
TOTAL_META = 10000


def run():
    snapshot_json = json.load(open(JSON_FILENAME))

    total_addr_cnt = len(snapshot_json)
    print(f'Loaded {total_addr_cnt} addresses from {JSON_FILENAME}!')

    # total_parts = 0
    # addr_processed = 0
    # to_airdrop = {}
    # for address, pool_ids in snapshot_json.items():
    #     if tinyman_client.asset_is_opted_in(META_ASA_ID, address):
    #         cnt = len(pool_ids)
    #         total_parts += cnt
    #         to_airdrop[address] = cnt
    #     addr_processed += 1
    #     if addr_processed % 20 == 0:
    #         print(f'Processed {addr_processed}/{total_addr_cnt} addresses!')
    #
    # with open(f'snapshots/outage_opted_in.json', 'w') as f:
    #     json.dump(to_airdrop, f, indent=4)

    to_airdrop = json.load(open(JSON_FILENAME))
    total_parts = 0
    for address, count in to_airdrop.items():
        total_parts += count

    addr_cnt = len(to_airdrop)
    per_part = TOTAL_META / total_parts

    print(f'{addr_cnt} addresses are opted-in, {per_part} META per one pool!')

    err_cnt = 0
    failed_amount = 0

    for address, count in to_airdrop.items():
        address_amount = count * per_part
        try:
            amount = send_tokens(address, address_amount, 'february_outage')
            print(f'Sent {amount} to {address}')
        except Exception as e:
            err_cnt += 1
            failed_amount += address_amount
            print(e, '\n', address)

    print(f'Sent {TOTAL_META - failed_amount} META to {addr_cnt - err_cnt} holders!')


if __name__ == '__main__':
    run()
