from pymongo import MongoClient

from core.new.cometa_database import CometaDatabase
from env import settings

mongodb_client = MongoClient(host=settings.mongodb_host, port=settings.mongodb_port)
mongodb_database = mongodb_client[settings.new_db_name]

db = CometaDatabase(mongodb_database)
