import json
import random
from dataclasses import dataclass

from dataclasses_json import dataclass_json

from flex.blockchain.base import indexer_client
from flex.data.assets import get_asset_info
from flex.tools.airdrop import send_airdrop
from flex.txns import TxInfo


@dataclass_json
@dataclass
class OptIn:
    address: str
    opted_round: int


def get_all_token_addresses(asa_id: int) -> list[OptIn]:
    addresses = []
    token = None
    while True:
        data = indexer_client.asset_balances(asset_id=asa_id, next_page=token)
        balances = data.get('balances', [])
        token = data.get('next-token')
        for balance in balances:
            address = balance['address']
            opted_round = balance['opted-in-at-round']
            addresses.append(OptIn(address=address, opted_round=opted_round))

        if token is None:
            break

    addresses.sort(key=lambda x: x.opted_round)
    with open(f'test_optins.json', 'w') as f:
        json.dump([item.to_dict() for item in addresses], f, indent=4)

    return addresses


@dataclass_json
@dataclass
class AlgoBalance:
    address: str
    amount: int


def get_addresses_algo_balances(addresses: list[str]) -> list[AlgoBalance]:
    balances = []
    for i, address in enumerate(addresses):
        balance = indexer_client.account_info(address=address)
        not_micros = int(balance['account']['amount']) / 1000000
        print(f'#{i} {format(not_micros, ".1f")}: {address}')
        balances.append(AlgoBalance(address=address, amount=not_micros))

    balances.sort(key=lambda x: x.amount)
    with open(f'temp_data/test_optins_balances.json', 'w') as f:
        f.writelines([f'"{format(item.amount, ".1f")}": "{item.address}",' for item in balances])

    return balances


def get_addresses_by_amount():
    with open('temp_data/test_optins_balances.json', 'r') as f:
        lines = f.readlines()
        line = lines[0]
        items = line.split(',')
        amount_addrs = {}

        for item in items:
            print(item)
            parts = item.split(':')
            if len(parts) < 2:
                continue
            amount_str, address_str = parts
            amount = amount_str.strip().replace('"', '')
            address = address_str.strip().replace('"', '')
            amount_addrs.setdefault(amount, []).append(address)

        return amount_addrs


TX_NOTE_PREFIXES = [
    'You are the BEST!!!',
    'From Cometa with ❤️',
    'You are the LEGEND',
    'Enjoy you day :)',
    'Your day gonna be successful as issue',
    'You are the KING, do you know that?',
    'YOU GETTING RICH EVERY DAY',
    'You are genius, for real',
    'Do not overthink, your day will be successful :)'
]


async def send_token_shares(
        asa_id: int,
        address_shares: dict[str, float],
        total_supply: float,
        airdrop_id: str
) -> list[TxInfo]:
    asset_info = await get_asset_info(asa_id)
    print(f'Asset info: {asset_info}')
    supply_micros = asset_info.amount_to_micros(total_supply)
    print(f'Supply micros: {supply_micros}')

    txns = await send_airdrop(
        asset_info=asset_info,
        total_amount_micros=supply_micros,
        address_shares=address_shares,
        notes=TX_NOTE_PREFIXES,
        airdrop_id=airdrop_id
    )

    print(f'{len(txns)} txns sent!')

    return txns


TEST_ASA_ID = 1866895625
AIRDROP_ID = 'test_test_1'
TEST_TOKEN_AMOUNT = 4200


async def make_airdrop():
    amount_addresses = get_addresses_by_amount()
    print(amount_addresses)
    amount_addresses_count = {amount: len(addresses) for amount, addresses in amount_addresses.items()}
    sorted_amount_addresses_count = dict(sorted(amount_addresses_count.items(), key=lambda item: item[0]))

    with open(f'test_optins_balances_count.json', 'w') as f:
        json.dump(sorted_amount_addresses_count, f, indent=4)

    address_share = {}
    for amount, addresses in amount_addresses.items():
        len_sqrt = len(addresses) ** 0.5
        for address in addresses:
            address_share[address] = 1 / len_sqrt

    print(address_share)

    await send_token_shares(
        asa_id=TEST_ASA_ID,
        address_shares=address_share,
        total_supply=TEST_TOKEN_AMOUNT,
        airdrop_id=AIRDROP_ID
    )


if __name__ == '__main__':
    # addresses = get_all_token_addresses(TEST_ASA_ID)
    # algo_balances = get_addresses_algo_balances([item.address for item in addresses])
    # print(f'Found {len(addresses)} addresses!')

    make_airdrop()
