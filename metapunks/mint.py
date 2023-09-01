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

asa_ids = [1164083210, 1164083660, 1164084663, 1164085440, 1164085797, 1164086092, 1164086385, 1164086704, 1164087145, 1164087351, 1164087625, 1164088830, 1164089344, 1164090112, 1164090458, 1164090810, 1164091097, 1164091626, 1164092232, 1164092717, 1164093102, 1164093538, 1164094705, 1164095218, 1164095687, 1164095985, 1164096487, 1164097479, 1164098361, 1164099100, 1164100237, 1164100782, 1164101382, 1164102293, 1164102935, 1164103537, 1164104238, 1164104784, 1164105652, 1164105977, 1164106531, 1164106819, 1164107350, 1164107915, 1164108215, 1164108618, 1164109093, 1164110090, 1164110837, 1164111332]

model_urls = [
'https://arweave.net/BKslEvMEztdUjlX8awYBHp2E8Vk4C9PBUfiOhOoqlOc',
'https://arweave.net/VEbEg-IEv8dXomB6EDsSVkDbe_tEA4gQuCerC1pGmLo',
'https://arweave.net/bPBeFfkvn_UkP25Z0oxbdURpeX7BGlfoGqeQhaN_Eto',
'https://arweave.net/mC3j4mIxU5IblNXYNaYSpa3mGjJ_9aUMNK0q-INdUCE',
'https://arweave.net/MD-mkjZxRxC9rcxKjHs17dqy_mbh8rgSOztIuCoInkY',
'https://arweave.net/dPvo7kkwbe1rngisFQql-WrgVKFZ1JJGAjG4XkBz9I4',
'https://arweave.net/FbLRv0NPDgyxIUsLPY0M1JKmVl09Di3Er_LDnYFybTQ',
'https://arweave.net/mhxd615VROGb0PJEjjECYLAkrLHz92V2Yam1Ju4GCZ8',
'https://arweave.net/AdWrTHlNRCTsfm2YTY8sOaURPq3yMNqx5N9yR-6h6PQ',
'https://arweave.net/lWv5AVWb9S_M1bL4DW1UPiDP0CWSk9DPxsxEg23Foc8',
'https://arweave.net/hD_r9q-UNjJxxKlGX5uc1AQIyf6W5J7-2x8UiU6Lkq8',
'https://arweave.net/TI-8Y3EsRBpT5A8LnkI41ekEKbNPUGbdFQSEpL9KBO8',
'https://arweave.net/lCfQGAbigJE9O_Voncu3H3LeQvFD7E3wefofwE1r9Wg',
'https://arweave.net/4n06kYL2go1V8dANmdVUNME975i4TETD8tI1-aBYb4c',
'https://arweave.net/RAWmDmH1Dos57pGoxIx-Y5m0wZ2SVn4dXYwkT02PbkI',
'https://arweave.net/oMZ-a9Nb53uNZsFzp0dSaP-LT7-yPmGaT1ffj5nMktM',
'https://arweave.net/K9cJgLtWJHPZVmmElN5tTJwTffCjUf0C1sIW8pquR6s',
'https://arweave.net/G2Tej1VL2UDjj3XIfRDgWvuHq_h1-Ah4BMhEIoo73qQ',
'https://arweave.net/J0Mg_OjxDbbVzuknVldpOhYDj78QR-X-jc3eq4YLeQI',
'https://arweave.net/2007MZdIORAi23_ct6kNIKI6M1prpoDQmZ-F-TqDvMk',
'https://arweave.net/BsTnA3hKhoBVYt7IL7anQ_EDtzogL7CtZp67LxbZWC0',
'https://arweave.net/HhhUJynAY5Rl2jCBj1SYy9EvyE8hWWN-LofkuDf8oZs',
'https://arweave.net/FZ9EpQ2uAbTxKOPtlYKq4WeYfV_qQKPYO6DCS0-UzqQ',
'https://arweave.net/OSRqf8m5JaFx46U-flBNNmD1bu26g1gM01THri2Hum8',
'https://arweave.net/nDuRZJ7jedHBuR1JSN1avAkCnZ9csepIIGKTKcxokLg',
'https://arweave.net/NgGI5aeMvKLFTF2YPpEsSLAwkREH87IHvCcsgO3okUA',
'https://arweave.net/xhd0NDSbNXCNccBVXHd707i8ZH0TYuSnP3Pl3Wde3EA',
'https://arweave.net/rXrLkTfPJk0b_7xejJsud912mPZf_ztaa5mIFlLiuQw',
'https://arweave.net/52k8GpfNIBEYrRsbEnSam4QAN-U_v2aNZGnOuCbWhAY',
'https://arweave.net/JIIAGufhVF125GDfNNeIJNMc1CbyUWcuyA_ixzaEFSI',
'https://arweave.net/4ov8QzMleBh9gtzPIEy0hBX_N-iDEx-HPekymX6tKHM',
'https://arweave.net/UNWgvsRu7HH_vzbIapA__f0D4M39GLERmMcBDbmnBNQ',
'https://arweave.net/a3fX4Zzj1C5BAdyvyKp2NzBALmeisMQQaKQy9nkw0vo',
'https://arweave.net/Ve3_1CjIwr2rTKjYLDegcQzsUU-_8_Ap9lf33SENnRQ',
'https://arweave.net/riCBQBOcMbQcofIxfQJmZyGp0wb2WLhF7ceLQ0SJKGM',
'https://arweave.net/jJ1EaEfQcE_NYIVR-DDgpV_Qm9UNiMWXkdVtWQjTm6s',
'https://arweave.net/FlGmHdg0kqowBB40jPRxGn1tpVVukLGw4BsBstt7tVs',
'https://arweave.net/gq5hEPOoZks7ucYsMZhvjScQcMJwYJW0acf2WmA1RbM',
'https://arweave.net/b690lXT5mW8h4kz2LBmFPMMBhNCYFJzt3nWskLvW_L0',
'https://arweave.net/Us4pr7Asynlw-6CZ7l6K3SMjXk7Hx3kjDPGRtOc0yU4',
'https://arweave.net/8qedyX672RaYy9JoDdzRv2y_E0-OPplD4HmaXjdzSb0',
'https://arweave.net/CY_qzV9SxlwD_06WpZLu0QG7u5sSCqVBPwyMvOAsRJc',
'https://arweave.net/MQct6Wm-wHr9fuCKl4TYevsL2zEnL4AYJsabFmVOhNc',
'https://arweave.net/4cfHiV6xQ8doNK322-rJJwcolbf7umoGAqQ3I1yWnZo',
'https://arweave.net/D-miXeMgA5qsebabNEXdqAWAFqN-E8SWNdbgd4fBoQI',
'https://arweave.net/OSvdJElrwavwhL97hVeOWTxaNIL1T-_axYBsahCu1ns',
'https://arweave.net/QAFOrxggt4IGTynEWIIVpKGj5fbnkTcHtekMEaNmO7I',
'https://arweave.net/unvVUoekdq_8a4OBSvyovE9CYQhtGIdglaZdLSji0zk',
'https://arweave.net/v80I6nxEQPQPXHQQ1pdRnnuGLVQJgZ29ku12pUL-vJk',
'https://arweave.net/e-XLRboRfAdDKU0FY4OSZMaqkcQfd-kZnP9aDpkmZuE',
]

