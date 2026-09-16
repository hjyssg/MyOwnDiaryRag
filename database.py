#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库访问层

以「只读」方式连接现有 diary_database.db，封装所有 SQL 查询。
每次请求独立打开一个只读连接，用完即关，线程安全。
绝不修改或写入数据库。
"""

import sqlite3
from pathlib import Path
from typing import List, Optional

# 预览正文的截取长度
PREVIEW_LEN = 120


class Database:
    """封装对日记数据库的只读访问"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        """打开一个只读连接"""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _preview(content: str, limit: int = PREVIEW_LEN) -> str:
        """截取正文开头作为预览，去掉多余空白"""
        text = " ".join(content.split()) if content else ""
        if len(text) > limit:
            return text[:limit] + "…"
        return text

    # ---------------- 浏览相关 ----------------

    def years(self) -> List[dict]:
        """所有年份的统计（按年份升序）"""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT year, COUNT(*) AS entries, COALESCE(SUM(word_count), 0) AS words
                FROM diary_entries
                GROUP BY year
                ORDER BY year
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def months(self, year: int) -> List[dict]:
        """某一年各月份的统计"""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT month, COUNT(*) AS entries, COALESCE(SUM(word_count), 0) AS words
                FROM diary_entries
                WHERE year = ?
                GROUP BY month
                ORDER BY month
                """,
                (year,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _build_where(self, year, month, entry_type, query, params) -> str:
        clauses = []
        if year is not None:
            clauses.append("year = ?")
            params.append(year)
        if month is not None:
            clauses.append("month = ?")
            params.append(month)
        if entry_type:
            clauses.append("entry_type = ?")
            params.append(entry_type)
        if query:
            clauses.append("content LIKE ?")
            params.append(f"%{query}%")
        where = " AND ".join(clauses)
        return (" WHERE " + where) if where else ""

    def count_entries(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        entry_type: Optional[str] = None,
        query: Optional[str] = None,
    ) -> int:
        conn = self._connect()
        try:
            params: List = []
            where = self._build_where(year, month, entry_type, query, params)
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM diary_entries{where}", params
            ).fetchone()
            return row["n"]
        finally:
            conn.close()

    def entries(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        entry_type: Optional[str] = None,
        query: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> List[dict]:
        """分页查询日记列表（含预览）"""
        conn = self._connect()
        try:
            params: List = []
            where = self._build_where(year, month, entry_type, query, params)
            offset = (page - 1) * per_page
            rows = conn.execute(
                f"""
                SELECT id, date, year, month, day, entry_type, word_count, content
                FROM diary_entries{where}
                ORDER BY date DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, per_page, offset),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["preview"] = self._preview(d.pop("content"))
                result.append(d)
            return result
        finally:
            conn.close()



    def entry(self, entry_id: int) -> Optional[dict]:
        """获取单篇日记全文"""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, date, year, month, day, entry_type, word_count,
                       content, file_source
                FROM diary_entries
                WHERE id = ?
                """,
                (entry_id,),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["preview"] = self._preview(d.get("content") or "")
            return d
        finally:
            conn.close()

    # ---------------- 批量总结（只读，供 scripts/batch_summary 复用） ----------------

    def review_entries(
        self,
        years: Optional[List[int]] = None,
        entry_types: Optional[List[str]] = None,
    ) -> List[dict]:
        """取出全部日记全文（批量总结日记用，只读）

        与分页接口 entries() 不同：这里返回完整 content，并按 (year, date, id)
        升序排列，便于调用方逐篇处理与断点续跑。
        参数为空表示不过滤该维度。
        """
        conn = self._connect()
        try:
            clauses: List[str] = []
            params: List = []
            if years:
                clauses.append(f"year IN ({','.join('?' * len(years))})")
                params.extend(int(y) for y in years)
            if entry_types:
                clauses.append(f"entry_type IN ({','.join('?' * len(entry_types))})")
                params.extend(entry_types)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                f"""
                SELECT id, date, year, month, day, entry_type, word_count,
                       file_source, content
                FROM diary_entries{where}
                ORDER BY year, date, id
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ---------------- 随机一天 ----------------

    def random_date(self) -> Optional[dict]:
        """随机抽取一个有日记记录的日期"""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT date, year, month, day
                FROM diary_entries
                ORDER BY RANDOM()
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def entries_for_date(self, date_str: str) -> List[dict]:
        """某一天的全部日记条目"""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, date, year, month, day, entry_type, word_count, content
                FROM diary_entries
                WHERE date = ?
                ORDER BY id
                """,
                (date_str,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                # 同时保留完整正文（供随机页直接展示）和正文预览
                d["preview"] = self._preview(d["content"])
                result.append(d)
            return result
        finally:
            conn.close()

    def nearby_entries(self, year: int, month: int, exclude_id: int, limit: int = 20) -> List[dict]:
        """同一年同月份的其他篇目（阅读页侧栏）"""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, date, day, entry_type, word_count, content
                FROM diary_entries
                WHERE year = ? AND month = ? AND id != ?
                ORDER BY day, id
                LIMIT ?
                """,
                (year, month, exclude_id, limit),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["preview"] = self._preview(d.pop("content"))
                result.append(d)
            return result
        finally:
            conn.close()

    # ---------------- 过去的今天 ----------------

    def on_this_day(self, month: int, day: int) -> List[dict]:
        """查询所有年份中某月日的日记条目（按年份升序）"""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, date, year, entry_type, word_count, content
                FROM diary_entries
                WHERE month = ? AND day = ?
                ORDER BY year, id
                """,
                (month, day),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["preview"] = self._preview(d.pop("content"))
                result.append(d)
            return result
        finally:
            conn.close()

    # ---------------- 全文搜索 ----------------

    def search(self, query: str, limit: int = 30) -> List[dict]:
        """使用 FTS5 全文检索，join 回主表获取完整信息"""
        conn = self._connect()
        try:
            # 对用户输入做基础清洗，避免 FTS 语法错误
            q = " ".join(query.split())
            q = q.replace('"', "")
            # FTS 表的 rowid 与主表 id 不对应，故用 (date, content) 作为 1:1 联结键
            rows = conn.execute(
                """
                SELECT e.id, e.date, e.year, e.month, e.day, e.entry_type,
                       e.word_count, e.content
                FROM diary_fts f
                JOIN diary_entries e ON e.date = f.date AND e.content = f.content
                WHERE diary_fts MATCH ?
                ORDER BY bm25(diary_fts), e.date DESC
                LIMIT ?
                """,
                (q, limit),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["preview"] = self._preview(d.pop("content"))
                result.append(d)
            return result
        finally:
            conn.close()
