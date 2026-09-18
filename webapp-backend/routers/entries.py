"""日记浏览 JSON API。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from database import Database
from dependencies import get_database
from schemas import EntryDetail, EntryListResponse, FullEntryListResponse
from services.entries import list_entries, list_full_entries

router = APIRouter(prefix="/api", tags=["entries"])


@router.get("/entries", response_model=EntryListResponse)
def api_entries(
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    entry_type: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Database = Depends(get_database),
) -> EntryListResponse:
    """日记列表：统一处理筛选、关键词和分页。"""

    return list_entries(
        db,
        year=year,
        month=month,
        entry_type=entry_type,
        query=q,
        page=page,
        per_page=per_page,
    )


@router.get("/entries/full", response_model=FullEntryListResponse)
def api_full_entries(
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    entry_type: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Database = Depends(get_database),
) -> FullEntryListResponse:
    """全文浏览：按当前筛选条件分页返回日记全文（契约与 /api/entries 一致）。"""

    return list_full_entries(
        db,
        year=year,
        month=month,
        entry_type=entry_type,
        query=q,
        page=page,
        per_page=per_page,
    )


@router.get("/entries/{entry_id}", response_model=EntryDetail)
def api_entry(
    entry_id: int,
    db: Database = Depends(get_database),
) -> dict:
    """单篇日记全文。"""

    entry = db.entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="日记不存在")
    return entry


@router.get("/search", response_model=EntryListResponse, deprecated=True)
def api_search(
    q: str = Query(min_length=1, description="搜索关键词"),
    limit: int = Query(default=30, ge=1, le=100),
    db: Database = Depends(get_database),
) -> EntryListResponse:
    """兼容旧搜索接口；新调用方应使用 ``/api/entries?q=``。"""

    if not q.strip():
        raise HTTPException(status_code=400, detail="搜索关键词不能为空")
    return list_entries(db, query=q, page=1, per_page=limit)