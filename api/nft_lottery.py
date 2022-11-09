import random
import time
from dataclasses import dataclass
from typing import Optional

from dataclasses_json import dataclass_json

from api.swaps import SwapInfo
from blockchain.nfts import get_nft_info
from core.db.db_manager import DbManager
from env import settings


@dataclass_json
@dataclass
class NftLottery:
    name: str
    asset_id: int
    min_amount: int
    probability: float
    available_nfts: list[int]
    win_title: str = 'You have won a prize NFT!'
    nft_amount: float = 1
    only_for_buy: bool = False

    def is_eligible(self, asset_id: int, amount: float) -> bool:
        return asset_id == self.asset_id and amount >= self.min_amount


@dataclass_json
@dataclass
class LotteryDraw:
    lottery_name: str
    wallet: str
    prize: Optional[int]
    timestamp: float
    claimed: bool = False
    nft_amount: float = 1


nft_lotteries = DbManager[NftLottery](settings.db_name, 'nft_lotteries', 'name', NftLottery)
lottery_draws = DbManager[LotteryDraw](settings.db_name, 'lottery_draws', 'swap_txid', LotteryDraw)


def draw_id(lottery: NftLottery) -> Optional[int]:
    if random.random() > lottery.probability:
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


def lottery_for_swap(swap: SwapInfo) -> Optional[NftPrize]:
    # TODO: optimize to get by asset id when it's more of them
    lotteries = nft_lotteries.get_all()

    for lottery in lotteries:
        swap_parts = [(swap.asset2_id, swap.asset2_amount)]
        if not lottery.only_for_buy:
            swap_parts += (swap.asset1_id, swap.asset1_amount)
        for asset_id, amount in swap_parts:
            if lottery.is_eligible(asset_id, amount):
                prize_id = draw_id(lottery)
                lottery_draws.create(LotteryDraw(lottery_name=lottery.name,
                                                 prize=prize_id,
                                                 wallet=swap.wallet,
                                                 nft_amount=lottery.nft_amount,
                                                 timestamp=time.time()))
                if prize_id is not None:
                    prize_info = get_nft_info(prize_id)
                    return NftPrize(asa_id=prize_id,
                                    name=prize_info.name,
                                    image_url=prize_info.image_url,
                                    title=lottery.win_title)
    return None
