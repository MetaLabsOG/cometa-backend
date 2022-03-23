from fastapi import FastAPI

from api import market

app = FastAPI()


@app.get('/floor_price')
async def floor_price(asset_id: int) -> int:
    return market.get_floor_price(asset_id)

# if __name__ == '__main__':
#     test()
