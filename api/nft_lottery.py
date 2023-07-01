import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from dataclasses_json import dataclass_json

from api.swaps import SwapInfo
from api.wallet import send_nft
from blockchain.nfts import get_nft_info
from blockchain.node import init_algod_client
from core.cometa import fetch_user_pools
from core.db.cometa_users import get_address_pools
from core.db.db_manager import DbManager
from core.db.pools import pools_db
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


nft_lotteries = DbManager[NftLottery](settings.db_name, 'nft_lotteries', 'name', NftLottery)
lottery_draws = DbManager[LotteryDraw](settings.db_name, 'lottery_draws', 'swap_txid', LotteryDraw)

algod_client = init_algod_client()

logger = logging.getLogger(__name__)


def draw_id(lottery: NftLottery) -> Optional[int]:
    if random.random() > lottery.probability:
        return None
    if not lottery.available_nfts:
        return None
    res = random.choice(lottery.available_nfts)
    lottery.available_nfts.remove(res)
    nft_lotteries.update(lottery)
    return res


@dataclass
class NftPrize:
    asa_id: int
    name: str
    image_url: str
    title: str


def get_nft_prize(lottery: NftLottery, asa_id: int) -> NftPrize:
    prize_info = get_nft_info(asa_id)
    return NftPrize(asa_id=asa_id,
                    name=prize_info.name,
                    image_url=prize_info.image_url,
                    title=lottery.win_title)


def lottery_for_swap(swap: SwapInfo) -> Optional[NftPrize]:
    lotteries = nft_lotteries.get_many({'type': LotteryType.SWAP})

    for lottery in lotteries:
        swap_parts = [(swap.asset2_id, swap.asset2_amount)]
        if not lottery.only_for_buy:
            swap_parts.append((swap.asset1_id, swap.asset1_amount))
        for asset_id, amount in swap_parts:
            if lottery.is_eligible(asset_id, amount):
                prize_id = draw_id(lottery)
                lottery_draws.create(LotteryDraw(lottery_name=lottery.name,
                                                 prize=prize_id,
                                                 wallet=swap.wallet,
                                                 timestamp=time.time()))
                if prize_id is not None:
                    return get_nft_prize(lottery, prize_id)
    return None


async def lottery_for_staking(pool_id: int, address: str, is_mainnet: bool = True) -> Optional[NftPrize]:
    lotteries = nft_lotteries.get_many({'type': LotteryType.STAKING, 'pool_id': pool_id})
    if not lotteries:
        logger.info(f'No lotteries found for pools_id {pool_id}')
        return None
    logger.info(f'Lotteries found for pools_id {pool_id}: {lotteries}')

    pools = await get_address_pools(address, is_mainnet)
    if not pools:
        logger.info(f'No pools found for address {address}')
        return None

    logger.info(f'Pools for address {address}:')
    for pool in pools:
        logger.info(f'{pool.pool_id} {pool.name}: {pool.staked_tokens} tokens staked')

    user_pool = next((p for p in pools if int(p.pool_id) == pool_id), None)
    if user_pool is None:
        return None

    logger.info(f'Found user pool {user_pool}')

    if settings.lottery_check_lock:
        if user_pool.lock_timestamp == 0:
            return None

        pool_info = pools_db.get_one({'id': pool_id})
        if pool_info is None:
            return None

        current_round = algod_client.status().get('last-round')
        user_lock_length = current_round - user_pool.lock_timestamp

        if user_lock_length < pool_info.lock_length_blocks:
            return None

        logger.info(f'{user_lock_length} < {pool_info.lock_length_blocks}')

    for lottery in lotteries:
        if len(lottery.available_nfts) == 0:
            continue

        logger.info(f'{lottery.min_amount} ? {user_pool.staked_tokens}')

        if not lottery.is_eligible(pool_id, user_pool.staked_tokens):
            continue

        logger.info(f'Eligible for lottery {lottery}')

        prize_id = draw_id(lottery)
        lottery_draws.create(LotteryDraw(lottery_name=lottery.name,
                                         prize=prize_id,
                                         wallet=address,
                                         timestamp=time.time()))
        if prize_id is not None:
            return get_nft_prize(lottery, prize_id)

    return None


def send_all_prizes():
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

        lottery_draws.update(draw)
        res.append(info)

    return {
        'sent_count': sent_count,
        'error_count': error_count,
        'results': res
    }
