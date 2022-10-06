from typing import List, Optional
from dataclasses import dataclass
from dataclasses_json import dataclass_json

from core.db import mongodb

humble_pools = mongodb.database.humblePools

@dataclass_json
@dataclass
class HumblePool:
    poolAddress: int
    poolTokenId: int
    mintedLiquidityTokens: int
    n2nn: bool
    tokenAId: int
    tokenABalance: str
    tokenAFees: str
    tokenADecimals: int
    tokenBId: int
    tokenBBalance: str
    tokenBFees: str
    tokenBDecimals: int


def get_pool_by_id(pool_id: int) -> Optional[HumblePool]:
    res = humble_pools.find_one({'poolAddress': pool_id })
    return HumblePool.from_dict(res) if res else None


def get_pools(args: dict) -> List[HumblePool]:
    return list(map(HumblePool.from_dict, humble_pools.find(args)))


def get_pools_by_assets(assetA: int, assetB: int) -> List[HumblePool]:
    return get_pools({'tokenAId': assetA, 'tokenBId': assetB})
