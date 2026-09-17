"""FastAPI 依赖。

数据库对象按请求获取，但 ``Database`` 本身不持有连接；每个查询仍会创建并关闭
独立的 SQLite 只读连接。测试可通过 ``app.dependency_overrides`` 注入临时库。
"""

from functools import lru_cache

from config import get_database_path
from database import Database


@lru_cache(maxsize=1)
def get_database() -> Database:
    """返回应用共享的只读数据库访问对象。"""

    return Database(get_database_path())