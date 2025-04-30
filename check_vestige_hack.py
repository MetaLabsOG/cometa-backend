import json

with open('temp_data/user_txns_35720000_37530000.json', 'r') as f:
    txns = json.load(f)
    active_cnt = 0
    for address, app_txns in txns.items():
        tx_cnt = 0
        for app_id, cnt in app_txns.items():
            tx_cnt += cnt
        if tx_cnt >= 3:
            active_cnt += 1
    print(active_cnt)
