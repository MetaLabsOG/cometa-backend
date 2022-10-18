import random
from dataclasses import dataclass
from typing import Optional

from dataclasses_json import dataclass_json

from api.swaps import SwapInfo
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

    def is_eligible(self, asset_id: int, amount: float) -> bool:
        return asset_id == self.asset_id and amount >= self.min_amount


@dataclass_json
@dataclass
class LotteryDraw:
    swap_id: str
    asset_id: int
    wallet: str
    prize: Optional[int]
    claimed: bool = False


nft_lotteries = DbManager[NftLottery](settings.db_name, 'nft_lotteries', 'asset_id', NftLottery)
lottery_draws = DbManager[LotteryDraw](settings.db_name, 'lottery_draws', 'swap_id', LotteryDraw)


def draw(lottery: NftLottery) -> Optional[int]:
    if random.random() > lottery.probability:
        return None
    res = random.choice(lottery.available_nfts)
    lottery.available_nfts.remove(res)
    nft_lotteries.update(lottery)
    return res


def lottery_for_swap(swap: SwapInfo) -> Optional[int]:
    # TODO: optimize to get by asset id when it's more of them
    lotteries = nft_lotteries.get_many({})
    for asset_id, amount in [(swap.asset1_id, swap.asset1_amount), (swap.asset2_id, swap.asset2_amount)]:
        for lottery in lotteries:
            if lottery.is_eligible(asset_id, amount):
                prize = draw(lottery)
                lottery_draws.create(LotteryDraw(swap_id=swap.txid, asset_id=asset_id, prize=prize, wallet=swap.wallet))
                return prize
    return None
