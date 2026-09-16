#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pydantic 数据模型

用于 API 输入校验与响应序列化，FastAPI 会基于这些模型自动生成 /docs 文档。
所有模型与数据库表 diary_entries 的字段一致。
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class EntryPreview(BaseModel):
    """日记列表项（不包含完整正文）"""

    id: int
    date: str
    year: int
    month: int
    day: int
    entry_type: str
    word_count: int
    preview: str


class EntryDetail(EntryPreview):
    """单篇日记完整信息"""

    content: str
    file_source: Optional[str] = None


class EntryListResponse(BaseModel):
    """日记列表分页响应"""

    total: int
    page: int
    per_page: int
    pages: int
    items: List[EntryPreview]
    year: Optional[int] = None
    month: Optional[int] = None
    entry_type: Optional[str] = None
    query: Optional[str] = None


class YearStat(BaseModel):
    """某一年份的统计"""

    year: int
    entries: int
    words: int


class MonthStat(BaseModel):
    """某一年某个月的统计"""

    month: int
    entries: int
    words: int


class OnThisDayItem(BaseModel):
    """过去的今天中的单条日记"""

    id: int
    date: str
    year: int
    entry_type: str
    word_count: int
    preview: str


class OnThisDayGroup(BaseModel):
    """过去的今天：按年份分组的条目"""

    year: int
    items: List[OnThisDayItem]


class OnThisDayResponse(BaseModel):
    """过去的今天整体响应"""

    month: int
    day: int
    total: int
    groups: List[OnThisDayGroup]


class SearchResult(EntryPreview):
    """搜索结果（复用列表项模型）"""

    pass


class RandomDayResponse(BaseModel):
    """随机一天的日记响应（该日期的全部条目）"""

    date: str
    year: int
    month: int
    day: int
    total: int
    items: List[OnThisDayItem]

