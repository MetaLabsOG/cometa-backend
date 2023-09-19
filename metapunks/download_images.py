import json
import os
import urllib.request

import concurrent.futures

NFT_INFO_PATH = '/Users/nikitagorokhov/metafarm-frontend/src/Metapunks.json'
TARGET_DIR = '/Users/nikitagorokhov/metapunks/ALL_DATA_METAPUNKS'

downloaded_cnt = 0

def download_images(asa_id: int, info: dict) -> None:
    global downloaded_cnt
    downloaded_cnt += 1

    punk_id = info['punk_id']

    if os.path.exists(f'{TARGET_DIR}/images/{punk_id}.png'):
        print(f'{punk_id} already downloaded')
        return

    print(f'Downloading {asa_id}/{punk_id}... ({downloaded_cnt} done)')

    main_url = info['main_url']
    urllib.request.urlretrieve(main_url, f'{TARGET_DIR}/images/{punk_id}.png')

    face_url = info['face_url']
    urllib.request.urlretrieve(face_url, f'{TARGET_DIR}/faces/{punk_id}.png')


num_threads = 8

with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
    with open(NFT_INFO_PATH) as f:
        nft_infos = json.load(f)
        print(f'Loaded {len(nft_infos)} nft infos')
        for asa_id, info in nft_infos.items():
            executor.submit(download_images, asa_id, info)

    executor.shutdown(wait=True)
