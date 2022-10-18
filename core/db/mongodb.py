from pymongo import MongoClient

from env import settings


cluster = MongoClient(host=settings.mongodb_host, port=settings.mongodb_port)


def get_db_collection(db_name: str, name: str):
    return cluster[db_name][name]
