"""摘要查询业务规则。"""

from database import Database
from summary_database import SummaryRepository
from webapp.schemas import SummaryListResponse


def repository(db: Database) -> SummaryRepository:
    return SummaryRepository(db.db_path)


def list_summaries(db: Database, **filters) -> SummaryListResponse:
    page, per_page = filters["page"], filters["per_page"]
    items, total = repository(db).list(**filters)
    return SummaryListResponse(total=total, page=page, per_page=per_page,
                               pages=max(1, (total + per_page - 1) // per_page), items=items)