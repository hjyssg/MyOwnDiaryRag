"""摘要查询业务规则。"""

from config import get_emotion_labels
from database import Database
from summary_database import SummaryRepository
from schemas import EmotionListResponse, SummaryListResponse


def repository(db: Database) -> SummaryRepository:
    return SummaryRepository(db.db_path)


def list_summaries(db: Database, **filters) -> SummaryListResponse:
    page, per_page = filters["page"], filters["per_page"]
    items, total = repository(db).list(**filters)
    return SummaryListResponse(total=total, page=page, per_page=per_page,
                               pages=max(1, (total + per_page - 1) // per_page), items=items)


def list_emotions(db: Database) -> EmotionListResponse:
    """标签全集（顺序取 .env）+ 各自条数：让前端下拉永远显示完整且顺序稳定的标签"""
    counts = repository(db).emotion_counts()
    return EmotionListResponse(
        items=[{"emotion": label, "count": int(counts.get(label, 0))}
               for label in get_emotion_labels()]
    )