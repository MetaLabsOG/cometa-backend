from typing import List

import requests
from pymongo import MongoClient

from api import market
from blockchain.indexer import get_asset_ids_by_creator
from env import META_ADDRESSES

db = MongoClient(port=27017)


def get_all_metapunk_ids() -> List[int]:
    res = []
    for address in META_ADDRESSES:
        asset_ids = get_asset_ids_by_creator(address)
        res = res + asset_ids
    return res


def get_listed_ids() -> List[int]:
    res = []
    for address in META_ADDRESSES:
        sales = market.get_sales(address)
        res = res + [s.asa_id for s in sales]
    return res


def get_unlisted_ids() -> List[int]:
    all_ids = get_all_metapunk_ids()
    print(len(all_ids))
    listed_ids = get_listed_ids()
    print(len(listed_ids))
    print(listed_ids)
    return list(set(all_ids) - set(listed_ids))


if __name__ == '__main__':
    # get_unlisted_ids()
    # data = {
    #     'name': 'find',
    #     'service': 'mongodb-atlas',
    #     'arguments': [
    #         {
    #             'collection': 'NftAb2Listings',
    #             'database': 'NftExplorer-Prod8',
    #             'query': {
    #               "assetInfo.creator": {
    #                 "$in": [
    #                   "METASWXOZB3CFFNWD6BDWU7CG5E42HNWFJZMM6IWR7MCT4P7NDW6755IMM",
    #                   "METAGTX4BELE3WVMF5GUOYZMCDYFMDEKBWBP6VLDF6AKTNFWJSGKUFDAYU",
    #                   "METAGLOPQRWQFZVA5Q2CFSVXEBPGWW4AUHZTC6B2ZQ6UQW24PS5JAMLQSY"
    #                 ]
    #               },
    #               "active": True
    #             },
    #             # 'sort': {
    #             #   "price": {
    #             #     "$numberInt": "1"
    #             #   }
    #             # }
    #         }
    #     ]
    # }
    data = {
      "name": "find",
      "arguments": [
        {
          "database": "NftExplorer-Prod8",
          "collection": "NftAssets",
          "query": {
            "creator": {
              "$in": [
                "METASWXOZB3CFFNWD6BDWU7CG5E42HNWFJZMM6IWR7MCT4P7NDW6755IMM",
                "METAGTX4BELE3WVMF5GUOYZMCDYFMDEKBWBP6VLDF6AKTNFWJSGKUFDAYU",
                "METAGLOPQRWQFZVA5Q2CFSVXEBPGWW4AUHZTC6B2ZQ6UQW24PS5JAMLQSY"
              ]
            },
            "deleted": False,
            "$or": [
              {
                "note.json.standard": "arc69"
              },
              {
                "enricher.json.properties": {
                  "$exists": {
                    "$numberInt": "1"
                  }
                }
              },
              {
                "enricher.json.attributes": {
                  "$exists": {
                    "$numberInt": "1"
                  }
                }
              }
            ]
          },
          "project": {
            "_id": {
              "$numberInt": "0"
            },
            "id": "$_id",
            "unitName": {
              "$numberInt": "1"
            },
            "arc69.attributes": "$note.json.attributes",
            "arc69.properties": "$note.json.properties",
            "alt.attributes": "$enricher.json.attributes",
            "alt.properties": "$enricher.json.properties"
          }
        }
      ],
      "service": "mongodb-atlas"
    }
    headers = {'authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJiYWFzX2RldmljZV9pZCI6IjYxZjk5MjgwOTgwYmY3NWRkY2FkMTlmNCIsImJhYXNfZG9tYWluX2lkIjoiNjE0OTkxN2Y4ZmMxODcxY2FhYmQ2ZjI1IiwiZXhwIjoxNjQ5NjgwMjAwLCJpYXQiOjE2NDk2Nzg0MDAsImlzcyI6IjYyNTQxODQwOGI3MGEyNzUxMmE0ZjBkYyIsInN0aXRjaF9kZXZJZCI6IjYxZjk5MjgwOTgwYmY3NWRkY2FkMTlmNCIsInN0aXRjaF9kb21haW5JZCI6IjYxNDk5MTdmOGZjMTg3MWNhYWJkNmYyNSIsInN1YiI6IjYxZjk3MmQxOGUxNjljMzNjYThhMDJhOCIsInR5cCI6ImFjY2VzcyJ9.6R8hJ5LVJFmU015RDDuRyEPxpjgq31MpMp2FoIZPs80'}
    resp = requests.post(
        url='https://eu-west-1.aws.realm.mongodb.com/api/client/v2.0/app/nftexplorerrealm-jwxpx/functions/call',
        headers=headers,
        data=data
    )
    print(resp.json())
