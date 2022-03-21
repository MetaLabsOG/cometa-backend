from fastapi import FastAPI

app = FastAPI()


@app.get('/floor_price')
async def floor_price(asset_id: int) -> int:
    return 420
