from fastapi import FastAPI

app = FastAPI()


@app.get('/floor_price')
async def floor_price(asset_id: int) -> int:
    return 420

# GET
# https://api.algoxnft.com/v1/nft-explorer/creator/METAGTX4BELE3WVMF5GUOYZMCDYFMDEKBWBP6VLDF6AKTNFWJSGKUFDAYU
# https://www.randswap.com/v1/listings/creator/METAGLOPQRWQFZVA5Q2CFSVXEBPGWW4AUHZTC6B2ZQ6UQW24PS5JAMLQSY
# https://algogems.io/api/nftexplorer/sales?address=METAGLOPQRWQFZVA5Q2CFSVXEBPGWW4AUHZTC6B2ZQ6UQW24PS5JAMLQSY
