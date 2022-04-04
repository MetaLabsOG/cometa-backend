from typing import List, Optional

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from api import market
from api.wallet_manager import WalletAsset, get_wallet_assets, TimedCost, get_wallet_total_cost

# TODO: fixrouting to /api
app = FastAPI(
    title="Cometa",
    version="0.1.1"
)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/floor_price')
async def floor_price(asset_id: int) -> int:
    return market.get_floor_price(asset_id)


@app.get('/wallet_assets/{address}')
async def wallet_assets(address: str) -> List[WalletAsset]:
    return get_wallet_assets(address)


@app.get('/total_cost/{address}')
async def total_cost(address: str, weeks_count: Optional[int] = 1) -> List[TimedCost]:
    return get_wallet_total_cost(address, weeks_count)

# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=5001)
