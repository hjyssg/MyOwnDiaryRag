"""摘要只读 JSON API。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from database import Database
from webapp.dependencies import get_database
from webapp.schemas import SummaryItem, SummaryListResponse
from webapp.services.summaries import list_summaries, repository

router = APIRouter(prefix="/api", tags=["summaries"])


@router.get("/summaries", response_model=SummaryListResponse)
def api_summaries(
    year: Optional[int] = None,
    month: Optional[int] = Query(default=None, ge=1, le=12),
    entry_type: Optional[str] = None,
    q: Optional[str] = None,
    status: str = Query(default="ok", pattern="^(ok|empty|failed|all)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Database = Depends(get_database),
) -> SummaryListResponse:
    return list_summaries(db, year=year, month=month, entry_type=entry_type,
                          query=(q or "").strip() or None, status=status,
                          page=page, per_page=per_page)


@router.get("/entries/{entry_id}/summary", response_model=SummaryItem)
def api_entry_summary(entry_id: int, db: Database = Depends(get_database)) -> dict:
    if db.entry(entry_id) is None:
        raise HTTPException(status_code=404, detail="日记不存在")
    return repository(db).for_entry(entry_id)