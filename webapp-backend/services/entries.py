"""日记浏览相关业务规则。"""

from typing import Optional

from database import Database
from schemas import EntryListResponse, FullEntryListResponse


def normalize_query(query: Optional[str]) -> Optional[str]:
    """去掉搜索词首尾空白；纯空白按未搜索处理。"""

    if query is None:
        return None
    normalized = query.strip()
    return normalized or None


def list_entries(
    db: Database,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    entry_type: Optional[str] = None,
    query: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> EntryListResponse:
    """按统一分页契约查询日记列表。"""

    normalized_query = normalize_query(query)
    items = db.entries(
        year=year,
        month=month,
        entry_type=entry_type,
        query=normalized_query,
        page=page,
        per_page=per_page,
    )
    total = db.count_entries(
        year=year,
        month=month,
        entry_type=entry_type,
        query=normalized_query,
    )
    pages = max(1, (total + per_page - 1) // per_page)
    return EntryListResponse(
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        items=items,
        year=year,
        month=month,
        entry_type=entry_type,
        query=normalized_query,
    )


def list_full_entries(
    db: Database,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    entry_type: Optional[str] = None,
    query: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> FullEntryListResponse:
    """按浏览筛选条件分页返回全文；与列表接口共用同一分页契约。"""

    normalized_query = normalize_query(query)
    items = db.full_entries(
        year=year,
        month=month,
        entry_type=entry_type,
        query=normalized_query,
        page=page,
        per_page=per_page,
    )
    total = db.count_entries(
        year=year,
        month=month,
        entry_type=entry_type,
        query=normalized_query,
    )
    pages = max(1, (total + per_page - 1) // per_page)
    return FullEntryListResponse(
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        items=items,
        year=year,
        month=month,
        entry_type=entry_type,
        query=normalized_query,
    )