image_urls = [
'https://arweave.net/umP16P0Cz91mBvtUg-gUPdBCpTfnDBIThjKrdDD-ahk',
'https://arweave.net/5TN5n9fPaZYHSRMS7f_GfuqZTUw1Sl9HfP96cyv-tP0',
'https://arweave.net/7SHqtRzhbl21G3O-huFf6odeDTy7iahrA1awfSIkCA8',
'https://arweave.net/dZkQtaa8uIP3bLO_FRSTM-sM3hgtxCAvMvTirni9sQw',
'https://arweave.net/nLlpZ0BHGs_ZNO8MdBXk9MW-y94BHUBou54Wb2mQJYo',
'https://arweave.net/Hl5fMAr2ryuj0CneNGiPiBcI9W6b0BE-Uzb3dGpDnYw',
'https://arweave.net/B0o2t_ujQcrSa1zChLqmxEyUEVbUsgSWiycfdDKKQfc',
'https://arweave.net/qSDWmDJsG6L4CTs8UrnQ3kZj2dvPLq5fsdIbluIyV4M',
'https://arweave.net/Ou1Ujbnx8jT5ux4Kw5Ga6vAGjXWD92kxeEvBBUkCKrc',
'https://arweave.net/-zYweJJNoglv0DT4HamyWUxwJTYXhewiNLAdFx8rCVI',
'https://arweave.net/QBM1a05sl0DLpe1_aDzcvC57gaSHdjhCYUNG7_5qPQ8',
'https://arweave.net/CJNoR7WEwlknboqAKePcE0jLm2jTpEyTgQolkiRSp4g',
'https://arweave.net/zATPhXkzYhxoCHw9qEnrFHYw_ce9Lfjx4kXNzwglZwk',
'https://arweave.net/04KSXV_oK_j6qsOOghthmyL2cqmiz3cRByjiUO-zF-I',
'https://arweave.net/FmJUdxf4rxHvsdXGpeBalM1HLvlFPnO-PNXbFT387pA',
'https://arweave.net/hALMGAkvhuRDbgmriQq-ZqzQDTIEInjZ5uANaS4ZgIM',
'https://arweave.net/2CccbI0OBrK_V6Pgb-t0RYCF5KmQPQUZKhLQae41BSQ',
'https://arweave.net/9lTkmVXSMPG7VQ8q7X3sNKijRBvCHHbRNtEws7s9k-s',
'https://arweave.net/O92-qLDA6WaiqPm4-HL1nnavtPhqBDpozjkJB6KtDxk',
'https://arweave.net/ElzCPyZuZqWctXngo6KcBsnH6HakMDBSgYm7AxYPMi4',
'https://arweave.net/WcR7earTUPIyZQwn-zd1vuSkfhFaJa2CzTOk0Wjyolk',
'https://arweave.net/cjIXXaulKmywYs_aCBG-E3TADE2LIzIPx1C_XiznUfU',
'https://arweave.net/u5OtDvoJvAFYzGJie0Ey5PYmrKhfn0RPgajGkmHW-yQ',
'https://arweave.net/THkk3AWrMMjsS8pkJ2hBtEDnElXWdq3i0XwxpSOtscQ',
'https://arweave.net/N7fC-bCzyqdSXmvXVxXVLXDbmCKP1m4g9f1QzuCRWko',
'https://arweave.net/isJbL270BHd7CG0RaWjMhQ7Fs3CeIbXddBGIKYAxs9s',
'https://arweave.net/8BNZ52KcPtITXavQSs5VJ9HwHd4PgwJ8sjdLUx0zKCE',
'https://arweave.net/4gDdmzh9w0Y1L1uvDbn0E_Yf489uYxh9Uu0KscP-n-s',
'https://arweave.net/kbSdWc8E8s1c0xpTLKBQv3FTboBh4yxRFujyx9RIaaU',
'https://arweave.net/71btUxZo51NjJHlGr_Thg26lJJQ2_nPCwIajrmBW5jA',
'https://arweave.net/2mGV-mMfMPEUze4MADCpePgAgQRs8rK8hYpFod1YS-A',
'https://arweave.net/AD1tC5Q-uyI0U7bg7LgkPmQPbMSNw7nwlY_zYDmiqBE',
'https://arweave.net/jvNloRT5xsONWViGGr1Y0q3AXIQ-zF7UBQRiZYCjxtc',
'https://arweave.net/DsfsMsxUo1Ar_olFhj9HTFwTx13w6t8XYUpTsBm-tno',
'https://arweave.net/OVoqjCGF4gHppI-PTv-JHcfs8SS_DMkXXt2bPKVcp1s',
'https://arweave.net/rZii84_sQW7f91-2notM78UzPyWO7MiFjNG1Ng5Ho-M',
'https://arweave.net/bMrCLfCI7IGOCoKo-VGJxD_onAfTW2Oep0Sw8Wshzi8',
'https://arweave.net/-VFi2291zHy_qNKcB8w8CEFphdV35COjeYMY9cTGaxA',
'https://arweave.net/hXP7Y6ZS6F0diVMjwUbnuH1fJV3CAru9Mk_vMxjjC2o',
'https://arweave.net/TrtKIikg5hf0sF6iM2tSwRna8nZjEeXuZtYfgliNA2k',
'https://arweave.net/UEqWRIhIPiQjytybd7UADmet7NUwFfRuvWQLavpIY5U',
'https://arweave.net/sWejR3-7eNbhUhcgaqEX8CRQyZJrR4RP4Vmme8KuIS4',
'https://arweave.net/iIxPJZIp-UEYGpNCH-PGdC9YbnZiCbMrxsKguu0scw8',
'https://arweave.net/FzuViSEUloFTeagB3DpRQti0BUCYryZSR-8CPVgP9l4',
'https://arweave.net/3UgK3nSskeBmGMxbf-Tj-JcbBLJ4_0ScCmaOHaGveKM',
'https://arweave.net/j3h_5KloyUxlgYz_CbK0lEMx3ZonKulPW1mN-PYHXRM',
'https://arweave.net/yGnsOMx-urz2R3R70ofNAwL4ybzLv_tQPGhnqY211yE',
'https://arweave.net/zOKrr6C69WJWV6pCA4TSE-X0tEb3l6nTnAq2Ey8o9ZU',
'https://arweave.net/sQnoJ5GCFs31nDWxvivZGZZQ_p4wFjQrP4pEtXiOhzA',
'https://arweave.net/_na1updENy4jJlutcxnR0c0VN1Tys1jBBQIlugtTbYs'
]


def get_info(num: int) -> (str, dict):
    with open(f'{SOURCE_DIR}/attrs_{num}.json') as attr_file:
        attr_json = json.load(attr_file)
        asset_id = asa_ids[num - 1]
        res = {
            'asset_id': asset_id,
            'punk_id': 2578 + num,
            'name': f'YBG Metapunk #{num}',
            'unit_name': f'YMETA{num}',
            'main_url': image_urls[num - 1],
            'model_3d_url': model_urls[num - 1],
            'face_url': image_urls[num - 1],
            'side_url': image_urls[num - 1],
            'attributes': attr_json
        }
        return str(asset_id), res


if __name__ == '__main__':
    first_num = 1
    total_cnt = 50

    # nfts = []
    # for i in range(first_num, first_num + total_cnt):
    #     asa_id = mint_ybg_nft(num=i)
    #     nfts.append(asa_id)
    # print(nfts)

    infos = {}
    for i in range(first_num, first_num + total_cnt):
        asa_id, info = get_info(i)
        infos[asa_id] = info
        with open(f'metapunks/ybg_info.json', 'w') as out_file:
            json.dump(infos, out_file)

    print(json.dumps(infos, indent=2))
