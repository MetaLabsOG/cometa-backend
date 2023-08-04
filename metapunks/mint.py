import json

from algosdk import mnemonic, account
from algosdk.transaction import AssetConfigTxn, wait_for_confirmation
from algosdk.v2client import algod
from arweave import Wallet, Transaction
from arweave.transaction_uploader import get_uploader

from blockchain.node import print_created_asset, print_asset_holding
from env import settings

BASE_UNIT_NAME = 'YMETA'
BASE_ASSET_NAME = 'YBG Metapunk'

SOURCE_DIR = '/Users/nikitagorokhov/YBG/first_batch'

private_key = mnemonic.to_private_key(settings.algo_mnemonic)
public_key = account.address_from_private_key(private_key)

algod_client = algod.AlgodClient(settings.algod_token, settings.algod_address,
                                 headers={'User-Agent': 'py-algorand-sdk', 'X-API-Key': settings.algod_token})


ARWEAVE_WALLET_PATH = '/Users/nikitagorokhov/metapunks/cometa-backend/metapunks/arweave_key.json'
ARWEAVE_BASE_PATH = 'https://arweave.net'
wallet = Wallet(ARWEAVE_WALLET_PATH)


def upload_file(file_path: str, mimetype: str) -> str:
    print(f'Uploading {file_path} to Arweave...')

    with open(file_path, "rb", buffering=0) as file_handler:
        tx = Transaction(wallet, file_handler=file_handler, file_path=file_path)
        tx.add_tag('Content-Type', mimetype)
        tx.sign()

        uploader = get_uploader(tx, file_handler)

        while not uploader.is_complete:
            uploader.upload_chunk()
            print(f'{uploader.pct_complete}% complete, {uploader.uploaded_chunks}/{uploader.total_chunks}')

        tx.send()

        link = f'{ARWEAVE_BASE_PATH}/{tx.id}'
        print(f"{file_path} successfully uploaded as {link}")

        return link


def create_nft(num: int, image_url: str, model_url: str, attrs_json: dict) -> int:
    print(f'Creating NFT #{num}\n{image_url}\n{model_url}\n{attrs_json}')
    print(f'\nALGOD: {algod_client.status()}')

    nft_metadata = {
        'standard': 'arc69',
        'external_url': f'https://app.cometa.farm/metapunks/ybg/{num}',
        'media_url': model_url,
        'mime_type': 'model/gltf-binary',
        'attributes': attrs_json
    }
    print(f'\nMetadata: {nft_metadata}')

    params = algod_client.suggested_params()
    txn = AssetConfigTxn(
        sender=public_key,
        sp=params,
        total=1,
        default_frozen=False,
        unit_name=f'{BASE_UNIT_NAME}{num:03d}',
        asset_name=f'{BASE_ASSET_NAME} #{num}',
        note=json.dumps(nft_metadata),
        manager=public_key,
        reserve=None,
        freeze=None,
        clawback=None,
        strict_empty_address_check=False,
        url=image_url,
        decimals=0
    )

    stxn = txn.sign(private_key)

    txid = algod_client.send_transaction(stxn)
    print(f'Asset Creation Transaction ID: {txid}')

    wait_for_confirmation(algod_client, txid, 4)

    ptx = algod_client.pending_transaction_info(txid)
    asset_id = ptx['asset-index']
    print_created_asset(algod_client, public_key, asset_id)
    print_asset_holding(algod_client, public_key, asset_id)

    return asset_id


def mint_ybg_nft(num: int) -> int:
    with open(f'{SOURCE_DIR}/attrs_{num}.json') as attr_file:
        attr_json = json.load(attr_file)

        # image_url = f'https://api.cometa.farm/images/metapunks/ybg/{i}.png'
        # model_url = f'https://api.cometa.farm/images/metapunks/ybg/{i}.glb'

        # caching already downloaded files
        if num == 1:
            image_url = 'https://arweave.net/umP16P0Cz91mBvtUg-gUPdBCpTfnDBIThjKrdDD-ahk'
            model_url = 'https://arweave.net/BKslEvMEztdUjlX8awYBHp2E8Vk4C9PBUfiOhOoqlOc'
        else:
            image_url = upload_file(f'{SOURCE_DIR}/image_{num}.png', 'image/png')
            model_url = upload_file(f'{SOURCE_DIR}/model_{num}.glb', 'model/gltf-binary')

        return create_nft(num=num,
                          image_url=image_url,
                          model_url=model_url,
                          attrs_json=attr_json
                          )


if __name__ == '__main__':
    first_num = 1
    total_cnt = 1

    nfts = []
    for i in range(first_num, first_num + total_cnt):
        asa_id = mint_ybg_nft(num=i)
        nfts.append(asa_id)

    print(nfts)
