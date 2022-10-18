from core.db.db_manager import DbManager
from core.db.model import PoolInfo
from env import settings


pools_db = DbManager[PoolInfo](settings.db_name, 'pools', 'id', PoolInfo)
