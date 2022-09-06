from pymongo import MongoClient

from env import settings

cluster = MongoClient(host=settings.mongodb_host, port=settings.mongodb_port)


def get_collection(name: str):
    return cluster['COMETA_BOT'][name]
