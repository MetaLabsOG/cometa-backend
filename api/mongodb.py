from pymongo import MongoClient

from env import settings

# TODO: refactor to have manager classes and inject client inside (at some point, maybe never lol)
client = MongoClient(host=settings.mongodb_host, port=settings.mongodb_port)
database = client[settings.db_name]
