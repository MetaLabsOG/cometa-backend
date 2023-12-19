import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from algosdk.v2client import indexer
from dataclasses_json import dataclass_json

from api.swaps import SwapInfo
from api.wallet import send_nft, cometa_public_key
from blockchain.nfts import get_nft_info
from blockchain.node import init_algod_client, get_current_round
from core.db.db_manager import DbManager
from env import settings


class LotteryType(str, Enum):
    SWAP = 'swap'
    STAKING = 'staking'

    def __str__(self):
        return self.value


@dataclass_json
@dataclass
class NftLottery:
    name: str
    asset_id: int
    min_amount: int
    probability: float
    available_nfts: list[int]
    win_title: str = 'You have won a prize NFT!'
    max_amount: Optional[int] = None
    type: Optional[str] = None
    only_for_buy: Optional[bool] = None
    pool_id: Optional[int] = None

    def is_eligible(self, entity_id: int, amount: float) -> bool:
        return (entity_id == self.asset_id or entity_id == self.pool_id) and amount >= self.min_amount and (
                self.max_amount is None or amount <= self.max_amount)


@dataclass_json
@dataclass
class LotteryDraw:
    wallet: str
    prize: Optional[int]
    timestamp: Optional[float] = None
    lottery_name: Optional[str] = None
    claimed: bool = False
    created_date: Optional[datetime] = None
    send_error: Optional[str] = None

    def __post_init__(self):
        if self.timestamp:
            self.created_date = datetime.fromtimestamp(self.timestamp)


@dataclass_json
@dataclass
class LotteryParticipant:
    address: str
    pool_id: int
    last_draw_block: int


nft_lotteries = DbManager[NftLottery](settings.db_name, 'nft_lotteries', 'name', NftLottery)
lottery_draws = DbManager[LotteryDraw](settings.db_name, 'lottery_draws', 'swap_txid', LotteryDraw)
lottery_participants = DbManager[LotteryParticipant](settings.db_name, 'lottery_participants', 'address', LotteryParticipant)

algod_client = init_algod_client()
indexer_client = indexer.IndexerClient(indexer_token=settings.algod_token, indexer_address=settings.algo_indexer_address)

logger = logging.getLogger(__name__)


def draw_id(lottery: NftLottery) -> Optional[int]:
    if random.random() > lottery.probability:
        return None
    while True:
        if not lottery.available_nfts:
            return None
        res = random.choice(lottery.available_nfts)
        data = indexer_client.lookup_account_assets(address=cometa_public_key, asset_id=res)
        assets = data.get('assets', [])
        if len(assets) > 0 and assets[0].get('amount', 0) > 0:
            # drawn nft persists in the wallet
            break
        logger.info(f'NFT {res} is not in the wallet, drawing again')
        lottery.available_nfts.remove(res)
        nft_lotteries.update(lottery)
    return res


@dataclass
class NftPrize:
    asa_id: int
    name: str
    image_url: str
    title: str


def get_nft_prize(lottery: NftLottery, asa_id: Optional[int]) -> Optional[NftPrize]:
    if asa_id is None:
        return None
    prize_info = get_nft_info(asa_id)

    PINATA_URL = 'https://gateway.pinata.cloud/ipfs/'
    image_url = prize_info.image_url.replace('ipfs://', PINATA_URL)

    return NftPrize(asa_id=asa_id,
                    name=prize_info.name,
                    image_url=image_url,
                    title=lottery.win_title)


def draw_prize(lottery: NftLottery, address: str) -> Optional[NftPrize]:
    logger.debug(f'Drawing lottery {lottery.name} for {address}')
    prize_id = draw_id(lottery)
    lottery_draws.create(LotteryDraw(lottery_name=lottery.name,
                                     prize=prize_id,
                                     wallet=address,
                                     timestamp=time.time()))
    return get_nft_prize(lottery, prize_id)


def lottery_for_swap(swap: SwapInfo) -> Optional[NftPrize]:
    lotteries = nft_lotteries.get_many({'type': LotteryType.SWAP})
    logger.debug(f'Swap lotteries cnt = {len(lotteries)}')

    prize = None
    for lottery in lotteries:
        if prize is None and lottery.is_eligible(swap.asset2_id, swap.asset2_amount):
            prize = draw_prize(lottery, swap.wallet)
        if prize is None and not lottery.only_for_buy and lottery.is_eligible(swap.asset1_id, swap.asset1_amount):
            prize = draw_prize(lottery, swap.wallet)

    return prize


async def lottery_for_staking(pool_id: int, address: str, is_mainnet: bool = True) -> Optional[NftPrize]:
    lotteries = nft_lotteries.get_many({'type': LotteryType.STAKING, 'pool_id': pool_id})
    if not lotteries:
        logger.info(f'No lotteries found for pools_id {pool_id}')
        return None
    logger.debug(f'Lotteries found for pools_id {pool_id}: {lotteries}')
    lottery = lotteries[0]

    if len(lottery.available_nfts) == 0:
        logger.warning(f'NFTS are OVER for lottery {lottery.name}')
        return None

    # participant = lottery_participants.get_by_primary_key(address)
    # if participant is None:
    #     participant = LotteryParticipant(address=address,
    #                                      pool_id=pool_id,
    #                                      last_draw_block=0)
    #     lottery_participants.create(participant)

    # !!! About lock check.
    # OMIT LOCK CHECK, considering that claim is active on front only after the lock.
    # And after the lock it again not available for the whole period.
    # SO we do not need explicit check here.
    # FIXME: this can easily be hacked just by backend requests (but I'll give it a shot lol, I don't believe there are too many smart people to do that)

    # lock_length = 183272 if is_mainnet else 1
    # current_block = get_current_round()
    #
    # if participant.last_draw_block + lock_length > current_block:
    #     logger.info(f'Still lock for address {address} {participant.last_draw_block + lock_length} > {current_block}')
    #     return None

    logger.info(f'Lottery {lottery.name} for pool {pool_id} and address {address} started')

    prize_id = draw_id(lottery)
    lottery_draws.create(LotteryDraw(lottery_name=lottery.name,
                                     prize=prize_id,
                                     wallet=address,
                                     timestamp=time.time()))

    logger.info(f'The prize is {prize_id}')

    # participant.last_draw_block = current_block
    # lottery_participants.update(participant)

    if prize_id is not None:
        prize_info = get_nft_prize(lottery, prize_id)
        logger.info(f'Prize info: {prize_info}')
        return prize_info

    return None


def send_all_prizes():
    logger.info('Sending all failed NFT prizes...')

    res = []
    sent_count = 0
    error_count = 0
    for draw in lottery_draws.get_many({'claimed': False, 'prize': {'$ne': None}}):
        info = {
            'wallet': draw.wallet,
            'prize': draw.prize,
            'lottery': draw.lottery_name
        }
        try:
            send_nft(draw.wallet, draw.prize)
            info['sent'] = datetime.utcnow()
            draw.claimed = True
            sent_count += 1
        except Exception as e:
            info['error'] = str(e)
            draw.send_error = str(e)
            error_count += 1

        logger.info(f'Sent NFT: {info}')

        lottery_draws.update(draw)
        res.append(info)


    return {
        'sent_count': sent_count,
        'error_count': error_count,
        'results': res
    }
