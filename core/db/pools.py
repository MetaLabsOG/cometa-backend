from core.db.db_manager import DbManager
from core.db.model import PoolInfo

pools_db = DbManager('pools', 'id', PoolInfo)
