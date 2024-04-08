import json
import logging

from flex import db
from flex.blockchain.base import cometa_public_key
from flex.blockchain.info import get_current_round, is_opted_in
from flex.db.model.blockchain import AssetInfo
from flex.db.model.priced import AirdropReward
from flex.txns import TxInfo, send_asset_micros_with_wait


AIRDROP_ID = 'meta_a200_2'

logger = logging.getLogger(__name__)


def send_airdrop(
        asset_info: AssetInfo,
        total_amount_micros: int,
        address_shares: dict[str, float],
        note: str
) -> list[TxInfo]:
    current_round = get_current_round()
    logger.info(f'Sending airdrop for {asset_info.name}! Round: {current_round}. Cometa address: {cometa_public_key}')

    logger.info('Checking opted-in addresses...')
    opted_in_shares = {}
    total_shares = 0
    it_num = 0
    for address, share in address_shares.items():
        it_num += 1
        if is_opted_in(address, asset_info.id):
            opted_in_shares[address] = share
            total_shares += share
        if it_num % 10 == 0:
             logger.info(f'{len(opted_in_shares)}/{it_num}')

    amount_per_share = asset_info.micros_to_amount(int(total_amount_micros / total_shares + 1))
    logger.info(f'Total shares: {total_shares}. Total amount: {asset_info.micros_to_amount(total_amount_micros)}. Amount per share: {amount_per_share}')

    opted_in_amounts = {}
    for address, share in opted_in_shares.items():
        amount_micros = int(share * total_amount_micros / total_shares + 1)
        opted_in_amounts[address] = amount_micros

    with open(f'airdrop_amounts_{asset_info.name.lower()}_{current_round}.json', 'w') as f:
        json.dump(opted_in_amounts, f, indent=4)

    sent_txns: list[TxInfo] = []
    total_sent_micros = 0

    it_num = 0
    for address, amount_micros in opted_in_amounts.items():
        try:
            it_num += 1
            logger.info(f'{it_num}/{len(opted_in_amounts)}')

            already_sent = db.airdrop_rewards.get_one(address=address, airdrop_id=AIRDROP_ID)
            if already_sent is not None:
                logger.info(f'Skipping {address}: already sent {asset_info.micros_to_amount(already_sent.amount_micros)} {asset_info.name} tokens with txid {already_sent.tx_id}!')
                continue

            tx_info = send_asset_micros_with_wait(asset_info, address, amount_micros, note)
            db.airdrop_rewards.create(AirdropReward(
                airdrop_id=AIRDROP_ID,
                address=address,
                asa_id=asset_info.id,
                amount_micros=amount_micros,
                txid=tx_info.id
            ))
            sent_txns.append(tx_info)
            total_sent_micros += amount_micros
        except Exception as e:
            logger.error(f'Error while sending airdrop to {address}: {e}', exc_info=True)

    logger.info(f'\nSent {asset_info.micros_to_amount(total_sent_micros)} {asset_info.name} tokens to {len(sent_txns)} addresses!')

    with open(f'airdrop_txns_{asset_info.name.lower()}_{current_round}.json', 'w') as f:
        json.dump([tx.to_dict() for tx in sent_txns], f, indent=4)

    return sent_txns
