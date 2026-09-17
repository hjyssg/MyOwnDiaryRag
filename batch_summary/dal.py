#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据访问适配层（零 SQL）

复用项目根目录 ``database.py`` 中的只读 ``Database`` 类，
本模块只负责转成"批量总结"需要的调用形式。

SQL 只存在于根 ``database.py`` 一处，符合该项目 README 中的维护约定：
「改数据查询：一律封装在 database.py 的 Database 类里，不直接写 SQL」。
"""

from pathlib import Path
from typing import List, Optional, Sequence

from database import Database
from batch_summary import config as bs_config


class DiaryReader:
    """批量总结专用的只读日记读取入口（只读连接，绝不写入）"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else Path(bs_config.get_settings()["db_path"])
        if not self.db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在：{self.db_path}")
        self._db = Database(self.db_path)

    @property
    def database(self):
        """暴露底层 Database 实例（复用现有 DAL 的其它方法）"""
        return self._db

    def entries(
        self,
        years: Optional[Sequence[int]] = None,
        entry_types: Optional[Sequence[str]] = None,
    ) -> List[dict]:
        """按年份/类型取出全部日记（含正文），按 (year, date, id) 升序"""
        return self._db.review_entries(
            years=list(years) if years else None,
            entry_types=list(entry_types) if entry_types else None,
        )
