from dataclasses import dataclass

from dataclasses_json import dataclass_json

from blockchain.indexer import get_asset


@dataclass_json
@dataclass
class NftInfo:
    asa_id: int
    name: str
    image_url: str


def get_nft_info(asa_id: int) -> NftInfo:
    asset = get_asset(asa_id)
    return NftInfo(asa_id=asa_id, name=asset["params"]["name"], image_url=asset["params"]["url"])
