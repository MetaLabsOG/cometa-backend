from pymongo import MongoClient

from env import settings
from flex.db.cometa_database import CometaDatabase

mongodb_client = MongoClient(
    host=settings.mongodb_host,
    port=settings.mongodb_port,
    username=settings.mongodb_username,
    password=settings.mongodb_password,
)
mongodb_database = mongodb_client[settings.new_db_name]

db = CometaDatabase(mongodb_database)
