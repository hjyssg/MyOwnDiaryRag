"""摘要只读 JSON API。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import get_emotion_labels
from database import Database
from webapp.dependencies import get_database
from webapp.schemas import EmotionListResponse, SummaryItem, SummaryListResponse
from webapp.services.summaries import list_emotions, list_summaries, repository

router = APIRouter(prefix="/api", tags=["summaries"])


@router.get("/summaries", response_model=SummaryListResponse)
def api_summaries(
    year: Optional[int] = None,
    month: Optional[int] = Query(default=None, ge=1, le=12),
    entry_type: Optional[str] = None,
    emotion: Optional[str] = None,
    q: Optional[str] = None,
    status: str = Query(default="ok", pattern="^(ok|empty|failed|all)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: Database = Depends(get_database),
) -> SummaryListResponse:
    emotion = (emotion or "").strip() or None      # ?emotion= 视为"不筛选"（与 q 的处理一致）
    if emotion and emotion not in get_emotion_labels():
        # 标签集来自根 .env 的 EMOTION_LABELS，所以在函数里校验而不是写死 Query(pattern=...)
        raise HTTPException(status_code=422, detail=f"emotion 取值不合法：{emotion}")
    return list_summaries(db, year=year, month=month, entry_type=entry_type, emotion=emotion,
                          query=(q or "").strip() or None, status=status,
                          page=page, per_page=per_page)


@router.get("/summaries/emotions", response_model=EmotionListResponse)
def api_emotion_labels(db: Database = Depends(get_database)) -> dict:
    """情绪标签全集 + 各自条数（顺序与 .env 的 EMOTION_LABELS 一致，供前端筛选下拉）"""
    return list_emotions(db)


@router.get("/entries/{entry_id}/summary", response_model=SummaryItem)
def api_entry_summary(entry_id: int, db: Database = Depends(get_database)) -> dict:
    if db.entry(entry_id) is None:
        raise HTTPException(status_code=404, detail="日记不存在")
    return repository(db).for_entry(entry_id)